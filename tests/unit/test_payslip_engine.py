from decimal import Decimal
import pytest

from app.modules.payroll.payslip_engine import (
    ComponentSpec,
    LineItem,
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
    assert half_out.net_salary == half_out.gross_salary - half_out.total_deductions + Decimal("500.00")

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
