import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate
from app.core.roles import HR_LEVEL_ROLES
from app.core.time import utcnow
from app.modules.hr.models import Department, Employee
from app.modules.identity.models import Company, User, UserRole
from app.modules.payroll.models import (
    PayrollItem,
    PayrollRun,
    PayrollRunStatus,
    PtSlab,
    StatutoryRate,
    TaxSlab,
)
from app.modules.platform.models import (
    Announcement,
    AuditLog,
    EmployeeDocument,
    FileObject,
    IndustryPreset,
    Notification,
    RateChangeDraft,
    RateReminderLog,
    RateSource,
)
from app.modules.projects.models import Project, TimeEntry
from app.modules.time_leave.models import (
    Attendance,
    AttendanceRegularizationRequest,
    AttendanceStatus,
    Leave,
    LeaveBalance,
    LeaveStatus,
)


class PayrollStatsRepository:
    """Payroll runs of every company, read as aggregates only (5.8). The caller is the super
    admin, whose session carries the platform-admin context, so row level security lets all
    tenants' runs be counted; nothing identifying a company or a person is selected."""

    PAID_STATUSES = (PayrollRunStatus.approved, PayrollRunStatus.paid)

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _in_range(first: int, last: int):
        month_key = PayrollRun.year * 12 + PayrollRun.month
        return (PayrollRun.deleted_at.is_(None), month_key >= first, month_key <= last)

    def runs_by_status(self, first: int, last: int) -> dict[tuple[int, int, str], int]:
        rows = self.db.execute(
            select(PayrollRun.year, PayrollRun.month, PayrollRun.status, func.count(PayrollRun.id))
            .where(*self._in_range(first, last))
            .group_by(PayrollRun.year, PayrollRun.month, PayrollRun.status)
        ).all()
        return {(int(y), int(m), status.value): int(n) for y, m, status, n in rows}

    def companies_with_runs(self, first: int, last: int) -> dict[tuple[int, int], int]:
        rows = self.db.execute(
            select(
                PayrollRun.year, PayrollRun.month, func.count(func.distinct(PayrollRun.company_id))
            )
            .where(*self._in_range(first, last))
            .group_by(PayrollRun.year, PayrollRun.month)
        ).all()
        return {(int(y), int(m)): int(n) for y, m, n in rows}

    def employees_paid(self, first: int, last: int) -> dict[tuple[int, int], int]:
        rows = self.db.execute(
            select(
                PayrollRun.year,
                PayrollRun.month,
                func.count(func.distinct(PayrollItem.employee_id)),
            )
            .join(PayrollItem, PayrollItem.payroll_run_id == PayrollRun.id)
            .where(*self._in_range(first, last), PayrollRun.status.in_(self.PAID_STATUSES))
            .group_by(PayrollRun.year, PayrollRun.month)
        ).all()
        return {(int(y), int(m)): int(n) for y, m, n in rows}

    def total_net_paid(self, first: int, last: int) -> dict[tuple[int, int], Decimal]:
        rows = self.db.execute(
            select(
                PayrollRun.year, PayrollRun.month, func.coalesce(func.sum(PayrollRun.total_net), 0)
            )
            .where(*self._in_range(first, last), PayrollRun.status.in_(self.PAID_STATUSES))
            .group_by(PayrollRun.year, PayrollRun.month)
        ).all()
        return {(int(y), int(m)): Decimal(total) for y, m, total in rows}


