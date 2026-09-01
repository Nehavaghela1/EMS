from typing import Literal

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.platform.schemas import JobStatusResponse
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/jobs", tags=["Jobs"])

JobState = Literal["queued", "started", "success", "failure"]

# Celery's own task states map onto route 136's four-value contract.
_STATE_MAP: dict[str, JobState] = {
    "PENDING": "queued",
    "RECEIVED": "queued",
    "STARTED": "started",
    "RETRY": "started",
    "SUCCESS": "success",
    "FAILURE": "failure",
}


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, _user: User = Depends(get_current_user)) -> JobStatusResponse:
    async_result = celery_app.AsyncResult(job_id)
    status = _STATE_MAP.get(async_result.state, "queued")
    return JobStatusResponse(
        job_id=job_id,
        status=status,
        result=async_result.result if status == "success" else None,
        error=str(async_result.result) if status == "failure" else None,
    )
