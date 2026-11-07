import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.core.official_sources import validate_source_url
from app.core.time import utcnow
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
# A country code as sent to a platform write route: spaces cut and upper-cased here, looked up
# in the shared list by the service.
_COUNTRY_CODE = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{2}$")
]
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


PAYOUT_ACCOUNT_MASK = "********"
_ACCOUNT_NUMBER = re.compile(r"[0-9]{9,18}")
_MASKED_ACCOUNT_NUMBER = re.compile(r"\*+[0-9]{0,4}")
_IFSC_CODE = re.compile(r"[A-Z]{4}0[A-Z0-9]{6}")


def mask_payout_account_number(last4: str | None) -> str | None:
    """Eight asterisks plus the stored last four digits, whatever the number's length."""
    return None if last4 is None else PAYOUT_ACCOUNT_MASK + last4


def is_masked_account_number(value: str) -> bool:
    """A value made only of asterisks and (at most) the last four digits: what a client sends
    back when it re-submits the masked value it was shown."""
    return _MASKED_ACCOUNT_NUMBER.fullmatch(value) is not None


class StatutoryRateResponse(BaseModel):
    id: uuid.UUID
    country: str
    scheme: str
    employee_rate: Decimal
    employer_rate: Decimal
    wage_ceiling: Decimal
    employer_epf_rate: Decimal | None
    employer_eps_rate: Decimal | None
    edli_rate: Decimal | None
    admin_charge_rate: Decimal | None
    employee_exempt_daily_wage: Decimal | None
    effective_from: date
    effective_to: date | None
    source_url: str
    source_title: str
    source_note: str | None
    verified_on: date

    model_config = {"from_attributes": True}


class StatutoryConfigResponse(BaseModel):
    country: str
    pf_enabled: bool
    pf_restrict_to_ceiling: bool
    esi_enabled: bool
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
    # Read-only: the platform rates in force today, each with its official source. Filled by
    # the service; a company cannot change them (5.2).
    effective_rates: list[StatutoryRateResponse] = []

    # `payout_account_number` is not a column: the service fills it (masked, or the plain
    # number on an audited reveal). The blob and last4 columns are never fields here.
    model_config = {"from_attributes": True}


class StatutoryConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pf_enabled: bool | None = None
    pf_restrict_to_ceiling: bool | None = None
    esi_enabled: bool | None = None
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

    @field_validator("payout_bank_name")
    @classmethod
    def _bank_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("Bank name must be 1 to 100 characters.")
        return value

    @field_validator("payout_account_number")
    @classmethod
    def _account_number(cls, value: str | None) -> str | None:
        # Never put the submitted value in the message: it is an account number.
        if value is None:
            return None
        value = value.strip()
        if is_masked_account_number(value) or _ACCOUNT_NUMBER.fullmatch(value):
            return value
        raise ValueError("Account number must be 9 to 18 digits.")

    @field_validator("payout_ifsc_code")
    @classmethod
    def _ifsc_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not _IFSC_CODE.fullmatch(value):
            raise ValueError("IFSC code must be 4 letters, a zero, then 6 letters or digits.")
        return value

    @model_validator(mode="after")
    def _enabled_is_not_null(self) -> "StatutoryConfigUpdateRequest":
        if "payout_enabled" in self.model_fields_set and self.payout_enabled is None:
            raise ValueError("payout_enabled must be true or false.")
        return self


class PtSlabResponse(BaseModel):
    id: uuid.UUID
    country: str
    state: str
    income_min: Decimal
    income_max: Decimal | None
    monthly_amount: Decimal
    special_month: int | None
    special_month_amount: Decimal | None
    effective_from: date
    effective_to: date | None
    source_url: str
    source_title: str
    source_note: str | None
    verified_on: date

    model_config = {"from_attributes": True}


# --- 5.2: every rate write carries its official source ------------------------------------

_RATE = Annotated[Decimal, Field(ge=0, le=100, decimal_places=3)]
_CEILING = Annotated[Decimal, Field(gt=0, le=_MAX_MONEY, decimal_places=2)]
_SLAB_MONEY = Annotated[Decimal, Field(ge=0, le=_MAX_MONEY, decimal_places=2)]
_SOURCE_URL = Annotated[str, AfterValidator(validate_source_url)]
_SOURCE_TITLE = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


def _check_effective_from(value: date) -> date:
    if not MIN_SALARY_DATE <= value <= MAX_SALARY_DATE:
        raise ValueError("effective_from must be between 2000 and 2100.")
    return value


