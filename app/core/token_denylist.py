"""Access tokens revoked before they expire (logout).

Access tokens are short-lived JWTs, so logout used to end only the refresh
cookie: an access token already held in a page kept working until it
expired. Logout now records the token's `jti` here until its own `exp`, and
`get_current_user` refuses any token on the list.

If Redis is unreachable the check fails open (logged at ERROR on
app.security): the token is still signed, unexpired and tied to an active
user, and refusing every request during a Redis outage would take the whole
app down.
"""

import logging
import math
from datetime import datetime

import redis

from app.core.config import settings
from app.core.time import utcnow

_redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
_logger = logging.getLogger("app.security")
_KEY_PREFIX = "revoked_access_jti:"


def revoke_access_token(jti: str, expires_at: datetime) -> None:
    ttl = math.ceil((expires_at - utcnow()).total_seconds())
    if ttl <= 0:
        return
    try:
        _redis_client.set(f"{_KEY_PREFIX}{jti}", "1", ex=ttl)
    except redis.RedisError as exc:
        _logger.error(
            "Could not record revoked access token",
            extra={"event": "access_token_revoke_failed", "error": type(exc).__name__},
        )


def is_access_token_revoked(jti: str | None) -> bool:
    if not jti:
        return False
    try:
        return bool(_redis_client.exists(f"{_KEY_PREFIX}{jti}"))
    except redis.RedisError as exc:
        _logger.error(
            "Could not check revoked access token",
            extra={"event": "access_token_revoke_check_failed", "error": type(exc).__name__},
        )
        return False
