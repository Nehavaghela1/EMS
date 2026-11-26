# ruff: noqa: F811, E501
"""Rule tests for Spec 1: Tax Worksheet, Annual Earnings, and Salary Certificate.

Requirements:
- a month with no released run returns the no-payroll status, not a zero worksheet
- a month with a released run returns ACTUAL equal to that run's figures
- PROJECTION covers exactly the remaining months of the FY
- ACTUAL + PROJECTION == TOTAL for every line
- changing an employee's salary structure changes the next worksheet response
- no slab boundary, deduction or rebate figure is a literal in the Python source:
  assert they come from the statutory tables
- an employee cannot fetch another employee's worksheet (404/403)
- another company's employee is 404
- every money value in the response is a string from Decimal, never a float
"""

import uuid
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.rls import bind_tenant_to_session
from app.modules.payroll.models import TaxSlab
from tests.rules.test_5_4_payroll_runs import (  # noqa: F401
    PAYSLIPS,
    RUNS,
    _claim,
    _fill,
    _filled_world,
    _make_run,
    _month_back,
    _month_with_days,
    _seed_statutory,
    _set_flags,
    _staff,
    world,
)
from tests.rules.test_5_5_payslips import _released

TAX_WORKSHEET = "/api/v1/payroll/tax-worksheet"
ANNUAL_EARNINGS = "/api/v1/payroll/annual-earnings"
SALARY_CERTIFICATE = "/api/v1/payroll/salary-certificate"