class RateSourceRepository:
    """RLS: No — platform data (5.9)."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, source_id: uuid.UUID) -> RateSource | None:
        return self.db.scalar(
            select(RateSource).where(RateSource.id == source_id, RateSource.deleted_at.is_(None))
        )

    def get_by_key(
        self, country: str, state: str | None, scheme_group: str, source_url: str
    ) -> RateSource | None:
        return self.db.scalar(
            select(RateSource).where(
                RateSource.country == country,
                func.coalesce(RateSource.state, "") == (state or ""),
                RateSource.scheme_group == scheme_group,
                RateSource.source_url == source_url,
                RateSource.deleted_at.is_(None),
            )
        )

    def list_sources(self, page_params: PageParams) -> tuple[list[RateSource], int, int]:
        stmt = (
            select(RateSource)
            .where(RateSource.deleted_at.is_(None))
            .order_by(RateSource.country, RateSource.title, RateSource.id)
        )
        return paginate(self.db, stmt, page_params)

    def due_ids(self, today: date) -> list[uuid.UUID]:
        return list(
            self.db.scalars(
                select(RateSource.id)
                .where(
                    RateSource.deleted_at.is_(None),
                    RateSource.active.is_(True),
                    RateSource.next_check_on <= today,
                )
                .order_by(RateSource.next_check_on, RateSource.id)
            ).all()
        )

    def create(self, **kwargs) -> RateSource:
        source = RateSource(**kwargs)
        self.db.add(source)
        self.db.flush()
        return source

    def update(self, source: RateSource, **kwargs) -> RateSource:
        for key, value in kwargs.items():
            setattr(source, key, value)
        self.db.flush()
        return source


class RateDraftRepository:
    """RLS: No — platform data (5.9)."""

    OPEN_STATUSES = ("pending", "verified")

    def __init__(self, db: Session):
        self.db = db

    def get(self, draft_id: uuid.UUID, *, lock: bool = False) -> RateChangeDraft | None:
        stmt = select(RateChangeDraft).where(
            RateChangeDraft.id == draft_id, RateChangeDraft.deleted_at.is_(None)
        )
        return self.db.scalar(stmt.with_for_update() if lock else stmt)

    def list_drafts(
        self, page_params: PageParams, status: str | None
    ) -> tuple[list[RateChangeDraft], int, int]:
        stmt = select(RateChangeDraft).where(RateChangeDraft.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(RateChangeDraft.status == status)
        return paginate(self.db, stmt.order_by(RateChangeDraft.created_at.desc()), page_params)

    def open_for_source(self, source_id: uuid.UUID) -> RateChangeDraft | None:
        return self.db.scalar(
            select(RateChangeDraft).where(
                RateChangeDraft.source_id == source_id,
                RateChangeDraft.status.in_(self.OPEN_STATUSES),
                RateChangeDraft.deleted_at.is_(None),
            )
        )

    def create(self, **kwargs) -> RateChangeDraft:
        draft = RateChangeDraft(**kwargs)
        self.db.add(draft)
        self.db.flush()
        return draft

    def update(self, draft: RateChangeDraft, **kwargs) -> RateChangeDraft:
        for key, value in kwargs.items():
            setattr(draft, key, value)
        self.db.flush()
        return draft


class RateReminderRepository:
    """RLS: No — platform data (5.9). Which stale rate rows to remind about, and when each was
    last reminded."""

    def __init__(self, db: Session):
        self.db = db

    def stale_rows(self, today: date, older_than: date) -> list[tuple[str, uuid.UUID, str, str]]:
        """(row kind, id, country, label) of the rows in force whose verification is older than
        `older_than`: statutory rates and PT slabs in force today, tax slabs of the current
        financial year. PT slabs are grouped to their state."""
        found: list[tuple[str, uuid.UUID, str, str]] = []
        for rate in self.db.scalars(
            select(StatutoryRate).where(
                StatutoryRate.deleted_at.is_(None),
                StatutoryRate.effective_from <= today,
                or_(StatutoryRate.effective_to.is_(None), StatutoryRate.effective_to >= today),
                StatutoryRate.verified_on < older_than,
            )
        ).all():
            found.append(("statutory_rate", rate.id, rate.country, rate.scheme))
        seen_states: set[tuple[str, str]] = set()
        for slab in self.db.scalars(
            select(PtSlab)
            .where(
                PtSlab.deleted_at.is_(None),
                PtSlab.effective_from <= today,
                or_(PtSlab.effective_to.is_(None), PtSlab.effective_to >= today),
                PtSlab.verified_on < older_than,
            )
            .order_by(PtSlab.country, PtSlab.state, PtSlab.income_min)
        ).all():
            if (slab.country, slab.state) in seen_states:
                continue
            seen_states.add((slab.country, slab.state))
            found.append(("pt_slab", slab.id, slab.country, f"pt {slab.state}"))
        financial_year = (
            f"{today.year}-{today.year + 1}"
            if today.month >= 4
            else (f"{today.year - 1}-{today.year}")
        )
        seen_tax: set[tuple[str, str]] = set()
        for tax in self.db.scalars(
            select(TaxSlab)
            .where(
                TaxSlab.deleted_at.is_(None),
                TaxSlab.financial_year == financial_year,
                TaxSlab.effective_from <= today,
                TaxSlab.verified_on < older_than,
            )
            .order_by(TaxSlab.country, TaxSlab.regime, TaxSlab.min_income)
        ).all():
            key = (tax.country, tax.regime.value)
            if key in seen_tax:
                continue
            seen_tax.add(key)
            found.append(("tax_slab", tax.id, tax.country, f"income tax {tax.regime.value}"))
        return found

    def last_reminded_on(self, row_kind: str, row_id: uuid.UUID) -> date | None:
        return self.db.scalar(
            select(func.max(RateReminderLog.reminded_on)).where(
                RateReminderLog.row_kind == row_kind, RateReminderLog.row_id == row_id
            )
        )

    def log(self, row_kind: str, row_id: uuid.UUID, reminded_on: date) -> None:
        self.db.add(RateReminderLog(row_kind=row_kind, row_id=row_id, reminded_on=reminded_on))
        self.db.flush()


class IndustryPresetRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_name(self, industry_name: str) -> IndustryPreset | None:
        return self.db.scalar(
            select(IndustryPreset).where(IndustryPreset.industry_name == industry_name)
        )

    def list_all(self) -> list[IndustryPreset]:
        return list(self.db.scalars(select(IndustryPreset).order_by(IndustryPreset.industry_name)))


class AuditRepository:
    """RLS: No — `audit_logs` is scoped here, in the repository layer, not
    by a policy (Spec 7.8). Every read method below requires `company_id`
    and filters on it explicitly; there is no unscoped reader in this work
    package (route 128 is HR-only per the route table, not super_admin)."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, **kwargs) -> AuditLog:
        log = AuditLog(**kwargs)
        self.db.add(log)
        self.db.flush()
        return log

    def _filtered(
        self,
        *,
        company_id: uuid.UUID,
        action: str | None,
        actor_email: str | None,
        entity_type: str | None,
        date_from: date | None,
        date_to: date | None,
    ):
        stmt = select(AuditLog).where(AuditLog.company_id == company_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if actor_email is not None:
            stmt = stmt.where(func.lower(AuditLog.actor_email) == actor_email.lower())
        if entity_type is not None:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if date_from is not None:
            # Comparing a bare `date` against a TIMESTAMPTZ column lets
            # Postgres cast it to midnight in the SESSION's timezone, not
            # UTC — a real bug this project hit here: a test's `date_from`
            # of "tomorrow" (by utcnow(), Spec 6.3) still matched a row
            # created today, because the server's session timezone put
            # midnight several hours before UTC midnight. Building the
            # boundary as an explicit UTC datetime in Python sidesteps the
            # server's timezone setting entirely.
            stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min, UTC))
        if date_to is not None:
            upper = datetime.combine(date_to + timedelta(days=1), time.min, UTC)
            stmt = stmt.where(AuditLog.created_at < upper)
        return stmt.order_by(AuditLog.created_at.desc())

    def list_for_company(
        self,
        *,
        company_id: uuid.UUID,
        action: str | None,
        actor_email: str | None,
        entity_type: str | None,
        date_from: date | None,
        date_to: date | None,
        page_params: PageParams,
    ) -> tuple[list[AuditLog], int, int]:
        stmt = self._filtered(
            company_id=company_id,
            action=action,
            actor_email=actor_email,
            entity_type=entity_type,
            date_from=date_from,
            date_to=date_to,
        )
        return paginate(self.db, stmt, page_params)

    def list_for_export(
        self,
        *,
        company_id: uuid.UUID,
        action: str | None,
        actor_email: str | None,
        entity_type: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> list[AuditLog]:
        stmt = self._filtered(
            company_id=company_id,
            action=action,
            actor_email=actor_email,
            entity_type=entity_type,
            date_from=date_from,
            date_to=date_to,
        )
        return list(self.db.scalars(stmt))

    def count_for_export(
        self,
        *,
        company_id: uuid.UUID,
        action: str | None,
        actor_email: str | None,
        entity_type: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> int:
        stmt = self._filtered(
            company_id=company_id,
            action=action,
            actor_email=actor_email,
            entity_type=entity_type,
            date_from=date_from,
            date_to=date_to,
        )
        return self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **kwargs) -> Notification:
        notification = Notification(**kwargs)
        self.db.add(notification)
        self.db.flush()
        return notification

    def get_by_id(
        self, notification_id: uuid.UUID, company_id: uuid.UUID, user_id: uuid.UUID
    ) -> Notification | None:
        """Own-only (10.1's 404-not-403 rule extends here too — a
        notification belonging to a different user in the same company
        must 404, not 403)."""
        return self.db.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.company_id == company_id,
                Notification.user_id == user_id,
                Notification.deleted_at.is_(None),
            )
        )

    def list_for_user(
        self,
        *,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        unread_only: bool,
        page_params: PageParams,
    ) -> tuple[list[Notification], int, int]:
        stmt = select(Notification).where(
            Notification.company_id == company_id,
            Notification.user_id == user_id,
            Notification.deleted_at.is_(None),
        )
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc())
        return paginate(self.db, stmt, page_params)

    def unread_count(self, company_id: uuid.UUID, user_id: uuid.UUID) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.company_id == company_id,
                    Notification.user_id == user_id,
                    Notification.is_read.is_(False),
                    Notification.deleted_at.is_(None),
                )
            )
            or 0
        )

    def mark_read(self, notification: Notification) -> Notification:
        notification.is_read = True
        if notification.read_at is None:
            notification.read_at = utcnow()
        self.db.flush()
        return notification

    def mark_all_read(self, company_id: uuid.UUID, user_id: uuid.UUID) -> int:
        unread = list(
            self.db.scalars(
                select(Notification).where(
                    Notification.company_id == company_id,
                    Notification.user_id == user_id,
                    Notification.is_read.is_(False),
                    Notification.deleted_at.is_(None),
                )
            )
        )
        now = utcnow()
        for notification in unread:
            notification.is_read = True
            notification.read_at = now
        self.db.flush()
        return len(unread)


