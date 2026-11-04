"""Spec 11.1, 11.6, 11.7 - The Payslip Calculation Engine.

Pure function. No database. No ORM objects. No routes.
All money is Decimal with explicit ROUND_HALF_UP quantization to 2 places.
"""

from calendar import monthrange
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.core.exceptions import ConflictError

TWO_PLACES = Decimal("0.01")


class MissingRateError(ConflictError):
    """A figure the payslip needs (a PF or ESI rate row, an income-tax slab, its rebate,
    standard deduction or cess) is not on file. The engine never falls back to a literal: the
    run stops with this message instead (5.2)."""


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _rule_amount(rules: dict, key: str, regime: str, financial_year: str) -> Decimal:
    value = rules.get(key)
    if value is None:
        raise MissingRateError(
            f"The income-tax slabs for the {regime} regime, financial year {financial_year}, "
            f"have no '{key}' figure on file."
        )
    return Decimal(str(value))


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
    """A company's switches and choices. Rates and ceilings are not here: they come from the
    effective-dated platform rows (`PfRateSpec`, `EsiRateSpec`, the slabs) of the payroll month."""

    pf_enabled: bool = True
    pf_restrict_to_ceiling: bool = True
    esi_enabled: bool = True
    pt_enabled: bool = True
    pt_state: str | None = "Gujarat"
    lwf_enabled: bool = False
    lwf_employee_amount: Decimal | None = None
    lwf_months: tuple[int, ...] = ()
    tds_enabled: bool = True
    default_tax_regime: str = "new"


@dataclass(frozen=True)
class PfRateSpec:
    """The EPF row in force on the first day of the payroll month."""

    employee_rate: Decimal
    employer_rate: Decimal
    wage_ceiling: Decimal


@dataclass(frozen=True)
class EsiRateSpec:
    """The ESI row in force on the first day of the payroll month. An employee whose average
    daily wage is at or below `employee_exempt_daily_wage` pays no employee share (the
    employer still pays its own)."""

    employee_rate: Decimal
    employer_rate: Decimal
    wage_ceiling: Decimal
    employee_exempt_daily_wage: Decimal | None = None


def esi_average_daily_wage(earned_gross: Decimal, days_in_month: Decimal) -> Decimal:
    """The average daily wage used for the ESI employee-share exemption.

    ASSUMPTION: esic.gov.in/contribution does not define how the average daily wage is
    computed. It is taken here as the ESI-liable earned gross of the payroll month divided by
    the calendar days of that month. This one function is the only place the formula lives;
    confirm it against the ESI (Central) Rules, 1950 and change it here if it differs.
    Not rounded: the comparison with the limit must not be moved by rounding.
    """
    return earned_gross / days_in_month


@dataclass(frozen=True)
class SalarySegment:
    """The days of a payroll month paid at one salary row (a raise that starts mid-month
    splits the month). `days` is the calendar days of the row inside the month; `lop_days` the
    loss-of-pay days that fall inside it."""

    salary_id: str
    from_date: date
    to_date: date
    days: int
    ctc_annual: Decimal
    components: Sequence[ComponentSpec]
    lop_days: Decimal


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
    cess_percent: Decimal
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
    gross_earned_ytd: Decimal = Decimal("0.00")
    reimbursement_amount: Decimal = Decimal("0")
    pf_rate: PfRateSpec | None = None
    esi_rate: EsiRateSpec | None = None
    # Last working day of a leaver; only a date inside the payroll month changes anything
    # (professional tax is paid for the days worked).
    last_working_date: date | None = None
    # Salary rows of the month, oldest first. When given, `ctc_annual` and `components` are the
    # salary at the month end (the last segment) and `lop_days` is the month's total.
    segments: Sequence[SalarySegment] | None = None


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


@dataclass(frozen=True)
class _SegmentAmounts:
    full_gross: Decimal  # a full month at this salary
    earned: dict[str, Decimal]  # per component: this segment's share of the month, after LOP
    specs: list[ComponentSpec]  # the earning components, in display order


