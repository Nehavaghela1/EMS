# ruff: noqa: F401, F811  (pytest fixtures imported from sibling test modules)
"""Module 7 fixes for problems found by the end-to-end test plan (21-Nov-2026).

BUG-074  a 12+ digit budget is a 422, not a server error
BUG-075  a body company_id naming another company is refused (company_id comes from the token)
BUG-076  huge estimated hours are a 422
BUG-077  a document without name or file id is a 422
BUG-078  a manager cannot set a member's hourly rate through add-member
BUG-079  an employee cannot mark their own time as overtime
BUG-080  a document cannot link another company's file
BUG-081  a duplicate project name, in any letter case, is a 409
BUG-082  hours with more than 2 decimals are refused, not rounded
BUG-100  concurrent-style reorders never leave two cards on one position
"""

import uuid

from fastapi.testclient import TestClient

from app.core.time import utcnow
from tests.rules.test_7_1_7_4_projects_and_members import _auth_headers, p1_setup
from tests.rules.test_7_5_7_7_time_and_costs import (
    _auth_headers as tc_headers,
)
from tests.rules.test_7_5_7_7_time_and_costs import (
    _create_project_with_members,
    p3_setup,
)

PROJECTS = "/api/v1/projects"


def _new(client, headers, **over):
    sfx = uuid.uuid4().hex[:5].upper()
    body = {"name": f"Proj {sfx}", "code": f"P-{sfx}"}
    body.update(over)
    return client.post(PROJECTS, json=body, headers=headers)


def test_budget_over_column_size_is_422(client: TestClient, p1_setup) -> None:
    hr = _auth_headers(p1_setup["hr_u"])
    assert _new(client, hr, budget="999999999999").status_code == 422
    assert _new(client, hr, budget="12.345").status_code == 422
    assert _new(client, hr, budget="9999999999.99").status_code == 201


def test_body_company_id_of_another_company_is_refused(client: TestClient, p1_setup) -> None:
    hr = _auth_headers(p1_setup["hr_u"])
    resp = _new(client, hr, company_id=str(p1_setup["cid_b"]))
    assert resp.status_code == 422, resp.text


def test_duplicate_project_name_any_case_is_409(client: TestClient, p1_setup) -> None:
    hr = _auth_headers(p1_setup["hr_u"])
    assert _new(client, hr, name="Website Revamp").status_code == 201
    assert _new(client, hr, name="Website Revamp").status_code == 409
    assert _new(client, hr, name="website REVAMP").status_code == 409


def test_huge_estimated_hours_is_422(client: TestClient, p3_setup) -> None:
    proj_id, _task = _create_project_with_members(client, p3_setup)
    resp = client.post(
        f"{PROJECTS}/{proj_id}/tasks",
        json={"title": "Big", "estimated_hours": "99999999999999"},
        headers=tc_headers(p3_setup["pm_u"]),
    )
    assert resp.status_code == 422, resp.text


def test_document_without_name_or_file_is_422(client: TestClient, p3_setup) -> None:
    proj_id, _task = _create_project_with_members(client, p3_setup)
    hr = tc_headers(p3_setup["hr_u"])
    url = f"{PROJECTS}/{proj_id}/documents"
    assert client.post(url, json={"name": "Spec"}, headers=hr).status_code == 422
    assert client.post(url, json={"file_id": str(uuid.uuid4())}, headers=hr).status_code == 422


def test_document_cannot_link_unknown_or_foreign_file(client: TestClient, p3_setup) -> None:
    proj_id, _task = _create_project_with_members(client, p3_setup)
    hr = tc_headers(p3_setup["hr_u"])
    resp = client.post(
        f"{PROJECTS}/{proj_id}/documents",
        json={"file_id": str(uuid.uuid4()), "name": "Spec"},
        headers=hr,
    )
    assert resp.status_code == 404, resp.text


def test_manager_cannot_set_rate_through_add_member(client: TestClient, p3_setup) -> None:
    proj_id, _task = _create_project_with_members(client, p3_setup)
    resp = client.post(
        f"{PROJECTS}/{proj_id}/members",
        json={"employee_id": str(p3_setup["emp2_e"].id), "role": "member", "hourly_rate": "900"},
        headers=tc_headers(p3_setup["pm_u"]),
    )
    assert resp.status_code in (403, 409), resp.text
    if resp.status_code == 409:  # emp2 already a member: check the rate rule with a new person
        resp = client.post(
            f"{PROJECTS}/{proj_id}/members",
            json={
                "employee_id": str(p3_setup["non_member_emp_e"].id),
                "role": "member",
                "hourly_rate": "900",
            },
            headers=tc_headers(p3_setup["pm_u"]),
        )
        assert resp.status_code == 403, resp.text


def test_employee_cannot_log_own_overtime(client: TestClient, p3_setup) -> None:
    proj_id, task_id = _create_project_with_members(client, p3_setup)
    body = {
        "project_id": proj_id,
        "task_id": task_id,
        "date": utcnow().date().isoformat(),
        "hours": "2.00",
        "description": "Work",
    }
    emp = tc_headers(p3_setup["emp1_u"])
    url = f"{PROJECTS}/time-entries"
    assert (
        client.post(
            url, json={**body, "is_overtime": True, "overtime_multiplier": "5"}, headers=emp
        ).status_code
        == 422
    )
    assert client.post(url, json={**body, "is_overtime": True}, headers=emp).status_code == 403
    assert client.post(url, json={**body, "hours": "1.255"}, headers=emp).status_code == 422
    assert client.post(url, json=body, headers=emp).status_code == 201


def test_reorder_keeps_positions_unique(client: TestClient, p3_setup) -> None:
    proj_id, first = _create_project_with_members(client, p3_setup)
    pm = tc_headers(p3_setup["pm_u"])
    ids = [first]
    for i in range(3):
        r = client.post(
            f"{PROJECTS}/{proj_id}/tasks", json={"title": f"T{i}", "status": "todo"}, headers=pm
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    # Every card asks for the same slot, as racing clients would.
    for tid in ids:
        assert (
            client.put(
                f"{PROJECTS}/tasks/{tid}/reorder", json={"position": 2}, headers=pm
            ).status_code
            == 200
        )
    tasks = client.get(f"{PROJECTS}/{proj_id}/tasks", headers=pm).json()
    items = tasks["items"] if isinstance(tasks, dict) else tasks
    positions = sorted(t["position"] for t in items if t["id"] in ids)
    assert positions == [0, 1, 2, 3]