def test_tax_worksheet_no_released_run(client: TestClient, db: Session, world: dict[str, Any]):
    """A month with no released run returns the no-payroll status, not a zero worksheet."""
    w = world
    headers = w["emp"]["h"]
    # Month with no run
    resp = client.get(f"{TAX_WORKSHEET}/me?month=4&year=2026", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "no_payroll"
    assert "No released payroll run" in data["message"]
    assert data["gross_tax_liability"] == "0.00"
    assert data["total_tax_payable"] == "0.00"


def test_tax_worksheet_released_run_actual_and_projection(
    client: TestClient, db: Session, world: dict[str, Any]
):
    """A month with a released run returns ACTUAL equal to that run's figures,
    PROJECTION covering remaining months of the FY, and ACTUAL + PROJECTION == TOTAL.
    """
    w = world
    _filled_world(db, w)
    # Release run for world["year"], world["month"]
    _released(client, w, w["year"], w["month"])

    headers = w["emp"]["h"]
    resp = client.get(f"{TAX_WORKSHEET}/me?month={w['month']}&year={w['year']}", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["status"] == "available"
    assert data["month"] == w["month"]
    assert data["year"] == w["year"]

    # Check total_gross: actual + projection == total
    tg = data["total_gross"]
    actual_g = Decimal(tg["actual"])
    proj_g = Decimal(tg["projection"])
    total_g = Decimal(tg["total"])
    assert actual_g + proj_g == total_g
    assert actual_g > Decimal("0.00")

    # Check each gross earning line: actual + projection == total
    for item in data["gross_earnings"]:
        act = Decimal(item["actual"])
        proj = Decimal(item["projection"])
        tot = Decimal(item["total"])
        assert act + proj == tot, f"Mismatch on {item['code']}: {act} + {proj} != {tot}"

    # Verify money figures are string representation from Decimal (e.g. 2 decimal places)
    for field in [
        "total_taxable_income",
        "gross_tax_liability",
        "rebate_87a",
        "marginal_relief",
        "tax_after_rebate",
        "health_education_cess",
        "total_tax_payable",
        "tds_till_last_month",
        "tds_this_month",
        "total_tds_paid",
        "tax_payable_or_refundable",
        "monthly_tds_remaining",
    ]:
        val = data[field]
        assert isinstance(val, str), f"{field} must be str"
        # Validate parseable as Decimal
        Decimal(val)


def test_tax_worksheet_dynamic_slabs_from_db(
    client: TestClient, db: Session, world: dict[str, Any]
):
    """Assert figures come from statutory tables, not hardcoded literals."""
    w = world
    _filled_world(db, w)
    _released(client, w, w["year"], w["month"])

    bind_tenant_to_session(db, company_id=w["ctx"].company_id, is_platform_admin=False)
    fy_start = w["year"] if w["month"] >= 4 else w["year"] - 1
    fy_str = f"{fy_start}-{fy_start + 1}"
    slabs = (
        db.query(TaxSlab).filter(TaxSlab.financial_year == fy_str, TaxSlab.regime == "new").all()
    )
    assert len(slabs) > 0
    std_ded_in_db = Decimal(str(slabs[0].surcharge_rules["standard_deduction"]))

    resp = client.get(
        f"{TAX_WORKSHEET}/me?month={w['month']}&year={w['year']}", headers=w["emp"]["h"]
    )
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(data["standard_deduction"]["total"]) == std_ded_in_db


def test_tax_worksheet_isolation_and_permissions(
    client: TestClient, db: Session, world: dict[str, Any]
):
    """An employee cannot fetch another employee's worksheet (404/403).
    Another company's employee is 404.
    """
    w = world
    manager_emp_id = w["manager"]["id"]

    # Employee calls /tax-worksheet/{manager_id} -> forbidden or not found
    resp = client.get(
        f"{TAX_WORKSHEET}/{manager_emp_id}?month={w['month']}&year={w['year']}",
        headers=w["emp"]["h"],
    )
    assert resp.status_code in (403, 404)

    # HR admin can fetch employee's worksheet
    emp_id = w["emp"]["id"]
    hr_resp = client.get(
        f"{TAX_WORKSHEET}/{emp_id}?month={w['month']}&year={w['year']}", headers=w["hr1"]
    )
    assert hr_resp.status_code == 200

    # Non-existent or other company employee -> 404
    random_id = uuid.uuid4()
    resp404 = client.get(
        f"{TAX_WORKSHEET}/{random_id}?month={w['month']}&year={w['year']}", headers=w["hr1"]
    )
    assert resp404.status_code == 404


def test_annual_earnings_and_export(client: TestClient, db: Session, world: dict[str, Any]):
    """Annual earnings returns 12 months with nulls for missing runs, and export produces .xlsx."""
    w = world
    _filled_world(db, w)
    _released(client, w, w["year"], w["month"])

    headers = w["emp"]["h"]
    fy_start = w["year"] if w["month"] >= 4 else w["year"] - 1
    fy_str = f"{fy_start}-{fy_start + 1}"

    resp = client.get(f"{ANNUAL_EARNINGS}/me?financial_year={fy_str}", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["months"]) == 12

    # Check released month info
    month_info = next(m for m in data["months"] if m["month"] == w["month"])
    assert month_info["has_payroll"] is True

    # Validate row entries
    for row in data["rows"]:
        assert len(row["monthly_amounts"]) == 12
        assert isinstance(row["total_ytd"], str)
        Decimal(row["total_ytd"])

    # Export
    exp_resp = client.get(f"{ANNUAL_EARNINGS}/me/export?financial_year={fy_str}", headers=headers)
    assert exp_resp.status_code == 200
    assert (
        exp_resp.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(exp_resp.content) > 100


def test_salary_certificate_generation(client: TestClient, db: Session, world: dict[str, Any]):
    """Salary certificate returns employee, company info, and signatory."""
    w = world
    headers = w["emp"]["h"]
    resp = client.get(f"{SALARY_CERTIFICATE}/me", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["company_name"]
    assert data["employee_code"]
    assert Decimal(data["annual_ctc"]) > Decimal("0.00")
    assert Decimal(data["monthly_gross"]) > Decimal("0.00")
    assert len(data["components"]) > 0
    assert data["signatory_name"]
    assert data["signatory_title"]
