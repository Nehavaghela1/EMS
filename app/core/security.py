import hashlib
import secrets
import uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.time import utcnow

# 64 MiB memory cost, per Spec 9.1 — memory-hard, GPU-resistant.
_hasher = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=4)

# A fixed hash of a throwaway value, used to keep login timing constant when no
# user matches the email (9.3). Generated once with the same PasswordHasher
# parameters above; not the hash of any real password.
DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "DgfRdr9QpZS/t3rQvv5Kyg$oRNLIsCSTykE+YhgLLqm8QRQVas+B2yQE+dqG6FXAsM"
)


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


def create_access_token(*, sub: str, company_id: str, role: str) -> str:
    now = utcnow()
    payload = {
        "sub": sub,
        "company_id": company_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    # Algorithm is explicitly listed, never taken from the token header (9.2) —
    # that is the algorithm-confusion attack.
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != "access":
        # A refresh token must never be usable as an access token (9.2).
        raise jwt.InvalidTokenError("Not an access token.")
    return payload


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
