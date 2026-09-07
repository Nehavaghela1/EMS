import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.cache import delete_by_prefix, get_json, set_json
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError
from app.core.pagination import PageParams
from app.core.time import utcnow
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole
from app.modules.platform.models import AuditLog, Notification, Announcement, FileObject, EmployeeDocument
from app.modules.platform.schemas import (
    AnnouncementCreate, SignedUrlResponse, EmployeeDocumentCreate,
    EmployeeDocumentResponse, GlobalSearchResponse, SearchResultItem
)
from app.modules.platform.repository import (
    AuditRepository,
    DashboardRepository,
    IndustryPresetRepository,
    NotificationRepository,
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
}


class UnsafeAuditDetailsError(AppError):
    """Raised, never swallowed: a caller tried to write a banned field into
    an append-only audit row. A caller-side bug here must fail the request,
    not silently record the secret (Spec 7.8, CLAUDE.md rule 10)."""

    status_code = 500
    code = "unsafe_audit_details"


def _assert_details_safe(details: dict[str, Any] | None) -> None:
    if details is None:
        return
    for key, value in details.items():
        if key.lower() in _BANNED_DETAIL_KEYS:
            raise UnsafeAuditDetailsError(
                "Refusing to write a sensitive field to audit_logs.details.",
                details={"field": key},
            )
        if isinstance(value, dict):
            _assert_details_safe(value)


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
        return self.repo.create(
            company_id=company_id,
            actor_user_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=safe_details,
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
        action: str | None,
        actor_email: str | None,
        entity_type: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> str:
        """Route 129: queues the real Celery job (13.1)."""
        from app.workers.tasks.platform import export_audit_logs_csv_task

        task = export_audit_logs_csv_task.delay(
            company_id=str(company_id),
            action=action,
            actor_email=actor_email,
            entity_type=entity_type,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
        )
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
        elif user.role == UserRole.hr_admin:
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
        return self.repo.create(
            company_id=company_id,
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            action_url=action_url,
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

    def create(self, company_id: uuid.UUID, user_id: uuid.UUID, data: AnnouncementCreate) -> Announcement:
        announcement = self.repo.create(
            company_id=company_id,
            created_by=user_id,
            title=data.title,
            content=data.content,
            target_role=data.target_role,
            expires_at=data.expires_at,
        )
        self.db.commit()
        self.db.refresh(announcement)
        return announcement

    def list_active(self, company_id: uuid.UUID, user_role: str) -> list[Announcement]:
        return self.repo.list_active(company_id, user_role)

    def delete(self, company_id: uuid.UUID, announcement_id: uuid.UUID) -> None:
        announcement = self.repo.get_by_id(company_id, announcement_id)
        if not announcement:
            raise NotFoundError("Announcement not found.")
        self.repo.soft_delete(announcement)
        self.db.commit()


class FileService:
    def __init__(self, db: Session):
        self.db = db
        from app.modules.platform.repository import FileRepository
        self.repo = FileRepository(db)

    def upload_file(self, company_id: uuid.UUID, user_id: uuid.UUID, file_name: str, file_type: str, file_bytes: bytes) -> FileObject:
        # 1. Validate Size (< 10MB)
        if len(file_bytes) > 10 * 1024 * 1024:
            raise AppError("File size exceeds 10MB limit.")

        # 2. Store in local uploads folder
        import os
        upload_dir = os.path.join(os.getcwd(), "uploads", str(company_id))
        os.makedirs(upload_dir, exist_ok=True)

        file_id = uuid.uuid4()
        storage_path = os.path.join(upload_dir, f"{file_id}_{file_name}")
        with open(storage_path, "wb") as f:
            f.write(file_bytes)

        # 3. Create FileObject
        file_obj = self.repo.create(
            company_id=company_id,
            uploaded_by=user_id,
            file_name=file_name,
            file_type=file_type,
            file_size=len(file_bytes),
            storage_path=storage_path,
        )
        self.db.commit()
        self.db.refresh(file_obj)
        return file_obj

    def generate_signed_url(self, company_id: uuid.UUID, file_id: uuid.UUID) -> SignedUrlResponse:
        file_obj = self.repo.get_by_id(company_id, file_id)
        if not file_obj:
            raise NotFoundError("File object not found.")

        # HMAC signed token valid for 3600 seconds
        import hmac, hashlib
        expires_at = int(datetime.now(UTC).timestamp()) + 3600
        signature_payload = f"{company_id}:{file_id}:{expires_at}".encode()
        signature = hmac.new(settings.SECRET_KEY.encode(), signature_payload, hashlib.sha256).hexdigest()

        url = f"/api/v1/files/download/{file_id}?expires={expires_at}&signature={signature}"
        return SignedUrlResponse(
            file_object_id=file_obj.id,
            file_name=file_obj.file_name,
            url=url,
            expires_in_seconds=3600
        )


class EmployeeDocumentService:
    def __init__(self, db: Session):
        self.db = db
        from app.modules.platform.repository import EmployeeDocumentRepository
        self.repo = EmployeeDocumentRepository(db)

    def attach_document(self, company_id: uuid.UUID, data: EmployeeDocumentCreate) -> EmployeeDocumentResponse:
        from app.modules.platform.repository import FileRepository
        file_obj = FileRepository(self.db).get_by_id(company_id, data.file_object_id)
        if not file_obj:
            raise NotFoundError("File object not found.")

        doc = self.repo.create(
            company_id=company_id,
            employee_id=data.employee_id,
            file_object_id=data.file_object_id,
            document_type=data.document_type,
            name=data.name,
        )
        self.db.commit()
        self.db.refresh(doc)
        return EmployeeDocumentResponse.model_validate(doc)

    def list_documents(self, company_id: uuid.UUID, employee_id: uuid.UUID) -> list[EmployeeDocumentResponse]:
        docs = self.repo.list_for_employee(company_id, employee_id)
        file_service = FileService(self.db)
        results = []
        for doc in docs:
            resp = EmployeeDocumentResponse.model_validate(doc)
            signed = file_service.generate_signed_url(company_id, doc.file_object_id)
            resp.download_url = signed.url
            results.append(resp)
        return results


class GlobalSearchService:
    def __init__(self, db: Session):
        self.db = db
        from app.modules.platform.repository import SearchRepository
        self.repo = SearchRepository(db)

    def search(self, company_id: uuid.UUID, query: str) -> GlobalSearchResponse:
        if not query or len(query.strip()) < 2:
            return GlobalSearchResponse(query=query, total_results=0, results=[])

        raw_results = self.repo.search_all(company_id, query.strip())
        items = [SearchResultItem(**r) for r in raw_results]
        return GlobalSearchResponse(
            query=query,
            total_results=len(items),
            results=items
        )
