import uuid
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate
from app.core.time import utcnow
from app.modules.hr.models import Employee
from app.modules.time_leave.models import Attendance, AttendanceStatus, EmployeeShift, Shift


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
