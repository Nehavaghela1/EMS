import logging
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams
from app.core.time import utcnow
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole
from app.modules.identity.repository import CompanySettingsRepository
from app.modules.time_leave.models import (
    Attendance,
    AttendanceSource,
    AttendanceStatus,
    EmployeeShift,
    Shift,
)
from app.modules.time_leave.repository import (
    AttendanceRepository,
    EmployeeShiftRepository,
    ShiftRepository,
)
from app.modules.time_leave.schemas import (
    AttendanceExportRequest,
    AttendanceRegularizeRequest,
    ShiftAssignRequest,
    ShiftCreateRequest,
    ShiftUpdateRequest,
)

logger = logging.getLogger("app")

_SEES_EVERYONE = (UserRole.hr_admin, UserRole.super_admin)


class AlreadyCheckedInError(ConflictError):
    def __init__(self) -> None:
        super().__init__("Already checked in for today.")


class NoCheckInError(AppError):
    status_code = 400
    code = "no_check_in"

    def __init__(self) -> None:
        super().__init__("No check-in record found for today.")


class InvalidCheckOutError(AppError):
    status_code = 400
    code = "invalid_check_out"

    def __init__(self) -> None:
        super().__init__("Check-out time must be after check-in.")


class InvalidReferenceError(AppError):
    """A body field references another resource that doesn't exist in this
    company — a business-rule violation (400), not a schema failure (422).
    Mirrors app.modules.hr.service's class of the same name; kept local so
    this module doesn't reach into hr's service layer for an exception."""

    status_code = 400
    code = "invalid_reference"


