import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import TenantBase, TimeStampedBase


class CompanyStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    suspended = "suspended"
    rejected = "rejected"


class UserRole(str, enum.Enum):
    employee = "employee"
    manager = "manager"
    hr_admin = "hr_admin"
    super_admin = "super_admin"


class Company(TimeStampedBase):
    """RLS: No — platform-level table (Spec 7.2).

    `users.company_id -> companies.id` and `companies.approved_by -> users.id`
    form a foreign-key cycle. `approved_by` below is declared `use_alter=True`
    so it is created by a second, follow-up migration (`op.create_foreign_key`
    after both tables exist) rather than inline in `companies`' own CREATE
    TABLE — the migration that creates `companies` still creates it without
    the constraint (Spec 7.2 migration-ordering note).
    """

    __tablename__ = "companies"
    __table_args__ = (
        Index("uq_companies_lower_email", text("lower(email)"), unique=True),
        Index("ix_companies_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    # Uniqueness is enforced by uq_companies_lower_email above (case-insensitive,
    # per Spec 7.2), not by a plain column constraint here — one mechanism, not two.
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    gst_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pan_number: Mapped[str | None] = mapped_column(String(10), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CompanyStatus] = mapped_column(
        Enum(CompanyStatus, name="company_status"),
        nullable=False,
        default=CompanyStatus.pending,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", use_alter=True, name="fk_companies_approved_by_users"),
        nullable=True,
    )
    last_employee_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # `approved_by` (above) is a second FK path between companies and users —
    # without foreign_keys, SQLAlchemy can't tell which one this relationship
    # should join on and refuses to configure the mapper at all.
    users: Mapped[list["User"]] = relationship(
        back_populates="company", foreign_keys="User.company_id"
    )


class User(TimeStampedBase):
    """RLS: No — scoped in the application layer, not by RLS (Spec 7.2).

    Every UserRepository method except the three documented pre-authentication
    lookups requires a `company_id` argument and filters on it (7.2). This model
    intentionally does NOT inherit TenantBase: TenantBase implies an RLS policy
    in the same migration, and users deliberately has none.
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_company_id_email", "company_id", text("lower(email)"), unique=True),
        Index(
            "uq_users_company_id_username",
            "company_id",
            text("lower(username)"),
            unique=True,
        ),
        Index("ix_users_company_id", "company_id"),
        Index("ix_users_email", "email"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), nullable=False, default=UserRole.employee
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped["Company"] = relationship(back_populates="users", foreign_keys=[company_id])
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", foreign_keys="RefreshToken.user_id"
    )


class RefreshToken(TimeStampedBase):
    """RLS: No — keyed by user, never queried across tenants (Spec 7.2)."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("uq_refresh_tokens_token_hash", "token_hash", unique=True),
        Index("ix_refresh_tokens_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("refresh_tokens.id"), nullable=True
    )
    device_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens", foreign_keys=[user_id])


class LeaveYearType(str, enum.Enum):
    calendar = "calendar"
    financial = "financial"


class PayrollWorkingDaysBasis(str, enum.Enum):
    calendar_days = "calendar_days"
    working_days = "working_days"
    fixed_30 = "fixed_30"


class CompanySettings(TenantBase):
    """RLS: Yes — the first RLS-protected table in the system (Spec 7.2, 8.3).

    One row per company. `company_id` is unique (enforced below, on top of
    the plain FK+index TenantBase already provides).
    """

    __tablename__ = "company_settings"
    __table_args__ = (Index("uq_company_settings_company_id", "company_id", unique=True),)

    # The single authority on the working week (Spec 7.2) — ISO weekday
    # numbers, Mon=1. '{7}' is a six-day week; '{6,7}' is five days.
    weekend_days: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, default=lambda: [6, 7]
    )
    half_day_hours_threshold: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("4")
    )
    full_day_hours: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("8")
    )
    leave_year_type: Mapped[LeaveYearType] = mapped_column(
        Enum(LeaveYearType, name="leave_year_type"),
        nullable=False,
        default=LeaveYearType.financial,
    )
    leave_year_start_month: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4)
    payroll_working_days_basis: Mapped[PayrollWorkingDaysBasis] = mapped_column(
        Enum(PayrollWorkingDaysBasis, name="payroll_working_days_basis"),
        nullable=False,
        default=PayrollWorkingDaysBasis.working_days,
    )
