import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.pagination import Page, PageParams, page_params
from app.modules.identity.models import User, UserRole
from app.modules.platform.models import AuditLog, Notification
from app.modules.platform.schemas import (
    AuditLogExportRequest,
    AuditLogResponse,
    DashboardResponse,
    JobQueuedResponse,
    JobStatusResponse,
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationResponse,
)
from app.modules.platform.service import AuditService, DashboardService, NotificationService
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/jobs", tags=["Jobs"])
dashboard_router = APIRouter(tags=["Dashboard"])
audit_logs_router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])
notifications_router = APIRouter(prefix="/notifications", tags=["Notifications"])

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


@dashboard_router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    payload = DashboardService(db).get_dashboard(user.company_id, user)
    return DashboardResponse(**payload)


def _to_audit_log_response(log: AuditLog) -> AuditLogResponse:
    return AuditLogResponse.model_validate(log)


@audit_logs_router.get("", response_model=Page[AuditLogResponse])
def list_audit_logs(
    action: str | None = None,
    actor_email: str | None = None,
    entity_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    items, total, pages = AuditService(db).list_audit_logs(
        user.company_id,
        action=action,
        actor_email=actor_email,
        entity_type=entity_type,
        date_from=date_from,
        date_to=date_to,
        page_params=params,
    )
    return Page(
        items=[_to_audit_log_response(log) for log in items],
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@audit_logs_router.post("/export", response_model=JobQueuedResponse, status_code=202)
def export_audit_logs(
    data: AuditLogExportRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    job_id = AuditService(db).queue_export(
        user.company_id,
        action=data.action,
        actor_email=data.actor_email,
        entity_type=data.entity_type,
        date_from=data.date_from,
        date_to=data.date_to,
    )
    return JobQueuedResponse(job_id=job_id)


def _to_notification_response(notification: Notification) -> NotificationResponse:
    return NotificationResponse.model_validate(notification)


@notifications_router.get("", response_model=NotificationListResponse)
def list_notifications(
    unread_only: bool = False,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    items, total, pages, unread_count = NotificationService(db).list_notifications(
        user.company_id, user.id, unread_only=unread_only, page_params=params
    )
    return NotificationListResponse(
        items=[_to_notification_response(n) for n in items],
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
        unread_count=unread_count,
    )


@notifications_router.put("/read-all", response_model=MarkAllReadResponse)
def mark_all_notifications_read(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    count = NotificationService(db).mark_all_read(user.company_id, user.id)
    return MarkAllReadResponse(marked_read=count)


@notifications_router.put("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    notification = NotificationService(db).mark_read(user.company_id, user.id, notification_id)
    return _to_notification_response(notification)
