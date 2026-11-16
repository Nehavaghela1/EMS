import logging
import unicodedata
import uuid
from calendar import monthrange
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit_context import audit_context_var
from app.core.cache import delete_by_prefix, get_json, set_json
from app.core.config import settings
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.pagination import PageParams
from app.core.regions import (
    COUNTRY_REGIONS_MAP,
    allowed_country_codes,
    canonical_country,
    canonical_state,
    country_name,
    is_payroll_ready,
)
from app.core.roles import HR_LEVEL_ROLES
from app.core.time import utcnow
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole
from app.modules.identity.repository import UserRepository
from app.modules.payroll.models import PayrollRunStatus, TaxRegime
from app.modules.payroll.repository import (
    PtSlabRepository,
    StatutoryRateRepository,
    TaxSlabRepository,
)
from app.modules.payroll.schemas import (
    PtSlabPutRequest,
    PtSlabResponse,
    StatutoryRateCreateRequest,
    StatutoryRateResponse,
    TaxSlabPostRequest,
    TaxSlabResponse,
)
from app.modules.platform.models import (
    Announcement,
    AuditLog,
    FileObject,
    Notification,
    RateChangeDraft,
    RateSource,
)
from app.modules.platform.rate_fetcher import PageFetcher, content_hash
from app.modules.platform.repository import (
    AuditRepository,
    DashboardRepository,
    IndustryPresetRepository,
    NotificationRepository,
    PayrollStatsRepository,
    RateDraftRepository,
    RateReminderRepository,
    RateSourceRepository,
)
from app.modules.platform.schemas import (
    AnnouncementCreate,
    EmployeeDocumentResponse,
    GlobalSearchResponse,
    PayrollMonthStats,
    RateDraftCreate,
    RateDraftCurrent,
    RateDraftDetail,
    RateDraftReject,
    RateDraftResponse,
    RateDraftSource,
    RateDraftUpdate,
    RateDraftVerify,
    RateSourceCreate,
    RateSourceUpdate,
    RegionResponse,
    SearchResultItem,
    SignedUrlResponse,
)
from app.modules.time_leave.repository import LeaveTypeRepository

# Fields that must never reach `audit_logs.details` (Spec 7.8, CLAUDE.md
# rule 10). Callers are expected to whitelist fields themselves (never pass
# a whole model's __dict__) — this is the backstop that makes a mistake
# there fail loudly instead of silently leaking.
_BANNED_DETAIL_KEYS = {
    "password",
    "hashed_password",
    "raw_password",
    "token",
    "raw_token",
    "activation_token_hash",
    "refresh_token",
    "access_token",
    "aadhaar",
    "aadhaar_number",
    "pan",
    "pan_number",
    "bank_account",
    "bank_account_number",
    "bank_details",
    "ifsc",
    "otp",
    "secret",
    "client_secret",
    "api_key",
    "authorization",
    "card_number",
    "cvv",
    "password_hash",
}


class UnsafeAuditDetailsError(AppError):
    """Raised, never swallowed: a caller tried to write a banned field into
    an append-only audit row. A caller-side bug here must fail the request,
    not silently record the secret (Spec 7.8, CLAUDE.md rule 10)."""

    status_code = 500
    code = "unsafe_audit_details"


def _assert_details_safe(details: Any) -> None:
    if details is None:
        return
    if isinstance(details, dict):
        for key, value in details.items():
            if str(key).lower() in _BANNED_DETAIL_KEYS:
                raise UnsafeAuditDetailsError(
                    "Refusing to write a sensitive field to audit_logs.details.",
                    details={"field": str(key)},
                )
            _assert_details_safe(value)
    elif isinstance(details, (list, tuple, set)):
        for item in details:
            _assert_details_safe(item)


class IndustryPresetService:
    """WP-14: backs the public `GET /industry-presets` list the company
    registration frontend page needs (Spec 14.3 page 2) — no route number
    exists for this in Section 10's table (spec gap, recorded in
    RECONCILIATION.md rather than inventing one)."""

    def __init__(self, db: Session):
        self.repo = IndustryPresetRepository(db)

    def list_names(self) -> list[str]:
        return [preset.industry_name for preset in self.repo.list_all()]


class AuditService:
    """Writes are always made inside the CALLING service's own transaction
    (create+flush, never commit — Spec 6.7/6.8) so the audit row and the
    mutation it describes succeed or fail together atomically."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = AuditRepository(db)

    def record(
        self,
        *,
        company_id: uuid.UUID | None,
        actor: User | None,
        action: str,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """`details` must be a small, explicit, whitelisted dict the caller
        builds field-by-field — never a model's `__dict__` or `model_dump()`
        wholesale, which is exactly how a token hash or bank field would
        leak in. `_assert_details_safe` is the backstop, not the primary
        control.
        """
        safe_details = jsonable(details) if details is not None else None
        _assert_details_safe(safe_details)
        ctx = audit_context_var.get()
        ip_addr = ctx.ip_address if ctx else None
        ua = ctx.user_agent if ctx else None
        req_id = ctx.request_id if ctx else None

        return self.repo.create(
            company_id=company_id,
            actor_user_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=safe_details,
            ip_address=ip_addr,
            user_agent=ua,
            request_id=req_id,
        )

    def list_audit_logs(
        self,
        company_id: uuid.UUID,
        *,
        action: str | None,
        actor_email: str | None,
        entity_type: str | None,
        date_from: date | None,
        date_to: date | None,
        page_params: PageParams,
    ) -> tuple[list[AuditLog], int, int]:
        """Route 128, HR only."""
        return self.repo.list_for_company(
            company_id=company_id,
            action=action,
            actor_email=actor_email,
            entity_type=entity_type,
            date_from=date_from,
            date_to=date_to,
            page_params=page_params,
        )

    def queue_export(
        self,
        company_id: uuid.UUID,
        *,
        actor: User,
        action: str | None,
        actor_email: str | None,
        entity_type: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> str:
        """Route 129: queues the real Celery job (13.1)."""
        from app.core.jobs import register_job
        from app.workers.tasks.platform import export_audit_logs_csv_task

        task = export_audit_logs_csv_task.delay(
            company_id=str(company_id),
            requester_id=str(actor.id),
            action=action,
            actor_email=actor_email,
            entity_type=entity_type,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
        )

        register_job(
            task.id,
            company_id=company_id,
            user_id=actor.id,
            kind="audit_logs_export",
        )

        used_filters = []
        if action is not None:
            used_filters.append("action")
        if actor_email is not None:
            used_filters.append("actor_email")
        if entity_type is not None:
            used_filters.append("entity_type")
        if date_from is not None:
            used_filters.append("date_from")
        if date_to is not None:
            used_filters.append("date_to")

        audit_details: dict[str, Any] = {"filters": used_filters}
        if date_from is not None:
            audit_details["date_from"] = date_from.isoformat()
        if date_to is not None:
            audit_details["date_to"] = date_to.isoformat()

        self.record(
            company_id=company_id,
            actor=actor,
            action="AUDIT_EXPORT_REQUESTED",
            entity_type="audit_log",
            entity_id=None,
            details=audit_details,
        )
        self.db.commit()

        return task.id


def _dashboard_cache_key(company_id: uuid.UUID, user_id: uuid.UUID, role: UserRole) -> str:
    return f"dashboard:{company_id}:{user_id}:{role.value}"


def jsonable(value: Any) -> Any:
    """Everything cached in Redis must round-trip through json.dumps —
    Decimal, date/datetime and UUID don't by default (Spec 11.1's Decimal
    rule doesn't stop applying just because this is a read-only summary)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value


