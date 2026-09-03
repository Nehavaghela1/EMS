"""WP-09: check-in/check-out (409/400 gates, overnight hours calc, Spec
11.5), role-scoped list, HR regularization, delete.
"""

import uuid
from datetime import UTC, datetime, time, timedelta

from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.modules.identity.models import User, UserRole
from app.modules.time_leave.models import Attendance, AttendanceSource, AttendanceStatus


def _create_employee(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "Test",
        "email": f"{uuid.uuid4().hex[:10]}@attendanceco.com",
        "hire_date": "2024-01-15",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/employees", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _link_user_to_employee(db, company_id, employee_id: str, role: UserRole) -> dict[str, str]:
    from app.modules.hr.models import Employee

    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@attendanceco.com",
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


def test_check_in_creates_a_present_record_and_a_second_check_in_returns_409(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )

    first = client.post("/api/v1/attendance/check-in", headers=own_headers)
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "present"
    assert first.json()["check_in"]

    second = client.post("/api/v1/attendance/check-in", headers=own_headers)
    assert second.status_code == 409


def test_database_constraint_holds_even_if_the_application_check_is_bypassed(client, company_a, db):
    """Proves `uq_attendance_employee_id_date` is a real database constraint,
    not just an app-level check — insert around the service layer entirely."""
    employee = _create_employee(client, company_a.hr_headers)
    today = utcnow().date()

    db.add(
        Attendance(
            company_id=company_a.company_id,
            employee_id=uuid.UUID(employee["id"]),
            date=today,
            status=AttendanceStatus.present,
            source=AttendanceSource.web,
        )
    )
    db.flush()

    dup = Attendance(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(employee["id"]),
        date=today,
        status=AttendanceStatus.present,
        source=AttendanceSource.web,
    )
    db.add(dup)
    try:
        db.flush()
        raised = False
    except IntegrityError:
        raised = True
    assert raised, "the database did not enforce uq_attendance_employee_id_date"
    db.rollback()


def test_check_out_without_check_in_returns_400(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )

    resp = client.post("/api/v1/attendance/check-out", headers=own_headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "no_check_in"


def test_check_out_computes_hours_and_marks_half_day_below_threshold(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )

    client.post("/api/v1/attendance/check-in", headers=own_headers)

    # Backdate check_in so check-out (right now) produces a short, sub-
    # threshold duration deterministically, rather than depending on how
    # fast this test happens to run.
    from app.modules.hr.models import Employee

    emp_row = db.get(Employee, uuid.UUID(employee["id"]))
    record = (
        db.query(Attendance)
        .filter(Attendance.company_id == company_a.company_id, Attendance.employee_id == emp_row.id)
        .one()
    )
    record.check_in = utcnow() - timedelta(hours=2)
    db.flush()

    resp = client.post("/api/v1/attendance/check-out", headers=own_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "half_day"
    assert 1.9 <= float(body["hours_worked"]) <= 2.1


def test_hours_worked_is_positive_for_a_shift_crossing_midnight(client, company_a, db):
    """Spec 7.4/11.5: a shift whose end_time < start_time crosses midnight —
    hours_worked must be computed across the date boundary, positive, not
    negative. Employee is genuinely assigned to such a shift; check-in is
    backdated to yesterday night the same way a real overnight worker's
    would be, and check-out runs for real through the live endpoint.
    """
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )

    shift_resp = client.post(
        "/api/v1/shifts",
        headers=company_a.hr_headers,
        json={"name": "Night Shift", "start_time": "22:00:00", "end_time": "06:00:00"},
    )
    assert shift_resp.status_code == 201, shift_resp.text
    shift_id = shift_resp.json()["id"]
    assert shift_resp.json()["start_time"] > shift_resp.json()["end_time"]

    yesterday = utcnow().date() - timedelta(days=1)
    assign_resp = client.post(
        f"/api/v1/shifts/{shift_id}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": employee["id"], "effective_from": yesterday.isoformat()},
    )
    assert assign_resp.status_code == 201, assign_resp.text

    check_in_time = datetime.combine(yesterday, time(22, 0), tzinfo=UTC)
    from app.modules.hr.models import Employee

    emp_row = db.get(Employee, uuid.UUID(employee["id"]))
    db.add(
        Attendance(
            company_id=company_a.company_id,
            employee_id=emp_row.id,
            date=yesterday,
            check_in=check_in_time,
            status=AttendanceStatus.present,
            source=AttendanceSource.web,
        )
    )
    db.commit()

    # Pre-existing flaky bug, found while chasing an unrelated CI failure:
    # this used to assert hours_worked > 8 on the assumption that "now" is
    # always well after 06:00 the day after check-in. That's only true
    # roughly 3/4 of the time — a real test run between 00:00 and 06:00 UTC
    # (this one included, and CI's own failing run: both ~05:40-06:00 UTC)
    # has elapsed well under 8 hours since 22:00 "yesterday", so the
    # assertion itself was wrong, not the code under test. Comparing
    # against the actual elapsed wall-clock time removes the time-of-day
    # assumption entirely while still catching the real bug this guards
    # against: naive clock-time-only arithmetic (e.g. end_time - start_time
    # as plain `time` values) going negative across the boundary, which
    # this dynamic comparison would still catch just as reliably.
    before_checkout = utcnow()
    resp = client.post("/api/v1/attendance/check-out", headers=own_headers)
    assert resp.status_code == 200, resp.text
    hours_worked = float(resp.json()["hours_worked"])
    expected_hours = (before_checkout - check_in_time).total_seconds() / 3600
    assert hours_worked > 0, "hours_worked went negative across the midnight boundary"
    assert abs(hours_worked - expected_hours) < 0.1, (
        f"expected ~{expected_hours:.2f}h since check-in, got {hours_worked}h"
    )


def test_manager_sees_only_their_teams_attendance(client, company_a, db):
    manager_employee = _create_employee(client, company_a.hr_headers, email="mgr@attendanceco.com")
    manager_headers = _link_user_to_employee(
        db, company_a.company_id, manager_employee["id"], UserRole.manager
    )
    report = _create_employee(
        client,
        company_a.hr_headers,
        email="report@attendanceco.com",
        reporting_manager_id=manager_employee["id"],
    )
    outsider = _create_employee(client, company_a.hr_headers, email="outsider@attendanceco.com")

    report_headers = _link_user_to_employee(
        db, company_a.company_id, report["id"], UserRole.employee
    )
    outsider_headers = _link_user_to_employee(
        db, company_a.company_id, outsider["id"], UserRole.employee
    )
    client.post("/api/v1/attendance/check-in", headers=report_headers)
    client.post("/api/v1/attendance/check-in", headers=outsider_headers)

    resp = client.get("/api/v1/attendance", headers=manager_headers)
    assert resp.status_code == 200
    employee_ids = {row["employee_id"] for row in resp.json()["items"]}
    assert employee_ids == {report["id"]}

    hr_resp = client.get("/api/v1/attendance", headers=company_a.hr_headers)
    hr_ids = {row["employee_id"] for row in hr_resp.json()["items"]}
    assert {report["id"], outsider["id"]} <= hr_ids


def test_hr_regularization_updates_the_record_and_requires_a_reason(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    created = client.post("/api/v1/attendance/check-in", headers=own_headers).json()

    missing_reason = client.put(
        f"/api/v1/attendance/{created['id']}",
        headers=company_a.hr_headers,
        json={"status": "wfh"},
    )
    assert missing_reason.status_code == 422  # `reason` is a required field

    resp = client.put(
        f"/api/v1/attendance/{created['id']}",
        headers=company_a.hr_headers,
        json={
            "status": "wfh",
            "notes": "Worked from home, confirmed by manager",
            "reason": "Employee forgot to switch status",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "wfh"


def test_hr_delete_soft_deletes_the_record(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    created = client.post("/api/v1/attendance/check-in", headers=own_headers).json()

    delete_resp = client.delete(f"/api/v1/attendance/{created['id']}", headers=company_a.hr_headers)
    assert delete_resp.status_code == 204

    get_resp = client.get(f"/api/v1/attendance/{created['id']}", headers=company_a.hr_headers)
    assert get_resp.status_code == 404

    row = db.get(Attendance, uuid.UUID(created["id"]))
    assert row is not None
    assert row.deleted_at is not None
