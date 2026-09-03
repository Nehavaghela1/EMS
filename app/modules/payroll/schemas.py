import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.payroll.models import (
    CalculationType,
    PercentageOf,
    ReimbursementStatus,
    ReimbursementType,
    SalaryComponentType,
    TaxRegime,
)


class SalaryComponentCreateRequest(BaseModel):
    name: str
    code: str
    type: SalaryComponentType
    calculation_type: CalculationType
    value: Decimal | None = None
    percentage_of: PercentageOf | None = None
    is_taxable: bool = True
    is_statutory: bool = False
    display_order: int = 0


class SalaryComponentResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    type: SalaryComponentType
    calculation_type: CalculationType
    value: Decimal | None
    percentage_of: PercentageOf | None
    is_taxable: bool
    is_statutory: bool
    display_order: int

    model_config = {"from_attributes": True}


class SalaryStructureCreateRequest(BaseModel):
    name: str
    country: str = "IN"
    level: str | None = None
    components: list[SalaryComponentCreateRequest] = Field(default_factory=list)


class SalaryStructureUpdateRequest(BaseModel):
    """Route 81. Does not retroactively change issued payslips (Spec 7.6) —
    payroll_items snapshots the breakdown at run time, so editing a
    structure only changes future calculations. Components are replaced
    wholesale when supplied (never a partial patch of one component —
    that would leave the "at most one balance component" invariant
    unverifiable from the request alone)."""

    name: str | None = None
    level: str | None = None
    is_active: bool | None = None
    components: list[SalaryComponentCreateRequest] | None = None


class SalaryStructureResponse(BaseModel):
    id: uuid.UUID
    name: str
    country: str
    level: str | None
    is_active: bool
    created_at: datetime
    components: list[SalaryComponentResponse]

    model_config = {"from_attributes": True}


class SalaryStructureListItem(BaseModel):
    id: uuid.UUID
    name: str
    country: str
    level: str | None
    is_active: bool
    component_count: int
    created_at: datetime


class SalaryAssignRequest(BaseModel):
    structure_id: uuid.UUID
    ctc: Decimal
    effective_from: date
    revision_reason: str | None = None


class SalaryComponentAmount(BaseModel):
    """One line of the computed breakdown (route 84). `amount` is null for
    a statutory component — PF/ESI/TDS are computed by the payslip engine
    (WP-18, not this session), never estimated here."""

    code: str
    name: str
    type: SalaryComponentType
    amount: Decimal | None
    note: str | None = None


class EmployeeSalaryResponse(BaseModel):
    employee_id: uuid.UUID
    structure_id: uuid.UUID
    structure_name: str
    ctc: Decimal
    effective_from: date
    effective_to: date | None
    revision_reason: str | None
    earnings: list[SalaryComponentAmount]
    deductions: list[SalaryComponentAmount]
    gross_earnings: Decimal


class StatutoryConfigResponse(BaseModel):
    country: str
    pf_enabled: bool
    pf_employee_rate: Decimal
    pf_employer_rate: Decimal
    pf_wage_ceiling: Decimal
    pf_restrict_to_ceiling: bool
    esi_enabled: bool
    esi_employee_rate: Decimal
    esi_employer_rate: Decimal
    esi_wage_ceiling: Decimal
    pt_enabled: bool
    pt_state: str | None
    lwf_enabled: bool
    lwf_employee_amount: Decimal | None
    lwf_months: list[int] | None
    tds_enabled: bool
    default_tax_regime: TaxRegime

    model_config = {"from_attributes": True}


class StatutoryConfigUpdateRequest(BaseModel):
    pf_enabled: bool | None = None
    pf_employee_rate: Decimal | None = None
    pf_employer_rate: Decimal | None = None
    pf_wage_ceiling: Decimal | None = None
    pf_restrict_to_ceiling: bool | None = None
    esi_enabled: bool | None = None
    esi_employee_rate: Decimal | None = None
    esi_employer_rate: Decimal | None = None
    esi_wage_ceiling: Decimal | None = None
    pt_enabled: bool | None = None
    pt_state: str | None = None
    lwf_enabled: bool | None = None
    lwf_employee_amount: Decimal | None = None
    lwf_months: list[int] | None = None
    tds_enabled: bool | None = None
    default_tax_regime: TaxRegime | None = None


