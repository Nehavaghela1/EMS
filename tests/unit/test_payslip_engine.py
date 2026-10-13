from decimal import Decimal

import pytest

from app.modules.payroll.payslip_engine import (
    ComponentSpec,
    PayslipInput,
    PTSlabSpec,
    StatutoryConfigSpec,
    TaxSlabSpec,
    calculate_payslip,
)


@pytest.fixture
def default_statutory() -> StatutoryConfigSpec:
    return StatutoryConfigSpec(
        pf_enabled=True,
        pf_employee_rate=Decimal("12.000"),
        pf_employer_rate=Decimal("12.000"),
        pf_wage_ceiling=Decimal("15000.00"),
        pf_restrict_to_ceiling=True,
        esi_enabled=True,
        esi_employee_rate=Decimal("0.750"),
        esi_employer_rate=Decimal("3.250"),
        esi_wage_ceiling=Decimal("21000.00"),
        pt_enabled=True,
        pt_state="Gujarat",
        tds_enabled=True,
        default_tax_regime="new",
    )


@pytest.fixture
def gujarat_pt_slabs() -> list[PTSlabSpec]:
    return [
        PTSlabSpec(
            state="Gujarat",
            income_min=Decimal("0.00"),
            income_max=Decimal("12000.00"),
            monthly_amount=Decimal("0.00"),
        ),
        PTSlabSpec(
            state="Gujarat",
            income_min=Decimal("12000.01"),
            income_max=None,
            monthly_amount=Decimal("200.00"),
        ),
    ]


@pytest.fixture
def india_tax_slabs() -> list[TaxSlabSpec]:
    return [
        TaxSlabSpec(
            country="IN",
            financial_year="2026-2027",
            regime="new",
            min_income=Decimal("0.00"),
            max_income=Decimal("400000.00"),
            rate_percent=Decimal("0.000"),
            cess_percent=Decimal("4.000"),
            surcharge_rules={"standard_deduction": "75000.00"},
        ),
        TaxSlabSpec(
            country="IN",
            financial_year="2026-2027",
            regime="new",
            min_income=Decimal("400000.01"),
            max_income=Decimal("800000.00"),
            rate_percent=Decimal("5.000"),
            cess_percent=Decimal("4.000"),
            surcharge_rules={"standard_deduction": "75000.00"},
        ),
        TaxSlabSpec(
            country="IN",
            financial_year="2026-2027",
            regime="new",
            min_income=Decimal("800000.01"),
            max_income=Decimal("1200000.00"),
            rate_percent=Decimal("10.000"),
            cess_percent=Decimal("4.000"),
            surcharge_rules={"standard_deduction": "75000.00"},
        ),
    ]


@pytest.fixture
def standard_components() -> list[ComponentSpec]:
    return [
        ComponentSpec(
            code="BASIC",
            name="Basic Pay",
            type="earning",
            calculation_type="percentage",
            value=Decimal("50.00"),
            percentage_of="ctc",
            display_order=1,
        ),
        ComponentSpec(
            code="HRA",
            name="House Rent Allowance",
            type="earning",
            calculation_type="percentage",
            value=Decimal("40.00"),
            percentage_of="basic",
            display_order=2,
        ),
        ComponentSpec(
            code="SPECIAL",
            name="Special Allowance",
            type="earning",
            calculation_type="balance",
            display_order=3,
        ),
    ]