_PRESENT_STATUSES = (AttendanceStatus.present, AttendanceStatus.wfh, AttendanceStatus.half_day)


class DashboardRepository:
    """Read-only aggregation queries backing route 121 (Spec 11.10), one
    method per stat rather than one giant query — each role only calls the
    subset it needs. Reaches across module boundaries deliberately (the same
    pattern time_leave's repositories already use for `hr.models.Employee`):
    a dashboard is inherently a cross-module read.
    """

    def __init__(self, db: Session):
        self.db = db

    # ── super_admin (platform-wide, companies/users have no RLS) ──
    def company_counts_by_status(self) -> dict[str, int]:
        rows = self.db.execute(select(Company.status, func.count()).group_by(Company.status)).all()
        return {status.value: count for status, count in rows}

    def platform_user_count(self) -> int:
        return self.db.scalar(select(func.count()).select_from(User)) or 0

    # ── hr_admin (company-wide) ────────────────────────────────────
    def headcount(self, company_id: uuid.UUID) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(Employee)
                .where(
                    Employee.company_id == company_id,
                    Employee.deleted_at.is_(None),
                    Employee.is_active.is_(True),
                )
            )
            or 0
        )

    def present_today(self, company_id: uuid.UUID, today: date) -> int:
        return self._present_count(company_id, today, employee_ids=None)

    def on_leave_today(self, company_id: uuid.UUID, today: date) -> int:
        return self._on_leave_count(company_id, today, employee_ids=None)

    def pending_leave_requests(self, company_id: uuid.UUID) -> int:
        return self._pending_leave_count(company_id, employee_ids=None)

    def recent_hires(self, company_id: uuid.UUID, limit: int = 5) -> list[Employee]:
        return list(
            self.db.scalars(
                select(Employee)
                .where(Employee.company_id == company_id, Employee.deleted_at.is_(None))
                .order_by(Employee.hire_date.desc())
                .limit(limit)
            )
        )

    def department_distribution(self, company_id: uuid.UUID) -> dict[str, int]:
        rows = self.db.execute(
            select(Department.name, func.count(Employee.id))
            .join(Employee, Employee.department_id == Department.id)
            .where(
                Department.company_id == company_id,
                Department.deleted_at.is_(None),
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
            )
            .group_by(Department.name)
        ).all()
        result = {name: count for name, count in rows}

        unassigned_count = (
            self.db.scalar(
                select(func.count(Employee.id)).where(
                    Employee.company_id == company_id,
                    Employee.department_id.is_(None),
                    Employee.deleted_at.is_(None),
                    Employee.is_active.is_(True),
                )
            )
            or 0
        )
        if unassigned_count > 0:
            result["Unassigned"] = unassigned_count

        return result

    # ── manager (team-scoped, given the caller's direct reports) ──
    def team_headcount(self, company_id: uuid.UUID, employee_ids: list[uuid.UUID]) -> int:
        if not employee_ids:
            return 0
        return (
            self.db.scalar(
                select(func.count())
                .select_from(Employee)
                .where(
                    Employee.company_id == company_id,
                    Employee.id.in_(employee_ids),
                    Employee.deleted_at.is_(None),
                    Employee.is_active.is_(True),
                )
            )
            or 0
        )

    def team_present_today(
        self, company_id: uuid.UUID, employee_ids: list[uuid.UUID], today: date
    ) -> int:
        if not employee_ids:
            return 0
        return self._present_count(company_id, today, employee_ids=employee_ids)

    def team_leave_requests_awaiting(
        self, company_id: uuid.UUID, employee_ids: list[uuid.UUID]
    ) -> int:
        if not employee_ids:
            return 0
        return self._pending_leave_count(company_id, employee_ids=employee_ids)

    # ── employee (own data) ────────────────────────────────────────
    def own_attendance_summary(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, month_start: date, month_end: date
    ) -> dict[str, int]:
        rows = self.db.execute(
            select(Attendance.status, func.count())
            .where(
                Attendance.company_id == company_id,
                Attendance.employee_id == employee_id,
                Attendance.date >= month_start,
                Attendance.date <= month_end,
                Attendance.deleted_at.is_(None),
            )
            .group_by(Attendance.status)
        ).all()
        return {status.value: count for status, count in rows}

    def own_leave_balances(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, year: int
    ) -> list[LeaveBalance]:
        return list(
            self.db.scalars(
                select(LeaveBalance).where(
                    LeaveBalance.company_id == company_id,
                    LeaveBalance.employee_id == employee_id,
                    LeaveBalance.year == year,
                    LeaveBalance.deleted_at.is_(None),
                )
            )
        )

    def own_pending_requests(self, company_id: uuid.UUID, employee_id: uuid.UUID) -> int:
        return self._pending_leave_count(company_id, employee_ids=[employee_id])

    # ── shared helpers ──────────────────────────────────────────────
    def _present_count(
        self, company_id: uuid.UUID, today: date, *, employee_ids: list[uuid.UUID] | None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Attendance)
            .where(
                Attendance.company_id == company_id,
                Attendance.date == today,
                Attendance.status.in_(_PRESENT_STATUSES),
                Attendance.deleted_at.is_(None),
            )
        )
        if employee_ids is not None:
            stmt = stmt.where(Attendance.employee_id.in_(employee_ids))
        return self.db.scalar(stmt) or 0

    def _on_leave_count(
        self, company_id: uuid.UUID, today: date, *, employee_ids: list[uuid.UUID] | None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Attendance)
            .where(
                Attendance.company_id == company_id,
                Attendance.date == today,
                Attendance.status == AttendanceStatus.on_leave,
                Attendance.deleted_at.is_(None),
            )
        )
        if employee_ids is not None:
            stmt = stmt.where(Attendance.employee_id.in_(employee_ids))
        return self.db.scalar(stmt) or 0

    def _pending_leave_count(
        self, company_id: uuid.UUID, *, employee_ids: list[uuid.UUID] | None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Leave)
            .where(
                Leave.company_id == company_id,
                Leave.status == LeaveStatus.pending,
                Leave.deleted_at.is_(None),
            )
        )
        if employee_ids is not None:
            stmt = stmt.where(Leave.employee_id.in_(employee_ids))
        return self.db.scalar(stmt) or 0


class AnnouncementRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        company_id: uuid.UUID,
        created_by: uuid.UUID,
        title: str,
        content: str,
        target_role: str,
        expires_at: datetime | None,
        department_id: uuid.UUID | None = None,
    ) -> Announcement:
        announcement = Announcement(
            company_id=company_id,
            created_by=created_by,
            title=title,
            content=content,
            target_role=target_role,
            expires_at=expires_at,
            department_id=department_id,
        )
        self.db.add(announcement)
        self.db.flush()
        return announcement

    def list_active(
        self,
        company_id: uuid.UUID,
        user: User,
        caller_department_id: uuid.UUID | None = None,
    ) -> list[Announcement]:
        now = datetime.now(UTC)
        stmt = select(Announcement).where(
            Announcement.company_id == company_id,
            Announcement.deleted_at.is_(None),
            (Announcement.expires_at.is_(None) | (Announcement.expires_at > now)),
        )
        if user.role not in HR_LEVEL_ROLES:
            stmt = stmt.outerjoin(
                Department,
                (Department.id == Announcement.department_id) & (Department.deleted_at.is_(None)),
            ).where(Announcement.department_id.is_(None) | Department.id.is_not(None))
            role_cond = Announcement.department_id.is_(None) & (
                (Announcement.target_role == "all") | (Announcement.target_role == user.role.value)
            )
            if caller_department_id is not None:
                dept_cond = Announcement.department_id == caller_department_id
                stmt = stmt.where(role_cond | dept_cond)
            else:
                stmt = stmt.where(role_cond)

        stmt = stmt.order_by(Announcement.created_at.desc()).limit(100)
        return list(self.db.scalars(stmt))

    def get_by_id(self, company_id: uuid.UUID, announcement_id: uuid.UUID) -> Announcement | None:
        return self.db.scalar(
            select(Announcement).where(
                Announcement.id == announcement_id,
                Announcement.company_id == company_id,
                Announcement.deleted_at.is_(None),
            )
        )

    def soft_delete(self, announcement: Announcement) -> None:
        announcement.deleted_at = datetime.now(UTC)
        self.db.flush()


class FileRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        company_id: uuid.UUID,
        uploaded_by: uuid.UUID,
        file_name: str,
        file_type: str,
        file_size: int,
        storage_path: str,
    ) -> FileObject:
        file_obj = FileObject(
            company_id=company_id,
            uploaded_by=uploaded_by,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            storage_path=storage_path,
        )
        self.db.add(file_obj)
        self.db.flush()
        return file_obj

    def get_by_id(self, company_id: uuid.UUID, file_id: uuid.UUID) -> FileObject | None:
        return self.db.scalar(
            select(FileObject).where(
                FileObject.id == file_id,
                FileObject.company_id == company_id,
                FileObject.deleted_at.is_(None),
            )
        )


class EmployeeDocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        file_object_id: uuid.UUID,
        document_type: str,
        name: str,
    ) -> EmployeeDocument:
        doc = EmployeeDocument(
            company_id=company_id,
            employee_id=employee_id,
            file_object_id=file_object_id,
            document_type=document_type,
            name=name,
        )
        self.db.add(doc)
        self.db.flush()
        return doc

    def list_for_employee(
        self, company_id: uuid.UUID, employee_id: uuid.UUID
    ) -> list[EmployeeDocument]:
        stmt = (
            select(EmployeeDocument)
            .where(
                EmployeeDocument.company_id == company_id,
                EmployeeDocument.employee_id == employee_id,
                EmployeeDocument.deleted_at.is_(None),
            )
            .order_by(EmployeeDocument.created_at.desc())
        )
        return list(self.db.scalars(stmt))

    def count_active_for_employee(self, company_id: uuid.UUID, employee_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(EmployeeDocument)
            .where(
                EmployeeDocument.company_id == company_id,
                EmployeeDocument.employee_id == employee_id,
                EmployeeDocument.deleted_at.is_(None),
            )
        )
        return self.db.scalar(stmt) or 0

    def get_by_id(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, document_id: uuid.UUID
    ) -> EmployeeDocument | None:
        stmt = select(EmployeeDocument).where(
            EmployeeDocument.id == document_id,
            EmployeeDocument.company_id == company_id,
            EmployeeDocument.employee_id == employee_id,
            EmployeeDocument.deleted_at.is_(None),
        )
        return self.db.scalar(stmt)

    def is_file_attached_to_employee_document(self, file_object_id: uuid.UUID) -> bool:
        stmt = (
            select(EmployeeDocument.id)
            .where(EmployeeDocument.file_object_id == file_object_id)
            .limit(1)
        )
        return self.db.scalar(stmt) is not None


