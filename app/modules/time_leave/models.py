import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
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


class Holiday(TenantBase):
    """RLS: Yes. `NULLS NOT DISTINCT` is essential (Spec 7.4): without it, a
    company-wide holiday (applies_to_department_id IS NULL) could be
    inserted twice for the same date, silently double-counting it out of
    every leave application spanning it (11.3)."""

    __tablename__ = "holidays"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "date",
            "applies_to_department_id",
            name="uq_holidays_company_id_date_department_id",
            postgresql_nulls_not_distinct=True,
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applies_to_department_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )


class LeaveType(TenantBase):
    """RLS: Yes — configurable per company, never a Python enum (Spec 7.4:
    "Do not put leave type names in a Python enum — that would make them
    un-configurable, breaking rule 7")."""

    __tablename__ = "leave_types"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_leave_types_company_id_code"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    annual_allowance: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("0")
    )
    carry_forward_limit: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("0")
    )
    max_consecutive_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_encashable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class LeaveStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class Leave(TenantBase):
    """RLS: Yes (Spec 7.4)."""

    __tablename__ = "leaves"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_leaves_end_date_after_start_date"),
        Index("ix_leaves_company_id_status", "company_id", "status"),
        Index("ix_leaves_employee_id_start_date", "employee_id", "start_date"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leave_types.id"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    is_half_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[LeaveStatus] = mapped_column(
        Enum(LeaveStatus, name="leave_status"), nullable=False, default=LeaveStatus.pending
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LeaveBalance(TenantBase):
    """RLS: Yes. A table, not a live computation (Spec 7.4): carry-forward,
    mid-year policy changes and exit encashment all need a stored, auditable
    opening position."""

    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "leave_type_id", "year", name="uq_leave_balances_employee_type_year"
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leave_types.id"), nullable=False
    )
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("0")
    )
    allocated: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    used: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=Decimal("0"))
    encashed: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=Decimal("0"))