def test_payslip_below_esi_ceiling(
    default_statutory: StatutoryConfigSpec,
    gujarat_pt_slabs: list[PTSlabSpec],
    india_tax_slabs: list[TaxSlabSpec],
    standard_components: list[ComponentSpec],
):
    """Hand-calculated Case 1: Below ESI ceiling.
    Annual CTC = 216,000 (Monthly CTC = 18,000).
    Basic (50% of CTC) = 9,000
    HRA (40% of Basic) = 3,600
    Employer PF (12% of Basic 9,000) = 1,080
    Special (Balance) = 18,000 - 9,000 - 3,600 - 1,080 = 4,320
    Full Gross = 16,920 (<= 21,000 ESI ceiling -> ESI applicable).
    Employee ESI = 0.75% of 16,920 = 126.90
    Employer ESI = 3.25% of 16,920 = 549.90
    Employee PF = 12% of 9,000 = 1,080.00
    PT (Gross 16,920 > 12,000) = 200.00
    Total Deductions = 1,080.00 + 126.90 + 200.00 = 1,406.90
    Net Salary = 16,920 - 1,406.90 = 15,513.10
    """
    inp = PayslipInput(
        ctc_annual=Decimal("216000.00"),
        components=standard_components,
        statutory=default_statutory,
        pt_slabs=gujarat_pt_slabs,
        tax_slabs=india_tax_slabs,
        month=4,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
    )

    out = calculate_payslip(inp)

    assert out.gross_salary == Decimal("16920.00")
    assert out.total_deductions == Decimal("1406.90")
    assert out.net_salary == Decimal("15513.10")

    # Invariant balance assertion check
    assert sum(e.amount for e in out.earnings) - out.total_deductions == out.net_salary

    # Component exact checks
    basic_line = next(e for e in out.earnings if e.code == "BASIC")
    hra_line = next(e for e in out.earnings if e.code == "HRA")
    special_line = next(e for e in out.earnings if e.code == "SPECIAL")
    assert basic_line.amount == Decimal("9000.00")
    assert hra_line.amount == Decimal("3600.00")
    assert special_line.amount == Decimal("4320.00")

    pf_ee = next(d for d in out.deductions if d.code == "EPF_EE")
    esi_ee = next(d for d in out.deductions if d.code == "ESI_EE")
    pt_line = next(d for d in out.deductions if d.code == "PT")
    assert pf_ee.amount == Decimal("1080.00")
    assert esi_ee.amount == Decimal("126.90")
    assert pt_line.amount == Decimal("200.00")


def test_payslip_above_esi_ceiling(
    default_statutory: StatutoryConfigSpec,
    gujarat_pt_slabs: list[PTSlabSpec],
    india_tax_slabs: list[TaxSlabSpec],
    standard_components: list[ComponentSpec],
):
    """Hand-calculated Case 2: Above ESI ceiling.
    Annual CTC = 600,000 (Monthly CTC = 50,000).
    Basic (50% of CTC) = 25,000
    HRA (40% of Basic) = 10,000
    PF Capped Wage = min(25,000, 15,000) = 15,000
    Employer PF (12% of 15,000) = 1,800
    Special (Balance) = 50,000 - 25,000 - 10,000 - 1,800 = 13,200
    Full Gross = 48,200 (> 21,000 ESI ceiling -> ESI EXEMPT).
    Employee PF = 12% of 15,000 = 1,800.00
    PT (Gross 48,200 > 12,000) = 200.00
    TDS = 0 (Income 578,400 - 75,000 std ded = 503,400 <= 1,200,000 New Regime 87A rebate).
    Total Deductions = 1,800.00 + 200.00 = 2,000.00
    Net Salary = 48,200 - 2,000.00 = 46,200.00
    """
    inp = PayslipInput(
        ctc_annual=Decimal("600000.00"),
        components=standard_components,
        statutory=default_statutory,
        pt_slabs=gujarat_pt_slabs,
        tax_slabs=india_tax_slabs,
        month=4,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
    )

    out = calculate_payslip(inp)

    assert out.gross_salary == Decimal("48200.00")
    assert out.total_deductions == Decimal("2000.00")
    assert out.net_salary == Decimal("46200.00")

    # ESI must NOT be present in deductions
    assert not any(d.code == "ESI_EE" for d in out.deductions)
    assert not any(er.code == "ESI_ER" for er in out.employer_contributions)


