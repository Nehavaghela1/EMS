"""Password-reset OTPs (Spec 7.9): stored in Redis with a TTL, never in a
database table — TTL expiry removes an entire class of cleanup bug a DB
column would need a background job for (Section 24's decision log entry
"Redis for OTPs, not a table"). Only the OTP's hash is ever stored; the raw
code exists only for the instant it is generated, on its way to
app.core.email.send_email — never logged, never returned in an HTTP
response (6.8, 9.3).
"""

import hashlib
import secrets

import redis

from app.core.config import settings

_redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _otp_key(email: str) -> str:
    # Spec 7.9's literal key shape: pwreset:{email_hash}
    return f"pwreset:{_hash(email.lower())}"


def _attempts_key(email: str) -> str:
    return f"{_otp_key(email)}:attempts"


def generate_and_store_otp(email: str) -> str:
    """Generates a fresh 6-digit OTP, stores its hash (never the raw code)
    with a 10-minute TTL, and resets the attempt counter. Returns the raw
    code — the only place it ever exists outside the caller's memory.
    """
    otp = f"{secrets.randbelow(1_000_000):06d}"
    ttl = settings.OTP_TTL_MINUTES * 60
    pipe = _redis_client.pipeline()
    pipe.set(_otp_key(email), _hash(otp), ex=ttl)
    pipe.set(_attempts_key(email), 0, ex=ttl)
    pipe.execute()
    return otp


def verify_otp(email: str, otp: str) -> bool:
    """Caps verification attempts at OTP_MAX_ATTEMPTS (Spec 7.9). The
    attempt counter increments on every call, right or wrong, so a correct
    code presented after the cap is already exhausted is still rejected —
    5 wrong guesses use up the cap; the 6th attempt fails even if correct.
    A correct code is consumed (deleted) so it can never be replayed.
    """
    key = _otp_key(email)
    stored_hash = _redis_client.get(key)
    if stored_hash is None:
        return False
    attempts = _redis_client.incr(_attempts_key(email))
    if attempts > settings.OTP_MAX_ATTEMPTS:
        return False
    if _hash(otp) != stored_hash:
        return False
    _redis_client.delete(key)
    _redis_client.delete(_attempts_key(email))
    return True
