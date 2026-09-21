import uuid
from datetime import date
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.modules.identity.models import User, UserRole
from tests.integration.test_employees import _create_employee


def test_resignation_and_fnf_workflow(client: TestClient, db: Session, company_a):
    hr_headers = company_a.hr_headers
    emp = _create_employee(client, hr_headers, email="resigning@example.com")
    emp_id = emp["id"]
    assert emp["notice_period_days"] == 30

    # 1. Submit early resignation: 2026-09-17 to 2026-10-01 (14 days served)
    # Expected shortfall = 30 - 14 = 16 days
    res_sub = client.post(
        f"/api/v1/employees/{emp_id}/resignation",
        json={"resignation_date": "2026-09-17", "last_working_date": "2026-10-01", "reason": "Better opportunity"},
        headers=hr_headers,
    )
    assert res_sub.status_code == 200, res_sub.text
    emp_res = res_sub.json()
    assert emp_res["resignation_status"] == "submitted"
    assert emp_res["notice_recovery_days"] == 16

    # 2. List resignations
    res_list = client.get("/api/v1/employees/resignations", headers=hr_headers)
    assert res_list.status_code == 200
    ids = [r["id"] for r in res_list.json()]
    assert emp_id in ids

    # 3. Approve resignation with notice recovery (16 days shortfall)
    res_app = client.put(
        f"/api/v1/employees/{emp_id}/resignation/approve",
        json={"approved": True, "notice_waived": False, "notice_recovery_days": 16},
        headers=hr_headers,
    )
    assert res_app.status_code == 200
    assert res_app.json()["resignation_status"] == "approved"
    assert res_app.json()["notice_recovery_days"] == 16
    assert res_app.json()["notice_waived"] is False

    # Create salary structure and assign ₹11,750.00 monthly gross to test exact math
    # CTC = 141,000 (11,750 * 12)
    struct_res = client.post(
        "/api/v1/payroll/structures",
        json={
            "name": "Standard L1 Structure",
            "components": [
                {
                    "code": "BASIC",
                    "name": "Basic Salary",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "percentage_of": "ctc",
                    "value": 50.0,
                    "is_taxable": True,
                    "is_statutory": False,
                    "display_order": 1,
                },
                {
                    "code": "SPECIAL",
                    "name": "Special Allowance",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "percentage_of": "ctc",
                    "value": 50.0,
                    "is_taxable": True,
                    "is_statutory": False,
                    "display_order": 2,
                },
            ],
        },
        headers=hr_headers,
    )
    assert struct_res.status_code == 201, struct_res.text
    struct_id = struct_res.json()["id"]

    sal_assign = client.post(
        f"/api/v1/payroll/employees/{emp_id}/assign",
        json={
            "structure_id": struct_id,
            "ctc": 141000.00,  # 141,000 annual CTC = 11,750 monthly gross
            "effective_from": "2026-01-01",
        },
        headers=hr_headers,
    )
    assert sal_assign.status_code == 201, sal_assign.text

    # 4. Calculate FnF Settlement
    res_fnf = client.get(f"/api/v1/employees/{emp_id}/fnf", headers=hr_headers)
    assert res_fnf.status_code == 200
    fnf_data = res_fnf.json()
    assert fnf_data["notice_days_required"] == 30
    assert fnf_data["notice_days_served"] == 14
    assert fnf_data["notice_recovery_days"] == 16
    assert Decimal(str(fnf_data["monthly_gross_salary"])) == Decimal("11750.00")
    # Per day salary = 11750 / 30 = 391.67
    assert Decimal(str(fnf_data["per_day_salary"])) == Decimal("391.67")
    # 16 days notice shortfall recovery = 16 * 391.67 = 6266.72
    assert Decimal(str(fnf_data["notice_recovery_amount"])) == Decimal("6266.72")
    # 1 day unpaid salary = 1 * 391.67 = 391.67
    assert Decimal(str(fnf_data["unpaid_salary_days"])) == 1
    assert Decimal(str(fnf_data["unpaid_salary_amount"])) == Decimal("391.67")
    assert "total_settlement_amount" in fnf_data

    # 5. Test Waive Notice behavior
    res_waive = client.put(
        f"/api/v1/employees/{emp_id}/resignation/approve",
        json={"approved": True, "notice_waived": True, "notice_recovery_days": 0},
        headers=hr_headers,
    )
    assert res_waive.status_code == 200
    assert res_waive.json()["notice_recovery_days"] == 0
    assert res_waive.json()["notice_waived"] is True

    fnf_waived = client.get(f"/api/v1/employees/{emp_id}/fnf", headers=hr_headers)
    assert fnf_waived.status_code == 200
    assert fnf_waived.json()["notice_recovery_days"] == 0
    assert Decimal(str(fnf_waived.json()["notice_recovery_amount"])) == Decimal("0.00")