def _segment_amounts(
    ctc_annual: Decimal,
    components: Sequence[ComponentSpec],
    pf: PfRateSpec | None,
    statutory: StatutoryConfigSpec,
    working_days: Decimal,
    segment_days: Decimal,
    lop_days: Decimal,
) -> _SegmentAmounts:
    """One salary's earnings for its days of the month: the full-month amounts of every
    component, scaled by (segment days - loss-of-pay days) / days of the month, each line rounded
    half up, the rounding residual put on the balance line (or the largest line). With one
    segment covering the whole month this is exactly the whole-month calculation."""
    monthly_ctc = _round(ctc_annual / Decimal("12"))

    # 1. Full-month earnings calculation
    earning_specs = [c for c in components if c.type == "earning"]
    earning_specs_sorted = sorted(earning_specs, key=lambda c: c.display_order)

    full_earnings: dict[str, Decimal] = {}
    basic_full: Decimal | None = None

    # First pass: Percentage of CTC and Fixed components
    for c in earning_specs_sorted:
        if c.calculation_type == "percentage" and c.percentage_of == "ctc":
            assert c.value is not None
            val = _round(monthly_ctc * c.value / Decimal("100"))
            full_earnings[c.code] = val
            if (
                c.code.upper() in ("BASIC", "BASIC_PAY", "BASIC_SALARY")
                or "BASIC" in c.name.upper()
            ):
                basic_full = val
        elif c.calculation_type == "fixed":
            assert c.value is not None
            full_earnings[c.code] = _round(c.value)
            if (
                c.code.upper() in ("BASIC", "BASIC_PAY", "BASIC_SALARY")
                or "BASIC" in c.name.upper()
            ):
                basic_full = full_earnings[c.code]

    # Second pass: Percentage of BASIC components
    for c in earning_specs_sorted:
        if c.calculation_type == "percentage" and c.percentage_of == "basic":
            assert c.value is not None
            base = basic_full if basic_full is not None else Decimal("0")
            full_earnings[c.code] = _round(base * c.value / Decimal("100"))

    # Estimate full employer PF for balance component calculation
    employer_pf_full = Decimal("0")
    if pf is not None and statutory.pf_enabled and basic_full is not None and basic_full > 0:
        pf_wage = (
            min(basic_full, pf.wage_ceiling) if statutory.pf_restrict_to_ceiling else basic_full
        )
        employer_pf_full = _round(pf_wage * pf.employer_rate / Decimal("100"))

    # Third pass: Balance component
    balance_spec = next((c for c in earning_specs_sorted if c.calculation_type == "balance"), None)
    if balance_spec is not None:
        non_balance_sum = sum(full_earnings.values(), Decimal("0"))
        full_earnings[balance_spec.code] = _round(
            monthly_ctc - (non_balance_sum + employer_pf_full)
        )

    full_gross = sum(full_earnings.values(), Decimal("0"))

    # 2. Apply the segment's days and Loss of Pay (LOP) and allocate rounding residual
    paid_days = segment_days - lop_days
    if working_days <= 0 or paid_days <= 0:
        earned_earnings = {code: Decimal("0.00") for code in full_earnings}
    else:
        ratio = paid_days / working_days
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
                largest = max(
                    earning_specs_sorted, key=lambda c: earned_earnings.get(c.code, Decimal("0"))
                )
                earned_earnings[largest.code] = earned_earnings[largest.code] + residual

    return _SegmentAmounts(full_gross, earned_earnings, earning_specs_sorted)


