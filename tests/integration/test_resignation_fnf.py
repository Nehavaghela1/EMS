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

    # 1. Submit resignation
    res_sub = client.post(
        f"/api/v1/employees/{emp_id}/resignation",
        json={"resignation_date": "2026-09-01", "last_working_date": "2026-10-01", "reason": "Better opportunity"},
        headers=hr_headers,
    )
    assert res_sub.status_code == 200, res_sub.text
    assert res_sub.json()["resignation_status"] == "submitted"

    # 2. List resignations
    res_list = client.get("/api/v1/employees/resignations", headers=hr_headers)
    assert res_list.status_code == 200
    ids = [r["id"] for r in res_list.json()]
    assert emp_id in ids

    # 3. Approve resignation with notice recovery
    res_app = client.put(
        f"/api/v1/employees/{emp_id}/resignation/approve",
        json={"approved": True, "notice_waived": False, "notice_recovery_days": 10},
        headers=hr_headers,
    )
    assert res_app.status_code == 200
    assert res_app.json()["resignation_status"] == "approved"

    # 4. Calculate FnF Settlement
    res_fnf = client.get(f"/api/v1/employees/{emp_id}/fnf", headers=hr_headers)
    assert res_fnf.status_code == 200
    fnf_data = res_fnf.json()
    assert fnf_data["notice_recovery_days"] == 10
    assert Decimal(str(fnf_data["notice_recovery_amount"])) > 0
    assert "total_settlement_amount" in fnf_data
