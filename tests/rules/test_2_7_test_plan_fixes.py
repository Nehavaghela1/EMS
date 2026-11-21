# ruff: noqa: F401, F811  (pytest fixtures imported from a sibling test module)
"""Module 2 fixes for problems found by the end-to-end test plan (21-Nov-2026).

BUG-018  employee phone refuses letters
BUG-019  create refuses a probation end date before the hire date (edit already did)
BUG-023  HR cannot (bulk-)deactivate a company owner, even when the company has no
         owner_user_id recorded
BUG-024  a rejected resignation clears the last working date
BUG-097  an approved resignation cannot then be rejected (second decision gets 409)
"""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.core.time import utcnow
from tests.rules.test_2_6_exit import _auth_headers, exit_setup


def _new_employee_body(dept_id: str, **overrides: Any) -> dict[str, Any]:
    import uuid

    body = {
        "first_name": "Ravi",
        "email": f"ravi-{uuid.uuid4().hex[:8]}@example.com",
        "department_id": dept_id,
        "hire_date": str(utcnow().date()),
    }
    body.update(overrides)
    return body


def test_employee_phone_refuses_letters(client: TestClient, exit_setup, limits_off) -> None:
    hr = _auth_headers(exit_setup["hr_user"])
    dept = str(exit_setup["dept_gen"].id)
    for bad in ["abcdefg", "12ab34567"]:
        resp = client.post(
            "/api/v1/employees", headers=hr, json=_new_employee_body(dept, phone=bad)
        )
        assert resp.status_code == 422, bad
    ok = client.post(
        "/api/v1/employees", headers=hr, json=_new_employee_body(dept, phone="+91 98765 43210")
    )
    assert ok.status_code == 201, ok.text


def test_create_refuses_probation_before_hire(client: TestClient, exit_setup, limits_off) -> None:
    hr = _auth_headers(exit_setup["hr_user"])
    today = utcnow().date()
    body = _new_employee_body(
        str(exit_setup["dept_gen"].id),
        hire_date=str(today),
        probation_end_date=str(today - timedelta(days=30)),
    )
    resp = client.post("/api/v1/employees", headers=hr, json=body)
    assert resp.status_code == 422
    assert "Probation end date" in resp.text


def test_bulk_deactivate_skips_owner_without_recorded_owner_id(
    client: TestClient,
    exit_setup,
) -> None:
    hr = _auth_headers(exit_setup["hr_user"])
    owner_emp = exit_setup["owner_emp"]
    emp = exit_setup["emp"]
    resp = client.post(
        "/api/v1/employees/bulk/deactivate",
        headers=hr,
        json={"employee_ids": [str(owner_emp.id), str(emp.id)]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert str(owner_emp.id) not in [str(x) for x in data["succeeded"]]
    assert {"id": str(owner_emp.id), "reason": "is_company_owner"} in [
        {"id": str(s["id"]), "reason": s["reason"]} for s in data["skipped"]
    ]
    assert str(emp.id) in [str(x) for x in data["succeeded"]]


def test_single_deactivate_refuses_owner_without_recorded_owner_id(
    client: TestClient,
    exit_setup,
) -> None:
    hr = _auth_headers(exit_setup["hr_user"])
    owner_emp = exit_setup["owner_emp"]
    resp = client.delete(f"/api/v1/employees/{owner_emp.id}", headers=hr)
    assert resp.status_code == 409, resp.text


def _submit_resignation(client: TestClient, setup: dict[str, Any]) -> None:
    emp = setup["emp"]
    today = utcnow().date()
    resp = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=_auth_headers(setup["emp_user"]),
        json={
            "resignation_date": str(today),
            "last_working_date": str(today + timedelta(days=30)),
            "reason": "Higher studies",
        },
    )
    assert resp.status_code in (200, 201), resp.text


def test_rejected_resignation_clears_last_working_date(
    client: TestClient,
    exit_setup,
) -> None:
    _submit_resignation(client, exit_setup)
    emp = exit_setup["emp"]
    hr = _auth_headers(exit_setup["hr_user"])
    resp = client.put(
        f"/api/v1/employees/{emp.id}/resignation/approve", headers=hr, json={"approved": False}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["resignation_status"] == "rejected"
    assert resp.json()["last_working_date"] is None


def test_approved_resignation_cannot_then_be_rejected(
    client: TestClient,
    exit_setup,
) -> None:
    _submit_resignation(client, exit_setup)
    emp = exit_setup["emp"]
    hr = _auth_headers(exit_setup["hr_user"])
    url = f"/api/v1/employees/{emp.id}/resignation/approve"
    assert client.put(url, headers=hr, json={"approved": True}).status_code == 200
    second = client.put(url, headers=hr, json={"approved": False})
    assert second.status_code == 409, second.text
    # HR can still amend the approved resignation (approved=True).
    assert client.put(url, headers=hr, json={"approved": True}).status_code == 200
