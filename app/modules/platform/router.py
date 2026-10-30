import logging
import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import (
    get_current_user,
    get_tenant_db,
    require_role,
)
from app.core.exceptions import (
    ConflictError,
    ExportTooLargeError,
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationError,
)
from app.core.jobs import get_registered_job
from app.core.pagination import Page, PageParams, page_params
from app.core.rate_limit import get_user_or_ip_key, limiter
from app.core.roles import HR_LEVEL_ROLES
from app.core.upload_validation import validate_document_upload
from app.db.session import get_db
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole
from app.modules.platform.models import AuditLog, FileObject, Notification
from app.modules.platform.repository import EmployeeDocumentRepository, FileRepository
from app.modules.platform.schemas import (
    VALID_DOCUMENT_TYPES,
    AnnouncementCreate,
    AnnouncementResponse,
    AuditLogExportRequest,
    AuditLogResponse,
    DashboardResponse,
    EmployeeDocumentResponse,
    FileUploadResponse,
    GlobalSearchResponse,
    JobQueuedResponse,
    JobStatusResponse,
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationResponse,
    SignedUrlResponse,
)
from app.modules.platform.service import (
    AnnouncementService,
    AuditService,
    DashboardService,
    EmployeeDocumentService,
    FileService,
    GlobalSearchService,
    IndustryPresetService,
    NotificationService,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

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


def _safe_result(result: Any) -> dict[str, Any] | None:
    if isinstance(result, dict):
        return {k: v for k, v in result.items() if k in {"row_count", "expires_at"}}
    return None


@router.get("/{job_id}", response_model=JobStatusResponse)
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def get_job_status(
    job_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> JobStatusResponse:
    try:
        uuid.UUID(job_id)
    except (ValueError, TypeError, AttributeError):
        raise NotFoundError("Job not found.") from None

    job_meta = get_registered_job(job_id)
    if not job_meta:
        raise NotFoundError("Job not found.")

    if user.role != UserRole.super_admin:
        if job_meta.get("company_id") != str(user.company_id):
            raise NotFoundError("Job not found.")
        is_starter = job_meta.get("user_id") and str(user.id) == str(job_meta.get("user_id"))
        is_hr_level = user.role in HR_LEVEL_ROLES
        if not (is_starter or is_hr_level):
            raise NotFoundError("Job not found.")

    async_result = celery_app.AsyncResult(job_id)
    status = _STATE_MAP.get(async_result.state, "queued")
    result = async_result.result if status == "success" else None

    safe_result = _safe_result(result)

    safe_error = None
    if status == "failure":
        task_err = async_result.result
        logger.error("Job %s failed: %s", job_id, repr(task_err))
        if isinstance(task_err, ExportTooLargeError):
            safe_error = str(task_err)
        elif isinstance(task_err, Exception):
            if type(task_err).__name__ == "ExportTooLargeError" or "ExportTooLargeError" in str(
                type(task_err)
            ):
                safe_error = str(task_err)
            else:
                safe_error = "Export failed. Please try again."
        elif isinstance(task_err, str) and "ExportTooLargeError" in task_err:
            safe_error = task_err
        else:
            safe_error = "Export failed. Please try again."

    return JobStatusResponse(
        job_id=job_id,
        status=status,
        result=safe_result,
        error=safe_error,
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
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def list_audit_logs(
    request: Request,
    action: str | None = Query(default=None, max_length=100),
    actor_email: str | None = Query(default=None, max_length=255),
    entity_type: str | None = Query(default=None, max_length=50),
    date_from: date | None = None,
    date_to: date | None = None,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    if date_from and date_to and date_from > date_to:
        raise ValidationError("date_from cannot be after date_to.")

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
@limiter.limit("5/minute", key_func=get_user_or_ip_key)
def export_audit_logs(
    request: Request,
    data: AuditLogExportRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    job_id = AuditService(db).queue_export(
        user.company_id,
        actor=user,
        action=data.action,
        actor_email=data.actor_email,
        entity_type=data.entity_type,
        date_from=data.date_from,
        date_to=data.date_to,
    )
    return JobQueuedResponse(job_id=job_id)


@audit_logs_router.get("/export/{job_id}/download")
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def download_audit_logs_export(
    job_id: str,
    request: Request,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    try:
        uuid.UUID(job_id)
    except (ValueError, TypeError, AttributeError):
        raise NotFoundError("Export not found.") from None

    job_meta = get_registered_job(job_id)
    if not job_meta:
        raise NotFoundError("Export not found.")

    if user.role != UserRole.super_admin:
        if job_meta.get("company_id") != str(user.company_id):
            raise NotFoundError("Export not found.")
        is_starter = job_meta.get("user_id") and str(user.id) == str(job_meta.get("user_id"))
        is_hr_level = user.role in HR_LEVEL_ROLES
        if not (is_starter or is_hr_level):
            raise NotFoundError("Export not found.")

    async_result = celery_app.AsyncResult(job_id)
    if async_result.state != "SUCCESS":
        raise NotFoundError("Export not found or still processing.")

    result = async_result.result
    if not isinstance(result, dict):
        raise NotFoundError("Export data not found.")

    file_path = result.get("file_path")
    expires_at_str = result.get("expires_at")
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.now(UTC) > expires_at:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
            raise NotFoundError("Export file has expired.")

    if not file_path or not os.path.exists(file_path):
        raise NotFoundError("Export file not found on disk.")

    resolved_path = Path(file_path).resolve()
    export_dir_resolved = Path(settings.EXPORT_DIR).resolve()
    if not resolved_path.is_relative_to(export_dir_resolved):
        raise NotFoundError("Export not found.")

    file_name = f"audit_logs_{datetime.now(UTC).strftime('%Y-%m-%d')}.csv"

    AuditService(db).record(
        company_id=user.company_id,
        actor=user,
        action="AUDIT_EXPORT_DOWNLOADED",
        entity_type="audit_log",
        entity_id=None,
        details={"job_id": job_id, "file_name": file_name},
    )
    db.commit()

    return FileResponse(
        path=str(resolved_path),
        filename=file_name,
        media_type="text/csv",
        headers={"Cache-Control": "no-store"},
    )


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
    file_obj = FileService(db).upload_file(
        user.company_id,
        user.id,
        file.filename or "file",
        file.content_type or "application/octet-stream",
        file_bytes,
    )
    return FileUploadResponse(
        file_object_id=file_obj.id,
        file_name=file_obj.file_name,
        file_type=file_obj.file_type,
        file_size=file_obj.file_size,
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
    import hashlib
    import hmac
    import os

    from fastapi.responses import FileResponse

    from app.core.config import settings

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
    expected_sig = hmac.new(
        settings.SECRET_KEY.encode(), signature_payload, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_sig, signature):
        from app.core.exceptions import ForbiddenError

        raise ForbiddenError("Invalid file signature.")

    if not os.path.exists(file_obj.storage_path):
        raise NotFoundError("File not found on disk.")

    return FileResponse(
        path=file_obj.storage_path, filename=file_obj.file_name, media_type=file_obj.file_type
    )


# ── Employee Documents (routes 132-133) ─────────────────────────
documents_router = APIRouter(prefix="/documents", tags=["Employee Documents"])


@documents_router.get("/{employee_id}", response_model=list[EmployeeDocumentResponse])
def list_employee_documents(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return EmployeeDocumentService(db).list_documents(user.company_id, employee_id, user)


@documents_router.post("/{employee_id}", response_model=EmployeeDocumentResponse, status_code=201)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def upload_employee_document(
    request: Request,
    employee_id: uuid.UUID,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    # 1. Access check
    is_hr_level = user.role in HR_LEVEL_ROLES
    if not is_hr_level:
        caller_emp = EmployeeRepository(db).get_by_user_id(user.company_id, user.id)
        if caller_emp is None or caller_emp.id != employee_id:
            raise ForbiddenError(
                "You do not have permission to upload documents for this employee."
            )

    # 2. Validate document_type and name
    clean_type = document_type.strip()
    if clean_type not in VALID_DOCUMENT_TYPES:
        valid_str = ", ".join(sorted(VALID_DOCUMENT_TYPES))
        raise ValidationError(
            f"Invalid document_type '{document_type}'. Must be one of: {valid_str}"
        )

    clean_doc_name = name.strip()
    if not clean_doc_name or len(clean_doc_name) > 255:
        raise ValidationError("Document name must be between 1 and 255 characters.")

    # 3. Early size check: Content-Length header
    max_mb = getattr(settings, "MAX_UPLOAD_MB", 10)
    max_bytes = max_mb * 1024 * 1024
    content_length_header = request.headers.get("content-length")
    if content_length_header:
        try:
            cl = int(content_length_header)
            if cl > (max_mb + 1) * 1024 * 1024:
                raise PayloadTooLargeError(
                    f"File size exceeds maximum upload limit of {max_mb} MB."
                )
        except ValueError:
            pass

    # Read file in 1 MB chunks and abort if exceeding max_bytes
    chunks = []
    total_read = 0
    file_obj_stream = file.file
    while True:
        chunk = file_obj_stream.read(1024 * 1024)
        if not chunk:
            break
        total_read += len(chunk)
        if total_read > max_bytes:
            raise PayloadTooLargeError(f"File size exceeds maximum upload limit of {max_mb} MB.")
        chunks.append(chunk)

    file_bytes = b"".join(chunks)

    # 4. Content & magic-byte validation
    clean_filename, extension, canonical_content_type = validate_document_upload(
        file.filename or "file", file_bytes
    )

    # 5. Lock employee row and verify tenant
    emp_repo = EmployeeRepository(db)
    target_emp = emp_repo.get_by_id_for_update(employee_id, user.company_id, allow_inactive=True)
    if target_emp is None:
        if not is_hr_level:
            raise ForbiddenError(
                "You do not have permission to upload documents for this employee."
            )
        raise NotFoundError("Employee not found.")

    # 6. Check cap 30 non-deleted documents
    doc_repo = EmployeeDocumentRepository(db)
    active_count = doc_repo.count_active_for_employee(user.company_id, employee_id)
    if active_count >= 30:
        raise ConflictError("Employee has reached maximum document limit of 30.")

    # 7. Write file to disk under random uuid4 hex name
    docs_base_path = Path(
        getattr(settings, "EMPLOYEE_DOCS_DIR", "var/employee_documents")
    ).resolve()
    company_docs_dir = docs_base_path / str(user.company_id)
    company_docs_dir.mkdir(parents=True, exist_ok=True)

    random_file_name = f"{uuid.uuid4().hex}.{extension}"
    target_path = (company_docs_dir / random_file_name).resolve()

    # Containment check where file is written
    if not target_path.is_relative_to(docs_base_path):
        logger.warning("Attempted path traversal when writing employee document")
        raise ForbiddenError("Invalid file destination path.")

    storage_path = str(target_path)

    written_to_disk = False
    try:
        with open(storage_path, "wb") as f:
            f.write(file_bytes)
        written_to_disk = True

        file_repo = FileRepository(db)
        file_obj = file_repo.create(
            company_id=user.company_id,
            uploaded_by=user.id,
            file_name=clean_filename,
            file_type=canonical_content_type,
            file_size=len(file_bytes),
            storage_path=storage_path,
        )

        doc = doc_repo.create(
            company_id=user.company_id,
            employee_id=employee_id,
            file_object_id=file_obj.id,
            document_type=clean_type,
            name=clean_doc_name,
        )

        AuditService(db).record(
            company_id=user.company_id,
            actor=user,
            action="EMPLOYEE_DOCUMENT_UPLOADED",
            entity_type="employee_document",
            entity_id=doc.id,
            details={
                "employee_id": str(employee_id),
                "document_id": str(doc.id),
                "document_type": clean_type,
            },
        )
        db.commit()
        db.refresh(doc)

        resp = EmployeeDocumentResponse.model_validate(doc)
        resp.download_url = f"/api/v1/documents/{employee_id}/{doc.id}/download"
        return resp
    except Exception:
        db.rollback()
        if written_to_disk and os.path.exists(storage_path):
            try:
                os.remove(storage_path)
            except OSError:
                pass
        raise


@documents_router.get(
    "/{employee_id}/{document_id}/download",
)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def download_employee_document(
    request: Request,
    employee_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    # Access check (same as viewing)
    is_hr_level = user.role in HR_LEVEL_ROLES
    if not is_hr_level:
        caller_emp = EmployeeRepository(db).get_by_user_id(user.company_id, user.id)
        if caller_emp is None or caller_emp.id != employee_id:
            raise ForbiddenError(
                "You do not have permission to download this employee's documents."
            )

    target_emp = EmployeeRepository(db).get_by_id_any_status(employee_id, user.company_id)
    if target_emp is None:
        if not is_hr_level:
            raise ForbiddenError(
                "You do not have permission to download this employee's documents."
            )
        raise NotFoundError("Employee not found.")

    doc_repo = EmployeeDocumentRepository(db)
    doc = doc_repo.get_by_id(user.company_id, employee_id, document_id)
    if not doc:
        raise NotFoundError("Document not found.")

    file_obj = FileRepository(db).get_by_id(user.company_id, doc.file_object_id)
    if not file_obj or not os.path.exists(file_obj.storage_path):
        raise NotFoundError("Document file not found.")

    # Path traversal protection: ensure stored path is strictly inside EMPLOYEE_DOCS_DIR
    docs_base_path = Path(
        getattr(settings, "EMPLOYEE_DOCS_DIR", "var/employee_documents")
    ).resolve()
    resolved_path = Path(file_obj.storage_path).resolve()
    if not resolved_path.is_relative_to(docs_base_path):
        logger.warning("Potential path traversal detected in employee document download")
        raise NotFoundError("Document not found.")

    # Audit download before returning
    AuditService(db).record(
        company_id=user.company_id,
        actor=user,
        action="EMPLOYEE_DOCUMENT_DOWNLOADED",
        entity_type="employee_document",
        entity_id=doc.id,
        details={
            "employee_id": str(employee_id),
            "document_id": str(doc.id),
            "document_type": doc.document_type,
        },
    )
    db.commit()

    return FileResponse(
        path=resolved_path,
        filename=file_obj.file_name,
        media_type=file_obj.file_type,
        content_disposition_type="attachment",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@documents_router.delete(
    "/{employee_id}/{document_id}",
    status_code=204,
)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def delete_employee_document(
    request: Request,
    employee_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(*HR_LEVEL_ROLES)),
):
    target_emp = EmployeeRepository(db).get_by_id_any_status(employee_id, user.company_id)
    if target_emp is None:
        raise NotFoundError("Employee not found.")

    doc_repo = EmployeeDocumentRepository(db)
    doc = doc_repo.get_by_id(user.company_id, employee_id, document_id)
    if not doc:
        raise NotFoundError("Document not found.")

    doc.deleted_at = datetime.now(UTC)

    AuditService(db).record(
        company_id=user.company_id,
        actor=user,
        action="EMPLOYEE_DOCUMENT_DELETED",
        entity_type="employee_document",
        entity_id=doc.id,
        details={
            "employee_id": str(employee_id),
            "document_id": str(doc.id),
            "document_type": doc.document_type,
        },
    )
    db.commit()


# ── Global Search (route 134) ───────────────────────────────────
search_router = APIRouter(prefix="/search", tags=["Global Search"])


@search_router.get("", response_model=GlobalSearchResponse)
def global_search(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return GlobalSearchService(db).search(user.company_id, q)