class DashboardService:
    """Route 121 (Spec 11.10). One role-shaped payload, cached in Redis for
    DASHBOARD_CACHE_TTL_SECONDS under a key scoped to company + user + role."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = DashboardRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.leave_type_repo = LeaveTypeRepository(db)

    def get_dashboard(self, company_id: uuid.UUID, user: User) -> dict[str, Any]:
        cache_key = _dashboard_cache_key(company_id, user.id, user.role)
        cached = get_json(cache_key)
        if cached is not None:
            return cached

        today = utcnow().date()
        if user.role == UserRole.super_admin:
            data = self._super_admin_data()
        elif user.role in (UserRole.hr_admin, UserRole.owner):
            data = self._hr_admin_data(company_id, today)
        elif user.role == UserRole.manager:
            data = self._manager_data(company_id, user, today)
        else:
            data = self._employee_data(company_id, user, today)

        payload = {
            "role": user.role.value,
            "generated_at": utcnow().isoformat(),
            "data": jsonable(data),
        }
        set_json(cache_key, payload, ttl_seconds=settings.DASHBOARD_CACHE_TTL_SECONDS)
        return payload

    @staticmethod
    def invalidate_company_dashboards(company_id: uuid.UUID) -> None:
        """Spec 11.10: on attendance mark, leave approval, and employee
        create/deactivate, delete the company's dashboard keys — every
        role/user combination cached under this company, not just the
        caller's own."""
        delete_by_prefix(f"dashboard:{company_id}:")

    def _super_admin_data(self) -> dict[str, Any]:
        counts = self.repo.company_counts_by_status()
        return {
            "company_counts_by_status": counts,
            "pending_approvals": counts.get("pending", 0),
            "platform_user_count": self.repo.platform_user_count(),
        }

    def _hr_admin_data(self, company_id: uuid.UUID, today: date) -> dict[str, Any]:
        return {
            "headcount": self.repo.headcount(company_id),
            "present_today": self.repo.present_today(company_id, today),
            "on_leave_today": self.repo.on_leave_today(company_id, today),
            "pending_leave_requests": self.repo.pending_leave_requests(company_id),
            # No `reimbursements`/`payroll_runs` table exists yet (out of
            # scope this session) — see RECONCILIATION for the forward
            # dependency this leaves for the payroll/reimbursement WPs.
            "pending_reimbursements": 0,
            "recent_hires": [
                {
                    "id": e.id,
                    "first_name": e.first_name,
                    "last_name": e.last_name,
                    "hire_date": e.hire_date,
                }
                for e in self.repo.recent_hires(company_id)
            ],
            "department_distribution": self.repo.department_distribution(company_id),
            "last_payroll_run": None,
        }

    def _manager_data(self, company_id: uuid.UUID, user: User, today: date) -> dict[str, Any]:
        caller_employee = self.employee_repo.get_by_user_id(company_id, user.id)
        employee_ids = (
            self.employee_repo.list_direct_report_ids(company_id, caller_employee.id)
            if caller_employee is not None
            else []
        )
        return {
            "team_headcount": self.repo.team_headcount(company_id, employee_ids),
            "team_present_today": self.repo.team_present_today(company_id, employee_ids, today),
            "team_leave_requests_awaiting": self.repo.team_leave_requests_awaiting(
                company_id, employee_ids
            ),
            # No `tasks` table exists yet (Projects module, out of scope
            # this session) — see RECONCILIATION.
            "team_task_load": 0,
        }

    def _employee_data(self, company_id: uuid.UUID, user: User, today: date) -> dict[str, Any]:
        employee = self.employee_repo.get_by_user_id(company_id, user.id)
        if employee is None:
            return {
                "attendance_this_month": {},
                "leave_balances": [],
                "pending_requests": 0,
                "latest_payslip_status": None,
                "assigned_open_tasks": 0,
            }
        month_start = today.replace(day=1)
        balances = []
        for balance in self.repo.own_leave_balances(company_id, employee.id, today.year):
            leave_type = self.leave_type_repo.get_by_id(balance.leave_type_id, company_id)
            available = (
                balance.opening_balance + balance.allocated - balance.used - balance.encashed
            )
            balances.append(
                {
                    "leave_type_id": balance.leave_type_id,
                    "leave_type_name": leave_type.name if leave_type else None,
                    "available": available,
                }
            )
        return {
            "attendance_this_month": self.repo.own_attendance_summary(
                company_id, employee.id, month_start, today
            ),
            "leave_balances": balances,
            "pending_requests": self.repo.own_pending_requests(company_id, employee.id),
            # No `payroll_runs`/`tasks` tables exist yet — see RECONCILIATION.
            "latest_payslip_status": None,
            "assigned_open_tasks": 0,
        }


