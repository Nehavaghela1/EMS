"""Hardening pass (post-WP-15): deliberate attempts to break tenant
isolation, role-based access, and the append-only audit trail, run from
the outside via `client` — the same surface a real attacker has. Each
test here either confirms an existing control holds, or is the permanent
regression test for something that didn't and was fixed in this pass.

Not a re-run of tests/isolation/ (that suite already proves RLS itself,
table by table) — this targets the layer RLS does NOT cover: server-side
scoping that lives in a service, not a database policy, and any id a
client supplies that a service must re-scope rather than trust.
"""

import uuid
from datetime import date, timedelta

from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.modules.identity.models import User, UserRole
from app.workers.celery_app import celery_app


def _create_employee(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "Test",
        "email": f"{uuid.uuid4().hex[:10]}@attackco.com",
        "hire_date": "2024-01-15",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/employees", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _link_user_to_employee(db, company_id, employee_id: str, role: UserRole) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@attackco.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    from app.modules.hr.models import Employee

    employee = db.get(Employee, uuid.UUID(employee_id))
    employee.user_id = user.id
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


# --- A manager reaching an employee who is not their report -----------------
# (already covered for list_employees, list_attendance, apply/decide leave in
# tests/integration/{test_employees,test_attendance,test_leaves}.py — these
# fill the individual-record-by-id gap, where RLS alone cannot help: the
# record legitimately belongs to the manager's own company.)


def test_manager_cannot_get_a_single_leave_that_is_not_their_reports(client, company_a, db):
    manager = _create_employee(client, company_a.hr_headers, first_name="Mgr")
    manager_headers = _link_user_to_employee(
        db, company_a.company_id, manager["id"], UserRole.manager
    )
    outsider = _create_employee(client, company_a.hr_headers, first_name="Outsider")
    outsider_headers = _link_user_to_employee(
        db, company_a.company_id, outsider["id"], UserRole.employee
    )
    leave_type = client.post(
        "/api/v1/leave-types",
        headers=company_a.hr_headers,
        json={"name": "Casual", "code": "casual", "annual_allowance": "10"},
    ).json()
    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    leave = client.post(
        "/api/v1/leaves",
        headers=outsider_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": tomorrow,
            "end_date": tomorrow,
            "reason": "Personal",
        },
    ).json()

    resp = client.get(f"/api/v1/leaves/{leave['id']}", headers=manager_headers)
    assert resp.status_code == 403

    # HR can still see it — this isn't a general outage.
    assert (
        client.get(f"/api/v1/leaves/{leave['id']}", headers=company_a.hr_headers).status_code == 200
    )


def test_manager_cannot_get_a_single_attendance_record_that_is_not_their_reports(
    client, company_a, db
):
    manager = _create_employee(client, company_a.hr_headers, first_name="Mgr2")
    manager_headers = _link_user_to_employee(
        db, company_a.company_id, manager["id"], UserRole.manager
    )
    outsider = _create_employee(client, company_a.hr_headers, first_name="Outsider2")
    outsider_headers = _link_user_to_employee(
        db, company_a.company_id, outsider["id"], UserRole.employee
    )
    checked_in = client.post("/api/v1/attendance/check-in", headers=outsider_headers)
    assert checked_in.status_code == 201
    record_id = checked_in.json()["id"]

    resp = client.get(f"/api/v1/attendance/{record_id}", headers=manager_headers)
    assert resp.status_code == 403


def test_manager_cannot_view_a_reports_leave_balance(client, company_a, db):
    """Route 66 is documented Own/HR only — no manager exception, unlike
    every other view route in this module. Confirms the router doesn't
    accidentally admit manager the way list/get routes do."""
    manager = _create_employee(client, company_a.hr_headers, first_name="Mgr3")
    manager_headers = _link_user_to_employee(
        db, company_a.company_id, manager["id"], UserRole.manager
    )
    report = _create_employee(
        client, company_a.hr_headers, first_name="Report3", reporting_manager_id=manager["id"]
    )

    resp = client.get(f"/api/v1/leaves/balance/{report['id']}", headers=manager_headers)
    assert resp.status_code == 403


def test_employee_cannot_view_a_coworkers_leave_balance(client, company_a, db):
    a = _create_employee(client, company_a.hr_headers, first_name="Alpha")
    a_headers = _link_user_to_employee(db, company_a.company_id, a["id"], UserRole.employee)
    b = _create_employee(client, company_a.hr_headers, first_name="Beta")

    resp = client.get(f"/api/v1/leaves/balance/{b['id']}", headers=a_headers)
    assert resp.status_code == 403


# --- An id inside a request body, trusted without re-scoping -----------------


