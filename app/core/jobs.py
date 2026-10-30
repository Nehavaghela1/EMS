"""Background job registry backed by Redis (Spec 13, WP 3.6).
Stores job metadata with 24-hour expiration so status and download routes can
verify ownership and tenant isolation.
"""

import uuid
from typing import Any

from app.core.cache import get_json, set_json

JOB_REGISTRY_TTL_SECONDS = 86400  # 24 hours


def register_job(
    job_id: str,
    company_id: uuid.UUID | str,
    user_id: uuid.UUID | str | None,
    kind: str,
) -> None:
    """Stores job metadata in Redis with 24-hour expiration."""
    payload = {
        "job_id": str(job_id),
        "company_id": str(company_id),
        "user_id": str(user_id) if user_id else None,
        "kind": kind,
    }
    set_json(f"job:{job_id}", payload, ttl_seconds=JOB_REGISTRY_TTL_SECONDS)


def get_registered_job(job_id: str) -> dict[str, Any] | None:
    """Retrieves job metadata from Redis or None if expired or not found."""
    return get_json(f"job:{job_id}")
