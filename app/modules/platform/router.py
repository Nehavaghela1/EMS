import uuid
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.exceptions import NotFoundError
from app.core.pagination import Page, PageParams, page_params
from app.db.session import get_db
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
    AnnouncementCreate,
    AnnouncementResponse,
    FileUploadResponse,
    SignedUrlResponse,
    EmployeeDocumentCreate,
    EmployeeDocumentResponse,
    GlobalSearchResponse,
)
from app.modules.platform.service import (
    AuditService,
    DashboardService,
    IndustryPresetService,
    NotificationService,
    AnnouncementService,
    FileService,
    EmployeeDocumentService,
    GlobalSearchService,
)
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/jobs", tags=["Jobs"])
dashboard_router = APIRouter(tags=["Dashboard"])
audit_logs_router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])
notifications_router = APIRouter(prefix="/notifications", tags=["Notifications"])
industry_presets_router = APIRouter(prefix="/industry-presets", tags=["Industry Presets"])


@industry_presets_router.get("", response_model=list[str])
def list_industry_presets(db: Session = Depends(get_db)):
    """Public, no tenant context (`industry_presets` has no RLS — Spec
    7.8, global seed data). Names only, not the full
    `departments_json`/`leave_types_json` payloads a caller has no use
    for before a company even exists. No route number is assigned to
    this in Section 10's table — see RECONCILIATION.md's spec gaps."""
    return IndustryPresetService(db).list_names()


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
def get_job_status(job_id: str, user: User = Depends(get_current_user)) -> JobStatusResponse:
    async_result = celery_app.AsyncResult(job_id)
    status = _STATE_MAP.get(async_result.state, "queued")
    result = async_result.result if status == "success" else None
    if (
        result is not None
        and user.role != UserRole.super_admin
        and isinstance(result, dict)
        and result.get("company_id") != str(user.company_id)
    ):
        # Every export task's result carries the company_id it ran for — a
        # job_id supplied by the client is exactly the kind of id a service
        # must re-scope rather than trust, even though Celery's own task ids
        # are high-entropy UUIDs and not practically guessable. 404, not 403
        # (10.1): the caller should not learn that a job with this id exists
        # at all.
        raise NotFoundError("Job not found.")
    return JobStatusResponse(
        job_id=job_id,
        status=status,
        result=result,
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


# ── Announcements (routes 122-124) ──────────────────────────────
announcements_router = APIRouter(prefix="/announcements", tags=["Announcements"])

@announcements_router.get("", response_model=list[AnnouncementResponse])
def list_announcements(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return AnnouncementService(db).list_active(user.company_id, user.role.value)

@announcements_router.post("", response_model=AnnouncementResponse, status_code=201)
def create_announcement(
    data: AnnouncementCreate,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager)),
):
    return AnnouncementService(db).create(user.company_id, user.id, data)

@announcements_router.delete("/{announcement_id}", status_code=204)
def delete_announcement(
    announcement_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin)),
):
    AnnouncementService(db).delete(user.company_id, announcement_id)


# ── File Uploads & Signed URLs (routes 130-131) ─────────────────
files_router = APIRouter(prefix="/files", tags=["Files"])

@files_router.post("/upload", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    file_bytes = await file.read()
    file_obj = FileService(db).upload_file(user.company_id, user.id, file.filename or "file", file.content_type or "application/octet-stream", file_bytes)
    return FileUploadResponse(
        file_object_id=file_obj.id,
        file_name=file_obj.file_name,
        file_type=file_obj.file_type,
        file_size=file_obj.file_size
    )

@files_router.get("/{file_id}/url", response_model=SignedUrlResponse)
def get_file_signed_url(
    file_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return FileService(db).generate_signed_url(user.company_id, file_id)

@files_router.get("/download/{file_id}")
def download_file(
    file_id: uuid.UUID,
    expires: int,
    signature: str,
    db: Session = Depends(get_db),
):
    # Verify HMAC Signature
    import hmac, hashlib, os
    from app.core.config import settings
    from app.modules.platform.models import FileObject
    from fastapi.responses import FileResponse

    # 1. Check expiration
    if int(datetime.now(UTC).timestamp()) > expires:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Signed URL has expired.")

    # 2. Get file object from db directly (public signed route)
    file_obj = db.query(FileObject).filter(FileObject.id == file_id).first()
    if not file_obj:
        raise NotFoundError("File object not found.")

    # 3. Verify signature
    signature_payload = f"{file_obj.company_id}:{file_id}:{expires}".encode()
    expected_sig = hmac.new(settings.SECRET_KEY.encode(), signature_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, signature):
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Invalid file signature.")

    if not os.path.exists(file_obj.storage_path):
        raise NotFoundError("File not found on disk.")

    return FileResponse(path=file_obj.storage_path, filename=file_obj.file_name, media_type=file_obj.file_type)


# ── Employee Documents (routes 132-133) ─────────────────────────
documents_router = APIRouter(prefix="/documents", tags=["Employee Documents"])

@documents_router.get("/{employee_id}", response_model=list[EmployeeDocumentResponse])
def list_employee_documents(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return EmployeeDocumentService(db).list_documents(user.company_id, employee_id)

@documents_router.post("", response_model=EmployeeDocumentResponse, status_code=201)
def attach_employee_document(
    data: EmployeeDocumentCreate,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin)),
):
    return EmployeeDocumentService(db).attach_document(user.company_id, data)


# ── Global Search (route 134) ───────────────────────────────────
search_router = APIRouter(prefix="/search", tags=["Global Search"])

@search_router.get("", response_model=GlobalSearchResponse)
def global_search(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return GlobalSearchService(db).search(user.company_id, q)
