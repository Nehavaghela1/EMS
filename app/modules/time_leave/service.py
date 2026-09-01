import logging
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams
from app.core.time import utcnow
from app.modules.hr.repository import DepartmentRepository, EmployeeRepository
from app.modules.identity.models import CompanySettings, LeaveYearType, User, UserRole
from app.modules.identity.repository import CompanySettingsRepository
from app.modules.time_leave.models import (
    Attendance,
    AttendanceSource,
    AttendanceStatus,
    EmployeeShift,
    Holiday,
    Leave,
    LeaveBalance,
    LeaveStatus,
    LeaveType,
    Shift,
)
from app.modules.time_leave.repository import (
    AttendanceRepository,
    EmployeeShiftRepository,
    HolidayRepository,
    LeaveBalanceRepository,
    LeaveRepository,
    LeaveTypeRepository,
    ShiftRepository,
)
from app.modules.time_leave.schemas import (
    AttendanceExportRequest,
    AttendanceRegularizeRequest,
    HolidayCreateRequest,
    LeaveApplyRequest,
    LeaveDecisionRequest,
    LeaveTypeCreateRequest,
    LeaveTypeUpdateRequest,
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


class LeaveValidationError(AppError):
    """Spec 11.3 steps 3, 5, 6 — a business-rule violation (400), not a
    schema failure (422)."""

    status_code = 400
    code = "invalid_leave_request"


class LeaveOverlapError(ConflictError):
    """Spec 11.3 step 7: 409, naming the conflicting dates."""

    code = "leave_overlap"

    def __init__(self, conflicts: list[dict]) -> None:
        super().__init__(
            "This leave overlaps an existing pending or approved leave.",
            details={"conflicts": conflicts},
        )


class InsufficientLeaveBalanceError(AppError):
    """Spec 11.3 step 8."""

    status_code = 400
    code = "insufficient_leave_balance"

    def __init__(self, *, available: Decimal, requested: Decimal) -> None:
        super().__init__(
            f"Insufficient leave balance: {available} available, {requested} requested.",
            details={"available": str(available), "requested": str(requested)},
        )


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


class HolidayService:
    """Routes 55-57 (10.4)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = HolidayRepository(db)
        self.department_repo = DepartmentRepository(db)

    def list_holidays(self, company_id: uuid.UUID, year: int) -> list[Holiday]:
        return self.repo.list_by_year(company_id, year)

    def create_holiday(self, company_id: uuid.UUID, data: HolidayCreateRequest) -> Holiday:
        if data.applies_to_department_id is not None:
            if self.department_repo.get_by_id(data.applies_to_department_id, company_id) is None:
                raise InvalidReferenceError(
                    "The specified department does not exist.",
                    details={"field": "applies_to_department_id"},
                )
        holiday = self.repo.create(company_id=company_id, **data.model_dump())
        self.db.commit()
        return holiday

    def delete_holiday(self, company_id: uuid.UUID, holiday_id: uuid.UUID) -> None:
        holiday = self.repo.get_by_id(holiday_id, company_id)
        if holiday is None:
            raise NotFoundError("Holiday not found.")
        self.repo.soft_delete(holiday)
        self.db.commit()


class LeaveTypeService:
    """Routes 58-60 (10.4)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = LeaveTypeRepository(db)

    def list_leave_types(self, company_id: uuid.UUID) -> list[LeaveType]:
        return self.repo.list_all(company_id)

    def create_leave_type(self, company_id: uuid.UUID, data: LeaveTypeCreateRequest) -> LeaveType:
        if self.repo.get_by_code(company_id, data.code):
            raise ConflictError("A leave type with this code already exists.")
        leave_type = self.repo.create(company_id=company_id, **data.model_dump())
        self.db.commit()
        return leave_type

    def update_leave_type(
        self, company_id: uuid.UUID, leave_type_id: uuid.UUID, data: LeaveTypeUpdateRequest
    ) -> LeaveType:
        leave_type = self.repo.get_by_id(leave_type_id, company_id)
        if leave_type is None:
            raise NotFoundError("Leave type not found.")
        self.repo.update(leave_type, **data.model_dump(exclude_unset=True))
        self.db.commit()
        return leave_type


class LeaveService:
    """Routes 61-66 (10.4): the eight application validations, in order
    (11.3), and balance recompute in the same transaction as the status
    change (11.4)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = LeaveRepository(db)
        self.leave_type_repo = LeaveTypeRepository(db)
        self.balance_repo = LeaveBalanceRepository(db)
        self.holiday_repo = HolidayRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.attendance_repo = AttendanceRepository(db)
        self.settings_repo = CompanySettingsRepository(db)

    def _leave_year(self, settings_row: CompanySettings | None, on_date: date) -> int:
        if settings_row is None or settings_row.leave_year_type == LeaveYearType.calendar:
            return on_date.year
        start_month = settings_row.leave_year_start_month
        return on_date.year if on_date.month >= start_month else on_date.year - 1

    def _weekend_days(self, settings_row: CompanySettings | None) -> set[int]:
        return set(settings_row.weekend_days) if settings_row else {6, 7}

    def _total_days(
        self,
        company_id: uuid.UUID,
        settings_row: CompanySettings | None,
        department_id: uuid.UUID | None,
        start_date: date,
        end_date: date,
        is_half_day: bool,
    ) -> Decimal:
        """Spec 11.3: dates inclusive, minus weekends (company_settings.
        weekend_days) and holidays applying to the employee's department."""
        if is_half_day and start_date == end_date:
            return Decimal("0.5")
        weekend_days = self._weekend_days(settings_row)
        holidays = {
            h.date
            for h in self.holiday_repo.list_in_range(
                company_id, start_date, end_date, department_id
            )
        }
        count = 0
        current = start_date
        while current <= end_date:
            if current.isoweekday() not in weekend_days and current not in holidays:
                count += 1
            current += timedelta(days=1)
        return Decimal(count)

    def _get_or_allocate_balance(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, leave_type: LeaveType, year: int
    ) -> LeaveBalance:
        """Balance is materialized the first time this employee needs this
        leave type in this year. WP-10 doesn't build a bulk annual-rollover
        scheduled task (not in either WP-09's or WP-10's deliverable list
        this session — see RECONCILIATION §9/§32) — this lazy path is what
        actually makes a newly created employee's leave usable today; a
        real `allocate_annual_leave` task would apply carry-forward here
        too, which this simpler path does not.
        """
        balance = self.balance_repo.get(employee_id, leave_type.id, year)
        if balance is None:
            balance = self.balance_repo.create(
                company_id=company_id,
                employee_id=employee_id,
                leave_type_id=leave_type.id,
                year=year,
                opening_balance=Decimal("0"),
                allocated=leave_type.annual_allowance,
            )
        return balance

    @staticmethod
    def _available(balance: LeaveBalance) -> Decimal:
        return balance.opening_balance + balance.allocated - balance.used - balance.encashed

    def apply_leave(
        self, company_id: uuid.UUID, data: LeaveApplyRequest, current_user: User
    ) -> Leave:
        """Route 62. Every validation in 11.3, in order — the first failure
        wins."""
        target_employee_id = data.employee_id
        if target_employee_id is None:
            caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
            if caller_employee is None:
                raise NotFoundError("You do not have an employee record.")
            target_employee_id = caller_employee.id

        # 1. The employee exists, is active, and belongs to the caller's company.
        employee = self.employee_repo.get_by_id(target_employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")

        # 2. The caller is that employee, HR, or that employee's manager.
        is_hr = current_user.role == UserRole.hr_admin
        is_own = employee.user_id == current_user.id
        is_manager = False
        if current_user.role == UserRole.manager:
            caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
            is_manager = (
                caller_employee is not None and employee.reporting_manager_id == caller_employee.id
            )
        if not (is_hr or is_own or is_manager):
            raise ForbiddenError(
                "You do not have permission to apply for leave on behalf of this employee."
            )

        # 3. end_date >= start_date.
        if data.end_date < data.start_date:
            raise LeaveValidationError(
                "end_date must be on or after start_date.", details={"field": "end_date"}
            )

        # 4. leave_type_id exists, belongs to this company, and is active.
        leave_type = self.leave_type_repo.get_by_id(data.leave_type_id, company_id)
        if leave_type is None or not leave_type.is_active:
            raise NotFoundError("Leave type not found.")

        # 5. start_date >= today, unless the caller is HR (may back-date; audited).
        today = utcnow().date()
        if data.start_date < today:
            if not is_hr:
                raise LeaveValidationError(
                    "Cannot apply for leave in the past.", details={"field": "start_date"}
                )
            logger.info(
                "leave_backdated_by_hr",
                extra={
                    "actor_id": str(current_user.id),
                    "employee_id": str(employee.id),
                    "start_date": data.start_date.isoformat(),
                },
            )

        settings_row = self.settings_repo.get_by_company(company_id)
        total_days = self._total_days(
            company_id,
            settings_row,
            employee.department_id,
            data.start_date,
            data.end_date,
            data.is_half_day,
        )

        # 6. max_consecutive_days on the leave type is not exceeded.
        if (
            leave_type.max_consecutive_days is not None
            and total_days > leave_type.max_consecutive_days
        ):
            raise LeaveValidationError(
                f"This leave type allows at most {leave_type.max_consecutive_days} "
                "consecutive day(s).",
                details={
                    "field": "end_date",
                    "max_consecutive_days": leave_type.max_consecutive_days,
                },
            )

        # 7. No overlap with an existing pending/approved leave for this employee.
        overlapping = self.repo.get_overlapping(
            company_id=company_id,
            employee_id=employee.id,
            start_date=data.start_date,
            end_date=data.end_date,
        )
        if overlapping:
            conflicts = [
                {
                    "id": str(o.id),
                    "start_date": o.start_date.isoformat(),
                    "end_date": o.end_date.isoformat(),
                }
                for o in overlapping
            ]
            raise LeaveOverlapError(conflicts)

        # 8. Sufficient balance for the year, unless the leave type is unpaid (LOP).
        if leave_type.is_paid:
            year = self._leave_year(settings_row, data.start_date)
            balance = self._get_or_allocate_balance(company_id, employee.id, leave_type, year)
            available = self._available(balance)
            if available < total_days:
                raise InsufficientLeaveBalanceError(available=available, requested=total_days)

        leave = self.repo.create(
            company_id=company_id,
            employee_id=employee.id,
            leave_type_id=leave_type.id,
            start_date=data.start_date,
            end_date=data.end_date,
            total_days=total_days,
            is_half_day=data.is_half_day,
            reason=data.reason,
            status=LeaveStatus.pending,
        )
        self.db.commit()
        return leave

    def _assert_can_view(self, company_id: uuid.UUID, employee, current_user: User) -> None:
        if current_user.role == UserRole.hr_admin:
            return
        if employee is not None and employee.user_id == current_user.id:
            return
        if current_user.role == UserRole.manager and employee is not None:
            caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
            if caller_employee is not None and employee.reporting_manager_id == caller_employee.id:
                return
        raise ForbiddenError("You do not have permission to view this leave.")

    def get_leave(self, company_id: uuid.UUID, leave_id: uuid.UUID, current_user: User) -> Leave:
        """Route 63: Own, Mgr, HR."""
        leave = self.repo.get_by_id(leave_id, company_id)
        if leave is None:
            raise NotFoundError("Leave not found.")
        employee = self.employee_repo.get_by_id_any_status(leave.employee_id, company_id)
        self._assert_can_view(company_id, employee, current_user)
        return leave

    def list_leaves(
        self,
        company_id: uuid.UUID,
        current_user: User,
        *,
        employee_id: uuid.UUID | None,
        status: LeaveStatus | None,
        leave_type_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        page_params: PageParams,
    ) -> tuple[list[Leave], int, int]:
        """Route 61: scoped by role, the same shape as attendance's list."""
        allowed: list[uuid.UUID] | None
        if current_user.role in _SEES_EVERYONE:
            allowed = None
        else:
            caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
            if caller_employee is None:
                return [], 0, 0
            if current_user.role == UserRole.manager:
                allowed = self.employee_repo.list_direct_report_ids(company_id, caller_employee.id)
            else:
                allowed = [caller_employee.id]
        if allowed is not None:
            if not allowed:
                return [], 0, 0
            if employee_id is not None and employee_id not in allowed:
                return [], 0, 0
        return self.repo.list_leaves(
            company_id=company_id,
            allowed_employee_ids=allowed,
            employee_id=employee_id,
            status=status,
            leave_type_id=leave_type_id,
            date_from=date_from,
            date_to=date_to,
            page_params=page_params,
        )

    def _write_attendance_for_leave(
        self,
        company_id: uuid.UUID,
        settings_row: CompanySettings | None,
        employee,
        leave: Leave,
    ) -> None:
        weekend_days = self._weekend_days(settings_row)
        holidays = {
            h.date
            for h in self.holiday_repo.list_in_range(
                company_id, leave.start_date, leave.end_date, employee.department_id
            )
        }
        current = leave.start_date
        while current <= leave.end_date:
            if current.isoweekday() not in weekend_days and current not in holidays:
                self.attendance_repo.upsert_for_leave(
                    company_id=company_id,
                    employee_id=employee.id,
                    on_date=current,
                    status=AttendanceStatus.on_leave,
                )
            current += timedelta(days=1)

    def _reverse_attendance_for_leave(self, company_id: uuid.UUID, employee, leave: Leave) -> None:
        """Undoes exactly what approval wrote: soft-deletes the `on_leave`,
        `source=system` rows the upsert created. A day the employee had
        already marked for real (present/wfh, source=web) before approval,
        if any, was overwritten by the upsert and cannot be recovered — the
        schema keeps no history of what a row was before an upsert; this is
        the only reversal the current data model supports."""
        current = leave.start_date
        while current <= leave.end_date:
            record = self.attendance_repo.get_by_employee_and_date(company_id, employee.id, current)
            if (
                record is not None
                and record.source == AttendanceSource.system
                and record.status == AttendanceStatus.on_leave
            ):
                self.attendance_repo.soft_delete(record)
            current += timedelta(days=1)

    def decide_leave(
        self, company_id: uuid.UUID, leave_id: uuid.UUID, data: LeaveDecisionRequest, actor: User
    ) -> Leave:
        """Route 64: Mgr (own reports only), HR. Approval auto-marks
        attendance and recomputes the balance inside the same transaction
        as the status change (11.4) — one commit, at the end."""
        leave = self.repo.get_by_id(leave_id, company_id)
        if leave is None:
            raise NotFoundError("Leave not found.")
        if leave.status != LeaveStatus.pending:
            raise ConflictError(f"Leave is not pending (current status: {leave.status.value}).")

        employee = self.employee_repo.get_by_id_any_status(leave.employee_id, company_id)
        is_hr = actor.role == UserRole.hr_admin
        is_manager = False
        if actor.role == UserRole.manager and employee is not None:
            caller_employee = self.employee_repo.get_by_user_id(company_id, actor.id)
            is_manager = (
                caller_employee is not None and employee.reporting_manager_id == caller_employee.id
            )
        if not (is_hr or is_manager):
            raise ForbiddenError("You do not have permission to decide this leave.")
        assert employee is not None  # guaranteed live by leave.employee_id's FK

        if data.status == "approved":
            leave_type = self.leave_type_repo.get_by_id(leave.leave_type_id, company_id)
            settings_row = self.settings_repo.get_by_company(company_id)
            self.repo.update(
                leave, status=LeaveStatus.approved, approved_by=actor.id, approved_at=utcnow()
            )
            if leave_type is not None and leave_type.is_paid:
                year = self._leave_year(settings_row, leave.start_date)
                balance = self._get_or_allocate_balance(company_id, employee.id, leave_type, year)
                self.balance_repo.update(balance, used=balance.used + leave.total_days)
            self._write_attendance_for_leave(company_id, settings_row, employee, leave)
        else:
            if not data.rejection_reason:
                raise LeaveValidationError(
                    "A rejection reason is required.", details={"field": "rejection_reason"}
                )
            self.repo.update(
                leave, status=LeaveStatus.rejected, rejection_reason=data.rejection_reason
            )

        self.db.commit()
        return leave

    def cancel_leave(self, company_id: uuid.UUID, leave_id: uuid.UUID, actor: User) -> Leave:
        """Route 65: the employee cancels their own **pending** leave; HR
        may additionally cancel an **approved** leave, reversing the
        attendance rows and restoring the balance (11.3)."""
        leave = self.repo.get_by_id(leave_id, company_id)
        if leave is None:
            raise NotFoundError("Leave not found.")
        employee = self.employee_repo.get_by_id_any_status(leave.employee_id, company_id)
        is_hr = actor.role == UserRole.hr_admin
        is_own = employee is not None and employee.user_id == actor.id

        if leave.status == LeaveStatus.pending:
            if not (is_hr or is_own):
                raise ForbiddenError("You do not have permission to cancel this leave.")
            self.repo.update(leave, status=LeaveStatus.cancelled)
        elif leave.status == LeaveStatus.approved:
            if not is_hr:
                raise ForbiddenError("Only HR may cancel an approved leave.")
            assert employee is not None
            settings_row = self.settings_repo.get_by_company(company_id)
            self._reverse_attendance_for_leave(company_id, employee, leave)
            leave_type = self.leave_type_repo.get_by_id(leave.leave_type_id, company_id)
            if leave_type is not None and leave_type.is_paid:
                year = self._leave_year(settings_row, leave.start_date)
                balance = self.balance_repo.get(employee.id, leave_type.id, year)
                if balance is not None:
                    self.balance_repo.update(
                        balance, used=max(balance.used - leave.total_days, Decimal("0"))
                    )
            self.repo.update(leave, status=LeaveStatus.cancelled)
        else:
            raise ConflictError(f"Cannot cancel a leave that is {leave.status.value}.")

        self.db.commit()
        return leave

    def get_balance(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, year: int, current_user: User
    ) -> list[tuple[LeaveBalance, str]]:
        """Route 66: Own, HR. Returns (balance, leave_type_name) pairs — the
        router maps each to a LeaveBalanceResponse with `available` computed."""
        employee = self.employee_repo.get_by_id(employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        is_hr = current_user.role == UserRole.hr_admin
        is_own = employee.user_id == current_user.id
        if not (is_hr or is_own):
            raise ForbiddenError("You do not have permission to view this balance.")

        balances = self.balance_repo.list_for_employee_year(employee_id, year)
        leave_type_names = {lt.id: lt.name for lt in self.leave_type_repo.list_all(company_id)}
        return [(b, leave_type_names.get(b.leave_type_id, "Unknown")) for b in balances]
