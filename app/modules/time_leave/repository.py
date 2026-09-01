import uuid
from datetime import date

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate
from app.core.time import utcnow
from app.modules.hr.models import Employee
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


class AttendanceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, attendance_id: uuid.UUID, company_id: uuid.UUID) -> Attendance | None:
        return self.db.scalar(
            select(Attendance).where(
                Attendance.id == attendance_id,
                Attendance.company_id == company_id,
                Attendance.deleted_at.is_(None),
            )
        )

    def get_by_employee_and_date(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, on_date: date
    ) -> Attendance | None:
        return self.db.scalar(
            select(Attendance).where(
                Attendance.company_id == company_id,
                Attendance.employee_id == employee_id,
                Attendance.date == on_date,
                Attendance.deleted_at.is_(None),
            )
        )

    def get_open_for_employee(
        self, company_id: uuid.UUID, employee_id: uuid.UUID
    ) -> Attendance | None:
        """Check-out (route 44) must not re-derive "today" independently of
        check-in: for a shift crossing midnight (11.5), check-in creates a
        row dated the day they checked IN, but by check-out time
        `utcnow().date()` may already be the next calendar day. The record
        to close is whichever one is still open, not whichever is dated
        "today" from check-out's own perspective."""
        return self.db.scalar(
            select(Attendance)
            .where(
                Attendance.company_id == company_id,
                Attendance.employee_id == employee_id,
                Attendance.check_in.is_not(None),
                Attendance.check_out.is_(None),
                Attendance.deleted_at.is_(None),
            )
            .order_by(Attendance.date.desc())
            .limit(1)
        )

    def _filtered(
        self,
        *,
        company_id: uuid.UUID,
        allowed_employee_ids: list[uuid.UUID] | None,
        employee_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: AttendanceStatus | None,
        department_id: uuid.UUID | None,
    ):
        stmt = select(Attendance).where(
            Attendance.company_id == company_id, Attendance.deleted_at.is_(None)
        )
        if allowed_employee_ids is not None:
            stmt = stmt.where(Attendance.employee_id.in_(allowed_employee_ids))
        if employee_id is not None:
            stmt = stmt.where(Attendance.employee_id == employee_id)
        if date_from is not None:
            stmt = stmt.where(Attendance.date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Attendance.date <= date_to)
        if status is not None:
            stmt = stmt.where(Attendance.status == status)
        if department_id is not None:
            stmt = stmt.join(Employee, Employee.id == Attendance.employee_id).where(
                Employee.department_id == department_id
            )
        return stmt

    def list_attendance(
        self,
        *,
        company_id: uuid.UUID,
        allowed_employee_ids: list[uuid.UUID] | None,
        employee_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: AttendanceStatus | None,
        department_id: uuid.UUID | None,
        page_params: PageParams,
    ) -> tuple[list[Attendance], int, int]:
        stmt = self._filtered(
            company_id=company_id,
            allowed_employee_ids=allowed_employee_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            department_id=department_id,
        ).order_by(Attendance.date.desc())
        return paginate(self.db, stmt, page_params)

    def list_for_export(
        self,
        *,
        company_id: uuid.UUID,
        employee_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: AttendanceStatus | None,
        department_id: uuid.UUID | None,
    ) -> list[Attendance]:
        stmt = self._filtered(
            company_id=company_id,
            allowed_employee_ids=None,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            department_id=department_id,
        ).order_by(Attendance.date.asc())
        return list(self.db.scalars(stmt).all())

    def create(self, **kwargs) -> Attendance:
        attendance = Attendance(**kwargs)
        self.db.add(attendance)
        self.db.flush()
        return attendance

    def update(self, attendance: Attendance, **kwargs) -> Attendance:
        for key, value in kwargs.items():
            setattr(attendance, key, value)
        self.db.flush()
        return attendance

    def soft_delete(self, attendance: Attendance) -> None:
        attendance.deleted_at = utcnow()
        self.db.flush()

    def upsert_for_leave(
        self,
        *,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        on_date: date,
        status: AttendanceStatus,
    ) -> None:
        """Spec 11.3: leave approval upserts via a real `ON CONFLICT
        (employee_id, date) DO UPDATE` — not a Python select-then-branch —
        since the employee may already have marked attendance that day."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(Attendance).values(
            id=uuid.uuid4(),
            company_id=company_id,
            employee_id=employee_id,
            date=on_date,
            status=status,
            source=AttendanceSource.system,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["employee_id", "date"],
            set_={"status": status, "source": AttendanceSource.system, "deleted_at": None},
        )
        self.db.execute(stmt)


class ShiftRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, shift_id: uuid.UUID, company_id: uuid.UUID) -> Shift | None:
        return self.db.scalar(
            select(Shift).where(
                Shift.id == shift_id, Shift.company_id == company_id, Shift.deleted_at.is_(None)
            )
        )

    def list_shifts(
        self, company_id: uuid.UUID, page_params: PageParams
    ) -> tuple[list[Shift], int, int]:
        stmt = (
            select(Shift)
            .where(Shift.company_id == company_id, Shift.deleted_at.is_(None))
            .order_by(Shift.name.asc())
        )
        return paginate(self.db, stmt, page_params)

    def create(self, **kwargs) -> Shift:
        shift = Shift(**kwargs)
        self.db.add(shift)
        self.db.flush()
        return shift

    def update(self, shift: Shift, **kwargs) -> Shift:
        for key, value in kwargs.items():
            setattr(shift, key, value)
        self.db.flush()
        return shift

    def soft_delete(self, shift: Shift) -> None:
        shift.deleted_at = utcnow()
        self.db.flush()

    def count_current_assignments(
        self, shift_id: uuid.UUID, company_id: uuid.UUID, today: date
    ) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(EmployeeShift)
                .where(
                    EmployeeShift.company_id == company_id,
                    EmployeeShift.shift_id == shift_id,
                    EmployeeShift.deleted_at.is_(None),
                    EmployeeShift.effective_from <= today,
                    or_(
                        EmployeeShift.effective_to.is_(None),
                        EmployeeShift.effective_to >= today,
                    ),
                )
            )
            or 0
        )


class EmployeeShiftRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_overlapping(
        self,
        *,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        effective_from: date,
        effective_to: date | None,
    ) -> list[EmployeeShift]:
        """Two [from, to] ranges (NULL `to` meaning ongoing) overlap iff each
        range's start is not after the other's end."""
        stmt = select(EmployeeShift).where(
            EmployeeShift.company_id == company_id,
            EmployeeShift.employee_id == employee_id,
            EmployeeShift.deleted_at.is_(None),
            EmployeeShift.effective_from <= (effective_to or date.max),
            or_(
                EmployeeShift.effective_to.is_(None),
                EmployeeShift.effective_to >= effective_from,
            ),
        )
        return list(self.db.scalars(stmt).all())

    def create(self, **kwargs) -> EmployeeShift:
        employee_shift = EmployeeShift(**kwargs)
        self.db.add(employee_shift)
        self.db.flush()
        return employee_shift


class HolidayRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, holiday_id: uuid.UUID, company_id: uuid.UUID) -> Holiday | None:
        return self.db.scalar(
            select(Holiday).where(
                Holiday.id == holiday_id,
                Holiday.company_id == company_id,
                Holiday.deleted_at.is_(None),
            )
        )

    def list_by_year(self, company_id: uuid.UUID, year: int) -> list[Holiday]:
        stmt = (
            select(Holiday)
            .where(
                Holiday.company_id == company_id,
                Holiday.deleted_at.is_(None),
                func.extract("year", Holiday.date) == year,
            )
            .order_by(Holiday.date.asc())
        )
        return list(self.db.scalars(stmt).all())

    def list_in_range(
        self,
        company_id: uuid.UUID,
        start_date: date,
        end_date: date,
        department_id: uuid.UUID | None,
    ) -> list[Holiday]:
        """Holidays that count against a leave spanning [start_date,
        end_date] — company-wide (`applies_to_department_id IS NULL`) plus
        the employee's own department's, if any (Spec 11.3)."""
        department_clause: ColumnElement[bool] = Holiday.applies_to_department_id.is_(None)
        if department_id is not None:
            department_clause = or_(
                Holiday.applies_to_department_id.is_(None),
                Holiday.applies_to_department_id == department_id,
            )
        stmt = select(Holiday).where(
            Holiday.company_id == company_id,
            Holiday.deleted_at.is_(None),
            Holiday.date >= start_date,
            Holiday.date <= end_date,
            department_clause,
        )
        return list(self.db.scalars(stmt).all())

    def create(self, **kwargs) -> Holiday:
        holiday = Holiday(**kwargs)
        self.db.add(holiday)
        self.db.flush()
        return holiday

    def soft_delete(self, holiday: Holiday) -> None:
        holiday.deleted_at = utcnow()
        self.db.flush()


class LeaveTypeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, leave_type_id: uuid.UUID, company_id: uuid.UUID) -> LeaveType | None:
        return self.db.scalar(
            select(LeaveType).where(
                LeaveType.id == leave_type_id,
                LeaveType.company_id == company_id,
                LeaveType.deleted_at.is_(None),
            )
        )

    def get_by_code(self, company_id: uuid.UUID, code: str) -> LeaveType | None:
        return self.db.scalar(
            select(LeaveType).where(
                LeaveType.company_id == company_id,
                func.lower(LeaveType.code) == code.lower(),
                LeaveType.deleted_at.is_(None),
            )
        )

    def list_all(self, company_id: uuid.UUID) -> list[LeaveType]:
        stmt = (
            select(LeaveType)
            .where(LeaveType.company_id == company_id, LeaveType.deleted_at.is_(None))
            .order_by(LeaveType.name.asc())
        )
        return list(self.db.scalars(stmt).all())

    def create(self, **kwargs) -> LeaveType:
        leave_type = LeaveType(**kwargs)
        self.db.add(leave_type)
        self.db.flush()
        return leave_type

    def update(self, leave_type: LeaveType, **kwargs) -> LeaveType:
        for key, value in kwargs.items():
            setattr(leave_type, key, value)
        self.db.flush()
        return leave_type


class LeaveRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, leave_id: uuid.UUID, company_id: uuid.UUID) -> Leave | None:
        return self.db.scalar(
            select(Leave).where(
                Leave.id == leave_id, Leave.company_id == company_id, Leave.deleted_at.is_(None)
            )
        )

    def get_overlapping(
        self,
        *,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> list[Leave]:
        """Spec 11.3 step 7: overlap against any existing `pending` or
        `approved` leave for this employee — `existing.start <= new.end AND
        existing.end >= new.start`."""
        stmt = select(Leave).where(
            Leave.company_id == company_id,
            Leave.employee_id == employee_id,
            Leave.deleted_at.is_(None),
            Leave.status.in_([LeaveStatus.pending, LeaveStatus.approved]),
            Leave.start_date <= end_date,
            Leave.end_date >= start_date,
        )
        return list(self.db.scalars(stmt).all())

    def list_leaves(
        self,
        *,
        company_id: uuid.UUID,
        allowed_employee_ids: list[uuid.UUID] | None,
        employee_id: uuid.UUID | None,
        status: LeaveStatus | None,
        leave_type_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        page_params: PageParams,
    ) -> tuple[list[Leave], int, int]:
        stmt = select(Leave).where(Leave.company_id == company_id, Leave.deleted_at.is_(None))
        if allowed_employee_ids is not None:
            stmt = stmt.where(Leave.employee_id.in_(allowed_employee_ids))
        if employee_id is not None:
            stmt = stmt.where(Leave.employee_id == employee_id)
        if status is not None:
            stmt = stmt.where(Leave.status == status)
        if leave_type_id is not None:
            stmt = stmt.where(Leave.leave_type_id == leave_type_id)
        if date_from is not None:
            stmt = stmt.where(Leave.end_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Leave.start_date <= date_to)
        stmt = stmt.order_by(Leave.start_date.desc())
        return paginate(self.db, stmt, page_params)

    def create(self, **kwargs) -> Leave:
        leave = Leave(**kwargs)
        self.db.add(leave)
        self.db.flush()
        return leave

    def update(self, leave: Leave, **kwargs) -> Leave:
        for key, value in kwargs.items():
            setattr(leave, key, value)
        self.db.flush()
        return leave


class LeaveBalanceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(
        self, employee_id: uuid.UUID, leave_type_id: uuid.UUID, year: int
    ) -> LeaveBalance | None:
        return self.db.scalar(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee_id,
                LeaveBalance.leave_type_id == leave_type_id,
                LeaveBalance.year == year,
            )
        )

    def list_for_employee_year(self, employee_id: uuid.UUID, year: int) -> list[LeaveBalance]:
        stmt = select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id, LeaveBalance.year == year
        )
        return list(self.db.scalars(stmt).all())

    def create(self, **kwargs) -> LeaveBalance:
        balance = LeaveBalance(**kwargs)
        self.db.add(balance)
        self.db.flush()
        return balance

    def update(self, balance: LeaveBalance, **kwargs) -> LeaveBalance:
        for key, value in kwargs.items():
            setattr(balance, key, value)
        self.db.flush()
        return balance
