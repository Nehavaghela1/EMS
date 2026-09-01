from typing import Any, Literal

from pydantic import BaseModel


class JobStatusResponse(BaseModel):
    """Route 136: polls a Celery task's own result-backend state directly —
    no dedicated `jobs` table exists in the spec's schema (Section 7), and
    Celery's result backend (Redis) already persists exactly this."""

    job_id: str
    status: Literal["queued", "started", "success", "failure"]
    result: Any = None
    error: str | None = None