def test_payslip_pt_slab_boundary(
    default_statutory: StatutoryConfigSpec,
    gujarat_pt_slabs: list[PTSlabSpec],
    india_tax_slabs: list[TaxSlabSpec],
    standard_components: list[ComponentSpec],
):
    """Hand-calculated Case 3: At PT slab boundary (<= ₹12,000/mo gross).
    Annual CTC = 144,000 (Monthly CTC = 12,000).
    Basic = 6,000
    HRA = 2,400
    Employer PF (12% of 6,000) = 720
    Special (Balance) = 12,000 - 6,000 - 2,400 - 720 = 2,880
    Full Gross = 11,280 (<= 12,000 -> PT is 0.00).
    """
    inp = PayslipInput(
        ctc_annual=Decimal("144000.00"),
        components=standard_components,
        statutory=default_statutory,
        pt_slabs=gujarat_pt_slabs,
        tax_slabs=india_tax_slabs,
        month=4,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
    )

    out = calculate_payslip(inp)

    assert out.gross_salary == Decimal("11280.00")
    # PT should NOT be in deductions because Gross 11,280 <= 12,000
    assert not any(d.code == "PT" for d in out.deductions)


def test_payslip_lop_and_full_lop(
    default_statutory: StatutoryConfigSpec,
    gujarat_pt_slabs: list[PTSlabSpec],
    india_tax_slabs: list[TaxSlabSpec],
    standard_components: list[ComponentSpec],
):
    # 1. Half LOP (15 days out of 30)
    half_lop_inp = PayslipInput(
        ctc_annual=Decimal("600000.00"),
        components=standard_components,
        statutory=default_statutory,
        pt_slabs=gujarat_pt_slabs,
        tax_slabs=india_tax_slabs,
        month=4,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("15"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("15"),
        reimbursement_amount=Decimal("500.00"),
    )

    half_out = calculate_payslip(half_lop_inp)
    assert half_out.gross_salary == Decimal("24100.00")  # Exactly 50% of 48,200
    assert half_out.net_salary == half_out.gross_salary - half_out.total_deductions + Decimal(
        "500.00"
    )

    # 2. Full LOP (30 days out of 30)
    full_lop_inp = PayslipInput(
        ctc_annual=Decimal("600000.00"),
        components=standard_components,
        statutory=default_statutory,
        pt_slabs=gujarat_pt_slabs,
        tax_slabs=india_tax_slabs,
        month=4,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("0"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("30"),
        reimbursement_amount=Decimal("1000.00"),
    )

    full_out = calculate_payslip(full_lop_inp)
    assert full_out.gross_salary == Decimal("0.00")
    assert full_out.total_deductions == Decimal("0.00")
    assert full_out.net_salary == Decimal("1000.00")  # Only reimbursement paid


def test_reimbursement_does_not_affect_statutory_deductions_only_net_salary(
    standard_components,
    default_statutory,
    gujarat_pt_slabs,
    india_tax_slabs,
):
    """Verifies that adding reimbursement does not change PF, ESI, PT, or TDS,
    and net_salary changes by exactly the reimbursement amount.
    """
    base_input_kwargs = dict(
        ctc_annual=Decimal("600000.00"),
        components=standard_components,
        statutory=default_statutory,
        pt_slabs=gujarat_pt_slabs,
        tax_slabs=india_tax_slabs,
        month=4,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
    )

    payslip_no_reimb = calculate_payslip(
        PayslipInput(**base_input_kwargs, reimbursement_amount=Decimal("0"))
    )
    payslip_with_reimb = calculate_payslip(
        PayslipInput(**base_input_kwargs, reimbursement_amount=Decimal("500.00"))
    )

    # Helper to extract statutory deduction lines by code
    def get_line(lines, code):
        return next((item for item in lines if item.code == code), None)

    for code in ["EPF_EE", "ESI_EE", "PT", "TDS"]:
        line_no = get_line(payslip_no_reimb.deductions, code)
        line_with = get_line(payslip_with_reimb.deductions, code)
        assert line_no == line_with, (
            f"Deduction line mismatch for code {code}: {line_no} vs {line_with}"
        )

    # Total deductions and gross must be identical
    assert payslip_no_reimb.gross_salary == payslip_with_reimb.gross_salary
    assert payslip_no_reimb.total_deductions == payslip_with_reimb.total_deductions

    # Only net salary changes, by exactly 500.00
    assert payslip_with_reimb.net_salary - payslip_no_reimb.net_salary == Decimal("500.00")


# --- Section 87A Marginal Relief & TDS Projection Tests ---

TAX_SLABS_EXTENDED = [
    TaxSlabSpec(
        country="IN",
        financial_year="2026-2027",
        regime="new",
        min_income=Decimal("0.00"),
        max_income=Decimal("400000.00"),
        rate_percent=Decimal("0.000"),
        cess_percent=Decimal("4.000"),
        surcharge_rules={"standard_deduction": "75000.00"},
    ),
    TaxSlabSpec(
        country="IN",
        financial_year="2026-2027",
        regime="new",
        min_income=Decimal("400000.01"),
        max_income=Decimal("800000.00"),
        rate_percent=Decimal("5.000"),
        cess_percent=Decimal("4.000"),
        surcharge_rules={"standard_deduction": "75000.00"},
    ),
    TaxSlabSpec(
        country="IN",
        financial_year="2026-2027",
        regime="new",
        min_income=Decimal("800000.01"),
        max_income=Decimal("1200000.00"),
        rate_percent=Decimal("10.000"),
        cess_percent=Decimal("4.000"),
        surcharge_rules={"standard_deduction": "75000.00"},
    ),
    TaxSlabSpec(
        country="IN",
        financial_year="2026-2027",
        regime="new",
        min_income=Decimal("1200000.01"),
        max_income=Decimal("1600000.00"),
        rate_percent=Decimal("15.000"),
        cess_percent=Decimal("4.000"),
        surcharge_rules={"standard_deduction": "75000.00"},
    ),
]


def _simple_earning_components() -> list[ComponentSpec]:
    return [
        ComponentSpec(
            code="BASIC",
            name="Basic Pay",
            type="earning",
            calculation_type="percentage",
            value=Decimal("100.00"),
            percentage_of="ctc",
            display_order=1,
        )
    ]


def _no_statutory() -> StatutoryConfigSpec:
    return StatutoryConfigSpec(
        pf_enabled=False,
        esi_enabled=False,
        pt_enabled=False,
        lwf_enabled=False,
        tds_enabled=True,
        default_tax_regime="new",
    )


def test_section_87a_new_regime_threshold_1200000():
    """Taxable income 12,00,000 under new regime: tax 0.
    Standard deduction = 75,000.
    Annual gross = 12,75,000.
    Monthly gross = 12,75,000 / 12 = 106,250.
    Taxable income = 12,75,000 - 75,000 = 12,00,000.
    Section 87A rebate applies -> tax is 0.
    """
    EXPECTED_MONTHLY_TDS = Decimal("0.00")

    annual_gross = Decimal("1275000.00")
    inp = PayslipInput(
        ctc_annual=annual_gross,
        components=_simple_earning_components(),
        statutory=_no_statutory(),
        pt_slabs=[],
        tax_slabs=TAX_SLABS_EXTENDED,
        month=4,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
    )
    out = calculate_payslip(inp)
    tds_line = next((d for d in out.deductions if d.code == "TDS"), None)
    actual_tds = tds_line.amount if tds_line else Decimal("0.00")
    assert actual_tds == EXPECTED_MONTHLY_TDS


def test_section_87a_new_regime_marginal_relief_1210000():
    """Taxable income 12,10,000 under new regime:
    Standard deduction = 75,000.
    In month 3 (March, months_remaining = 1):
      gross_earned_ytd = 1,177,916.63
      this month's gross = 107,083.37
      projected_annual_gross = 1,177,916.63 + 107,083.37 * 1 = 1,285,000.00
      taxable_annual_income = 1,285,000.00 - 75,000 = 1,210,000.00
    Slab tax:
      0 - 400k @ 0% = 0
      400k - 800k @ 5% = 20,000
      800k - 1200k @ 10% = 40,000
      1200k - 1210k @ 15% = 1,500
      Total slab tax = 61,500.00.
    Marginal relief:
      Excess taxable income over 12,00,000 = 10,000.00.
      annual_tax_before_cess = min(61,500, 10,000) = 10,000.00.
    Cess (4%):
      4% of 10,000 = 400.00.
      Total annual tax with cess = 10,400.00.
    tds_paid_ytd = 0.
    months_remaining = 1 -> monthly_tds = 10,400.00 / 1 = 10,400.00.
    """
    EXPECTED_SLAB_TAX = Decimal("61500.00")
    EXPECTED_TAX_AFTER_RELIEF = Decimal("10000.00")
    EXPECTED_ANNUAL_TAX_WITH_CESS = Decimal("10400.00")
    EXPECTED_MONTHLY_TDS = Decimal("10400.00")

    # Assert expected formula constants against arithmetic
    assert (
        min(EXPECTED_SLAB_TAX, Decimal("1210000.00") - Decimal("1200000.00"))
        == EXPECTED_TAX_AFTER_RELIEF
    )
    assert EXPECTED_TAX_AFTER_RELIEF * Decimal("1.04") == EXPECTED_ANNUAL_TAX_WITH_CESS

    inp = PayslipInput(
        ctc_annual=Decimal("1285000.44"),  # monthly_ctc = 107083.37
        components=_simple_earning_components(),
        statutory=_no_statutory(),
        pt_slabs=[],
        tax_slabs=TAX_SLABS_EXTENDED,
        month=3,
        year=2027,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
        gross_earned_ytd=Decimal("1177916.63"),
        tds_paid_ytd=Decimal("0.00"),
    )
    out = calculate_payslip(inp)
    tds_line = next((d for d in out.deductions if d.code == "TDS"), None)
    assert tds_line is not None
    assert tds_line.amount == EXPECTED_MONTHLY_TDS


def test_section_87a_new_regime_no_relief_1300000():
    """Taxable income 13,00,000 under new regime:
    Standard deduction = 75,000.
    Annual gross = 13,75,000.
    Taxable income = 13,75,000 - 75,000 = 13,00,000.
    Slab tax:
      0 - 400k @ 0% = 0
      400k - 800k @ 5% = 20,000
      800k - 1200k @ 10% = 40,000
      1200k - 1300k @ 15% = 15,000
      Total slab tax = 75,000.
    Marginal relief check:
      Excess over 12,00,000 = 100,000.
      min(75,000, 100,000) = 75,000 (no relief applies).
    Cess (4%):
      4% of 75,000 = 3,000.
      Total annual tax = 78,000.
    In month 4 (April, 12 months remaining):
      monthly_tds = 78,000 / 12 = 6,500.00.
    """
    EXPECTED_SLAB_TAX = Decimal("75000.00")
    EXPECTED_TAX_NO_RELIEF = Decimal("75000.00")
    EXPECTED_ANNUAL_TAX_WITH_CESS = Decimal("78000.00")
    EXPECTED_MONTHLY_TDS = Decimal("6500.00")

    assert (
        min(EXPECTED_SLAB_TAX, Decimal("1300000.00") - Decimal("1200000.00"))
        == EXPECTED_TAX_NO_RELIEF
    )
    assert EXPECTED_TAX_NO_RELIEF * Decimal("1.04") == EXPECTED_ANNUAL_TAX_WITH_CESS

    annual_gross = Decimal("1375000.00")
    inp = PayslipInput(
        ctc_annual=annual_gross,
        components=_simple_earning_components(),
        statutory=_no_statutory(),
        pt_slabs=[],
        tax_slabs=TAX_SLABS_EXTENDED,
        month=4,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
    )
    out = calculate_payslip(inp)
    tds_line = next((d for d in out.deductions if d.code == "TDS"), None)
    assert tds_line is not None
    assert tds_line.amount == EXPECTED_MONTHLY_TDS


# --- Fix 2: Monthly TDS Projection Tests ---


def test_tds_projection_april_first_month_zero_ytd():
    """Fix 2 (a): April (month 4), gross_earned_ytd = 0.
    Must give identical result to old behaviour (12 x this month's gross).
    Arithmetic:
      monthly_gross = 100,000.00
      months_remaining in April = 16 - 4 = 12
      projected_annual_gross = gross_earned_ytd (0) + 100,000 * 12 = 1,200,000.00
      std_deduction = 75,000.00
      taxable_annual_income = 1,200,000.00 - 75,000.00 = 1,125,000.00
      Since taxable_annual_income <= 1,200,000.00 (Section 87A threshold),
      annual_tax = 0.00 -> monthly_tds = 0.00.
    Now check with monthly_gross = 150,000.00:
      ctc_annual = 1,800,000.00 -> monthly_gross = 150,000.00
      projected_annual_gross = 0 + 150,000 * 12 = 1,800,000.00
      std_deduction = 75,000.00
      taxable_annual_income = 1,800,000 - 75,000 = 1,725,000.00
      Slabs:
        0 - 400k @ 0% = 0
        400k - 800k @ 5% = 20,000
        800k - 1200k @ 10% = 40,000
        1200k - 1600k @ 15% = 60,000
        1600k - 1725k @ 20% = 25,000
        Total slab tax = 145,000.00
      Cess 4% = 5,800.00
      Total projected annual tax = 150,800.00
      monthly_tds = 150,800.00 / 12 = 12,566.67
    """
    EXPECTED_PROJECTED_GROSS = Decimal("1800000.00")
    EXPECTED_TAXABLE_INCOME = Decimal("1725000.00")
    EXPECTED_ANNUAL_TAX = Decimal("150800.00")
    EXPECTED_MONTHLY_TDS = Decimal("12566.67")

    assert EXPECTED_PROJECTED_GROSS - Decimal("75000.00") == EXPECTED_TAXABLE_INCOME
    assert (EXPECTED_ANNUAL_TAX / Decimal("12")).quantize(Decimal("0.01")) == EXPECTED_MONTHLY_TDS

    tax_slabs_all = TAX_SLABS_EXTENDED + [
        TaxSlabSpec(
            country="IN",
            financial_year="2026-2027",
            regime="new",
            min_income=Decimal("1600000.01"),
            max_income=Decimal("2000000.00"),
            rate_percent=Decimal("20.000"),
            cess_percent=Decimal("4.000"),
            surcharge_rules={"standard_deduction": "75000.00"},
        ),
    ]

    inp = PayslipInput(
        ctc_annual=Decimal("1800000.00"),
        components=_simple_earning_components(),
        statutory=_no_statutory(),
        pt_slabs=[],
        tax_slabs=tax_slabs_all,
        month=4,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
        gross_earned_ytd=Decimal("0.00"),
        tds_paid_ytd=Decimal("0.00"),
    )
    out = calculate_payslip(inp)
    tds_line = next((d for d in out.deductions if d.code == "TDS"), None)
    assert tds_line is not None
    assert tds_line.amount == EXPECTED_MONTHLY_TDS


def test_tds_projection_october_mid_year_raise():
    """Fix 2 (b): October (month 10), employee received a raise.
    Months remaining including October = 16 - 10 = 6 months (Oct, Nov, Dec, Jan, Feb, Mar).
    Actual earned gross from April to September (6 months at 100,000/mo):
      gross_earned_ytd = 600,000.00
    New salary starting October:
      ctc_annual = 1,800,000.00 -> monthly_gross = 150,000.00
    Projection arithmetic:
      projected_annual_gross = gross_earned_ytd + (this month's gross * 6)
                             = 600,000.00 + (150,000.00 * 6)
                             = 600,000.00 + 900,000.00
                             = 1,500,000.00
      (Under old behaviour of 12 x 150,000, projected gross would have been 1,800,000.00).
    Tax calculation on 1,500,000.00:
      std_deduction = 75,000.00
      taxable_annual_income = 1,500,000.00 - 75,000.00 = 1,425,000.00
      Slabs:
        0 - 400k @ 0% = 0
        400k - 800k @ 5% = 20,000
        800k - 1200k @ 10% = 40,000
        1200k - 1425k @ 15% = 33,750
        Total slab tax = 93,750.00
      Cess 4% = 3,750.00
      Total projected annual tax = 97,500.00
    Suppose TDS already deducted in Apr-Sep was 0 (since old annual 1,200,000 was exempt under 87A):
      tds_paid_ytd = 0.00
      months_remaining = 6
      monthly_tds = 97,500.00 / 6 = 16,250.00
    """
    EXPECTED_PROJECTED_GROSS = Decimal("1500000.00")
    EXPECTED_TAXABLE_INCOME = Decimal("1425000.00")
    EXPECTED_SLAB_TAX = Decimal("93750.00")
    EXPECTED_ANNUAL_TAX_WITH_CESS = Decimal("97500.00")
    EXPECTED_MONTHLY_TDS = Decimal("16250.00")

    assert EXPECTED_PROJECTED_GROSS - Decimal("75000.00") == EXPECTED_TAXABLE_INCOME
    assert EXPECTED_SLAB_TAX * Decimal("1.04") == EXPECTED_ANNUAL_TAX_WITH_CESS
    assert EXPECTED_ANNUAL_TAX_WITH_CESS / Decimal("6") == EXPECTED_MONTHLY_TDS

    inp = PayslipInput(
        ctc_annual=Decimal("1800000.00"),
        components=_simple_earning_components(),
        statutory=_no_statutory(),
        pt_slabs=[],
        tax_slabs=TAX_SLABS_EXTENDED,
        month=10,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
        gross_earned_ytd=Decimal("600000.00"),
        tds_paid_ytd=Decimal("0.00"),
    )
    out = calculate_payslip(inp)
    tds_line = next((d for d in out.deductions if d.code == "TDS"), None)
    assert tds_line is not None
    assert tds_line.amount == EXPECTED_MONTHLY_TDS


def test_tds_projection_mid_year_joiner():
    """Fix 2 (c): Mid-year joiner who joined in October.
    Months prior to joining (Apr-Sep) have gross_earned_ytd = 0 because employee was not here.
    Months remaining in FY including October = 16 - 10 = 6.
    Arithmetic:
      monthly_gross = 250,000.00 (ctc_annual = 3,000,000.00)
      gross_earned_ytd = 0.00
      months_remaining = 6
      projected_annual_gross = gross_earned_ytd + this month's gross * 6
                             = 0 + 250,000.00 * 6 = 1,500,000.00
      Note: Months before joining (Apr-Sep) are NOT added to the projection.
      std_deduction = 75,000.00
      taxable_annual_income = 1,500,000.00 - 75,000.00 = 1,425,000.00
      Slab tax:
        0 - 400k @ 0% = 0
        400k - 800k @ 5% = 20,000
        800k - 1200k @ 10% = 40,000
        1200k - 1425k @ 15% = 33,750
        Total slab tax = 93,750.00
      Cess 4% = 3,750.00
      Total projected annual tax = 97,500.00
      tds_paid_ytd = 0.00
      months_remaining = 6
      monthly_tds = 97,500.00 / 6 = 16,250.00
    """
    EXPECTED_PROJECTED_GROSS = Decimal("1500000.00")
    EXPECTED_TAXABLE_INCOME = Decimal("1425000.00")
    EXPECTED_SLAB_TAX = Decimal("93750.00")
    EXPECTED_ANNUAL_TAX_WITH_CESS = Decimal("97500.00")
    EXPECTED_MONTHLY_TDS = Decimal("16250.00")

    assert EXPECTED_PROJECTED_GROSS - Decimal("75000.00") == EXPECTED_TAXABLE_INCOME
    assert EXPECTED_SLAB_TAX * Decimal("1.04") == EXPECTED_ANNUAL_TAX_WITH_CESS
    assert EXPECTED_ANNUAL_TAX_WITH_CESS / Decimal("6") == EXPECTED_MONTHLY_TDS

    inp = PayslipInput(
        ctc_annual=Decimal("3000000.00"),
        components=_simple_earning_components(),
        statutory=_no_statutory(),
        pt_slabs=[],
        tax_slabs=TAX_SLABS_EXTENDED,
        month=10,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
        gross_earned_ytd=Decimal("0.00"),  # mid-year joiner has no prior company earnings
        tds_paid_ytd=Decimal("0.00"),
    )
    out = calculate_payslip(inp)
    tds_line = next((d for d in out.deductions if d.code == "TDS"), None)
    assert tds_line is not None
    assert tds_line.amount == EXPECTED_MONTHLY_TDS


def test_tds_projection_october_with_tds_paid_ytd():
    """Engine test: October (month 10), tds_paid_ytd = 6 x monthly TDS already paid.
    Shows monthly TDS is remaining tax divided by remaining months
    (not full annual tax / remaining months).
    Arithmetic:
      ctc_annual = 1,800,000.00 -> monthly gross = 150,000.00
      Months 4 to 9 (April to September): 6 months at 150,000.00/mo.
      gross_earned_ytd = 150,000.00 * 6 = 900,000.00
      Months remaining including October = 16 - 10 = 6 months.
      projected_annual_gross = 900,000.00 + (150,000.00 * 6) = 1,800,000.00
      std_deduction = 75,000.00
      taxable_annual_income = 1,800,000.00 - 75,000.00 = 1,725,000.00
      Slabs:
        0 - 400k @ 0% = 0
        400k - 800k @ 5% = 20,000
        800k - 1200k @ 10% = 40,000
        1200k - 1600k @ 15% = 60,000
        1600k - 1725k @ 20% = 25,000
        Total slab tax = 145,000.00
      Cess 4% = 5,800.00
      Total projected annual tax = 150,800.00
      In April-September, annual tax was projected as 150,800.00 with monthly TDS:
        150,800.00 / 12 = 12,566.67 per month.
      Over 6 months (April-Sept), total TDS paid:
        tds_paid_ytd = 6 * 12,566.67 = 75,400.02
      In October (6 months remaining):
        remaining_tax = projected_annual_tax - tds_paid_ytd
                      = 150,800.00 - 75,400.02 = 75,399.98
        monthly_tds = remaining_tax / 6 = 75,399.98 / 6 = 12,566.66
      Notice:
        If the engine had erroneously divided full annual tax by remaining months (150,800 / 6),
        monthly TDS would have spiked to 25,133.33 (over-deducting by 100%).
        Subtracting tds_paid_ytd correctly keeps the monthly deduction at 12,566.66.
    """
    EXPECTED_ANNUAL_TAX = Decimal("150800.00")
    TDS_PAID_YTD = Decimal("75400.02")  # 6 * 12,566.67
    EXPECTED_REMAINING_TAX = Decimal("75399.98")
    EXPECTED_MONTHLY_TDS = Decimal("12566.66")

    assert EXPECTED_ANNUAL_TAX - TDS_PAID_YTD == EXPECTED_REMAINING_TAX
    assert (EXPECTED_REMAINING_TAX / Decimal("6")).quantize(Decimal("0.01")) == EXPECTED_MONTHLY_TDS

    tax_slabs_all = TAX_SLABS_EXTENDED + [
        TaxSlabSpec(
            country="IN",
            financial_year="2026-2027",
            regime="new",
            min_income=Decimal("1600000.01"),
            max_income=Decimal("2000000.00"),
            rate_percent=Decimal("20.000"),
            cess_percent=Decimal("4.000"),
            surcharge_rules={"standard_deduction": "75000.00"},
        ),
    ]

    inp = PayslipInput(
        ctc_annual=Decimal("1800000.00"),
        components=_simple_earning_components(),
        statutory=_no_statutory(),
        pt_slabs=[],
        tax_slabs=tax_slabs_all,
        month=10,
        year=2026,
        financial_year="2026-2027",
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        paid_leave_days=Decimal("0"),
        lop_days=Decimal("0"),
        gross_earned_ytd=Decimal("900000.00"),
        tds_paid_ytd=TDS_PAID_YTD,
    )
    out = calculate_payslip(inp)
    tds_line = next((d for d in out.deductions if d.code == "TDS"), None)
    assert tds_line is not None
    assert tds_line.amount == EXPECTED_MONTHLY_TDS
