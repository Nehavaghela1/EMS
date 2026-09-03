"""Spec 7.6. WP-16 delivers salary_structures, salary_components,
employee_salaries, statutory_configs, pt_slabs and tax_slabs — payroll_runs,
payroll_items and reimbursements are WP-19/WP-20, not this session.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy import (
    Numeric as SANumeric,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import TenantBase, TimeStampedBase


class SalaryComponentType(str, enum.Enum):
    earning = "earning"
    deduction = "deduction"
    employer_contribution = "employer_contribution"


class CalculationType(str, enum.Enum):
    percentage = "percentage"
    fixed = "fixed"
    balance = "balance"
    statutory = "statutory"


class PercentageOf(str, enum.Enum):
    ctc = "ctc"
    basic = "basic"


class TaxRegime(str, enum.Enum):
    old = "old"
    new = "new"


class SalaryStructure(TenantBase):
    """RLS: Yes (Spec 7.6)."""

    __tablename__ = "salary_structures"
    __table_args__ = (
        Index("ix_salary_structures_company_id_is_active", "company_id", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    components: Mapped[list["SalaryComponent"]] = relationship(
        "SalaryComponent",
        order_by="SalaryComponent.display_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SalaryComponent(TenantBase):
    """RLS: Yes. Carries `company_id` and its own policy even though it is a
    child of `salary_structures` — it is reachable by UUID through routes
    78-81, and the redundancy costs one column but buys rule 1's guarantee
    (7.6)."""

    __tablename__ = "salary_components"
    __table_args__ = (
        UniqueConstraint("structure_id", "code", name="uq_salary_components_structure_code"),
    )

    structure_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("salary_structures.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    type: Mapped[SalaryComponentType] = mapped_column(
        SAEnum(SalaryComponentType, name="salary_component_type"), nullable=False
    )
    calculation_type: Mapped[CalculationType] = mapped_column(
        SAEnum(CalculationType, name="salary_calculation_type"), nullable=False
    )
    # Percent (e.g. 40.000 for 40%) or fixed rupee amount, depending on
    # calculation_type. NULL for balance/statutory, which are computed, not
    # read from here (Spec 7.6).
    value: Mapped[Decimal | None] = mapped_column(SANumeric(14, 3), nullable=True)
    # gross is deliberately not an option (Spec 7.6): gross isn't known until
    # the balance component resolves, so a gross-based earning would be
    # self-referential. ESI (a % of gross) is computed by the engine, not
    # from a percentage_of column.
    percentage_of: Mapped[PercentageOf | None] = mapped_column(
        SAEnum(PercentageOf, name="salary_percentage_of"), nullable=True
    )
    is_taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_statutory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EmployeeSalary(TenantBase):
    """RLS: Yes. Append a new row for every revision; never update an old
    one (7.6) — the row where `effective_from <= payroll_date AND
    (effective_to IS NULL OR effective_to >= payroll_date)` is the one in
    force. No two rows for the same employee may overlap; enforced in the
    service (mirrors employee_shifts' own overlap check, WP-09), not a
    database constraint — a date-range overlap isn't expressible as a
    simple UNIQUE/CHECK constraint here any more than shift assignments
    were.
    """

    __tablename__ = "employee_salaries"
    __table_args__ = (
        Index("ix_employee_salaries_company_id_employee_id", "company_id", "employee_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    structure_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("salary_structures.id"), nullable=False
    )
    ctc: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    revision_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )


class StatutoryConfig(TenantBase):
    """RLS: Yes — per-company statutory switches and rates (7.6). One row
    per company, lazily created on first access with the rates verified in
    Spec 12.2 (WP-16) as defaults — HR can then edit any of them via route
    86 if their company's real situation differs (e.g. a different state,
    or an EPF-exempt establishment). The defaults below are a one-time row
    population, not a calculation — the payslip engine (WP-18) will read
    this table's columns, never a Python literal (CLAUDE.md rule 5).
    """

    __tablename__ = "statutory_configs"
    __table_args__ = (Index("uq_statutory_configs_company_id", "company_id", unique=True),)

    country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")

    # EPF — verified against EPFO's own "Present Rates of Contribution"
    # (Spec 12.2, checked 2026-09-03). 12% employee, 12% employer (split
    # into EPS 8.33%-capped-at-₹1,250 + EDLI 0.5% + the EPF remainder at
    # calculation time, not stored as separate columns here — Spec 7.6
    # names only employee/employer totals and the ceiling), ₹15,000 ceiling.
    pf_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    pf_employee_rate: Mapped[Decimal] = mapped_column(
        SANumeric(6, 3), nullable=False, default=Decimal("12.000")
    )
    pf_employer_rate: Mapped[Decimal] = mapped_column(
        SANumeric(6, 3), nullable=False, default=Decimal("12.000")
    )
    pf_wage_ceiling: Mapped[Decimal] = mapped_column(
        SANumeric(14, 2), nullable=False, default=Decimal("15000.00")
    )
    pf_restrict_to_ceiling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ESI — verified against ESIC's own published contribution rates,
    # effective 01-07-2019 (Spec 12.2, checked 2026-09-03).
    esi_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    esi_employee_rate: Mapped[Decimal] = mapped_column(
        SANumeric(6, 3), nullable=False, default=Decimal("0.750")
    )
    esi_employer_rate: Mapped[Decimal] = mapped_column(
        SANumeric(6, 3), nullable=False, default=Decimal("3.250")
    )
    esi_wage_ceiling: Mapped[Decimal] = mapped_column(
        SANumeric(14, 2), nullable=False, default=Decimal("21000.00")
    )

    pt_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    pt_state: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # LWF — deliberately unverified this session (Spec 12, §0.3): no
    # default rate is set, and it stays disabled until a real one is.
    lwf_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lwf_employee_amount: Mapped[Decimal | None] = mapped_column(SANumeric(14, 2), nullable=True)
    lwf_months: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger), nullable=True)

    tds_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_tax_regime: Mapped[TaxRegime] = mapped_column(
        SAEnum(TaxRegime, name="statutory_config_tax_regime"), nullable=False, default=TaxRegime.new
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class PtSlab(TimeStampedBase):
    """RLS: No — government-defined, platform-managed (7.6), the same
    treatment as `industry_presets`: global reference data, not tenant
    data, because a state's Professional Tax slab isn't any one company's
    property. Effective-dated (`effective_from`/`effective_to`) so a
    lookup is always "the rate in force on this date," never "the latest
    row" — a payslip for March must use March's rate even if a newer one
    has since taken effect.
    """

    __tablename__ = "pt_slabs"
    __table_args__ = (Index("ix_pt_slabs_state_effective_from", "state", "effective_from"),)

    state: Mapped[str] = mapped_column(String(50), nullable=False)
    income_min: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    income_max: Mapped[Decimal | None] = mapped_column(SANumeric(14, 2), nullable=True)
    monthly_amount: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    # Some states levy a different amount in one nominated month to reach
    # the constitutional ₹2,500/year cap without a uniform monthly rate
    # that would exceed it (e.g. Karnataka, Maharashtra) — Gujarat's own
    # flat ₹200/month totals ₹2,400/year already under the cap, so neither
    # column is set for its seeded rows (Spec 12.2).
    special_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    special_month_amount: Mapped[Decimal | None] = mapped_column(SANumeric(14, 2), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_note: Mapped[str] = mapped_column(Text, nullable=False)


class TaxSlab(TimeStampedBase):
    """RLS: No — government-defined, platform-managed (7.6), same
    reasoning as `PtSlab`. Bracketed by `financial_year` + `regime` rather
    than an effective_to range (Spec 7.6 names no effective_to column here)
    — a lookup resolves the financial year a payroll date falls in (April
    to March) and reads that year's brackets directly.
    """

    __tablename__ = "tax_slabs"
    __table_args__ = (
        Index("ix_tax_slabs_country_fy_regime", "country", "financial_year", "regime"),
    )

    country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)  # e.g. "2026-2027"
    regime: Mapped[TaxRegime] = mapped_column(
        SAEnum(TaxRegime, name="tax_slab_regime"), nullable=False
    )
    min_income: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    max_income: Mapped[Decimal | None] = mapped_column(SANumeric(14, 2), nullable=True)
    rate_percent: Mapped[Decimal] = mapped_column(SANumeric(6, 3), nullable=False)
    cess_percent: Mapped[Decimal] = mapped_column(SANumeric(6, 3), nullable=False)
    # Standard deduction, 87A rebate and surcharge slabs — not one row per
    # bracket, so they ride along as JSON on every row of a given FY+regime
    # rather than a separate table this session doesn't need (WP-18 reads
    # them from here when it builds the actual TDS projection).
    surcharge_rules: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    source_note: Mapped[str] = mapped_column(Text, nullable=False)


class PayrollRunStatus(str, enum.Enum):
    draft = "draft"
    processing = "processing"
    pending_approval = "pending_approval"
    approved = "approved"
    paid = "paid"
    failed = "failed"


class PayrollRunType(str, enum.Enum):
    regular = "regular"
    off_cycle = "off_cycle"


class PayrollRun(TenantBase):
    """RLS: Yes (Spec 7.6)."""

    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_payroll_runs_company_idempotency_key"),
        Index(
            "uq_payroll_runs_company_month_year_regular",
            "company_id",
            "month",
            "year",
            postgresql_where=text("run_type = 'regular'"),
            unique=True,
        ),
    )

    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[PayrollRunStatus] = mapped_column(
        SAEnum(PayrollRunStatus, name="payroll_run_status"),
        nullable=False,
        default=PayrollRunStatus.draft,
    )
    run_type: Mapped[PayrollRunType] = mapped_column(
        SAEnum(PayrollRunType, name="payroll_run_type"),
        nullable=False,
        default=PayrollRunType.regular,
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    total_employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_gross: Mapped[Decimal | None] = mapped_column(SANumeric(14, 2), nullable=True)
    total_deductions: Mapped[Decimal | None] = mapped_column(SANumeric(14, 2), nullable=True)
    total_net: Mapped[Decimal | None] = mapped_column(SANumeric(14, 2), nullable=True)
    total_employer_cost: Mapped[Decimal | None] = mapped_column(SANumeric(14, 2), nullable=True)

    run_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    items: Mapped[list["PayrollItem"]] = relationship(
        "PayrollItem",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PayrollItem(TenantBase):
    """RLS: Yes (Spec 7.6). Append-only payslip snapshot per employee per run."""

    __tablename__ = "payroll_items"
    __table_args__ = (
        UniqueConstraint("payroll_run_id", "employee_id", name="uq_payroll_items_run_employee"),
    )

    payroll_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payroll_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    ctc_snapshot: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    gross_salary: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    total_deductions: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    net_salary: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    employer_cost: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)

    earnings_json: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    deductions_json: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    employer_contributions_json: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)

    working_days: Mapped[Decimal] = mapped_column(SANumeric(5, 1), nullable=False)
    present_days: Mapped[Decimal] = mapped_column(SANumeric(5, 1), nullable=False)
    absent_days: Mapped[Decimal] = mapped_column(SANumeric(5, 1), nullable=False, default=Decimal("0.0"))
    half_days: Mapped[Decimal] = mapped_column(SANumeric(5, 1), nullable=False, default=Decimal("0.0"))
    paid_leave_days: Mapped[Decimal] = mapped_column(SANumeric(5, 1), nullable=False, default=Decimal("0.0"))
    lop_days: Mapped[Decimal] = mapped_column(SANumeric(5, 1), nullable=False, default=Decimal("0.0"))
    reimbursement_amount: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False, default=Decimal("0.00"))