def calculate_payslip(data: PayslipInput) -> PayslipOutput:
    """Computes a complete payslip using exact Decimal arithmetic and explicit
    ROUND_HALF_UP quantization per Spec 11.6.
    """
    # The PF and ESI figures of the payroll month must be on file when the item is switched on.
    pf = data.pf_rate
    esi = data.esi_rate
    if data.statutory.pf_enabled and pf is None:
        raise MissingRateError(
            f"No EPF rate is on file for {data.year}-{data.month:02d}, but PF is switched on."
        )
    if data.statutory.esi_enabled and esi is None:
        raise MissingRateError(
            f"No ESI rate is on file for {data.year}-{data.month:02d}, but ESI is switched on."
        )

    # 1-2. Earnings: one calculation per salary segment of the month (B1-B3). The month's
    # earned amounts are the sums per component. Anything that tests a "full month" figure (the
    # ESI ceiling, professional tax, TDS) uses the salary in force at the month end, the last
    # segment, as before.
    segments = (
        list(data.segments)
        if data.segments
        else [
            SalarySegment(
                salary_id="",
                from_date=date(data.year, data.month, 1),
                to_date=date(data.year, data.month, monthrange(data.year, data.month)[1]),
                days=int(data.working_days),
                ctc_annual=data.ctc_annual,
                components=data.components,
                lop_days=data.lop_days,
            )
        ]
    )
    earned_earnings: dict[str, Decimal] = {}
    merged_specs: dict[str, ComponentSpec] = {}
    full_gross = Decimal("0")
    for segment in segments:
        amounts = _segment_amounts(
            segment.ctc_annual,
            segment.components,
            pf,
            data.statutory,
            data.working_days,
            # A single segment of a plain run covers the whole month by definition.
            data.working_days if not data.segments else Decimal(segment.days),
            segment.lop_days,
        )
        for code, value in amounts.earned.items():
            earned_earnings[code] = earned_earnings.get(code, Decimal("0")) + value
        for spec in amounts.specs:
            merged_specs.setdefault(spec.code, spec)
        full_gross = amounts.full_gross
    earning_specs_sorted = sorted(merged_specs.values(), key=lambda c: c.display_order)
    earned_gross = sum(earned_earnings.values(), Decimal("0.00"))

    # Build earning line items
    earning_lines = [
        LineItem(code=c.code, name=c.name, amount=earned_earnings.get(c.code, Decimal("0.00")))
        for c in earning_specs_sorted
    ]

    # 3. Statutory deductions & Employer contributions
    deduction_lines: list[LineItem] = []
    employer_lines: list[LineItem] = []

    earned_basic = earned_earnings.get(BASIC_CODE)
    if earned_basic is None:
        for c in earning_specs_sorted:
            if (
                c.code.upper() in ("BASIC", "BASIC_PAY", "BASIC_SALARY")
                or "BASIC" in c.name.upper()
            ):
                earned_basic = earned_earnings.get(c.code)
                break
    if earned_basic is None:
        earned_basic = Decimal("0.00")

    # EPF Calculation (12% of Basic Pay, capped at statutory ceiling if checked)
    if pf is not None and data.statutory.pf_enabled and earned_basic > 0:
        pf_wage = (
            min(earned_basic, pf.wage_ceiling)
            if data.statutory.pf_restrict_to_ceiling
            else earned_basic
        )
        epf_ee = _round(pf_wage * pf.employee_rate / Decimal("100"))
        epf_er = _round(pf_wage * pf.employer_rate / Decimal("100"))

        deduction_lines.append(LineItem(code="EPF_EE", name="Employee PF", amount=epf_ee))
        employer_lines.append(LineItem(code="EPF_ER", name="Employer PF", amount=epf_er))

    # ESI Calculation (Tested on FULL-MONTH gross; rate applied to earned gross)
    if (
        esi is not None
        and data.statutory.esi_enabled
        and full_gross <= esi.wage_ceiling
        and earned_gross > 0
    ):
        exempt_limit = esi.employee_exempt_daily_wage
        employee_exempt = exempt_limit is not None and (
            esi_average_daily_wage(earned_gross, data.working_days) <= exempt_limit
        )
        esi_ee = (
            Decimal("0.00")
            if employee_exempt
            else _round(earned_gross * esi.employee_rate / Decimal("100"))
        )
        esi_er = _round(earned_gross * esi.employer_rate / Decimal("100"))

        deduction_lines.append(LineItem(code="ESI_EE", name="Employee ESI", amount=esi_ee))
        employer_lines.append(LineItem(code="ESI_ER", name="Employer ESI", amount=esi_er))

    # Professional Tax (PT) Calculation (Tested on FULL-MONTH gross)
    if data.statutory.pt_enabled and earned_gross > 0 and data.pt_slabs:
        matching_slab = None
        for slab in data.pt_slabs:
            if slab.income_min <= full_gross and (
                slab.income_max is None or full_gross <= slab.income_max
            ):
                matching_slab = slab
                break

        if matching_slab is not None:
            pt_amount = matching_slab.monthly_amount
            if (
                matching_slab.special_month == data.month
                and matching_slab.special_month_amount is not None
            ):
                pt_amount = matching_slab.special_month_amount

            # A leaver pays for the days worked (Gujarat schedule, Entry 1, Explanation II):
            # days from the 1st up to and including the last working day, over the month's days.
            last_day = data.last_working_date
            if last_day is not None and (last_day.year, last_day.month) == (data.year, data.month):
                month_days = monthrange(data.year, data.month)[1]
                pt_amount = _round(pt_amount * Decimal(last_day.day) / Decimal(month_days))

            if pt_amount > 0:
                deduction_lines.append(
                    LineItem(code="PT", name="Professional Tax", amount=_round(pt_amount))
                )

    # Labour Welfare Fund (LWF) Calculation
    if (
        data.statutory.lwf_enabled
        and data.statutory.lwf_employee_amount is not None
        and data.month in data.statutory.lwf_months
    ):
        deduction_lines.append(
            LineItem(
                code="LWF",
                name="Labour Welfare Fund",
                amount=_round(data.statutory.lwf_employee_amount),
            )
        )

    # TDS (Income Tax) Calculation
    if data.statutory.tds_enabled and full_gross > 0:
        # Financial year is April (month 4) to March (month 3)
        # Months remaining in FY including current month:
        # April (4) -> 12, May (5) -> 11, ..., March (3) -> 1
        if data.month >= 4:
            months_remaining = 16 - data.month
        else:
            months_remaining = 4 - data.month
        months_remaining = max(1, months_remaining)

        # Fix 2: Projected annual gross incorporates actual gross earned in FY so far
        projected_annual_gross = data.gross_earned_ytd + full_gross * Decimal(str(months_remaining))
        tax_regime = data.statutory.default_tax_regime

        # Filter tax slabs for matching regime. Every figure below comes from the slab rows
        # (brackets, cess, standard deduction, 87A rebate); a missing one stops the run.
        matching_tax_slabs = [s for s in data.tax_slabs if s.regime == tax_regime]
        if not matching_tax_slabs:
            raise MissingRateError(
                f"No income-tax slabs for the {tax_regime} regime, financial year "
                f"{data.financial_year}, are on file."
            )
        rules = matching_tax_slabs[0].surcharge_rules or {}
        std_deduction = _rule_amount(rules, "standard_deduction", tax_regime, data.financial_year)
        rebate = rules.get("rebate_87a") or {}
        rebate_limit = _rule_amount(rebate, "income_limit", tax_regime, data.financial_year)
        rebate_max = _rule_amount(rebate, "max_rebate", tax_regime, data.financial_year)
        cess_percent = matching_tax_slabs[0].cess_percent

        taxable_annual_income = max(Decimal("0.00"), projected_annual_gross - std_deduction)

        annual_tax = Decimal("0.00")
        for tax_slab in sorted(matching_tax_slabs, key=lambda s: s.min_income):
            if taxable_annual_income > tax_slab.min_income:
                top = (
                    taxable_annual_income
                    if tax_slab.max_income is None
                    else min(taxable_annual_income, tax_slab.max_income)
                )
                taxable_in_bracket = top - tax_slab.min_income
                annual_tax += _round(taxable_in_bracket * tax_slab.rate_percent / Decimal("100"))

        # Section 87A: a rebate up to the row's maximum on incomes up to the row's limit; in
        # the new regime marginal relief just above the limit (tax never exceeds the income
        # over the limit).
        if taxable_annual_income <= rebate_limit:
            annual_tax -= min(annual_tax, rebate_max)
        elif tax_regime == "new":
            annual_tax = min(annual_tax, taxable_annual_income - rebate_limit)

        annual_cess = _round(annual_tax * cess_percent / Decimal("100"))
        projected_annual_tax = annual_tax + annual_cess

        monthly_tds = _round(
            max(
                Decimal("0.00"),
                (projected_annual_tax - data.tds_paid_ytd) / Decimal(str(months_remaining)),
            )
        )
        if monthly_tds > 0:
            deduction_lines.append(
                LineItem(code="TDS", name="Income Tax (Estimated)", amount=monthly_tds)
            )

    total_deductions = sum((d.amount for d in deduction_lines), Decimal("0.00"))
    net_salary = earned_gross - total_deductions + data.reimbursement_amount
    employer_cost = earned_gross + sum((er.amount for er in employer_lines), Decimal("0.00"))

    # Invariant assertions (Spec 11.1 / 11.6 step 6)
    assert sum((e.amount for e in earning_lines), Decimal("0.00")) == earned_gross, (
        "Earnings line sum mismatch"
    )
    assert earned_gross - total_deductions + data.reimbursement_amount == net_salary, (
        "Net salary balance mismatch"
    )

    return PayslipOutput(
        earnings=earning_lines,
        deductions=deduction_lines,
        employer_contributions=employer_lines,
        gross_salary=earned_gross,
        total_deductions=total_deductions,
        net_salary=net_salary,
        employer_cost=employer_cost,
    )
