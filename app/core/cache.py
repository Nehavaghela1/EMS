"""Generic Redis JSON cache (Spec 11.10's dashboard cache). Same
module-level-client shape as app.core.otp — one client, reused across
requests, redis-py pools connections internally.
"""

import json
from typing import Any

import redis

from app.core.config import settings

_redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def get_json(key: str) -> Any | None:
    raw = _redis_client.get(key)
    return json.loads(raw) if raw is not None else None


def set_json(key: str, value: Any, *, ttl_seconds: int) -> None:
    _redis_client.set(key, json.dumps(value), ex=ttl_seconds)


def delete_by_prefix(prefix: str) -> None:
    """Cache invalidation (11.10): drops every key under a prefix — e.g. all
    of one company's cached dashboards, regardless of which user/role cached
    them. `scan_iter` rather than `KEYS`, so this never blocks Redis on a
    large keyspace.
    """
    keys = list(_redis_client.scan_iter(match=f"{prefix}*"))
    if keys:
        _redis_client.delete(*keys)
