import uuid
from datetime import date
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.tax_slabs import seed_tax_slabs
from tests.conftest import TenantContext


@pytest.fixture(autouse=True)
def _seed_statutory_tables(db: Session):
    """Ensure pt_slabs and tax_slabs are seeded for tests."""
    seed_pt_slabs(db)
    seed_tax_slabs(db)


def test_get_and_update_statutory_config(client: TestClient, company_a: TenantContext):
    # 1. GET statutory config - lazily creates default config with verified rates
    res = client.get("/api/v1/payroll/statutory-config", headers=company_a.hr_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["country"] == "IN"
    assert data["pf_enabled"] is True
    assert data["pf_employee_rate"] == "12.000"
    assert data["pf_employer_rate"] == "12.000"
    assert data["pf_wage_ceiling"] == "15000.00"
    assert data["esi_enabled"] is True
    assert data["esi_employee_rate"] == "0.750"
    assert data["esi_employer_rate"] == "3.250"
    assert data["esi_wage_ceiling"] == "21000.00"
    assert data["default_tax_regime"] == "new"

    # 2. PUT statutory config - HR updates company statutory settings
    update_payload = {
        "pf_wage_ceiling": "21000.00",
        "pt_state": "Gujarat",
        "esi_enabled": False,
    }
    update_res = client.put(
        "/api/v1/payroll/statutory-config",
        json=update_payload,
        headers=company_a.hr_headers,
    )
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["pf_wage_ceiling"] == "21000.00"
    assert updated_data["pt_state"] == "Gujarat"
    assert updated_data["esi_enabled"] is False


def test_statutory_config_access_control(client: TestClient, company_a: TenantContext):
    # Non-HR user attempting to view or update statutory config gets 403 Forbidden
    res_get = client.get(
        "/api/v1/payroll/statutory-config", headers=company_a.employee_headers
    )
    assert res_get.status_code == 403

    res_put = client.put(
        "/api/v1/payroll/statutory-config",
        json={"pf_wage_ceiling": "18000.00"},
        headers=company_a.employee_headers,
    )
    assert res_put.status_code == 403


def test_list_and_update_pt_slabs(
    client: TestClient, company_a: TenantContext, super_admin_headers: dict[str, str]
):
    # 1. HR admin lists PT slabs for company state
    res = client.get("/api/v1/payroll/pt-slabs", headers=company_a.hr_headers)
    assert res.status_code == 200
    slabs = res.json()
    assert len(slabs) > 0
    assert any(s["source_note"] != "" for s in slabs)

    # 2. HR Admin attempting PUT on PT slabs (Super Admin only) gets 403 Forbidden
    put_res_hr = client.put(
        "/api/v1/payroll/pt-slabs",
        json={
            "state": "Maharashtra",
            "effective_from": "2026-04-01",
            "source_note": "Test Maharashtra PT Slab Notification 2026",
            "slabs": [
                {
                    "income_min": "0.00",
                    "income_max": "7500.00",
                    "monthly_amount": "0.00",
                },
                {
                    "income_min": "7500.01",
                    "income_max": "10000.00",
                    "monthly_amount": "175.00",
                },
            ],
        },
        headers=company_a.hr_headers,
    )
    assert put_res_hr.status_code == 403

    # 3. Super Admin adds PT slab set successfully
    put_res_sa = client.put(
        "/api/v1/payroll/pt-slabs",
        json={
            "state": "Maharashtra",
            "effective_from": "2026-04-01",
            "source_note": "Test Maharashtra PT Slab Notification 2026",
            "slabs": [
                {
                    "income_min": "0.00",
                    "income_max": "7500.00",
                    "monthly_amount": "0.00",
                },
                {
                    "income_min": "7500.01",
                    "income_max": None,
                    "monthly_amount": "200.00",
                },
            ],
        },
        headers=super_admin_headers,
    )
    assert put_res_sa.status_code == 200
    new_slabs = put_res_sa.json()
    assert len(new_slabs) == 2
    assert new_slabs[0]["state"] == "Maharashtra"


def test_list_and_post_tax_slabs(
    client: TestClient, company_a: TenantContext, super_admin_headers: dict[str, str]
):
    # 1. HR admin lists tax slabs for FY 2026-2027 and regime=new
    res = client.get(
        "/api/v1/payroll/tax-slabs?financial_year=2026-2027&regime=new",
        headers=company_a.hr_headers,
    )
    assert res.status_code == 200
    brackets = res.json()
    assert len(brackets) > 0
    assert brackets[0]["financial_year"] == "2026-2027"
    assert brackets[0]["regime"] == "new"
    assert brackets[0]["source_note"] != ""

    # 2. HR Admin attempting POST on tax slabs (Super Admin only) gets 403 Forbidden
    post_res_hr = client.post(
        "/api/v1/payroll/tax-slabs",
        json={
            "country": "IN",
            "financial_year": "2027-2028",
            "regime": "new",
            "cess_percent": "4.000",
            "effective_from": "2027-04-01",
            "source_note": "Budget 2027 Notification",
            "brackets": [
                {
                    "min_income": "0.00",
                    "max_income": "500000.00",
                    "rate_percent": "0.000",
                }
            ],
        },
        headers=company_a.hr_headers,
    )
    assert post_res_hr.status_code == 403

    # 3. Super Admin posts tax slabs for new FY
    post_res_sa = client.post(
        "/api/v1/payroll/tax-slabs",
        json={
            "country": "IN",
            "financial_year": "2027-2028",
            "regime": "new",
            "cess_percent": "4.000",
            "effective_from": "2027-04-01",
            "source_note": "Budget 2027 Notification",
            "brackets": [
                {
                    "min_income": "0.00",
                    "max_income": "500000.00",
                    "rate_percent": "0.000",
                },
                {
                    "min_income": "500000.01",
                    "max_income": None,
                    "rate_percent": "10.000",
                },
            ],
        },
        headers=super_admin_headers,
    )
    assert post_res_sa.status_code == 201
    created_brackets = post_res_sa.json()
    assert len(created_brackets) == 2
    assert created_brackets[0]["financial_year"] == "2027-2028"
