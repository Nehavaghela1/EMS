import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Numeric as SANumeric,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantBase


class Department(TenantBase):
    """RLS: Yes (Spec 7.3)."""

    __tablename__ = "departments"
    __table_args__ = (
        Index(
            "uq_departments_company_lower_name",
            "company_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "clearance_function IN ('it', 'finance', 'hr')",
            name="ck_departments_clearance_function",
        ),
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    clearance_function: Mapped[Literal["it", "finance", "hr"] | None] = mapped_column(
        String(20), nullable=True
    )
    # `employees` and `departments` reference each other (department_id on
    # employees, head_employee_id here) — a real FK cycle, same shape as the
    # companies/users cycle (7.2). departments is created first (WP-06) with
    # this column FK-less; employees (WP-07) is created next, then this FK is
    # added via a follow-up migration with use_alter=True.
    head_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "employees.id", use_alter=True, name="fk_departments_head_employee_id_employees"
        ),
        nullable=True,
    )


class EmploymentType(str, enum.Enum):
    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    intern = "intern"


class InvitationStatus(str, enum.Enum):
    not_sent = "not_sent"
    sent = "sent"
    activated = "activated"
    expired = "expired"


class ResignationStatus(str, enum.Enum):
    none = "none"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"


class Employee(TenantBase):
    """RLS: Yes — the central table (Spec 7.3).

    Resignation columns (`resignation_status`, `resignation_date`,
    `last_working_date`, `notice_waived`, `notice_recovery_days`) are part of
    this table's spec-defined schema and are created now so WP-27 (routes
    27-30, out of scope this session) never needs an ALTER TABLE — but no
    route in this package writes to them.
    """

    __tablename__ = "employees"
    __table_args__ = (
        Index(
            "uq_employees_company_id_employee_code",
            "company_id",
            "employee_code",
            unique=True,
        ),
        # Case-insensitive, consistent with companies.email and users.email
        # (7.2's established convention) — the spec's own table for
        # employees doesn't repeat the case-insensitivity note, but nothing
        # about this table suggests it should be treated differently.
        Index(
            "uq_employees_company_id_email",
            "company_id",
            "email",
            unique=True,
        ),
        Index("ix_employees_company_id_department_id", "company_id", "department_id"),
        Index("ix_employees_company_id_is_active", "company_id", "is_active"),
        Index("ix_employees_reporting_manager_id", "reporting_manager_id"),
        CheckConstraint("reporting_manager_id <> id", name="ck_employees_manager_not_self"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=True
    )
    employee_code: Mapped[str] = mapped_column(String(30), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    personal_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("company_locations.id"), nullable=True
    )
    position: Mapped[str | None] = mapped_column(String(150), nullable=True)
    level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reporting_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    employment_type: Mapped[EmploymentType] = mapped_column(
        Enum(EmploymentType, name="employment_type"),
        nullable=False,
        default=EmploymentType.full_time,
    )
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    probation_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_attendance_exempt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    invitation_status: Mapped[InvitationStatus] = mapped_column(
        Enum(InvitationStatus, name="invitation_status"),
        nullable=False,
        default=InvitationStatus.not_sent,
    )
    activation_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    activation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resignation_status: Mapped[ResignationStatus] = mapped_column(
        Enum(ResignationStatus, name="resignation_status"),
        nullable=False,
        default=ResignationStatus.none,
    )
    resignation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_working_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_waived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notice_recovery_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Separation / Involuntary Termination & FnF settlement tracking
    separation_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # voluntary, involuntary, pip_failed
    termination_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    severance_pay: Mapped[Decimal | None] = mapped_column(
        SANumeric(14, 2), nullable=True, default=Decimal("0.00")
    )
    pending_reimbursements: Mapped[Decimal | None] = mapped_column(
        SANumeric(14, 2), nullable=True, default=Decimal("0.00")
    )
    gratuity_bonus: Mapped[Decimal | None] = mapped_column(
        SANumeric(14, 2), nullable=True, default=Decimal("0.00")
    )
    asset_deductions: Mapped[Decimal | None] = mapped_column(
        SANumeric(14, 2), nullable=True, default=Decimal("0.00")
    )
    it_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hr_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    finance_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fnf_settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmployeeAddress(TenantBase):
    __tablename__ = "employee_addresses"
    __table_args__ = (
        CheckConstraint("kind IN ('current', 'permanent')", name="ck_employee_addresses_kind"),
        Index("ix_employee_addresses_company_employee", "company_id", "employee_id"),
        Index(
            "uq_employee_addresses_employee_kind",
            "employee_id",
            "kind",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    line1: Mapped[str] = mapped_column(String(255), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(100), nullable=False)


class EmployeeEmergencyContact(TenantBase):
    __tablename__ = "employee_emergency_contacts"
    __table_args__ = (
        Index("ix_employee_emergency_contacts_company_employee", "company_id", "employee_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    relationship: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    alt_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)


class EmployeeSkill(TenantBase):
    __tablename__ = "employee_skills"
    __table_args__ = (
        CheckConstraint(
            "level IN ('beginner', 'intermediate', 'advanced', 'expert')",
            name="ck_employee_skills_level",
        ),
        CheckConstraint(
            "years_experience >= 0 AND years_experience <= 60",
            name="ck_employee_skills_years_experience",
        ),
        Index("ix_employee_skills_company_employee", "company_id", "employee_id"),
        Index(
            "uq_employee_skills_employee_lower_name",
            "employee_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    years_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EmployeeEducation(TenantBase):
    __tablename__ = "employee_education"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('unverified', 'verified')",
            name="ck_employee_education_verification_status",
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_employee_education_end_after_start",
        ),
        Index("ix_employee_education_company_employee", "company_id", "employee_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    institution: Mapped[str] = mapped_column(String(200), nullable=False)
    degree: Mapped[str] = mapped_column(String(150), nullable=False)
    field_of_study: Mapped[str | None] = mapped_column(String(150), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unverified"
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmployeeExperience(TenantBase):
    __tablename__ = "employee_experience"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('unverified', 'verified')",
            name="ck_employee_experience_verification_status",
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_employee_experience_end_after_start",
        ),
        Index("ix_employee_experience_company_employee", "company_id", "employee_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    employer: Mapped[str] = mapped_column(String(200), nullable=False)
    job_title: Mapped[str] = mapped_column(String(150), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unverified"
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
