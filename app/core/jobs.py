"""Background job registry backed by Redis (Spec 13, WP 3.6).
Stores job metadata with 24-hour expiration so status and download routes can
verify ownership and tenant isolation.
"""

import uuid
from typing import Any

from app.core.cache import get_json, set_json
from app.core.exceptions import NotFoundError
from app.core.roles import HR_LEVEL_ROLES
from app.modules.identity.models import User

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


def authorize_export_job(
    job_id: str,
    user: User,
    not_found_message: str = "Job not found.",
) -> dict[str, Any]:
    """Validates job UUID and checks registry ownership:
    - job_id must be a valid UUID.
    - Registry record must exist.
    - Must belong to the caller's company (no super_admin cross-company bypass).
    - Caller must be the starter or HR-level (owner, hr_admin, super_admin) of that company.
    Any violation raises NotFoundError(not_found_message).
    """
    try:
        uuid.UUID(job_id)
    except (ValueError, TypeError, AttributeError):
        raise NotFoundError(not_found_message) from None

    job_meta = get_registered_job(job_id)
    if not job_meta:
        raise NotFoundError(not_found_message)

    if job_meta.get("company_id") != str(user.company_id):
        raise NotFoundError(not_found_message)

    is_starter = bool(job_meta.get("user_id") and str(user.id) == str(job_meta.get("user_id")))
    is_hr_level = user.role in HR_LEVEL_ROLES
    if not (is_starter or is_hr_level):
        raise NotFoundError(not_found_message)

    return job_meta
