import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.masking import mask_tail
from app.modules.payroll.models import (
    CalculationType,
    PercentageOf,
    ReimbursementStatus,
    ReimbursementType,
    SalaryComponentType,
    TaxRegime,
)

# Input limits for salary structures and assignments (Spec 7.6 column sizes). They are limits
# on what a request may carry, not statutory rates.
_MAX_MONEY = Decimal("99999999.99")
_STRUCTURE_NAME = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
_LEVEL = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10)]
_COUNTRY = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
_COMPONENT_NAME = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
_COMPONENT_CODE = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9_]{2,20}$")]
_REASON = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
MIN_SALARY_DATE = date(2000, 1, 1)
MAX_SALARY_DATE = date(2100, 12, 31)


def _decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


class SalaryComponentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: _COMPONENT_NAME
    code: _COMPONENT_CODE
    type: SalaryComponentType
    calculation_type: CalculationType
    value: Decimal | None = Field(default=None, ge=0)
    percentage_of: PercentageOf | None = None
    is_taxable: bool = True
    is_statutory: bool = False
    display_order: int = Field(default=0, ge=0, le=1000)

    @model_validator(mode="after")
    def _value_limits(self) -> "SalaryComponentCreateRequest":
        if self.value is None:
            return self
        if self.calculation_type == CalculationType.percentage:
            if self.value > 100 or _decimal_places(self.value) > 3:
                raise ValueError("A percentage must be between 0 and 100 with at most 3 decimals.")
        elif self.calculation_type == CalculationType.fixed:
            if self.value > _MAX_MONEY or _decimal_places(self.value) > 2:
                raise ValueError("A fixed amount may have at most 2 decimals.")
        return self


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
    model_config = ConfigDict(extra="forbid")

    name: _STRUCTURE_NAME
    country: _COUNTRY = "IN"
    level: _LEVEL | None = None
    components: list[SalaryComponentCreateRequest] = Field(default_factory=list, max_length=30)


class SalaryStructureUpdateRequest(BaseModel):
    """Route 81. Does not retroactively change issued payslips (Spec 7.6) —
    payroll_items snapshots the breakdown at run time, so editing a
    structure only changes future calculations. Components are replaced
    wholesale when supplied (never a partial patch of one component —
    that would leave the "at most one balance component" invariant
    unverifiable from the request alone)."""

    model_config = ConfigDict(extra="forbid")

    name: _STRUCTURE_NAME | None = None
    level: _LEVEL | None = None
    is_active: bool | None = None
    components: list[SalaryComponentCreateRequest] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def _required_fields_are_not_null(self) -> "SalaryStructureUpdateRequest":
        for field in ("name", "is_active", "components"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null.")
        return self


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
    model_config = ConfigDict(extra="forbid")

    structure_id: uuid.UUID
    ctc: Decimal = Field(gt=0, le=_MAX_MONEY, decimal_places=2)
    effective_from: date
    revision_reason: _REASON | None = None

    @field_validator("effective_from")
    @classmethod
    def _effective_from_in_range(cls, value: date) -> date:
        if not MIN_SALARY_DATE <= value <= MAX_SALARY_DATE:
            raise ValueError("effective_from must be between 2000 and 2100.")
        return value


class SalaryHistoryItem(BaseModel):
    """One row of an employee's salary history (route `salary-history`)."""

    id: uuid.UUID
    structure_id: uuid.UUID
    structure_name: str
    ctc: Decimal
    effective_from: date
    effective_to: date | None
    revision_reason: str | None
    created_at: datetime


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


def mask_payout_account_number(v: str | None) -> str | None:
    return mask_tail(v)


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
    payout_bank_name: str | None = None
    payout_account_number: str | None = None
    payout_ifsc_code: str | None = None
    payout_enabled: bool = False

    model_config = {"from_attributes": True}

    @field_validator("payout_account_number", mode="after")
    @classmethod
    def mask_account_number(cls, v: str | None) -> str | None:
        return mask_payout_account_number(v)


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
    payout_bank_name: str | None = None
    payout_account_number: str | None = None
    payout_ifsc_code: str | None = None
    payout_enabled: bool | None = None


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
    model_config = ConfigDict(extra="forbid")

    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)
    run_type: Literal["regular", "off_cycle"] = "regular"
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
    skipped_json: list[dict] | None = None
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
