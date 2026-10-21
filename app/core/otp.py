"""Password-reset OTPs (Spec 7.9): stored in Redis with a TTL, never in a
database table — TTL expiry removes an entire class of cleanup bug a DB
column would need a background job for (Section 24's decision log entry
"Redis for OTPs, not a table").

F3: Key by (email, company_id). Store HMAC-SHA256 keyed with SECRET_KEY,
not plain sha256 (a Redis leak must not allow offline recovery of a 6-digit code).
Verify with ONE atomic Redis Lua script: read the stored value, INCR attempts,
reject when over OTP_MAX_ATTEMPTS, compare, delete code and counter on success.
A new request replaces the code and resets that code's attempt counter.
"""

import hashlib
import hmac
import secrets
import uuid

import redis

from app.core.config import settings

_redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

# Atomic Lua scripts for OTP verification (F3).
# Check script: checks code WITHOUT deleting it; counts the attempt.
# Returns:
#   1  = VALID_CODE (match, code preserved, attempt counted)
#   0  = WRONG_CODE (code exists, attempts <= max_attempts, but HMAC does not match)
#  -1  = MISSING_OR_EXPIRED (code does not exist)
#  -2  = EXHAUSTED (attempts reached or exceeded max_attempts)
_CHECK_OTP_LUA = """
local code_key = KEYS[1]
local attempts_key = KEYS[2]
local expected_hmac = ARGV[1]
local max_attempts = tonumber(ARGV[2])

local stored_val = redis.call("GET", code_key)
if not stored_val then
    return -1
end

local attempts = redis.call("INCR", attempts_key)
if attempts > max_attempts then
    return -2
end

if stored_val == expected_hmac then
    return 1
else
    if attempts >= max_attempts then
        redis.call("DEL", code_key)
        return -2
    end
    return 0
end
"""
_check_script = _redis_client.register_script(_CHECK_OTP_LUA)

# Consume script: atomic compare-and-delete (no attempt increment).
# Returns:
#   1  = SUCCESS (deleted)
#   0  = MISMATCH_OR_ALREADY_CONSUMED
_CONSUME_OTP_LUA = """
local code_key = KEYS[1]
local attempts_key = KEYS[2]
local expected_hmac = ARGV[1]

local stored_val = redis.call("GET", code_key)
if stored_val == expected_hmac then
    redis.call("DEL", code_key)
    redis.call("DEL", attempts_key)
    return 1
else
    return 0
end
"""
_consume_script = _redis_client.register_script(_CONSUME_OTP_LUA)

# Atomic verify-and-consume in ONE script for verify_otp:
_VERIFY_AND_CONSUME_OTP_LUA = """
local code_key = KEYS[1]
local attempts_key = KEYS[2]
local expected_hmac = ARGV[1]
local max_attempts = tonumber(ARGV[2])

local stored_val = redis.call("GET", code_key)
if not stored_val then
    return -1
end

local attempts = redis.call("INCR", attempts_key)
if attempts > max_attempts then
    return -2
end

if stored_val == expected_hmac then
    redis.call("DEL", code_key)
    redis.call("DEL", attempts_key)
    return 1
else
    if attempts >= max_attempts then
        redis.call("DEL", code_key)
        return -2
    end
    return 0
end
"""
_verify_and_consume_script = _redis_client.register_script(_VERIFY_AND_CONSUME_OTP_LUA)


def _hash(value: str) -> str:
    """Computes HMAC-SHA256 keyed with SECRET_KEY (F3)."""
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def _email_hash(email: str) -> str:
    """Plain sha256 of lowercase email for keying and rate limiting."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()


def _otp_key(email: str, company_id: str | uuid.UUID | None = None) -> str:
    # Key by (email, company_id) (F3)
    scoped = f"{email.lower().strip()}:{str(company_id) if company_id else ''}"
    return f"pwreset:{_email_hash(scoped)}"


def _attempts_key(email: str, company_id: str | uuid.UUID | None = None) -> str:
    return f"{_otp_key(email, company_id)}:attempts"


def _account_req_key(email: str) -> str:
    """F1 Per-account limit: Redis counter key sha256(lower(email))"""
    return f"pwreset_req:{_email_hash(email)}"


def check_and_increment_account_limit(
    email: str, limit: int = 3, window_seconds: int = 3600
) -> int:
    """F1: make counter + expiry atomic using pipeline(transaction=True):
    SET key 0 EX window NX, then INCR.
    Counts every request, including unknown emails.
    Returns the current request count.
    """
    key = _account_req_key(email)
    pipe = _redis_client.pipeline(transaction=True)
    pipe.set(key, 0, ex=window_seconds, nx=True)
    pipe.incr(key)
    results = pipe.execute()
    return int(results[1])


def generate_and_store_otp(email: str, company_id: str | uuid.UUID | None = None) -> str:
    """Generates a fresh 6-digit OTP, stores its HMAC-SHA256 (never the raw code)
    with a 10-minute TTL, and resets the attempt counter. Returns the raw code.
    Keyed by (email, company_id) only.
    """
    otp = f"{secrets.randbelow(1_000_000):06d}"
    ttl = settings.OTP_TTL_MINUTES * 60
    hashed_otp = _hash(otp)

    code_key = _otp_key(email, company_id)
    att_key = _attempts_key(email, company_id)

    pipe = _redis_client.pipeline(transaction=True)
    pipe.set(code_key, hashed_otp, ex=ttl)
    pipe.set(att_key, 0, ex=ttl)
    pipe.execute()
    return otp


def verify_otp_atomic(
    email: str, otp: str, company_id: str | uuid.UUID | None = None
) -> tuple[bool, str]:
    """Atomic Lua verification:
    Returns (success: bool, reason: str).
    Reasons:
      - 'ok' (success, code verified and preserved)
      - 'missing_or_expired' (-1)
      - 'exhausted' (-2)
      - 'wrong_code' (0)
    """
    code_key = _otp_key(email, company_id)
    att_key = _attempts_key(email, company_id)
    expected_hmac = _hash(otp)

    res = int(
        _check_script(
            keys=[code_key, att_key],
            args=[expected_hmac, settings.OTP_MAX_ATTEMPTS],
        )
    )

    if res == 1:
        return True, "ok"
    elif res == -1:
        return False, "missing_or_expired"
    elif res == -2:
        return False, "exhausted"
    else:
        return False, "wrong_code"


def consume_otp_atomic(email: str, otp: str, company_id: str | uuid.UUID | None = None) -> bool:
    """Atomic compare-and-delete Lua script (no attempt increment).
    Consumes the code so it cannot be used again. Returns True if deleted.
    """
    code_key = _otp_key(email, company_id)
    att_key = _attempts_key(email, company_id)
    expected_hmac = _hash(otp)

    res = int(
        _consume_script(
            keys=[code_key, att_key],
            args=[expected_hmac],
        )
    )
    return res == 1


def verify_otp(email: str, otp: str, company_id: str | uuid.UUID | None = None) -> bool:
    """Caps verification attempts at OTP_MAX_ATTEMPTS (Spec 7.9, F3).
    Atomic Redis Lua script verification and consumption in one step.
    """
    code_key = _otp_key(email, company_id)
    att_key = _attempts_key(email, company_id)
    expected_hmac = _hash(otp)

    res = int(
        _verify_and_consume_script(
            keys=[code_key, att_key],
            args=[expected_hmac, settings.OTP_MAX_ATTEMPTS],
        )
    )
    return res == 1