class PtSlabResponse(BaseModel):
    id: uuid.UUID
    state: str
    income_min: Decimal
    income_max: Decimal | None
    monthly_amount: Decimal
    special_month: int | None
    special_month_amount: Decimal | None
    effective_from: date
    effective_to: date | None
    source_note: str

    model_config = {"from_attributes": True}


class PtSlabRowInput(BaseModel):
    income_min: Decimal
    income_max: Decimal | None = None
    monthly_amount: Decimal
    special_month: int | None = None
    special_month_amount: Decimal | None = None


class PtSlabPutRequest(BaseModel):
    """Route 88, SA only. Adds a new effective-dated slab set for one state
    — never mutates a historical row in place (Spec 12: a payslip for a
    past month must keep resolving to the rate that was actually in force
    then)."""

    state: str
    effective_from: date
    source_note: str
    slabs: list[PtSlabRowInput]


class TaxSlabResponse(BaseModel):
    id: uuid.UUID
    country: str
    financial_year: str
    regime: TaxRegime
    min_income: Decimal
    max_income: Decimal | None
    rate_percent: Decimal
    cess_percent: Decimal
    surcharge_rules: dict | None
    effective_from: date
    source_note: str

    model_config = {"from_attributes": True}


class TaxSlabBracketInput(BaseModel):
    min_income: Decimal
    max_income: Decimal | None = None
    rate_percent: Decimal


class TaxSlabPostRequest(BaseModel):
    """Route 90, SA only. Adds a new financial year's (or regime's)
    brackets — never mutates a past year's row in place."""

    country: str = "IN"
    financial_year: str
    regime: TaxRegime
    cess_percent: Decimal
    surcharge_rules: dict | None = None
    effective_from: date
    source_note: str
    brackets: list[TaxSlabBracketInput]


class PayrollRunCreateRequest(BaseModel):
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)
    run_type: str = "regular"  # "regular" or "off_cycle"
    employee_ids: list[uuid.UUID] | None = None


class PayrollRunResponse(BaseModel):
    id: uuid.UUID
    month: int
    year: int
    status: str
    run_type: str
    idempotency_key: str
    total_employees: int | None
    total_gross: Decimal | None
    total_deductions: Decimal | None
    total_net: Decimal | None
    total_employer_cost: Decimal | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PayrollItemResponse(BaseModel):
    id: uuid.UUID
    payroll_run_id: uuid.UUID
    employee_id: uuid.UUID
    ctc_snapshot: Decimal
    gross_salary: Decimal
    total_deductions: Decimal
    net_salary: Decimal
    employer_cost: Decimal
    earnings_json: list[dict]
    deductions_json: list[dict]
    employer_contributions_json: list[dict]
    working_days: Decimal
    present_days: Decimal
    absent_days: Decimal
    half_days: Decimal
    paid_leave_days: Decimal
    lop_days: Decimal
    reimbursement_amount: Decimal

    model_config = {"from_attributes": True}


class PayrollRunDetailResponse(BaseModel):
    run: PayrollRunResponse
    items: list[PayrollItemResponse]


class ReimbursementCreateRequest(BaseModel):
    type: ReimbursementType
    amount: Decimal = Field(gt=0)
    expense_date: date
    description: str = Field(min_length=1)
    file_object_id: uuid.UUID | None = None


class ReimbursementReviewRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    rejection_reason: str | None = None


class ReimbursementResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    type: ReimbursementType
    amount: Decimal
    expense_date: date
    description: str
    file_object_id: uuid.UUID | None
    status: ReimbursementStatus
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    rejection_reason: str | None
    added_to_payroll_run_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


