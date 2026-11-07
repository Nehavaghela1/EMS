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
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
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
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
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
        # One live structure per name per company, ignoring case (a deleted one frees its name).
        Index(
            "uq_salary_structures_company_lower_name",
            "company_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    components: Mapped[list["SalaryComponent"]] = relationship(
        "SalaryComponent",
        order_by="[SalaryComponent.display_order, SalaryComponent.code]",
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
    force. No two live rows for the same employee may overlap: the service
    checks it (with a lock on the employee row) and the database enforces
    it with an exclusion constraint on the employee and the date range.
    """

    __tablename__ = "employee_salaries"
    __table_args__ = (
        Index("ix_employee_salaries_company_id_employee_id", "company_id", "employee_id"),
        ExcludeConstraint(
            ("employee_id", "="),
            (
                text("daterange(effective_from, coalesce(effective_to, 'infinity'::date), '[]')"),
                "&&",
            ),
            name="ex_employee_salaries_no_overlap",
            using="gist",
            where=text("deleted_at IS NULL"),
        ),
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
    # hourly_rate: used for contract/hourly employees. If NULL, the payroll engine
    # falls back to monthly_ctc / 160 (standard for full-time equivalents).
    # Store as ₹/hour to 2 decimal places (e.g. 500.00 for ₹500/hr).
    hourly_rate: Mapped[Decimal | None] = mapped_column(SANumeric(14, 2), nullable=True)
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

    # A company only switches PF and ESI on or off here. The rates and wage ceilings are
    # platform-managed, effective-dated rows in `statutory_rates` (5.2), each with its
    # official source; the row in force on the first day of the payroll month applies.
    pf_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    pf_restrict_to_ceiling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    esi_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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
    # Direct corporate banking & Zoho Payouts gateway integration
    payout_bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # AES-256-GCM blob (app/core/encryption.py) and the last four digits beside it, so the
    # masked value is shown without decrypting anything (Spec 9.6).
    payout_account_number_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    payout_account_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    payout_ifsc_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payout_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
    __table_args__ = (
        Index("ix_pt_slabs_country_state_effective_from", "country", "state", "effective_from"),
    )

    country: Mapped[str] = mapped_column(
        String(2), nullable=False, default="IN", server_default="IN"
    )
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
    # Official source (5.2): a link on the government list, a title, the day it was checked.
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_on: Mapped[date] = mapped_column(Date, nullable=False)


class StatutoryScheme(str, enum.Enum):
    epf = "epf"
    esi = "esi"


class StatutoryRate(TimeStampedBase):
    """RLS: No — government-defined, platform-managed (5.2), like `pt_slabs`. One
    effective-dated row per scheme and period; old rows are kept so a payroll month always
    resolves to the numbers in force on its first day. Rows of one scheme never overlap
    (exclusion constraint). `employer_epf_rate`, `employer_eps_rate`, `edli_rate` and
    `admin_charge_rate` are EPF-only breakdown figures (null for ESI).
    """

    __tablename__ = "statutory_rates"
    __table_args__ = (
        CheckConstraint("scheme IN ('epf', 'esi')", name="ck_statutory_rates_scheme"),
        ExcludeConstraint(
            ("country", "="),
            ("scheme", "="),
            (
                text("daterange(effective_from, coalesce(effective_to, 'infinity'::date), '[]')"),
                "&&",
            ),
            name="ex_statutory_rates_no_overlap",
            using="gist",
            where=text("deleted_at IS NULL"),
        ),
    )

    country: Mapped[str] = mapped_column(
        String(2), nullable=False, default="IN", server_default="IN"
    )
    scheme: Mapped[str] = mapped_column(String(10), nullable=False)
    employee_rate: Mapped[Decimal] = mapped_column(SANumeric(6, 3), nullable=False)
    employer_rate: Mapped[Decimal] = mapped_column(SANumeric(6, 3), nullable=False)
    wage_ceiling: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    employer_epf_rate: Mapped[Decimal | None] = mapped_column(SANumeric(6, 3), nullable=True)
    employer_eps_rate: Mapped[Decimal | None] = mapped_column(SANumeric(6, 3), nullable=True)
    edli_rate: Mapped[Decimal | None] = mapped_column(SANumeric(6, 3), nullable=True)
    admin_charge_rate: Mapped[Decimal | None] = mapped_column(SANumeric(6, 3), nullable=True)
    # ESI only: an employee whose average daily wage is at or below this pays no employee
    # share (the employer still pays its own).
    employee_exempt_daily_wage: Mapped[Decimal | None] = mapped_column(
        SANumeric(14, 2), nullable=True
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_on: Mapped[date] = mapped_column(Date, nullable=False)


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
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_on: Mapped[date] = mapped_column(Date, nullable=False)


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
        UniqueConstraint(
            "company_id", "idempotency_key", name="uq_payroll_runs_company_idempotency_key"
        ),
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
    # Employees left out of this run: [{"employee_id": ..., "reason": ...}]
    skipped_json: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

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
    absent_days: Mapped[Decimal] = mapped_column(
        SANumeric(5, 1), nullable=False, default=Decimal("0.0")
    )
    half_days: Mapped[Decimal] = mapped_column(
        SANumeric(5, 1), nullable=False, default=Decimal("0.0")
    )
    paid_leave_days: Mapped[Decimal] = mapped_column(
        SANumeric(5, 1), nullable=False, default=Decimal("0.0")
    )
    lop_days: Mapped[Decimal] = mapped_column(
        SANumeric(5, 1), nullable=False, default=Decimal("0.0")
    )
    reimbursement_amount: Mapped[Decimal] = mapped_column(
        SANumeric(14, 2), nullable=False, default=Decimal("0.00")
    )
    # The salary rows this month was paid at: [{salary_id, from_date, to_date, days, ctc}].
    # More than one when a raise started mid-month (paid by days at the old and new CTC).
    salary_segments_json: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)


class EmployeeBankAccount(TenantBase):
    """RLS: Yes. An employee's bank details (5.8). One ACTIVE row per employee; a change adds a
    new row and deactivates the old one, which stays as history. The number is an AES-256-GCM
    blob (app/core/encryption.py) with its last four digits beside it."""

    __tablename__ = "employee_bank_accounts"
    __table_args__ = (
        Index(
            "uq_employee_bank_accounts_one_active",
            "employee_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    account_holder: Mapped[str] = mapped_column(String(100), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_number_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    account_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    ifsc_code: Mapped[str] = mapped_column(String(11), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )


class PayrollRunPayment(TenantBase):
    """RLS: Yes. One payment line per employee of an approved run, written in the same save as
    the approval (5.8). A later change of bank details never alters it. An employee who is left
    out has no bank fields and an `excluded_reason`."""

    __tablename__ = "payroll_run_payments"
    __table_args__ = (
        UniqueConstraint(
            "payroll_run_id", "employee_id", name="uq_payroll_run_payments_run_employee"
        ),
    )

    payroll_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    employee_code: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    account_holder: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    account_number_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    account_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    ifsc_code: Mapped[str | None] = mapped_column(String(11), nullable=True)
    excluded_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)


class ReimbursementType(str, enum.Enum):
    travel = "travel"
    food = "food"
    medical = "medical"
    telephone = "telephone"
    other = "other"


class ReimbursementStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    paid = "paid"
    # The claimant took the claim back while it was still pending (5.6).
    withdrawn = "withdrawn"


class Reimbursement(TenantBase):
    """RLS: Yes (Spec 7.6)."""

    __tablename__ = "reimbursements"
    __table_args__ = (
        # One receipt backs one open claim; a rejected or withdrawn claim frees its receipt.
        Index(
            "uq_reimbursements_open_receipt",
            "company_id",
            "file_object_id",
            unique=True,
            postgresql_where=text(
                "file_object_id IS NOT NULL AND status IN ('pending', 'approved', 'paid')"
            ),
        ),
        # The same employee cannot have two open claims for the same date, type and amount.
        Index(
            "uq_reimbursements_open_claim",
            "company_id",
            "employee_id",
            "expense_date",
            "type",
            "amount",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved', 'paid')"),
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    type: Mapped[ReimbursementType] = mapped_column(
        SAEnum(ReimbursementType, name="reimbursement_type"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(SANumeric(14, 2), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # The receipt. Nullable only for claims that pre-date the receipt rule; the service
    # requires one for every new claim.
    file_object_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("file_objects.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[ReimbursementStatus] = mapped_column(
        SAEnum(ReimbursementStatus, name="reimbursement_status"),
        nullable=False,
        default=ReimbursementStatus.pending,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_to_payroll_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll_runs.id"), nullable=True
    )
