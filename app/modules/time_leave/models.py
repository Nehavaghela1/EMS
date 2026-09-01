import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Time as SATime
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantBase


class AttendanceStatus(str, enum.Enum):
    present = "present"
    absent = "absent"
    half_day = "half_day"
    wfh = "wfh"
    on_leave = "on_leave"
    holiday = "holiday"
    weekend = "weekend"


class AttendanceSource(str, enum.Enum):
    web = "web"
    mobile = "mobile"
    system = "system"
    import_ = "import"


class Attendance(TenantBase):
    """RLS: Yes (Spec 7.4)."""

    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_attendance_employee_id_date"),
        Index("ix_attendance_company_id_date", "company_id", "date"),
        Index("ix_attendance_employee_id_date", "employee_id", "date"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus, name="attendance_status"), nullable=False
    )
    hours_worked: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    source: Mapped[AttendanceSource] = mapped_column(
        # values_callable: `import` is a Python keyword, so the enum member
        # is named `import_` — without this, SQLAlchemy's default behaviour
        # (store the Python member NAME, not its .value) would put the
        # literal string "import_" in the database instead of Spec 7.4's
        # "import". Every other enum in this codebase happens to have
        # name == value, which is what made this easy to miss.
        Enum(
            AttendanceSource,
            name="attendance_source",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=AttendanceSource.web,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Shift(TenantBase):
    """RLS: Yes. A shift whose end_time < start_time crosses midnight — hours
    calculation for anyone assigned to it must handle that (Spec 7.4)."""

    __tablename__ = "shifts"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[time] = mapped_column(SATime, nullable=False)
    end_time: Mapped[time] = mapped_column(SATime, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    night_allowance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EmployeeShift(TenantBase):
    """RLS: Yes. No two rows for the same employee may have overlapping
    [effective_from, effective_to] ranges — enforced in the service layer,
    not the database (Spec 7.4 names no constraint for this one)."""

    __tablename__ = "employee_shifts"
    __table_args__ = (Index("ix_employee_shifts_employee_id", "employee_id"),)

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
