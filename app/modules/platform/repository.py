import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate
from app.core.time import utcnow
from app.modules.hr.models import Department, Employee
from app.modules.identity.models import Company, User
from app.modules.platform.models import AuditLog, IndustryPreset, Notification, Announcement, FileObject, EmployeeDocument
from app.modules.time_leave.models import (
    Attendance,
    AttendanceStatus,
    Leave,
    LeaveBalance,
    LeaveStatus,
)


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
        return {name: count for name, count in rows}

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

    def create(self, company_id: uuid.UUID, created_by: uuid.UUID, title: str, content: str, target_role: str, expires_at: datetime | None) -> Announcement:
        announcement = Announcement(
            company_id=company_id,
            created_by=created_by,
            title=title,
            content=content,
            target_role=target_role,
            expires_at=expires_at,
        )
        self.db.add(announcement)
        self.db.flush()
        return announcement

    def list_active(self, company_id: uuid.UUID, user_role: str) -> list[Announcement]:
        now = datetime.now(UTC)
        stmt = (
            select(Announcement)
            .where(
                Announcement.company_id == company_id,
                Announcement.deleted_at.is_(None),
                (Announcement.expires_at.is_(None) | (Announcement.expires_at > now)),
                (Announcement.target_role == "all") | (Announcement.target_role == user_role),
            )
            .order_by(Announcement.created_at.desc())
        )
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

    def create(self, company_id: uuid.UUID, uploaded_by: uuid.UUID, file_name: str, file_type: str, file_size: int, storage_path: str) -> FileObject:
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

    def create(self, company_id: uuid.UUID, employee_id: uuid.UUID, file_object_id: uuid.UUID, document_type: str, name: str) -> EmployeeDocument:
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

    def list_for_employee(self, company_id: uuid.UUID, employee_id: uuid.UUID) -> list[EmployeeDocument]:
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


class SearchRepository:
    def __init__(self, db: Session):
        self.db = db

    def search_all(self, company_id: uuid.UUID, query: str) -> list[dict]:
        from app.modules.projects.models import Project, Task
        q = f"%{query.lower()}%"
        results = []

        # 1. Employees
        emp_stmt = select(Employee).where(
            Employee.company_id == company_id,
            Employee.deleted_at.is_(None),
            Employee.is_active.is_(True),
            (
                func.lower(Employee.first_name).like(q) |
                func.lower(Employee.last_name).like(q) |
                func.lower(Employee.email).like(q) |
                func.lower(Employee.employee_code).like(q)
            )
        ).limit(10)
        for emp in self.db.scalars(emp_stmt):
            results.append({
                "id": emp.id,
                "type": "employee",
                "title": f"{emp.first_name} {emp.last_name}",
                "subtitle": f"{emp.employee_code} • {emp.email}",
                "url": f"/employees/{emp.id}"
            })

        # 2. Projects
        proj_stmt = select(Project).where(
            Project.company_id == company_id,
            (
                func.lower(Project.name).like(q) |
                func.lower(Project.code).like(q) |
                func.lower(Project.client_name).like(q)
            )
        ).limit(10)
        for proj in self.db.scalars(proj_stmt):
            results.append({
                "id": proj.id,
                "type": "project",
                "title": proj.name,
                "subtitle": f"Code: {proj.code} • Status: {proj.status}",
                "url": f"/projects/{proj.id}"
            })

        # 3. Tasks
        task_stmt = select(Task).where(
            Task.company_id == company_id,
            (
                func.lower(Task.title).like(q) |
                func.lower(Task.description).like(q)
            )
        ).limit(10)
        for task in self.db.scalars(task_stmt):
            results.append({
                "id": task.id,
                "type": "task",
                "title": task.title,
                "subtitle": f"Status: {task.status} • Priority: {task.priority}",
                "url": f"/projects/{task.project_id}"
            })

        return results