logger = logging.getLogger(__name__)


def _clean_action_url(action_url: str | None) -> str | None:
    if action_url is None:
        return None
    if not action_url.startswith("/") or action_url.startswith("//"):
        logger.warning("Rejected invalid notification action_url: %s", action_url)
        return None
    if ":" in action_url or "\\" in action_url:
        logger.warning("Rejected notification action_url with scheme or backslash: %s", action_url)
        return None
    if any(c.isspace() or unicodedata.category(c).startswith("C") for c in action_url):
        logger.warning(
            "Rejected notification action_url with spaces or control characters: %s",
            action_url,
        )
        return None
    return action_url


class NotificationService:
    """Routes 125-127 (Spec 7.8, 10.8). In-app only — no email, no SMS."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = NotificationRepository(db)

    def notify(
        self,
        *,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        type: str,
        title: str,
        message: str,
        action_url: str | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> Notification:
        """Create+flush only (Spec 6.7) — called from inside the mutating
        service's own transaction, which commits once at the end."""
        clean_url = _clean_action_url(action_url)
        return self.repo.create(
            company_id=company_id,
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            action_url=clean_url,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    def list_notifications(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        unread_only: bool,
        page_params: PageParams,
    ) -> tuple[list[Notification], int, int, int]:
        """Route 125. Returns (items, total, pages, unread_count) — the
        count is computed alongside the list rather than adding a route the
        spec's table (10.8) doesn't have room for."""
        items, total, pages = self.repo.list_for_user(
            company_id=company_id, user_id=user_id, unread_only=unread_only, page_params=page_params
        )
        unread_count = self.repo.unread_count(company_id, user_id)
        return items, total, pages, unread_count

    def mark_read(
        self, company_id: uuid.UUID, user_id: uuid.UUID, notification_id: uuid.UUID
    ) -> Notification:
        """Route 126."""
        notification = self.repo.get_by_id(notification_id, company_id, user_id)
        if notification is None:
            raise NotFoundError("Notification not found.")
        self.repo.mark_read(notification)
        self.db.commit()
        return notification

    def mark_all_read(self, company_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """Route 127."""
        count = self.repo.mark_all_read(company_id, user_id)
        self.db.commit()
        return count


class AnnouncementService:
    def __init__(self, db: Session):
        self.db = db
        from app.modules.platform.repository import AnnouncementRepository

        self.repo = AnnouncementRepository(db)

    def create(self, company_id: uuid.UUID, user: User, data: AnnouncementCreate) -> Announcement:
        from app.modules.hr.models import Department, Employee

        is_hr_level = user.role in HR_LEVEL_ROLES
        caller_emp = (
            self.db.query(Employee)
            .filter(
                Employee.company_id == company_id,
                Employee.user_id == user.id,
                Employee.deleted_at.is_(None),
            )
            .first()
        )

        if not is_hr_level:
            if user.role != UserRole.manager:
                raise ForbiddenError("Only HR-level roles and managers can create announcements.")
            if data.department_id is None:
                raise ForbiddenError("Managers must specify a department for announcements.")
            if caller_emp is None:
                raise ForbiddenError("Manager must have an active employee record.")

        if data.department_id is not None:
            dept = (
                self.db.query(Department)
                .filter(
                    Department.id == data.department_id,
                    Department.company_id == company_id,
                    Department.deleted_at.is_(None),
                )
                .first()
            )
            if not dept:
                raise NotFoundError("Department not found.")

            if not is_hr_level:
                assert caller_emp is not None
                is_own = caller_emp.department_id == dept.id
                is_head = dept.head_employee_id == caller_emp.id
                if not (is_own or is_head):
                    raise ForbiddenError(
                        "Managers can only post to their own department or a department they head."
                    )

        announcement = self.repo.create(
            company_id=company_id,
            created_by=user.id,
            title=data.title,
            content=data.content,
            target_role=data.target_role,
            expires_at=data.expires_at,
            department_id=data.department_id,
        )

        audience_kind = (
            "department"
            if data.department_id is not None
            else ("role" if data.target_role != "all" else "company")
        )
        AuditService(self.db).record(
            company_id=company_id,
            actor=user,
            action="ANNOUNCEMENT_CREATED",
            entity_type="announcement",
            entity_id=announcement.id,
            details={
                "announcement_id": str(announcement.id),
                "audience_kind": audience_kind,
                "department_id": str(data.department_id) if data.department_id else None,
            },
        )
        self.db.commit()
        self.db.refresh(announcement)
        return announcement

    def list_active(self, company_id: uuid.UUID, user: User) -> list[Announcement]:
        from app.modules.hr.models import Employee

        caller_dept_id = None
        if user.role not in HR_LEVEL_ROLES:
            caller_emp = (
                self.db.query(Employee)
                .filter(
                    Employee.company_id == company_id,
                    Employee.user_id == user.id,
                    Employee.deleted_at.is_(None),
                )
                .first()
            )
            if caller_emp and caller_emp.department_id:
                from app.modules.hr.models import Department

                active_dept = (
                    self.db.query(Department)
                    .filter(
                        Department.id == caller_emp.department_id,
                        Department.company_id == company_id,
                        Department.deleted_at.is_(None),
                    )
                    .first()
                )
                if active_dept:
                    caller_dept_id = active_dept.id

        return self.repo.list_active(
            company_id=company_id,
            user=user,
            caller_department_id=caller_dept_id,
        )

    def delete(self, company_id: uuid.UUID, announcement_id: uuid.UUID, user: User) -> None:
        announcement = self.repo.get_by_id(company_id, announcement_id)
        if not announcement:
            raise NotFoundError("Announcement not found.")

        is_hr_level = user.role in HR_LEVEL_ROLES
        is_poster = announcement.created_by == user.id
        if not (is_hr_level or is_poster):
            raise NotFoundError("Announcement not found.")

        self.repo.soft_delete(announcement)
        AuditService(self.db).record(
            company_id=company_id,
            actor=user,
            action="ANNOUNCEMENT_DELETED",
            entity_type="announcement",
            entity_id=announcement.id,
            details={"announcement_id": str(announcement.id)},
        )
        self.db.commit()


SIGNED_URL_TTL_SECONDS = 600
MAX_FILE_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


class FileService:
    def __init__(self, db: Session):
        self.db = db
        from app.modules.platform.repository import FileRepository

        self.repo = FileRepository(db)

    def can_access(self, company_id: uuid.UUID, user: User, file_obj: FileObject) -> bool:
        if file_obj.uploaded_by is not None and file_obj.uploaded_by == user.id:
            return True
        if user.role in HR_LEVEL_ROLES:
            return True

        from app.modules.hr.models import Employee
        from app.modules.projects.models import Project, ProjectDocument, ProjectMember

        pdocs = (
            self.db.query(ProjectDocument)
            .filter(
                ProjectDocument.company_id == company_id,
                ProjectDocument.file_id == file_obj.id,
            )
            .all()
        )
        if not pdocs:
            return False

        employee = (
            self.db.query(Employee)
            .filter(Employee.company_id == company_id, Employee.user_id == user.id)
            .first()
        )
        if not employee:
            return False

        for pdoc in pdocs:
            proj = (
                self.db.query(Project)
                .filter(Project.id == pdoc.project_id, Project.company_id == company_id)
                .first()
            )
            if proj and proj.manager_id == employee.id:
                return True

            is_member = (
                self.db.query(ProjectMember)
                .filter(
                    ProjectMember.company_id == company_id,
                    ProjectMember.project_id == pdoc.project_id,
                    ProjectMember.employee_id == employee.id,
                )
                .first()
                is not None
            )
            if is_member:
                return True

        return False

    def upload_file(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        file_name: str,
        file_type: str,
        file_bytes: bytes,
        actor: User | None = None,
    ) -> FileObject:
        from pathlib import Path

        from app.core.exceptions import PayloadTooLargeError
        from app.core.upload_validation import validate_document_upload

        if len(file_bytes) > MAX_FILE_UPLOAD_BYTES:
            raise PayloadTooLargeError("File size exceeds maximum upload limit of 25 MB.")

        clean_name, ext, canonical_content_type = validate_document_upload(file_name, file_bytes)

        upload_root = Path(settings.UPLOAD_DIR).resolve()
        company_dir = (upload_root / str(company_id)).resolve()
        company_dir.mkdir(parents=True, exist_ok=True)

        random_filename = f"{uuid.uuid4().hex}.{ext}"
        target_path = (company_dir / random_filename).resolve()
        if not target_path.is_relative_to(upload_root):
            raise AppError("Invalid file storage path.")

        with open(target_path, "wb") as f:
            f.write(file_bytes)

        file_obj = self.repo.create(
            company_id=company_id,
            uploaded_by=user_id,
            file_name=clean_name,
            file_type=canonical_content_type,
            file_size=len(file_bytes),
            storage_path=str(target_path),
        )

        AuditService(self.db).record(
            company_id=company_id,
            actor=actor,
            action="FILE_UPLOADED",
            entity_type="file_object",
            entity_id=file_obj.id,
            details={
                "file_id": str(file_obj.id),
                "file_size": file_obj.file_size,
                "file_type": file_obj.file_type,
            },
        )
        self.db.commit()
        self.db.refresh(file_obj)
        return file_obj

    def build_signed_url(self, company_id: uuid.UUID, file_id: uuid.UUID) -> str:
        """Constructs a signed download URL without access checks or audit logging."""
        import hashlib
        import hmac

        expires_at = int(datetime.now(UTC).timestamp()) + SIGNED_URL_TTL_SECONDS
        signature_payload = f"{company_id}:{file_id}:{expires_at}".encode()
        signature = hmac.new(
            settings.SECRET_KEY.encode(), signature_payload, hashlib.sha256
        ).hexdigest()
        return f"/api/v1/files/download/{file_id}?expires={expires_at}&signature={signature}"

    def generate_signed_url(
        self,
        company_id: uuid.UUID,
        file_id: uuid.UUID,
        user: User,
    ) -> SignedUrlResponse:
        file_obj = self.repo.get_by_id(company_id, file_id)
        if not file_obj:
            raise NotFoundError("File object not found.")

        from app.modules.platform.repository import EmployeeDocumentRepository

        if EmployeeDocumentRepository(self.db).is_file_attached_to_employee_document(file_id):
            raise NotFoundError("File object not found.")

        if not self.can_access(company_id, user, file_obj):
            raise NotFoundError("File object not found.")

        url = self.build_signed_url(company_id, file_id)

        AuditService(self.db).record(
            company_id=company_id,
            actor=user,
            action="FILE_LINK_ISSUED",
            entity_type="file_object",
            entity_id=file_obj.id,
            details={"file_id": str(file_obj.id)},
        )
        self.db.commit()

        return SignedUrlResponse(
            file_object_id=file_obj.id,
            file_name=file_obj.file_name,
            url=url,
            expires_in_seconds=SIGNED_URL_TTL_SECONDS,
        )


class EmployeeDocumentService:
    def __init__(self, db: Session):
        self.db = db
        from app.modules.platform.repository import EmployeeDocumentRepository

        self.repo = EmployeeDocumentRepository(db)

    def list_documents(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, caller: User
    ) -> list[EmployeeDocumentResponse]:
        if caller.role not in HR_LEVEL_ROLES:
            caller_employee = EmployeeRepository(self.db).get_by_user_id(company_id, caller.id)
            if caller_employee is None or employee_id != caller_employee.id:
                raise ForbiddenError(
                    "You do not have permission to view this employee's documents."
                )

        target_employee = EmployeeRepository(self.db).get_by_id_any_status(employee_id, company_id)
        if target_employee is None:
            if caller.role not in HR_LEVEL_ROLES:
                raise ForbiddenError(
                    "You do not have permission to view this employee's documents."
                )
            raise NotFoundError("Employee not found.")

        docs = self.repo.list_for_employee(company_id, employee_id)
        results = []
        for doc in docs:
            resp = EmployeeDocumentResponse.model_validate(doc)
            # Design 9: Stop generating signed links; set download_url to the relative route path
            resp.download_url = f"/api/v1/documents/{employee_id}/{doc.id}/download"
            results.append(resp)
        return results


class RegionService:
    """`GET /regions`: the one shared country and state list (5.2)."""

    @staticmethod
    def list_regions() -> list[RegionResponse]:
        return [
            RegionResponse(
                code=code,
                name=entry["name"],
                payroll_ready=is_payroll_ready(code),
                states=list(entry["states"]),
            )
            for code, entry in COUNTRY_REGIONS_MAP.items()
        ]


MAX_STATS_MONTHS = 24


def _month_key(value: str) -> tuple[int, int]:
    year, month = value.split("-")
    return int(year), int(month)


class PayrollStatsService:
    """`GET /platform/payroll-stats` (5.8): per-month payroll totals across all companies, for
    the platform's own view. No company, no person, no per-company amount."""

    def __init__(self, db: Session):
        self.repo = PayrollStatsRepository(db)

    def stats(self, from_month: str, to_month: str) -> list[PayrollMonthStats]:
        first_year, first_month = _month_key(from_month)
        last_year, last_month = _month_key(to_month)
        first = first_year * 12 + first_month
        last = last_year * 12 + last_month
        if first > last:
            raise ValidationError("'from' must not be after 'to'.", details={"field": "from"})
        if last - first + 1 > MAX_STATS_MONTHS:
            raise ValidationError(
                f"At most {MAX_STATS_MONTHS} months can be asked for at once.",
                details={"field": "to"},
            )
        by_status = self.repo.runs_by_status(first, last)
        companies = self.repo.companies_with_runs(first, last)
        employees = self.repo.employees_paid(first, last)
        totals = self.repo.total_net_paid(first, last)
        result = []
        for key in range(first, last + 1):
            year, month = divmod(key - 1, 12)
            month += 1
            slot = (year, month)
            statuses = {s.value: by_status.get((year, month, s.value), 0) for s in PayrollRunStatus}
            result.append(
                PayrollMonthStats(
                    month=f"{year}-{month:02d}",
                    companies_with_runs=companies.get(slot, 0),
                    runs_total=sum(statuses.values()),
                    runs_by_status=statuses,
                    employees_paid=employees.get(slot, 0),
                    total_net_paid=totals.get(slot, Decimal("0")).quantize(Decimal("0.01")),
                )
            )
        return result


# --- 5.9 platform rate updates ------------------------------------------------------------

FAILED_CHECK_RETRY_DAYS = 7
STALE_RATE_DAYS = 180
REMINDER_GAP_DAYS = 30
DRAFT_CREATED_NOTICE = "rate_draft_created"
CHECK_FAILED_NOTICE = "rate_check_failed"
VERIFICATION_DUE_NOTICE = "rate_verification_due"


def add_months(day: date, months: int) -> date:
    """`day` plus whole months; the day of month is cut back to the last day when needed."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, monthrange(year, month)[1]))


def _listed_country(code: str) -> str:
    country = canonical_country(code)
    if country is None:
        raise ValidationError(
            f"Country must be one of: {allowed_country_codes()}.", details={"field": "country"}
        )
    return country


def _listed_state(country: str, state: str | None) -> str | None:
    if state is None:
        return None
    canonical = canonical_state(country, state)
    if canonical is None:
        raise ValidationError(
            f"The state must be one of the states of {country_name(country)} in the shared list.",
            details={"field": "state"},
        )
    return canonical


class RateSourceService:
    """`/platform/rate-sources`: the pages the daily check reads (super admin only)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = RateSourceRepository(db)
        self.audit = AuditService(db)

    def list_sources(self, page_params: PageParams):
        return self.repo.list_sources(page_params)

    def create(self, data: RateSourceCreate, actor: User) -> RateSource:
        country = _listed_country(data.country)
        state = _listed_state(country, data.state)
        if self.repo.get_by_key(country, state, data.scheme_group, data.source_url) is not None:
            raise ConflictError(DUPLICATE_SOURCE_MESSAGE)
        try:
            source = self.repo.create(
                country=country,
                state=state,
                scheme_group=data.scheme_group,
                title=data.title,
                source_url=data.source_url,
                interval_months=data.interval_months,
                next_check_on=data.next_check_on,
                active=data.active,
                last_result="never",
            )
        except IntegrityError:
            self.db.rollback()
            raise ConflictError(DUPLICATE_SOURCE_MESSAGE) from None
        self.audit.record(
            company_id=actor.company_id,
            actor=actor,
            action="RATE_SOURCE_CREATED",
            entity_type="rate_source",
            entity_id=source.id,
            details={"country": country, "scheme_group": source.scheme_group},
        )
        self.db.commit()
        return source

    def update(self, source_id: uuid.UUID, data: RateSourceUpdate, actor: User) -> RateSource:
        source = self.repo.get(source_id)
        if source is None:
            raise NotFoundError("Rate source not found.")
        changes = data.model_dump(exclude_unset=True)
        new_url = changes.get("source_url")
        if new_url is not None and new_url != source.source_url:
            if self.repo.get_by_key(source.country, source.state, source.scheme_group, new_url):
                raise ConflictError(DUPLICATE_SOURCE_MESSAGE)
            # A new page starts a new baseline: the old hash says nothing about it.
            changes.update(content_hash=None, last_result="never", last_checked_on=None)
        if changes:
            try:
                self.repo.update(source, **changes)
            except IntegrityError:
                self.db.rollback()
                raise ConflictError(DUPLICATE_SOURCE_MESSAGE) from None
            self.audit.record(
                company_id=actor.company_id,
                actor=actor,
                action="RATE_SOURCE_UPDATED",
                entity_type="rate_source",
                entity_id=source.id,
                details={"country": source.country, "fields": sorted(data.model_fields_set)},
            )
            self.db.commit()
        return source


DUPLICATE_SOURCE_MESSAGE = (
    "A source with the same country, state, scheme group and link already exists."
)
DRAFT_CLOSED_MESSAGE = "A {status} draft can no longer be changed."


def _validation_errors(exc: PydanticValidationError) -> list[dict[str, str]]:
    """Where and why only: never the submitted value."""
    return [{"loc": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()]


class RateDraftService:
    """`/platform/rate-drafts`: a proposed change of live rates. pending -> verified ->
    approved (or rejected). Only `approve` changes a rate row, and it does so through the very
    services the direct write routes use (so the overlap, source and date rules are the same)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = RateDraftRepository(db)
        self.source_repo = RateSourceRepository(db)
        self.audit = AuditService(db)

    # --- reading -------------------------------------------------------------------

    def list_drafts(self, page_params: PageParams, status: str | None):
        return self.repo.list_drafts(page_params, status)

    def detail(self, draft_id: uuid.UUID) -> RateDraftDetail:
        return self._detail(self._get(draft_id))

    def _get(self, draft_id: uuid.UUID, *, lock: bool = False) -> RateChangeDraft:
        draft = self.repo.get(draft_id, lock=lock)
        if draft is None:
            raise NotFoundError("Rate draft not found.")
        return draft

    def _detail(self, draft: RateChangeDraft) -> RateDraftDetail:
        source = self.source_repo.get(draft.source_id) if draft.source_id else None
        sources: list[RateDraftSource] = []
        for fetched in draft.fetched_sources or []:
            url = fetched.get("url", "")
            sources.append(
                RateDraftSource(
                    title=source.title if source and source.source_url == url else None,
                    url=url,
                    fetched_at=fetched.get("fetched_at"),
                    hash=fetched.get("hash"),
                )
            )
        if source is not None and source.source_url not in [s.url for s in sources]:
            sources.append(RateDraftSource(title=source.title, url=source.source_url))
        base = RateDraftResponse.model_validate(draft)
        return RateDraftDetail(
            **base.model_dump(),
            current=self._current(draft, source),
            sources=sources,
        )

    def _current(self, draft: RateChangeDraft, source: RateSource | None) -> RateDraftCurrent:
        """The rows in force today for the draft's country, state and scheme."""
        today = utcnow().date()
        group = source.scheme_group if source is not None else None
        proposed = draft.proposed or {}
        current = RateDraftCurrent()
        if draft.kind == "statutory_rate" or (draft.kind == "no_numbers" and group == "epf_esi"):
            scheme = proposed.get("scheme")
            rows = StatutoryRateRepository(self.db).list_in_force(draft.country, today)
            current.statutory_rates = [
                StatutoryRateResponse.model_validate(r)
                for r in rows
                if scheme is None or r.scheme == scheme
            ]
        if draft.kind == "pt_slabs" or (draft.kind == "no_numbers" and group == "professional_tax"):
            state = draft.state or (source.state if source is not None else None)
            if state:
                slabs = PtSlabRepository(self.db).list_for_state(
                    draft.country, state, on_date=today
                )
                current.pt_slabs = [PtSlabResponse.model_validate(s) for s in slabs]
        if draft.kind == "tax_slabs" or (draft.kind == "no_numbers" and group == "income_tax"):
            year = proposed.get("financial_year") or (
                f"{today.year}-{today.year + 1}"
                if today.month >= 4
                else f"{today.year - 1}-{today.year}"
            )
            for regime in TaxRegime:
                rows_t = TaxSlabRepository(self.db).list_in_force(
                    draft.country, year, regime, today
                )
                current.tax_slabs += [TaxSlabResponse.model_validate(t) for t in rows_t]
        return current

    # --- writing -------------------------------------------------------------------

    @staticmethod
    def _parse(kind: str, proposed: dict[str, Any], country: str, state: str | None) -> Any:
        """The proposed numbers, validated by exactly the schema of the matching direct write
        route, and checked to belong to the draft's country (and state)."""
        schemas: dict[str, Any] = {
            "statutory_rate": StatutoryRateCreateRequest,
            "pt_slabs": PtSlabPutRequest,
            "tax_slabs": TaxSlabPostRequest,
        }
        payload = {"verified_on": utcnow().date().isoformat(), **proposed}
        try:
            model = schemas[kind].model_validate(payload)
        except PydanticValidationError as exc:
            raise ValidationError(
                "The proposed numbers are not valid.",
                details={"field": "proposed", "errors": _validation_errors(exc)},
            ) from None
        if model.country != country:
            raise ValidationError(
                "The proposed numbers belong to another country than the draft.",
                details={"field": "proposed"},
            )
        if kind == "pt_slabs" and canonical_state(country, model.state) != state:
            raise ValidationError(
                "The state of the numbers must be the draft's state.", details={"field": "state"}
            )
        return model

    def _numbers(
        self, kind: str, proposed: dict[str, Any] | None, country: str, state: str | None
    ) -> tuple[dict[str, Any] | None, date | None]:
        """What to store for `proposed` and `effective_from`, after checking kind and numbers."""
        if kind == "no_numbers":
            if proposed is not None:
                raise ValidationError(
                    "A draft without numbers carries no proposed numbers.",
                    details={"field": "proposed"},
                )
            return None, None
        if proposed is None:
            raise ValidationError(
                "The proposed numbers are required for this kind of draft.",
                details={"field": "proposed"},
            )
        if kind == "pt_slabs" and state is None:
            raise ValidationError(
                "A professional-tax draft needs its state.", details={"field": "state"}
            )
        model = self._parse(kind, proposed, country, state)
        return model.model_dump(mode="json"), model.effective_from

    def create(self, data: RateDraftCreate, actor: User) -> RateDraftDetail:
        country = _listed_country(data.country)
        state = _listed_state(country, data.state)
        if data.source_id is not None and self.source_repo.get(data.source_id) is None:
            raise NotFoundError("Rate source not found.")
        proposed, effective_from = self._numbers(data.kind, data.proposed, country, state)
        draft = self.repo.create(
            source_id=data.source_id,
            country=country,
            state=state,
            kind=data.kind,
            status="pending",
            proposed=proposed,
            effective_from=effective_from,
            reason=data.reason,
            fetched_sources=[],
            created_by=actor.id,
        )
        self._audit(draft, actor, "RATE_DRAFT_CREATED")
        self.db.commit()
        return self._detail(draft)

    def update(self, draft_id: uuid.UUID, data: RateDraftUpdate, actor: User) -> RateDraftDetail:
        draft = self._get(draft_id, lock=True)
        if draft.status not in RateDraftRepository.OPEN_STATUSES:
            raise ConflictError(DRAFT_CLOSED_MESSAGE.format(status=draft.status))
        fields = data.model_fields_set
        kind = data.kind if "kind" in fields and data.kind is not None else draft.kind
        proposed = data.proposed if "proposed" in fields else draft.proposed
        stored, effective_from = self._numbers(kind, proposed, draft.country, draft.state)
        changes: dict[str, Any] = {
            "kind": kind,
            "proposed": stored,
            "effective_from": effective_from,
        }
        if "reason" in fields and data.reason is not None:
            changes["reason"] = data.reason
        if draft.status == "verified":
            # Verification is void after a change: the sources must be looked at again.
            changes.update(
                status="pending", verified_by=None, verified_at=None, sources_checked=None
            )
        self.repo.update(draft, **changes)
        self._audit(draft, actor, "RATE_DRAFT_UPDATED")
        self.db.commit()
        return self._detail(draft)

    def verify(self, draft_id: uuid.UUID, data: RateDraftVerify, actor: User) -> RateDraftDetail:
        draft = self._get(draft_id, lock=True)
        if draft.status != "pending":
            raise ConflictError(
                f"Only a pending draft can be verified; this one is {draft.status}."
            )
        if draft.kind == "no_numbers" or draft.proposed is None:
            raise ConflictError("The numbers must be filled in before this draft can be verified.")
        if draft.source_id is not None:
            source = self.source_repo.get(draft.source_id)
            if source is not None and source.source_url not in data.sources_checked:
                raise ValidationError(
                    "The draft's own source must be one of the sources checked.",
                    details={"field": "sources_checked"},
                )
        try:
            self._parse(draft.kind, draft.proposed, draft.country, draft.state)
        except ValidationError:
            raise ConflictError("The proposed numbers are not valid; correct them first.") from None
        self.repo.update(
            draft,
            status="verified",
            verified_by=actor.id,
            verified_at=utcnow(),
            sources_checked=list(data.sources_checked),
        )
        self._audit(draft, actor, "RATE_DRAFT_VERIFIED")
        self.db.commit()
        return self._detail(draft)

    def approve(self, draft_id: uuid.UUID, actor: User) -> RateDraftDetail:
        draft = self._get(draft_id, lock=True)
        if draft.status != "verified":
            raise ConflictError(
                f"Only a verified draft can be approved; this one is {draft.status}. "
                "Verify it first."
            )
        # Imported here: payroll's service module imports this module's audit service.
        from app.modules.payroll.service import (
            PtSlabService,
            StatutoryRateService,
            TaxSlabService,
        )

        try:
            model = self._parse(draft.kind, draft.proposed or {}, draft.country, draft.state)
            model = model.model_copy(update={"verified_on": utcnow().date()})
            # The same code as the direct routes, without their own commit: the rows are
            # closed, the new rows added, and the draft marked approved in ONE save.
            if draft.kind == "statutory_rate":
                StatutoryRateService(self.db).add_rate(model, actor, commit=False)
            elif draft.kind == "pt_slabs":
                PtSlabService(self.db).add_slab_set(model, actor, commit=False)
            else:
                TaxSlabService(self.db).add_bracket_set(model, actor, commit=False)
            self.repo.update(draft, status="approved", approved_by=actor.id, approved_at=utcnow())
            self._remember_fetched_hash(draft)
            self._audit(draft, actor, "RATE_DRAFT_APPROVED")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._detail(draft)

    def reject(self, draft_id: uuid.UUID, data: RateDraftReject, actor: User) -> RateDraftDetail:
        draft = self._get(draft_id, lock=True)
        if draft.status not in RateDraftRepository.OPEN_STATUSES:
            raise ConflictError(DRAFT_CLOSED_MESSAGE.format(status=draft.status))
        self.repo.update(draft, status="rejected", decision_note=data.note)
        # The page that raised this draft is now the known page: the same unchanged page must
        # not raise the same draft again.
        self._remember_fetched_hash(draft)
        self._audit(draft, actor, "RATE_DRAFT_REJECTED")
        self.db.commit()
        return self._detail(draft)

    def _remember_fetched_hash(self, draft: RateChangeDraft) -> None:
        if draft.source_id is None:
            return
        source = self.source_repo.get(draft.source_id)
        if source is None:
            return
        fetched = [f for f in draft.fetched_sources or [] if f.get("url") == source.source_url]
        if fetched and fetched[-1].get("hash"):
            self.source_repo.update(source, content_hash=fetched[-1]["hash"])

    def _audit(self, draft: RateChangeDraft, actor: User, action: str) -> None:
        # Ids, country, kind and status names only: never a rate value or page text.
        self.audit.record(
            company_id=actor.company_id,
            actor=actor,
            action=action,
            entity_type="rate_change_draft",
            entity_id=draft.id,
            details={"country": draft.country, "kind": draft.kind, "status": draft.status},
        )


class RateCheckService:
    """The daily page check (5.9). It reads each due source through the fetcher it is given,
    compares the SHA-256 of the normalised text with the stored one and records the result. A
    changed page makes a `no_numbers` draft and notifies the super admins; nothing here ever
    writes to a rate table."""

    def __init__(self, db: Session):
        self.db = db
        self.sources = RateSourceRepository(db)
        self.drafts = RateDraftRepository(db)
        self.reminders = RateReminderRepository(db)
        self.users = UserRepository(db)
        self.audit = AuditService(db)

    def run(self, fetcher: PageFetcher) -> dict[str, Any]:
        today = utcnow().date()
        results: Counter[str] = Counter()
        for source_id in self.sources.due_ids(today):
            # One source at a time, each in its own transaction: a bad one cannot stop the rest.
            try:
                result, notice = self._check_one(source_id, fetcher, today)
            except Exception:  # noqa: BLE001 - one source must never stop the others
                self.db.rollback()
                logger.exception("rate_source_check_failed", extra={"source_id": str(source_id)})
                results["error"] += 1
                continue
            results[result] += 1
            if notice is not None:
                self._notify(*notice)
        reminded = self._remind_stale(today)
        return {"checked": sum(results.values()), "results": dict(results), "reminded": reminded}

    def _check_one(
        self, source_id: uuid.UUID, fetcher: PageFetcher, today: date
    ) -> tuple[str, tuple[str, RateSource, uuid.UUID | None] | None]:
        source = self.sources.get(source_id)
        if source is None or not source.active:
            return "skipped", None
        try:
            page = fetcher.fetch(source.source_url)
            fetched_hash = content_hash(page.text)
        except Exception:  # noqa: BLE001 - any failure to read the page is a failed check
            retry_on = today + timedelta(days=FAILED_CHECK_RETRY_DAYS)
            self.sources.update(
                source, last_checked_on=today, last_result="fetch_failed", next_check_on=retry_on
            )
            self.db.commit()
            return "fetch_failed", (CHECK_FAILED_NOTICE, source, None)

        next_check = add_months(today, source.interval_months)
        notice: tuple[str, RateSource, uuid.UUID | None] | None = None
        if source.content_hash is None:
            result = "baseline"
            self.sources.update(source, content_hash=fetched_hash)
        elif source.content_hash == fetched_hash:
            result = "unchanged"
        else:
            result = "changed"
            if self.drafts.open_for_source(source.id) is None:
                draft = self.drafts.create(
                    source_id=source.id,
                    country=source.country,
                    state=source.state,
                    kind="no_numbers",
                    status="pending",
                    proposed=None,
                    reason=(
                        f"The page '{source.title}' changed since it was last checked. Read it, "
                        "fill in the numbers, verify and approve."
                    ),
                    fetched_sources=[
                        {
                            "url": source.source_url,
                            "fetched_at": utcnow().isoformat(),
                            "hash": fetched_hash,
                        }
                    ],
                )
                self.audit.record(
                    company_id=None,
                    actor=None,
                    action="RATE_SOURCE_CHANGED",
                    entity_type="rate_change_draft",
                    entity_id=draft.id,
                    details={
                        "country": source.country,
                        "scheme_group": source.scheme_group,
                        "status": draft.status,
                    },
                )
                notice = (DRAFT_CREATED_NOTICE, source, draft.id)
        self.sources.update(
            source, last_checked_on=today, last_result=result, next_check_on=next_check
        )
        self.db.commit()
        return result, notice

    def _notify(self, kind: str, source: RateSource, draft_id: uuid.UUID | None) -> None:
        """After the commit: a failing notice never undoes the saved result."""
        where = f"{source.country} {source.scheme_group}"
        if kind == DRAFT_CREATED_NOTICE:
            title = "Rate page changed"
            message = f"{where}: the source page changed. A draft was created for review."
            url = f"/platform/rate-drafts/{draft_id}"
        else:
            title = "Rate page check failed"
            message = (
                f"{where}: the source page could not be read. It will be tried again on "
                f"{source.next_check_on.isoformat()}."
            )
            url = "/platform/rate-sources"
        self._tell_super_admins(kind, title, message, url, draft_id or source.id)

    def _tell_super_admins(
        self, kind: str, title: str, message: str, url: str, entity_id: uuid.UUID
    ) -> None:
        try:
            notifier = NotificationService(self.db)
            for admin in self.users.list_active_super_admins():
                notifier.notify(
                    company_id=admin.company_id,
                    user_id=admin.id,
                    type=kind,
                    title=title,
                    message=message,
                    action_url=url,
                    entity_type="rate",
                    entity_id=entity_id,
                )
            self.db.commit()
        except Exception:  # noqa: BLE001 - the result is already saved; a notice must not undo it
            self.db.rollback()
            logger.warning("rate_notification_failed", exc_info=True)

    def _remind_stale(self, today: date) -> int:
        """A reminder for each rate row in force that was last verified over 180 days ago, at
        most one per row per 30 days."""
        reminded = 0
        stale = self.reminders.stale_rows(today, today - timedelta(days=STALE_RATE_DAYS))
        for row_kind, row_id, country, label in stale:
            last = self.reminders.last_reminded_on(row_kind, row_id)
            if last is not None and (today - last).days < REMINDER_GAP_DAYS:
                continue
            self.reminders.log(row_kind, row_id, today)
            self.db.commit()
            self._tell_super_admins(
                VERIFICATION_DUE_NOTICE,
                "Rate needs re-checking",
                f"{country} {label}: the rate in force was last verified over "
                f"{STALE_RATE_DAYS} days ago. Check it against its official source.",
                "/platform/rate-sources",
                row_id,
            )
            reminded += 1
        return reminded


class GlobalSearchService:
    def __init__(self, db: Session):
        self.db = db
        from app.modules.platform.repository import SearchRepository

        self.repo = SearchRepository(db)

    def search(self, company_id: uuid.UUID, user: User, query: str) -> GlobalSearchResponse:
        trimmed = query.strip()
        if len(trimmed) < 2 or len(trimmed) > 100:
            raise ValidationError("Search query must be between 2 and 100 characters.")

        raw_results = self.repo.search_all(company_id, user, trimmed)
        items = [SearchResultItem(**r) for r in raw_results]
        return GlobalSearchResponse(query=trimmed, total_results=len(items), results=items)