def test_shift_assignment_rejects_an_employee_id_from_another_company(client, company_a, company_b):
    shift = client.post(
        "/api/v1/shifts",
        headers=company_a.hr_headers,
        json={"name": "Day", "start_time": "09:00:00", "end_time": "18:00:00"},
    ).json()
    other_company_employee = _create_employee(client, company_b.hr_headers, first_name="Foreign")

    resp = client.post(
        f"/api/v1/shifts/{shift['id']}/assign",
        headers=company_a.hr_headers,
        json={
            "employee_id": other_company_employee["id"],
            "effective_from": date.today().isoformat(),
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_reference"


def test_leave_application_rejects_an_employee_id_from_another_company(
    client, company_a, company_b
):
    leave_type = client.post(
        "/api/v1/leave-types",
        headers=company_a.hr_headers,
        json={"name": "Sick", "code": "sick", "annual_allowance": "10"},
    ).json()
    other_company_employee = _create_employee(client, company_b.hr_headers, first_name="Foreign2")
    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()

    resp = client.post(
        "/api/v1/leaves",
        headers=company_a.hr_headers,
        json={
            "employee_id": other_company_employee["id"],
            "leave_type_id": leave_type["id"],
            "start_date": tomorrow,
            "end_date": tomorrow,
            "reason": "Should not cross tenants",
        },
    )
    # Employee lookup is scoped by company_id (get_by_id), so a foreign id
    # simply doesn't exist in this tenant's view — 404, not a leak, not a 500.
    assert resp.status_code == 404


def test_department_update_rejects_a_head_employee_id_from_another_company(
    client, company_a, company_b
):
    dept = client.post(
        "/api/v1/departments", headers=company_a.hr_headers, json={"name": "Ops"}
    ).json()
    other_company_employee = _create_employee(client, company_b.hr_headers, first_name="Foreign3")

    resp = client.put(
        f"/api/v1/departments/{dept['id']}",
        headers=company_a.hr_headers,
        json={"head_employee_id": other_company_employee["id"]},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_reference"


def test_create_employee_rejects_a_reporting_manager_id_from_another_company(
    client, company_a, company_b
):
    other_company_employee = _create_employee(client, company_b.hr_headers, first_name="Foreign4")

    resp = client.post(
        "/api/v1/employees",
        headers=company_a.hr_headers,
        json={
            "first_name": "New",
            "email": "new@attackco.com",
            "hire_date": "2024-01-01",
            "reporting_manager_id": other_company_employee["id"],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_reference"


# --- A query filter used to reach another company's rows ---------------------


def test_attendance_list_filter_by_a_foreign_employee_id_returns_empty_not_an_error(
    client, company_a, company_b
):
    other_company_employee = _create_employee(client, company_b.hr_headers, first_name="Foreign5")

    resp = client.get(
        f"/api/v1/attendance?employee_id={other_company_employee['id']}",
        headers=company_a.hr_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# --- A background-job id, trusted without checking who queued it -------------


def test_job_status_is_scoped_to_the_company_that_queued_it(client, company_a, company_b):
    """Hardening pass: GET /jobs/{job_id} had zero ownership check at all —
    any authenticated user of any company who obtained or guessed another
    company's export job_id got that company's row_count and server file
    path back. Celery job ids are high-entropy UUIDs, so this was never
    practically guessable, but it was still a real, fixable authorization
    gap — the exact "an id a client supplies that a service trusts without
    re-scoping" pattern, just on a Celery result instead of a database row.
    Fixed by having export tasks return their own company_id and having the
    router check it against the caller's, matching Spec 10.1 (404, not 403).
    """
    job_id = str(uuid.uuid4())
    celery_app.backend.store_result(
        job_id,
        {
            "company_id": str(company_a.company_id),
            "file_path": "/tmp/whatever.csv",
            "row_count": 42,
        },
        "SUCCESS",
    )
    try:
        owner_resp = client.get(f"/api/v1/jobs/{job_id}", headers=company_a.hr_headers)
        assert owner_resp.status_code == 200
        assert owner_resp.json()["result"]["row_count"] == 42

        other_resp = client.get(f"/api/v1/jobs/{job_id}", headers=company_b.hr_headers)
        assert other_resp.status_code == 404

        admin_resp = client.get(f"/api/v1/jobs/{job_id}", headers=company_a.employee_headers)
        # Same company, lower role: the job route has no role check by
        # design (any authenticated caller can poll a job they can prove
        # they know the id of) — company scoping is the actual boundary.
        assert admin_resp.status_code == 200
    finally:
        celery_app.backend.forget(job_id)


def test_super_admin_bypasses_job_company_scoping(client, company_a, super_admin_headers):
    job_id = str(uuid.uuid4())
    celery_app.backend.store_result(
        job_id,
        {"company_id": str(company_a.company_id), "file_path": "/tmp/whatever.csv", "row_count": 7},
        "SUCCESS",
    )
    try:
        resp = client.get(f"/api/v1/jobs/{job_id}", headers=super_admin_headers)
        assert resp.status_code == 200
    finally:
        celery_app.backend.forget(job_id)


# --- An employee reaching an HR-only route ------------------------------------


def test_employee_cannot_create_a_department(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers, first_name="Plain")
    employee_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    resp = client.post(
        "/api/v1/departments", headers=employee_headers, json={"name": "Should Not Exist"}
    )
    assert resp.status_code == 403


def test_employee_cannot_list_the_company_employee_directory(client, company_a):
    """require_role(hr_admin, manager) on the router — a plain employee
    gets 403 before EmployeeService.list_employees ever runs."""
    resp = client.get("/api/v1/employees", headers=company_a.employee_headers)
    assert resp.status_code == 403


def test_employee_cannot_regularize_attendance(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers, first_name="Regularize")
    employee_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    checked_in = client.post("/api/v1/attendance/check-in", headers=employee_headers)
    record_id = checked_in.json()["id"]

    resp = client.put(
        f"/api/v1/attendance/{record_id}",
        headers=employee_headers,
        json={"status": "present", "reason": "self-service correction attempt"},
    )
    assert resp.status_code == 403