class AttendanceService:
    """Routes 43-49 (10.4), hours calculation (11.5)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = AttendanceRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.settings_repo = CompanySettingsRepository(db)

    def _resolve_scope(self, company_id: uuid.UUID, current_user: User) -> list[uuid.UUID] | None:
        """None = unrestricted (HR/SA). A list = restricted to exactly these
        employee ids (self for an employee, direct reports for a manager)."""
        if current_user.role in _SEES_EVERYONE:
            return None
        caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
        if caller_employee is None:
            return []
        if current_user.role == UserRole.manager:
            return self.employee_repo.list_direct_report_ids(company_id, caller_employee.id)
        return [caller_employee.id]

    def check_in(self, company_id: uuid.UUID, current_user: User) -> Attendance:
        """Route 43. 409 if a record already exists for today — the
        database's `uq_attendance_employee_id_date` is the real backstop
        (11.5); this proactive check just gives a friendlier message."""
        employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
        if employee is None:
            raise NotFoundError("You do not have an employee record.")
        today = utcnow().date()
        if self.repo.get_by_employee_and_date(company_id, employee.id, today):
            raise AlreadyCheckedInError()
        record = self.repo.create(
            company_id=company_id,
            employee_id=employee.id,
            date=today,
            check_in=utcnow(),
            status=AttendanceStatus.present,
            source=AttendanceSource.web,
        )
        self.db.commit()
        return record

    def check_out(self, company_id: uuid.UUID, current_user: User) -> Attendance:
        """Route 44. 400 with no check-in, or check_out <= check_in.
        hours_worked is real elapsed time between two TIMESTAMPTZ values —
        correct across a midnight boundary with no special-casing, unlike
        naive TIME-of-day arithmetic on a shift's start/end would be."""
        employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
        if employee is None:
            raise NotFoundError("You do not have an employee record.")
        record = self.repo.get_open_for_employee(company_id, employee.id)
        if record is None:
            raise NoCheckInError()
        assert record.check_in is not None  # guaranteed by get_open_for_employee's own filter
        now = utcnow()
        if now <= record.check_in:
            raise InvalidCheckOutError()

        hours = (Decimal((now - record.check_in).total_seconds()) / Decimal(3600)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        settings_row = self.settings_repo.get_by_company(company_id)
        threshold = settings_row.half_day_hours_threshold if settings_row else Decimal("4")
        status = AttendanceStatus.half_day if hours < threshold else AttendanceStatus.present

        self.repo.update(record, check_out=now, hours_worked=hours, status=status)
        self.db.commit()
        return record

    def list_attendance(
        self,
        company_id: uuid.UUID,
        current_user: User,
        *,
        employee_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: AttendanceStatus | None,
        department_id: uuid.UUID | None,
        page_params: PageParams,
    ) -> tuple[list[Attendance], int, int]:
        """Route 45: employees see own, managers their team, HR everyone."""
        allowed = self._resolve_scope(company_id, current_user)
        if allowed is not None:
            if not allowed:
                return [], 0, 0
            if employee_id is not None and employee_id not in allowed:
                return [], 0, 0
        return self.repo.list_attendance(
            company_id=company_id,
            allowed_employee_ids=allowed,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            department_id=department_id,
            page_params=page_params,
        )

    def _assert_can_view(
        self, company_id: uuid.UUID, record: Attendance, current_user: User
    ) -> None:
        if current_user.role in _SEES_EVERYONE:
            return
        caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
        if caller_employee is not None and record.employee_id == caller_employee.id:
            return
        if current_user.role == UserRole.manager and caller_employee is not None:
            report_ids = self.employee_repo.list_direct_report_ids(company_id, caller_employee.id)
            if record.employee_id in report_ids:
                return
        raise ForbiddenError("You do not have permission to view this attendance record.")

    def get_attendance(
        self, company_id: uuid.UUID, attendance_id: uuid.UUID, current_user: User
    ) -> Attendance:
        """Route 46: Own, Mgr, HR."""
        record = self.repo.get_by_id(attendance_id, company_id)
        if record is None:
            raise NotFoundError("Attendance record not found.")
        self._assert_can_view(company_id, record, current_user)
        return record

    def regularize(
        self,
        company_id: uuid.UUID,
        attendance_id: uuid.UUID,
        data: AttendanceRegularizeRequest,
        actor: User,
    ) -> Attendance:
        """Route 47, HR only. The previous value and reason are logged
        structurally now — audit_logs (WP-11) will replace this with a real
        row; see the TODO below."""
        record = self.repo.get_by_id(attendance_id, company_id)
        if record is None:
            raise NotFoundError("Attendance record not found.")

        previous = {
            "check_in": record.check_in.isoformat() if record.check_in else None,
            "check_out": record.check_out.isoformat() if record.check_out else None,
            "status": record.status.value,
            "notes": record.notes,
        }
        updates = data.model_dump(exclude={"reason"}, exclude_unset=True)
        self.repo.update(record, **updates)
        # TODO(WP-11): write a real audit_logs row (action=attendance_regularized)
        # once that table exists — this structured log line is the interim record.
        logger.info(
            "attendance_regularized",
            extra={
                "attendance_id": str(record.id),
                "actor_id": str(actor.id),
                "reason": data.reason,
                "previous": previous,
                "new": {
                    k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in updates.items()
                },
            },
        )
        self.db.commit()
        return record

    def delete_attendance(
        self, company_id: uuid.UUID, attendance_id: uuid.UUID, actor: User
    ) -> None:
        """Route 48, HR only. Soft delete (7.1's universal rule; `attendance`
        is not append-only), audited the same interim way as regularize."""
        record = self.repo.get_by_id(attendance_id, company_id)
        if record is None:
            raise NotFoundError("Attendance record not found.")
        # TODO(WP-11): write a real audit_logs row (action=attendance_deleted).
        logger.info(
            "attendance_deleted", extra={"attendance_id": str(record.id), "actor_id": str(actor.id)}
        )
        self.repo.soft_delete(record)
        self.db.commit()

    def queue_export(self, company_id: uuid.UUID, data: AttendanceExportRequest) -> str:
        """Route 49: queues the real Celery job (13.1), returns its id."""
        from app.workers.tasks.attendance import export_attendance_csv_task

        task = export_attendance_csv_task.delay(
            company_id=str(company_id),
            employee_id=str(data.employee_id) if data.employee_id else None,
            date_from=data.date_from.isoformat() if data.date_from else None,
            date_to=data.date_to.isoformat() if data.date_to else None,
            status=data.status.value if data.status else None,
            department_id=str(data.department_id) if data.department_id else None,
        )
        return task.id


class ShiftService:
    """Routes 50-54 (10.4)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = ShiftRepository(db)
        self.employee_shift_repo = EmployeeShiftRepository(db)
        self.employee_repo = EmployeeRepository(db)

    def list_shifts(
        self, company_id: uuid.UUID, page_params: PageParams
    ) -> tuple[list[Shift], int, int]:
        return self.repo.list_shifts(company_id, page_params)

    def create_shift(self, company_id: uuid.UUID, data: ShiftCreateRequest) -> Shift:
        shift = self.repo.create(company_id=company_id, **data.model_dump())
        self.db.commit()
        return shift

    def _get_or_404(self, company_id: uuid.UUID, shift_id: uuid.UUID) -> Shift:
        shift = self.repo.get_by_id(shift_id, company_id)
        if shift is None:
            raise NotFoundError("Shift not found.")
        return shift

    def get_shift(self, company_id: uuid.UUID, shift_id: uuid.UUID) -> Shift:
        return self._get_or_404(company_id, shift_id)

    def update_shift(
        self, company_id: uuid.UUID, shift_id: uuid.UUID, data: ShiftUpdateRequest
    ) -> Shift:
        shift = self._get_or_404(company_id, shift_id)
        self.repo.update(shift, **data.model_dump(exclude_unset=True))
        self.db.commit()
        return shift

    def delete_shift(self, company_id: uuid.UUID, shift_id: uuid.UUID) -> None:
        """Route 53: blocked if currently assigned (effective_from <= today
        <= effective_to-or-ongoing)."""
        shift = self._get_or_404(company_id, shift_id)
        today = utcnow().date()
        count = self.repo.count_current_assignments(shift_id, company_id, today)
        if count > 0:
            raise ConflictError(
                f"Cannot delete a shift with {count} current assignment(s).",
                details={"assignment_count": count},
            )
        self.repo.soft_delete(shift)
        self.db.commit()

    def assign_shift(
        self, company_id: uuid.UUID, shift_id: uuid.UUID, data: ShiftAssignRequest
    ) -> EmployeeShift:
        """Route 54: rejects overlapping assignments for the same employee."""
        self._get_or_404(company_id, shift_id)
        employee = self.employee_repo.get_by_id(data.employee_id, company_id)
        if employee is None:
            raise InvalidReferenceError(
                "The specified employee does not exist.", details={"field": "employee_id"}
            )
        if data.effective_to is not None and data.effective_to < data.effective_from:
            raise InvalidReferenceError(
                "effective_to must be on or after effective_from.",
                details={"field": "effective_to"},
            )
        overlapping = self.employee_shift_repo.get_overlapping(
            company_id=company_id,
            employee_id=data.employee_id,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
        )
        if overlapping:
            raise ConflictError(
                "This employee already has a shift assignment overlapping these dates."
            )
        assignment = self.employee_shift_repo.create(
            company_id=company_id,
            employee_id=data.employee_id,
            shift_id=shift_id,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
        )
        self.db.commit()
        return assignment