class _SourcedWrite(BaseModel):
    """The source of a rate write: a link on the government list, a title, the day it was
    checked (never in the future) and an optional note. Unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")

    source_url: _SOURCE_URL
    source_title: _SOURCE_TITLE
    verified_on: date
    source_note: str | None = None

    @field_validator("verified_on")
    @classmethod
    def _not_in_the_future(cls, value: date) -> date:
        if value > utcnow().date():
            raise ValueError("verified_on cannot be in the future.")
        return value


class StatutoryRateCreateRequest(_SourcedWrite):
    """`POST /payroll/statutory-rates`, super_admin only."""

    # Checked against the shared country list by the service (422 naming the allowed codes).
    country: _COUNTRY_CODE = "IN"
    scheme: Literal["epf", "esi"]
    employee_rate: _RATE
    employer_rate: _RATE
    wage_ceiling: _CEILING
    employer_epf_rate: _RATE | None = None
    employer_eps_rate: _RATE | None = None
    edli_rate: _RATE | None = None
    admin_charge_rate: _RATE | None = None
    # ESI only: average daily wage at or below which the employee pays no ESI share.
    employee_exempt_daily_wage: _CEILING | None = None
    effective_from: date

    _effective_from_in_range = field_validator("effective_from")(_check_effective_from)

    @model_validator(mode="after")
    def _exemption_is_an_esi_figure(self) -> "StatutoryRateCreateRequest":
        if self.employee_exempt_daily_wage is not None and self.scheme != "esi":
            raise ValueError("employee_exempt_daily_wage applies to the esi scheme only.")
        return self


class PtSlabRowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    income_min: _SLAB_MONEY
    income_max: _SLAB_MONEY | None = None
    monthly_amount: _SLAB_MONEY
    special_month: Annotated[int, Field(ge=1, le=12)] | None = None
    special_month_amount: _SLAB_MONEY | None = None


class PtSlabPutRequest(_SourcedWrite):
    """Route 88, SA only. Adds a new effective-dated slab set for one state
    — never mutates a historical row in place (Spec 12: a payslip for a
    past month must keep resolving to the rate that was actually in force
    then)."""

    # Country and state are checked against the shared list by the service, which also stores
    # the state in its canonical spelling.
    country: _COUNTRY_CODE = "IN"
    state: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    effective_from: date
    slabs: Annotated[list[PtSlabRowInput], Field(min_length=1)]

    _effective_from_in_range = field_validator("effective_from")(_check_effective_from)


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
    source_url: str
    source_title: str
    source_note: str | None
    verified_on: date

    model_config = {"from_attributes": True}


class TaxSlabBracketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_income: _SLAB_MONEY
    max_income: _SLAB_MONEY | None = None
    rate_percent: _RATE


class TaxSlabPostRequest(_SourcedWrite):
    """Route 90, SA only. Adds a new financial year's (or regime's)
    brackets — never mutates a past year's row in place."""

    country: _COUNTRY_CODE = "IN"
    financial_year: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{4}$")]
    regime: TaxRegime
    cess_percent: _RATE
    surcharge_rules: dict | None = None
    effective_from: date
    brackets: Annotated[list[TaxSlabBracketInput], Field(min_length=1)]

    _effective_from_in_range = field_validator("effective_from")(_check_effective_from)


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
    # The salary rows the month was paid at (more than one after a mid-month raise).
    salary_segments_json: list[dict] | None = None

    model_config = {"from_attributes": True}


class PaymentExclusion(BaseModel):
    """An employee left out of a run's payment file, and why. Never a bank detail or an amount."""

    employee_id: uuid.UUID
    reason: str


class PayrollRunDetailResponse(BaseModel):
    run: PayrollRunResponse
    items: list[PayrollItemResponse]
    # None for a run that is not approved yet or was approved before payment lines were saved.
    payment_exclusions: list[PaymentExclusion] | None = None


class BankAccountRequest(BaseModel):
    """`PUT` of an employee's bank details (5.8). Every field is required; a client that
    re-submits the masked account number keeps the stored one."""

    model_config = ConfigDict(extra="forbid")

    account_holder: str
    bank_name: str
    account_number: str
    ifsc_code: str

    @field_validator("account_holder")
    @classmethod
    def _holder(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("Account holder must be 1 to 100 characters.")
        return value

    @field_validator("bank_name")
    @classmethod
    def _bank(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("Bank name must be 1 to 100 characters.")
        return value

    @field_validator("account_number")
    @classmethod
    def _number(cls, value: str) -> str:
        # Never put the submitted value in the message: it is an account number.
        value = value.strip()
        if is_masked_account_number(value) or _ACCOUNT_NUMBER.fullmatch(value):
            return value
        raise ValueError("Account number must be 9 to 18 digits.")

    @field_validator("ifsc_code")
    @classmethod
    def _ifsc(cls, value: str) -> str:
        value = value.strip().upper()
        if not _IFSC_CODE.fullmatch(value):
            raise ValueError("IFSC code must be 4 letters, a zero, then 6 letters or digits.")
        return value


class BankAccountResponse(BaseModel):
    employee_id: uuid.UUID
    account_holder: str
    bank_name: str
    # Eight asterisks and the last four digits; the whole number only on an audited reveal.
    account_number: str
    ifsc_code: str
    updated_at: datetime


# Input limits for a claim (5.6): what a request may carry, not statutory figures.
MAX_REIMBURSEMENT_AMOUNT = Decimal("1000000.00")
_CLAIM_TEXT = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
_REJECTION_REASON = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ReimbursementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ReimbursementType
    amount: Decimal = Field(gt=0, le=MAX_REIMBURSEMENT_AMOUNT, decimal_places=2)
    expense_date: date
    description: _CLAIM_TEXT
    file_object_id: uuid.UUID


class ReimbursementReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"]
    rejection_reason: _REJECTION_REASON | None = Field(default=None, validate_default=True)

    @field_validator("rejection_reason")
    @classmethod
    def _reason_matches_action(cls, value: str | None, info: ValidationInfo) -> str | None:
        action = info.data.get("action")
        if action == "reject" and not value:
            raise ValueError("A rejection needs a reason of 1 to 500 characters.")
        if action == "approve" and value is not None:
            raise ValueError("An approval takes no reason.")
        return value


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