class SearchRepository:
    def __init__(self, db: Session):
        self.db = db

    def search_all(self, company_id: uuid.UUID, user: User, query: str) -> list[dict[str, Any]]:
        from app.modules.hr.models import Department, Employee
        from app.modules.projects.models import Project, ProjectMember, Task

        escaped = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        contains_pat = f"%{escaped}%"

        caller_emp = self.db.scalar(
            select(Employee)
            .where(
                Employee.company_id == company_id,
                Employee.user_id == user.id,
                Employee.deleted_at.is_(None),
            )
            .limit(1)
        )
        is_hr_level = user.role in HR_LEVEL_ROLES

        results: list[dict[str, Any]] = []

        # ── 1. Employees ──────────────────────────────────────────
        name_match = func.lower(Employee.first_name).ilike(contains_pat, escape="\\") | func.lower(
            func.coalesce(Employee.last_name, "")
        ).ilike(contains_pat, escape="\\")
        code_email_match = func.lower(Employee.email).ilike(contains_pat, escape="\\") | func.lower(
            Employee.employee_code
        ).ilike(contains_pat, escape="\\")

        team_ids: set[uuid.UUID] = set()
        if user.role == UserRole.manager and caller_emp:
            team_ids.add(caller_emp.id)
            direct_report_ids = self.db.scalars(
                select(Employee.id).where(
                    Employee.company_id == company_id,
                    Employee.reporting_manager_id == caller_emp.id,
                    Employee.deleted_at.is_(None),
                )
            ).all()
            team_ids.update(direct_report_ids)

        if is_hr_level:
            emp_filter = name_match | code_email_match
        elif user.role == UserRole.manager:
            if team_ids:
                emp_filter = name_match | (Employee.id.in_(team_ids) & code_email_match)
            else:
                emp_filter = name_match
        else:
            if caller_emp:
                emp_filter = name_match | ((Employee.id == caller_emp.id) & code_email_match)
            else:
                emp_filter = name_match

        q_lower = query.lower()
        emp_starts_with = (
            func.lower(Employee.first_name).startswith(q_lower)
            | func.lower(func.coalesce(Employee.last_name, "")).startswith(q_lower)
            | func.lower(
                func.concat(Employee.first_name, " ", func.coalesce(Employee.last_name, ""))
            ).startswith(q_lower)
        )
        emp_stmt = (
            select(Employee, Department.name.label("dept_name"))
            .outerjoin(
                Department,
                (Department.id == Employee.department_id) & (Department.deleted_at.is_(None)),
            )
            .where(
                Employee.company_id == company_id,
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
                emp_filter,
            )
            .order_by(
                case((emp_starts_with, 0), else_=1),
                Employee.first_name,
                Employee.last_name,
            )
            .limit(10)
        )
        emp_rows = self.db.execute(emp_stmt).all()
        for emp, dept_name in emp_rows:
            full_name = f"{emp.first_name} {emp.last_name or ''}".strip()
            has_full_details = (
                is_hr_level
                or (user.role == UserRole.manager and emp.id in team_ids)
                or (caller_emp is not None and emp.id == caller_emp.id)
            )
            if has_full_details:
                subtitle = f"{emp.employee_code} • {emp.email}"
                url = f"/employees/{emp.id}"
            else:
                subtitle = dept_name
                url = None

            results.append(
                {
                    "id": emp.id,
                    "type": "employee",
                    "title": full_name,
                    "subtitle": subtitle,
                    "url": url,
                }
            )

        # ── 2. Projects ───────────────────────────────────────────
        proj_filter_conditions = [Project.company_id == company_id]
        if hasattr(Project, "deleted_at"):
            proj_filter_conditions.append(Project.deleted_at.is_(None))

        accessible_proj_ids: set[uuid.UUID] = set()
        if is_hr_level:
            pass
        elif caller_emp:
            member_pids = self.db.scalars(
                select(ProjectMember.project_id).where(
                    ProjectMember.company_id == company_id,
                    ProjectMember.employee_id == caller_emp.id,
                )
            ).all()
            accessible_proj_ids.update(member_pids)
            managed_pids = self.db.scalars(
                select(Project.id).where(
                    Project.company_id == company_id,
                    Project.manager_id == caller_emp.id,
                )
            ).all()
            accessible_proj_ids.update(managed_pids)
            proj_filter_conditions.append(Project.id.in_(accessible_proj_ids))
        else:
            proj_filter_conditions.append(Project.id.in_([]))

        proj_match = (
            func.lower(Project.name).ilike(contains_pat, escape="\\")
            | func.lower(Project.code).ilike(contains_pat, escape="\\")
            | func.lower(func.coalesce(Project.client_name, "")).ilike(contains_pat, escape="\\")
        )
        proj_filter_conditions.append(proj_match)

        proj_starts_with = func.lower(Project.name).startswith(q_lower) | func.lower(
            Project.code
        ).startswith(q_lower)
        proj_stmt = (
            select(Project)
            .where(*proj_filter_conditions)
            .order_by(
                case((proj_starts_with, 0), else_=1),
                Project.name,
            )
            .limit(10)
        )
        projs = list(self.db.scalars(proj_stmt))
        for proj in projs:
            results.append(
                {
                    "id": proj.id,
                    "type": "project",
                    "title": proj.name,
                    "subtitle": f"Code: {proj.code} • Status: {proj.status}",
                    "url": f"/projects/{proj.id}",
                }
            )

        # ── 3. Tasks ──────────────────────────────────────────────
        task_filter_conditions = [Task.company_id == company_id]
        if hasattr(Task, "deleted_at"):
            task_filter_conditions.append(Task.deleted_at.is_(None))

        if is_hr_level:
            pass
        elif caller_emp:
            task_filter_conditions.append(
                Task.project_id.in_(accessible_proj_ids) | (Task.assigned_to == caller_emp.id)
            )
        else:
            task_filter_conditions.append(Task.id.in_([]))

        task_match = func.lower(Task.title).ilike(contains_pat, escape="\\") | func.lower(
            func.coalesce(Task.description, "")
        ).ilike(contains_pat, escape="\\")
        task_filter_conditions.append(task_match)

        task_starts_with = func.lower(Task.title).startswith(q_lower)
        task_stmt = (
            select(Task)
            .where(*task_filter_conditions)
            .order_by(
                case((task_starts_with, 0), else_=1),
                Task.title,
            )
            .limit(10)
        )
        tasks = list(self.db.scalars(task_stmt))
        for task in tasks:
            results.append(
                {
                    "id": task.id,
                    "type": "task",
                    "title": task.title,
                    "subtitle": f"Status: {task.status} • Priority: {task.priority}",
                    "url": f"/projects/{task.project_id}",
                }
            )

        return results


