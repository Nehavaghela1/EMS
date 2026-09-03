"""Spec 11.1, 11.6, 11.7 - The Payslip Calculation Engine.

Pure function. No database. No ORM objects. No routes.
All money is Decimal with explicit ROUND_HALF_UP quantization to 2 places.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

TWO_PLACES = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ComponentSpec:
    code: str
    name: str
    type: str  # "earning", "deduction", "employer_contribution"
    calculation_type: str  # "percentage", "fixed", "balance", "statutory"
    value: Decimal | None = None
    percentage_of: str | None = None  # "ctc", "basic"
    is_taxable: bool = True
    is_statutory: bool = False
    display_order: int = 0


@dataclass(frozen=True)
class StatutoryConfigSpec:
    pf_enabled: bool = True
    pf_employee_rate: Decimal = Decimal("12.000")
    pf_employer_rate: Decimal = Decimal("12.000")
    pf_wage_ceiling: Decimal = Decimal("15000.00")
    pf_restrict_to_ceiling: bool = True
    esi_enabled: bool = True
    esi_employee_rate: Decimal = Decimal("0.750")
    esi_employer_rate: Decimal = Decimal("3.250")
    esi_wage_ceiling: Decimal = Decimal("21000.00")
    pt_enabled: bool = True
    pt_state: str | None = "Gujarat"
    lwf_enabled: bool = False
    lwf_employee_amount: Decimal | None = None
    lwf_months: tuple[int, ...] = ()
    tds_enabled: bool = True
    default_tax_regime: str = "new"


@dataclass(frozen=True)
class PTSlabSpec:
    state: str
    income_min: Decimal
    income_max: Decimal | None
    monthly_amount: Decimal
    special_month: int | None = None
    special_month_amount: Decimal | None = None


@dataclass(frozen=True)
class TaxSlabSpec:
    country: str
    financial_year: str
    regime: str  # "new", "old"
    min_income: Decimal
    max_income: Decimal | None
    rate_percent: Decimal
    cess_percent: Decimal = Decimal("4.000")
    surcharge_rules: dict | None = None


@dataclass(frozen=True)
class PayslipInput:
    ctc_annual: Decimal
    components: Sequence[ComponentSpec]
    statutory: StatutoryConfigSpec
    pt_slabs: Sequence[PTSlabSpec]
    tax_slabs: Sequence[TaxSlabSpec]
    month: int  # 1-12
    year: int
    financial_year: str  # e.g. "2026-2027"
    working_days: Decimal
    present_days: Decimal
    paid_leave_days: Decimal
    lop_days: Decimal
    tds_paid_ytd: Decimal = Decimal("0")
    reimbursement_amount: Decimal = Decimal("0")


@dataclass(frozen=True)
class LineItem:
    code: str
    name: str
    amount: Decimal
    note: str | None = None


@dataclass(frozen=True)
class PayslipOutput:
    earnings: list[LineItem]
    deductions: list[LineItem]
    employer_contributions: list[LineItem]
    gross_salary: Decimal
    total_deductions: Decimal
    net_salary: Decimal
    employer_cost: Decimal


BASIC_CODE = "BASIC"


def calculate_payslip(data: PayslipInput) -> PayslipOutput:
    """Computes a complete payslip using exact Decimal arithmetic and explicit
    ROUND_HALF_UP quantization per Spec 11.6.
    """
    monthly_ctc = _round(data.ctc_annual / Decimal("12"))

    # 1. Full-month earnings calculation
    earning_specs = [c for c in data.components if c.type == "earning"]
    earning_specs_sorted = sorted(earning_specs, key=lambda c: c.display_order)

    full_earnings: dict[str, Decimal] = {}
    basic_full: Decimal | None = None

    # First pass: Percentage of CTC and Fixed components
    for c in earning_specs_sorted:
        if c.calculation_type == "percentage" and c.percentage_of == "ctc":
            assert c.value is not None
            val = _round(monthly_ctc * c.value / Decimal("100"))
            full_earnings[c.code] = val
            if c.code == BASIC_CODE:
                basic_full = val
        elif c.calculation_type == "fixed":
            assert c.value is not None
            full_earnings[c.code] = _round(c.value)

    # Second pass: Percentage of BASIC components
    for c in earning_specs_sorted:
        if c.calculation_type == "percentage" and c.percentage_of == "basic":
            assert c.value is not None
            base = basic_full if basic_full is not None else Decimal("0")
            full_earnings[c.code] = _round(base * c.value / Decimal("100"))

    # Estimate full employer PF for balance component calculation
    employer_pf_full = Decimal("0")
    if data.statutory.pf_enabled and basic_full is not None and basic_full > 0:
        pf_wage = (
            min(basic_full, data.statutory.pf_wage_ceiling)
            if data.statutory.pf_restrict_to_ceiling
            else basic_full
        )
        employer_pf_full = _round(pf_wage * data.statutory.pf_employer_rate / Decimal("100"))

    # Third pass: Balance component
    balance_spec = next((c for c in earning_specs_sorted if c.calculation_type == "balance"), None)
    if balance_spec is not None:
        non_balance_sum = sum(full_earnings.values(), Decimal("0"))
        full_earnings[balance_spec.code] = _round(monthly_ctc - (non_balance_sum + employer_pf_full))

    full_gross = sum(full_earnings.values(), Decimal("0"))

    # 2. Apply Loss of Pay (LOP) and allocate rounding residual
    if data.working_days <= 0 or data.lop_days >= data.working_days:
        earned_gross = Decimal("0.00")
        earned_earnings = {code: Decimal("0.00") for code in full_earnings}
    else:
        paid_days = data.working_days - data.lop_days
        ratio = paid_days / data.working_days
        target_gross = _round(full_gross * ratio)

        earned_earnings = {}
        for c in earning_specs_sorted:
            if c.calculation_type != "balance":
                earned_earnings[c.code] = _round(full_earnings.get(c.code, Decimal("0")) * ratio)

        if balance_spec is not None:
            non_balance_earned = sum(earned_earnings.values(), Decimal("0"))
            earned_earnings[balance_spec.code] = _round(target_gross - non_balance_earned)
        else:
            # If no balance component, allocate residual to largest earning line
            non_balance_earned = sum(earned_earnings.values(), Decimal("0"))
            residual = target_gross - non_balance_earned
            if residual != 0 and earning_specs_sorted:
                largest = max(earning_specs_sorted, key=lambda c: earned_earnings.get(c.code, Decimal("0")))
                earned_earnings[largest.code] = earned_earnings[largest.code] + residual

        earned_gross = sum(earned_earnings.values(), Decimal("0"))

    # Build earning line items
    earning_lines = [
        LineItem(code=c.code, name=c.name, amount=earned_earnings.get(c.code, Decimal("0.00")))
        for c in earning_specs_sorted
    ]

    # 3. Statutory deductions & Employer contributions
    deduction_lines: list[LineItem] = []
    employer_lines: list[LineItem] = []

    earned_basic = earned_earnings.get(BASIC_CODE, Decimal("0.00"))

    # EPF Calculation
    if data.statutory.pf_enabled and earned_basic > 0:
        pf_wage = (
            min(earned_basic, data.statutory.pf_wage_ceiling)
            if data.statutory.pf_restrict_to_ceiling
            else earned_basic
        )
        epf_ee = _round(pf_wage * data.statutory.pf_employee_rate / Decimal("100"))
        epf_er = _round(pf_wage * data.statutory.pf_employer_rate / Decimal("100"))

        deduction_lines.append(LineItem(code="EPF_EE", name="Employee PF", amount=epf_ee))
        employer_lines.append(LineItem(code="EPF_ER", name="Employer PF", amount=epf_er))

    # ESI Calculation (Tested on FULL-MONTH gross; rate applied to earned gross)
    if data.statutory.esi_enabled and full_gross <= data.statutory.esi_wage_ceiling and earned_gross > 0:
        esi_ee = _round(earned_gross * data.statutory.esi_employee_rate / Decimal("100"))
        esi_er = _round(earned_gross * data.statutory.esi_employer_rate / Decimal("100"))

        deduction_lines.append(LineItem(code="ESI_EE", name="Employee ESI", amount=esi_ee))
        employer_lines.append(LineItem(code="ESI_ER", name="Employer ESI", amount=esi_er))

    # Professional Tax (PT) Calculation (Tested on FULL-MONTH gross)
    if data.statutory.pt_enabled and earned_gross > 0 and data.pt_slabs:
        matching_slab = None
        for slab in data.pt_slabs:
            if slab.income_min <= full_gross and (slab.income_max is None or full_gross <= slab.income_max):
                matching_slab = slab
                break

        if matching_slab is not None:
            pt_amount = matching_slab.monthly_amount
            if matching_slab.special_month == data.month and matching_slab.special_month_amount is not None:
                pt_amount = matching_slab.special_month_amount

            if pt_amount > 0:
                deduction_lines.append(LineItem(code="PT", name="Professional Tax", amount=_round(pt_amount)))

    # Labour Welfare Fund (LWF) Calculation
    if (
        data.statutory.lwf_enabled
        and data.statutory.lwf_employee_amount is not None
        and data.month in data.statutory.lwf_months
    ):
        deduction_lines.append(
            LineItem(code="LWF", name="Labour Welfare Fund", amount=_round(data.statutory.lwf_employee_amount))
        )

    # TDS (Income Tax) Calculation
    if data.statutory.tds_enabled and full_gross > 0:
        projected_annual_gross = full_gross * Decimal("12")
        tax_regime = data.statutory.default_tax_regime

        # Filter tax slabs for matching regime
        matching_tax_slabs = [s for s in data.tax_slabs if s.regime == tax_regime]

        # Standard deduction from surcharge_rules JSON or default
        std_deduction = Decimal("75000.00") if tax_regime == "new" else Decimal("50000.00")
        if matching_tax_slabs and matching_tax_slabs[0].surcharge_rules:
            rules = matching_tax_slabs[0].surcharge_rules
            if "standard_deduction" in rules:
                std_deduction = Decimal(str(rules["standard_deduction"]))

        taxable_annual_income = max(Decimal("0.00"), projected_annual_gross - std_deduction)

        annual_tax = Decimal("0.00")
        cess_percent = Decimal("4.000")
        if matching_tax_slabs:
            cess_percent = matching_tax_slabs[0].cess_percent
            for slab in sorted(matching_tax_slabs, key=lambda s: s.min_income):
                if taxable_annual_income > slab.min_income:
                    top = taxable_annual_income if slab.max_income is None else min(taxable_annual_income, slab.max_income)
                    taxable_in_bracket = top - slab.min_income
                    annual_tax += _round(taxable_in_bracket * slab.rate_percent / Decimal("100"))

        # Section 87A Rebate check
        if tax_regime == "new" and taxable_annual_income <= Decimal("1200000.00"):
            annual_tax = Decimal("0.00")
        elif tax_regime == "old" and taxable_annual_income <= Decimal("500000.00"):
            annual_tax = Decimal("0.00")

        annual_cess = _round(annual_tax * cess_percent / Decimal("100"))
        projected_annual_tax = annual_tax + annual_cess

        # Financial year is April (month 4) to March (month 3)
        # Months remaining in FY including current month:
        # April (4) -> 12, May (5) -> 11, ..., March (3) -> 1
        if data.month >= 4:
            months_remaining = 16 - data.month
        else:
            months_remaining = 4 - data.month
        months_remaining = max(1, months_remaining)

        monthly_tds = _round(max(Decimal("0.00"), (projected_annual_tax - data.tds_paid_ytd) / Decimal(str(months_remaining))))
        if monthly_tds > 0:
            deduction_lines.append(LineItem(code="TDS", name="Income Tax (Estimated)", amount=monthly_tds))

    total_deductions = sum((d.amount for d in deduction_lines), Decimal("0.00"))
    net_salary = earned_gross - total_deductions + data.reimbursement_amount
    employer_cost = earned_gross + sum((er.amount for er in employer_lines), Decimal("0.00"))

    # Invariant assertions (Spec 11.1 / 11.6 step 6)
    assert sum((e.amount for e in earning_lines), Decimal("0.00")) == earned_gross, "Earnings line sum mismatch"
    assert earned_gross - total_deductions + data.reimbursement_amount == net_salary, "Net salary balance mismatch"

    return PayslipOutput(
        earnings=earning_lines,
        deductions=deduction_lines,
        employer_contributions=employer_lines,
        gross_salary=earned_gross,
        total_deductions=total_deductions,
        net_salary=net_salary,
        employer_cost=employer_cost,
    )
