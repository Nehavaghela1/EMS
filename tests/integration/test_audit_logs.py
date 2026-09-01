"""WP-11: audit logging wired into employee create/update/deactivate, leave
approve/reject, and attendance regularize/delete — plus route 128's filters
and the sensitive-field guard (Spec 7.8, CLAUDE.md rule 10).
"""

import uuid
from datetime import timedelta

from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole
from app.modules.platform.service import AuditService, UnsafeAuditDetailsError


def _create_employee(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "Test",
        "email": f"{uuid.uuid4().hex[:10]}@auditco.com",
        "hire_date": "2024-01-15",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/employees", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _link_user_to_employee(db, company_id, employee_id: str, role: UserRole) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@auditco.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    employee = db.get(Employee, uuid.UUID(employee_id))
    employee.user_id = user.id
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


def _create_leave_type(client, headers, **overrides) -> dict:
    payload = {
        "name": "Annual Leave",
        "code": f"annual-{uuid.uuid4().hex[:6]}",
        "annual_allowance": "20",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/leave-types", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _actions(resp) -> set[str]:
    assert resp.status_code == 200, resp.text
    return {row["action"] for row in resp.json()["items"]}


def test_employee_create_update_deactivate_each_write_an_audit_row(client, company_a):
    employee = _create_employee(client, company_a.hr_headers)

    update_resp = client.put(
        f"/api/v1/employees/{employee['id']}",
        headers=company_a.hr_headers,
        json={"position": "Senior Engineer"},
    )
    assert update_resp.status_code == 200, update_resp.text

    deactivate_resp = client.delete(
        f"/api/v1/employees/{employee['id']}", headers=company_a.hr_headers
    )
    assert deactivate_resp.status_code == 204

    listed = client.get("/api/v1/audit-logs?entity_type=employee", headers=company_a.hr_headers)
    actions = _actions(listed)
    assert {"EMPLOYEE_CREATED", "EMPLOYEE_UPDATED", "EMPLOYEE_DEACTIVATED"} <= actions

    updated_row = next(row for row in listed.json()["items"] if row["action"] == "EMPLOYEE_UPDATED")
    assert updated_row["entity_id"] == employee["id"]
    assert updated_row["details"]["position"]["to"] == "Senior Engineer"


def test_leave_approve_and_reject_each_write_an_audit_row(client, company_a, db):
    leave_type = _create_leave_type(client, company_a.hr_headers)
    employee = _create_employee(client, company_a.hr_headers)

    approved = client.post(
        "/api/v1/leaves",
        headers=company_a.hr_headers,
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "start_date": "2031-04-07",
            "end_date": "2031-04-07",
            "is_half_day": True,
            "reason": "Audit check",
        },
    ).json()
    decide_resp = client.put(
        f"/api/v1/leaves/{approved['id']}",
        headers=company_a.hr_headers,
        json={"status": "approved"},
    )
    assert decide_resp.status_code == 200, decide_resp.text

    rejected = client.post(
        "/api/v1/leaves",
        headers=company_a.hr_headers,
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "start_date": "2031-04-08",
            "end_date": "2031-04-08",
            "is_half_day": True,
            "reason": "Audit check 2",
        },
    ).json()
    reject_resp = client.put(
        f"/api/v1/leaves/{rejected['id']}",
        headers=company_a.hr_headers,
        json={"status": "rejected", "rejection_reason": "Not enough notice"},
    )
    assert reject_resp.status_code == 200, reject_resp.text

    listed = client.get("/api/v1/audit-logs?entity_type=leave", headers=company_a.hr_headers)
    actions = _actions(listed)
    assert {"LEAVE_APPROVED", "LEAVE_REJECTED"} <= actions


def test_attendance_regularize_and_delete_each_write_an_audit_row(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    created = client.post("/api/v1/attendance/check-in", headers=own_headers).json()

    regularize_resp = client.put(
        f"/api/v1/attendance/{created['id']}",
        headers=company_a.hr_headers,
        json={"status": "wfh", "reason": "Forgot to mark WFH"},
    )
    assert regularize_resp.status_code == 200, regularize_resp.text

    second = client.post(
        "/api/v1/employees",
        headers=company_a.hr_headers,
        json={
            "first_name": "Delete",
            "email": f"{uuid.uuid4().hex[:10]}@auditco.com",
            "hire_date": "2024-01-15",
        },
    ).json()
    second_headers = _link_user_to_employee(
        db, company_a.company_id, second["id"], UserRole.employee
    )
    second_attendance = client.post("/api/v1/attendance/check-in", headers=second_headers).json()
    delete_resp = client.delete(
        f"/api/v1/attendance/{second_attendance['id']}", headers=company_a.hr_headers
    )
    assert delete_resp.status_code == 204

    listed = client.get("/api/v1/audit-logs?entity_type=attendance", headers=company_a.hr_headers)
    actions = _actions(listed)
    assert {"ATTENDANCE_REGULARIZED", "ATTENDANCE_DELETED"} <= actions


def test_audit_log_filters_by_action_and_date_range(client, company_a):
    _create_employee(client, company_a.hr_headers)

    by_action = client.get(
        "/api/v1/audit-logs?action=EMPLOYEE_CREATED", headers=company_a.hr_headers
    )
    assert by_action.status_code == 200
    assert all(row["action"] == "EMPLOYEE_CREATED" for row in by_action.json()["items"])
    assert by_action.json()["total"] >= 1

    # Created "today" (per utcnow()), so a date_from of tomorrow excludes it —
    # proves the filter is actually applied, not ignored.
    strictly_future = (utcnow().date() + timedelta(days=1)).isoformat()
    excluded = client.get(
        f"/api/v1/audit-logs?date_from={strictly_future}", headers=company_a.hr_headers
    )
    assert excluded.status_code == 200
    assert excluded.json()["total"] == 0


def test_only_hr_may_read_or_export_audit_logs(client, company_a):
    employee_resp = client.get("/api/v1/audit-logs", headers=company_a.employee_headers)
    assert employee_resp.status_code == 403

    manager_resp = client.get("/api/v1/audit-logs", headers=company_a.manager_headers)
    assert manager_resp.status_code == 403

    export_resp = client.post(
        "/api/v1/audit-logs/export", headers=company_a.employee_headers, json={}
    )
    assert export_resp.status_code == 403


def test_export_returns_202_and_a_pollable_job_id(client, company_a):
    _create_employee(client, company_a.hr_headers)
    resp = client.post("/api/v1/audit-logs/export", headers=company_a.hr_headers, json={})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["job_id"]

    job_resp = client.get(f"/api/v1/jobs/{body['job_id']}", headers=company_a.hr_headers)
    assert job_resp.status_code == 200
    assert job_resp.json()["status"] in {"queued", "started", "success", "failure"}


def test_audit_service_refuses_a_banned_detail_field(db):
    audit = AuditService(db)
    try:
        audit.record(
            company_id=None,
            actor=None,
            action="TEST_ACTION",
            details={"password": "hunter2"},
        )
        raised = False
    except UnsafeAuditDetailsError:
        raised = True
    assert raised, "AuditService.record must refuse a banned field, not silently store it"

    # A nested dict must be checked too — a caller could bury the sensitive
    # field one level down without meaning to.
    try:
        audit.record(
            company_id=None,
            actor=None,
            action="TEST_ACTION",
            details={"employee": {"bank_account": "1234567890"}},
        )
        raised = False
    except UnsafeAuditDetailsError:
        raised = True
    assert raised