class PlatformStatsRepository:
    """Platform statistics across all companies (B2, B4).
    Reads under FORCE RLS with is_platform_admin=True session context.
    Aggregates only: zero per-employee rows, zero confidential amounts."""

    def __init__(self, db: Session):
        self.db = db

    def get_overview(self) -> dict[str, Any]:
        now = utcnow()
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
        cur_year, cur_month = now.year, now.month
        prev_month = 12 if cur_month == 1 else cur_month - 1
        prev_year = cur_year - 1 if cur_month == 1 else cur_year

        # 1. companies_by_status
        status_rows = self.db.execute(
            select(Company.status, func.count(Company.id))
            .where(Company.deleted_at.is_(None))
            .group_by(Company.status)
        ).all()
        companies_by_status = {"active": 0, "pending": 0, "deactivated": 0}
        for s, count in status_rows:
            key = s.value if hasattr(s, "value") else str(s)
            companies_by_status[key] = count

        # 2. companies_created_this_month
        created_count = (
            self.db.scalar(
                select(func.count(Company.id)).where(
                    Company.deleted_at.is_(None), Company.created_at >= month_start
                )
            )
            or 0
        )

        # 3. total_users
        total_users = (
            self.db.scalar(
                select(func.count(User.id)).where(
                    User.deleted_at.is_(None), User.role != UserRole.super_admin
                )
            )
            or 0
        )

        # 4. total_employees
        total_employees = (
            self.db.scalar(select(func.count(Employee.id)).where(Employee.deleted_at.is_(None)))
            or 0
        )

        # 5. total_net_paid_this_month
        net_paid_cur = self.db.scalar(
            select(func.coalesce(func.sum(PayrollRun.total_net), Decimal("0.00"))).where(
                PayrollRun.deleted_at.is_(None),
                PayrollRun.status.in_((PayrollRunStatus.approved, PayrollRunStatus.paid)),
                PayrollRun.year == cur_year,
                PayrollRun.month == cur_month,
            )
        ) or Decimal("0.00")

        # 6. total_net_paid_last_month
        net_paid_prev = self.db.scalar(
            select(func.coalesce(func.sum(PayrollRun.total_net), Decimal("0.00"))).where(
                PayrollRun.deleted_at.is_(None),
                PayrollRun.status.in_((PayrollRunStatus.approved, PayrollRunStatus.paid)),
                PayrollRun.year == prev_year,
                PayrollRun.month == prev_month,
            )
        ) or Decimal("0.00")

        return {
            "companies_by_status": companies_by_status,
            "companies_created_this_month": created_count,
            "total_users": total_users,
            "total_employees": total_employees,
            "total_net_paid_this_month": net_paid_cur,
            "total_net_paid_last_month": net_paid_prev,
        }

    def list_companies_stats(
        self,
        page_params: PageParams,
        search: str | None = None,
        status_filter: str | None = None,
        sort_by: str = "name",
        sort_dir: str = "asc",
    ) -> tuple[list[dict[str, Any]], int, int]:
        now = utcnow()
        month_start_date = date(now.year, now.month, 1)

        stmt = select(Company).where(Company.deleted_at.is_(None))
        if search:
            search_pat = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Company.name.ilike(search_pat),
                    Company.code.ilike(search_pat),
                )
            )
        if status_filter:
            if status_filter == "deactivated":
                stmt = stmt.where(Company.is_active.is_(False))
            else:
                stmt = stmt.where(Company.status == status_filter)

        # Ordering
        sort_col = getattr(Company, sort_by, Company.name)
        if sort_dir == "desc":
            stmt = stmt.order_by(sort_col.desc())
        else:
            stmt = stmt.order_by(sort_col.asc())

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.scalar(count_stmt) or 0
        pages = (total + page_params.limit - 1) // page_params.limit if total > 0 else 0

        # Paginate
        offset = (page_params.page - 1) * page_params.limit
        companies = list(self.db.scalars(stmt.offset(offset).limit(page_params.limit)))
        if not companies:
            return [], total, pages

        cids = [c.id for c in companies]

        # Bulk queries for these companies:
        # Headcount (active employees)
        headcount_rows = self.db.execute(
            select(Employee.company_id, func.count(Employee.id))
            .where(
                Employee.company_id.in_(cids),
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
            )
            .group_by(Employee.company_id)
        ).all()
        headcounts = {cid: cnt for cid, cnt in headcount_rows}

        # Active user count
        active_user_rows = self.db.execute(
            select(User.company_id, func.count(User.id))
            .where(
                User.company_id.in_(cids),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
            .group_by(User.company_id)
        ).all()
        active_users = {cid: cnt for cid, cnt in active_user_rows}

        # Joiners this month
        joiner_rows = self.db.execute(
            select(Employee.company_id, func.count(Employee.id))
            .where(
                Employee.company_id.in_(cids),
                Employee.deleted_at.is_(None),
                Employee.hire_date >= month_start_date,
            )
            .group_by(Employee.company_id)
        ).all()
        joiners = {cid: cnt for cid, cnt in joiner_rows}

        # Leavers this month
        leaver_rows = self.db.execute(
            select(Employee.company_id, func.count(Employee.id))
            .where(
                Employee.company_id.in_(cids),
                Employee.is_active.is_(False),
                Employee.updated_at >= datetime(now.year, now.month, 1, tzinfo=UTC),
            )
            .group_by(Employee.company_id)
        ).all()
        leavers = {cid: cnt for cid, cnt in leaver_rows}

        # Last payroll run date
        last_run_rows = self.db.execute(
            select(PayrollRun.company_id, func.max(PayrollRun.created_at))
            .where(
                PayrollRun.company_id.in_(cids),
                PayrollRun.deleted_at.is_(None),
                PayrollRun.status.in_((PayrollRunStatus.approved, PayrollRunStatus.paid)),
            )
            .group_by(PayrollRun.company_id)
        ).all()
        last_runs = {cid: dt.date() if dt else None for cid, dt in last_run_rows}

        # Most recent login across company users
        login_rows = self.db.execute(
            select(User.company_id, func.max(User.last_login_at))
            .where(User.company_id.in_(cids), User.deleted_at.is_(None))
            .group_by(User.company_id)
        ).all()
        logins = {cid: dt for cid, dt in login_rows}

        items = []
        for c in companies:
            status_str = c.status.value if hasattr(c.status, "value") else str(c.status)
            items.append(
                {
                    "company_id": c.id,
                    "name": c.name,
                    "code": c.code,
                    "status": status_str,
                    "created_at": c.created_at,
                    "headcount": headcounts.get(c.id, 0),
                    "active_user_count": active_users.get(c.id, 0),
                    "joiners_this_month": joiners.get(c.id, 0),
                    "leavers_this_month": leavers.get(c.id, 0),
                    "last_payroll_run_date": last_runs.get(c.id),
                    "most_recent_login": logins.get(c.id),
                }
            )

        return items, total, pages

    def list_payroll_stats(
        self,
        page_params: PageParams,
        company_id: uuid.UUID | None = None,
        from_month: str | None = None,
        to_month: str | None = None,
    ) -> tuple[list[dict[str, Any]], int, int]:
        now = utcnow()
        if not to_month:
            to_month = f"{now.year:04d}-{now.month:02d}"
        if not from_month:
            to_y, to_m = int(to_month.split("-")[0]), int(to_month.split("-")[1])
            start_m = to_y * 12 + to_m - 11
            from_y, from_m = (start_m - 1) // 12, ((start_m - 1) % 12) + 1
            from_month = f"{from_y:04d}-{from_m:02d}"

        from_y, from_m = int(from_month.split("-")[0]), int(from_month.split("-")[1])
        to_y, to_m = int(to_month.split("-")[0]), int(to_month.split("-")[1])
        first_key = from_y * 12 + from_m
        last_key = to_y * 12 + to_m

        month_key = PayrollRun.year * 12 + PayrollRun.month
        base_stmt = select(
            PayrollRun.company_id,
            PayrollRun.year,
            PayrollRun.month,
            PayrollRun.status,
            func.count(PayrollRun.id).label("run_count"),
            func.coalesce(func.sum(PayrollRun.total_employees), 0).label("emp_count"),
            func.coalesce(func.sum(PayrollRun.total_net), Decimal("0.00")).label("net_sum"),
            func.coalesce(func.sum(PayrollRun.total_employer_cost), Decimal("0.00")).label(
                "cost_sum"
            ),
        ).where(
            PayrollRun.deleted_at.is_(None),
            month_key >= first_key,
            month_key <= last_key,
        )
        if company_id:
            base_stmt = base_stmt.where(PayrollRun.company_id == company_id)

        base_stmt = base_stmt.group_by(
            PayrollRun.company_id,
            PayrollRun.year,
            PayrollRun.month,
            PayrollRun.status,
        )

        rows = self.db.execute(base_stmt).all()
        grouped: dict[tuple[uuid.UUID, int, int], dict[str, Any]] = {}
        for r in rows:
            key = (r.company_id, r.year, r.month)
            if key not in grouped:
                grouped[key] = {
                    "company_id": r.company_id,
                    "year": r.year,
                    "month": r.month,
                    "runs_by_status": {},
                    "total_employees_in_run": 0,
                    "total_net_paid": Decimal("0.00"),
                    "total_employer_cost": Decimal("0.00"),
                    "total_statutory_contributions": Decimal("0.00"),
                }
            status_val = r.status.value if hasattr(r.status, "value") else str(r.status)
            grouped[key]["runs_by_status"][status_val] = r.run_count
            if status_val in ("approved", "paid"):
                grouped[key]["total_employees_in_run"] += int(r.emp_count)
                grouped[key]["total_net_paid"] += Decimal(str(r.net_sum))
                grouped[key]["total_employer_cost"] += Decimal(str(r.cost_sum))
                stat = Decimal(str(r.cost_sum)) - Decimal(str(r.net_sum))
                grouped[key]["total_statutory_contributions"] += max(Decimal("0.00"), stat)

        all_cids = {k[0] for k in grouped.keys()}
        if company_id:
            all_cids.add(company_id)
        companies_map: dict[uuid.UUID, tuple[str, str]] = {}
        if all_cids:
            c_rows = self.db.execute(
                select(Company.id, Company.name, Company.code).where(Company.id.in_(all_cids))
            ).all()
            companies_map = {c.id: (c.name, c.code) for c in c_rows}

        flat_list = []
        for (cid, _y, _m), data in sorted(
            grouped.items(), key=lambda x: (x[0][1], x[0][2], str(x[0][0])), reverse=True
        ):
            name, code = companies_map.get(cid, ("Unknown", "UNK"))
            data["company_name"] = name
            data["company_code"] = code
            flat_list.append(data)

        total = len(flat_list)
        pages = (total + page_params.limit - 1) // page_params.limit if total > 0 else 0
        offset = (page_params.page - 1) * page_params.limit
        paged_items = flat_list[offset : offset + page_params.limit]
        return paged_items, total, pages

    def list_activity_stats(
        self,
        page_params: PageParams,
        company_id: uuid.UUID | None = None,
    ) -> tuple[list[dict[str, Any]], int, int]:
        now = utcnow()
        cur_year, cur_month = now.year, now.month
        month_start_date = date(cur_year, cur_month, 1)
        month_start_dt = datetime(cur_year, cur_month, 1, tzinfo=UTC)

        stmt = select(Company).where(Company.deleted_at.is_(None))
        if company_id:
            stmt = stmt.where(Company.id == company_id)
        stmt = stmt.order_by(Company.name.asc())

        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        pages = (total + page_params.limit - 1) // page_params.limit if total > 0 else 0
        offset = (page_params.page - 1) * page_params.limit
        companies = list(self.db.scalars(stmt.offset(offset).limit(page_params.limit)))

        if not companies:
            return [], total, pages

        cids = [c.id for c in companies]

        # 1. Punch count
        punch_rows = self.db.execute(
            select(Attendance.company_id, func.count(Attendance.id))
            .where(
                Attendance.company_id.in_(cids),
                Attendance.deleted_at.is_(None),
                Attendance.date >= month_start_date,
            )
            .group_by(Attendance.company_id)
        ).all()
        punch_map = {cid: cnt for cid, cnt in punch_rows}

        # 2. Leave requests by status
        leave_rows = self.db.execute(
            select(Leave.company_id, Leave.status, func.count(Leave.id))
            .where(
                Leave.company_id.in_(cids),
                Leave.deleted_at.is_(None),
                Leave.created_at >= month_start_dt,
            )
            .group_by(Leave.company_id, Leave.status)
        ).all()
        leave_status_map: dict[uuid.UUID, dict[str, int]] = {}
        pending_approvals_map: dict[uuid.UUID, int] = {}
        for cid, st, cnt in leave_rows:
            st_val = st.value if hasattr(st, "value") else str(st)
            if cid not in leave_status_map:
                leave_status_map[cid] = {}
            leave_status_map[cid][st_val] = cnt
            if st_val == "pending":
                pending_approvals_map[cid] = cnt

        # 3. Pending regularizations
        reg_rows = self.db.execute(
            select(
                AttendanceRegularizationRequest.company_id,
                func.count(AttendanceRegularizationRequest.id),
            )
            .where(
                AttendanceRegularizationRequest.company_id.in_(cids),
                AttendanceRegularizationRequest.deleted_at.is_(None),
                AttendanceRegularizationRequest.status == "pending",
            )
            .group_by(AttendanceRegularizationRequest.company_id)
        ).all()
        reg_map = {cid: cnt for cid, cnt in reg_rows}

        # 4. Active projects
        proj_rows = self.db.execute(
            select(Project.company_id, func.count(Project.id))
            .where(
                Project.company_id.in_(cids),
                Project.status == "active",
            )
            .group_by(Project.company_id)
        ).all()
        proj_map = {cid: cnt for cid, cnt in proj_rows}

        # 5. Approved hours logged
        hours_rows = self.db.execute(
            select(
                TimeEntry.company_id,
                func.coalesce(func.sum(TimeEntry.hours), Decimal("0.00")),
            )
            .where(
                TimeEntry.company_id.in_(cids),
                TimeEntry.status == "approved",
                TimeEntry.date >= month_start_date,
            )
            .group_by(TimeEntry.company_id)
        ).all()
        hours_map = {cid: Decimal(str(hrs)) for cid, hrs in hours_rows}

        items = []
        for c in companies:
            items.append(
                {
                    "company_id": c.id,
                    "company_name": c.name,
                    "company_code": c.code,
                    "punch_count": punch_map.get(c.id, 0),
                    "leave_requests_by_status": leave_status_map.get(c.id, {}),
                    "pending_approvals": pending_approvals_map.get(c.id, 0),
                    "pending_regularizations": reg_map.get(c.id, 0),
                    "active_projects": proj_map.get(c.id, 0),
                    "approved_hours_logged": hours_map.get(c.id, Decimal("0.00")),
                }
            )

        return items, total, pages

    def get_platform_health(self) -> dict[str, Any]:
        from app.core.cache import _redis_client
        from app.workers.celery_app import celery_app

        # 1. Background jobs
        jobs_by_status = {"queued": 0, "started": 0, "success": 0, "failure": 0}
        try:
            job_keys = list(_redis_client.scan_iter(match="job:*"))
            for k in job_keys:
                job_id = k.split("job:", 1)[-1]
                res = celery_app.AsyncResult(job_id)
                st = (res.state or "queued").lower()
                if st == "success":
                    jobs_by_status["success"] += 1
                elif st == "failure":
                    jobs_by_status["failure"] += 1
                elif st in ("started", "running"):
                    jobs_by_status["started"] += 1
                else:
                    jobs_by_status["queued"] += 1
        except Exception:
            pass

        failures_24h = jobs_by_status["failure"]

        # 2. Rate drafts awaiting verification (status == "pending")
        drafts_awaiting = (
            self.db.scalar(
                select(func.count(RateChangeDraft.id)).where(RateChangeDraft.status == "pending")
            )
            or 0
        )

        # 3. Next scheduled rate check dates
        sources = list(
            self.db.scalars(
                select(RateSource)
                .where(RateSource.active.is_(True))
                .order_by(RateSource.next_check_on.asc())
            )
        )
        next_checks = {s.title: s.next_check_on.isoformat() for s in sources}

        # 4. Storage bytes by company
        storage_rows = self.db.execute(
            select(FileObject.company_id, func.coalesce(func.sum(FileObject.file_size), 0))
            .where(FileObject.deleted_at.is_(None))
            .group_by(FileObject.company_id)
        ).all()
        storage_map = {str(cid): int(sz) for cid, sz in storage_rows}

        # 5. Notification backlog (unread notifications)
        notification_backlog = (
            self.db.scalar(
                select(func.count(Notification.id)).where(Notification.is_read.is_(False))
            )
            or 0
        )

        return {
            "jobs_by_status": jobs_by_status,
            "job_failures_last_24h": failures_24h,
            "rate_drafts_awaiting_verification": drafts_awaiting,
            "next_scheduled_rate_checks": next_checks,
            "storage_bytes_by_company": storage_map,
            "notification_backlog": notification_backlog,
        }
