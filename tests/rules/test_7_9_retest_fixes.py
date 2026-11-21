# ruff: noqa: F401, F811  (pytest fixtures imported from sibling test modules)
"""Fixes found during the retest review (21-Nov-2026).

BUG-088  a plain project member does not see the project budget
BUG-036  a plain employee does not see shift night allowance
"""

from fastapi.testclient import TestClient

from tests.rules.test_7_5_7_7_time_and_costs import (
    _auth_headers,
    _create_project_with_members,
    p3_setup,
)


def test_plain_member_does_not_see_project_budget(client: TestClient, p3_setup) -> None:
    proj_id, _ = _create_project_with_members(client, p3_setup)
    hr = _auth_headers(p3_setup["hr_u"])
    assert (
        client.put(f"/api/v1/projects/{proj_id}", json={"budget": "50000"}, headers=hr).status_code
        == 200
    )
    emp = _auth_headers(p3_setup["emp1_u"])
    assert client.get(f"/api/v1/projects/{proj_id}", headers=emp).json()["budget"] is None
    assert (
        client.get(f"/api/v1/projects/{proj_id}/summary", headers=emp).json()["project"]["budget"]
        is None
    )
    listed = client.get("/api/v1/projects", headers=emp).json()
    items = listed["items"] if isinstance(listed, dict) else listed
    assert all(p["budget"] is None for p in items if p["id"] == proj_id)
    assert float(client.get(f"/api/v1/projects/{proj_id}", headers=hr).json()["budget"]) == 50000.0


def test_employee_does_not_see_night_allowance(client: TestClient, company_a) -> None:
    created = client.post(
        "/api/v1/shifts",
        json={
            "name": "Night QA",
            "start_time": "22:00",
            "end_time": "06:00",
            "night_allowance": "250",
        },
        headers=company_a.hr_headers,
    )
    assert created.status_code == 201, created.text
    emp_items = client.get("/api/v1/shifts", headers=company_a.employee_headers).json()["items"]
    assert emp_items and all(s["night_allowance"] is None for s in emp_items)
    hr_items = client.get("/api/v1/shifts", headers=company_a.hr_headers).json()["items"]
    assert any(s["night_allowance"] is not None for s in hr_items)
