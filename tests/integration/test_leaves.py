"""WP-10: all eight application validations from Spec 11.3, in order, each
triggered directly; total_days excluding weekends and holidays; approval
upserting attendance for exactly the working days covered; cancellation
reversing both attendance and balance.
"""

import uuid
from datetime import timedelta

from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole
from app.modules.time_leave.models import Attendance


def _create_employee(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "Test",
        "email": f"{uuid.uuid4().hex[:10]}@leaveco.com",
        "hire_date": "2024-01-15",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/employees", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _link_user_to_employee(db, company_id, employee_id: str, role: UserRole) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@leaveco.com",
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


def _next_weekday(iso_weekday: int, start_offset: int = 1):
    d = utcnow().date() + timedelta(days=start_offset)
    while d.isoweekday() != iso_weekday:
        d += timedelta(days=1)
    return d


def _next_friday_through_monday():
    friday = _next_weekday(5)
    return friday, friday + timedelta(days=3)


def _next_monday_through_friday():
    monday = _next_weekday(1)
    return monday, monday + timedelta(days=4)


# --- The eight validations, in order (Spec 11.3) ---------------------------


def test_validation_1_employee_must_exist_in_this_company(client, company_a):
    resp = client.post(
        "/api/v1/leaves",
        headers=company_a.hr_headers,
        json={
            "employee_id": str(uuid.uuid4()),
            "leave_type_id": str(uuid.uuid4()),
            "start_date": "2030-01-07",
            "end_date": "2030-01-08",
            "reason": "Test",
        },
    )
    assert resp.status_code == 404


def test_validation_2_caller_must_be_self_hr_or_manager(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    leave_type = _create_leave_type(client, company_a.hr_headers)
    other = _create_employee(client, company_a.hr_headers, email="other@leaveco.com")
    other_headers = _link_user_to_employee(db, company_a.company_id, other["id"], UserRole.employee)

    monday, friday = _next_monday_through_friday()
    resp = client.post(
        "/api/v1/leaves",
        headers=other_headers,
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "Not mine to apply for",
        },
    )
    assert resp.status_code == 403


def test_validation_3_end_date_must_not_be_before_start_date(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave_type = _create_leave_type(client, company_a.hr_headers)

    resp = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": "2030-01-10",
            "end_date": "2030-01-05",
            "reason": "Backwards range",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_leave_request"


def test_validation_4_leave_type_must_exist_in_this_company(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    monday, friday = _next_monday_through_friday()

    resp = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": str(uuid.uuid4()),
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "Unknown leave type",
        },
    )
    assert resp.status_code == 404


def test_validation_5_start_date_must_not_be_in_the_past_unless_hr(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave_type = _create_leave_type(client, company_a.hr_headers)
    past = (utcnow().date() - timedelta(days=5)).isoformat()

    employee_resp = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": past,
            "end_date": past,
            "is_half_day": True,
            "reason": "Backdated by the employee",
        },
    )
    assert employee_resp.status_code == 400
    assert employee_resp.json()["error"]["details"]["field"] == "start_date"

    hr_resp = client.post(
        "/api/v1/leaves",
        headers=company_a.hr_headers,
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "start_date": past,
            "end_date": past,
            "is_half_day": True,
            "reason": "Backdated by HR, audited",
        },
    )
    assert hr_resp.status_code == 201


def test_validation_6_max_consecutive_days_not_exceeded(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave_type = _create_leave_type(
        client,
        company_a.hr_headers,
        name="Short Leave",
        max_consecutive_days=3,
        annual_allowance="30",
    )
    monday, friday = _next_monday_through_friday()  # 5 consecutive weekdays

    resp = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "Too long",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_leave_request"


def test_validation_7_overlapping_leave_returns_409_naming_conflicting_dates(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave_type = _create_leave_type(client, company_a.hr_headers, annual_allowance="30")
    monday, friday = _next_monday_through_friday()

    first = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "First application",
        },
    )
    assert first.status_code == 201, first.text

    overlap_start = monday + timedelta(days=2)
    overlap_end = friday + timedelta(days=2)
    second = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": overlap_start.isoformat(),
            "end_date": overlap_end.isoformat(),
            "reason": "Overlapping application",
        },
    )
    assert second.status_code == 409
    conflicts = second.json()["error"]["details"]["conflicts"]
    assert conflicts[0]["start_date"] == monday.isoformat()
    assert conflicts[0]["end_date"] == friday.isoformat()


def test_validation_8_insufficient_balance_is_rejected_but_unpaid_leave_is_never_blocked(
    client, company_a, db
):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    monday, friday = _next_monday_through_friday()  # 5 working days requested

    small_paid = _create_leave_type(
        client, company_a.hr_headers, name="Tiny Leave", annual_allowance="2"
    )
    paid_resp = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": small_paid["id"],
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "More than the balance allows",
        },
    )
    assert paid_resp.status_code == 400
    assert paid_resp.json()["error"]["code"] == "insufficient_leave_balance"

    unpaid = _create_leave_type(
        client, company_a.hr_headers, name="Unpaid Leave", annual_allowance="0", is_paid=False
    )
    unpaid_resp = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": unpaid["id"],
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "Unpaid, always allowed regardless of balance",
        },
    )
    assert unpaid_resp.status_code == 201


# --- total_days, holidays, approval and cancellation ------------------------


def test_total_days_excludes_weekends(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave_type = _create_leave_type(client, company_a.hr_headers, annual_allowance="30")
    friday, monday = _next_friday_through_monday()  # Fri, Sat, Sun, Mon = 4 calendar days

    resp = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": friday.isoformat(),
            "end_date": monday.isoformat(),
            "reason": "Spans a weekend",
        },
    )
    assert resp.status_code == 201, resp.text
    assert float(resp.json()["total_days"]) == 2.0


def test_leave_spanning_a_company_holiday_counts_one_day_fewer(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave_type = _create_leave_type(client, company_a.hr_headers, annual_allowance="30")
    monday, friday = _next_monday_through_friday()  # 5 working days

    wednesday = monday + timedelta(days=2)
    holiday_resp = client.post(
        "/api/v1/holidays",
        headers=company_a.hr_headers,
        json={"name": "Company Holiday", "date": wednesday.isoformat()},
    )
    assert holiday_resp.status_code == 201, holiday_resp.text

    resp = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "Spans a holiday",
        },
    )
    assert resp.status_code == 201, resp.text
    assert float(resp.json()["total_days"]) == 4.0  # 5 weekdays minus the one holiday


def test_approving_a_leave_creates_on_leave_attendance_for_exactly_the_working_days(
    client, company_a, db
):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave_type = _create_leave_type(client, company_a.hr_headers, annual_allowance="30")
    friday, monday = _next_friday_through_monday()

    apply_resp = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": friday.isoformat(),
            "end_date": monday.isoformat(),
            "reason": "Approve me",
        },
    )
    leave_id = apply_resp.json()["id"]

    approve_resp = client.put(
        f"/api/v1/leaves/{leave_id}", headers=company_a.hr_headers, json={"status": "approved"}
    )
    assert approve_resp.status_code == 200, approve_resp.text

    emp_row = db.get(Employee, uuid.UUID(employee["id"]))
    saturday = friday + timedelta(days=1)
    sunday = friday + timedelta(days=2)
    for covered_date in (friday, monday):
        row = (
            db.query(Attendance)
            .filter(Attendance.employee_id == emp_row.id, Attendance.date == covered_date)
            .one()
        )
        assert row.status.value == "on_leave"
        assert row.source.value == "system"
    for weekend_date in (saturday, sunday):
        row = (
            db.query(Attendance)
            .filter(Attendance.employee_id == emp_row.id, Attendance.date == weekend_date)
            .one_or_none()
        )
        assert row is None, "a weekend day should not get an attendance row from leave approval"


def test_cancelling_an_approved_leave_reverses_attendance_and_restores_balance(
    client, company_a, db
):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave_type = _create_leave_type(client, company_a.hr_headers, annual_allowance="10")
    monday, friday = _next_monday_through_friday()

    apply_resp = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "Approve then cancel",
        },
    )
    leave_id = apply_resp.json()["id"]
    client.put(
        f"/api/v1/leaves/{leave_id}", headers=company_a.hr_headers, json={"status": "approved"}
    )

    year = monday.year if monday.month >= 4 else monday.year - 1
    mid_balance = client.get(
        f"/api/v1/leaves/balance/{employee['id']}?year={year}", headers=company_a.hr_headers
    ).json()
    used_after_approval = next(
        b["used"] for b in mid_balance if b["leave_type_id"] == leave_type["id"]
    )
    assert float(used_after_approval) == 5.0

    cancel_resp = client.delete(f"/api/v1/leaves/{leave_id}", headers=company_a.hr_headers)
    assert cancel_resp.status_code == 200, cancel_resp.text
    assert cancel_resp.json()["status"] == "cancelled"

    emp_row = db.get(Employee, uuid.UUID(employee["id"]))
    for covered_date in (monday, friday):
        row = (
            db.query(Attendance)
            .filter(Attendance.employee_id == emp_row.id, Attendance.date == covered_date)
            .one()
        )
        assert row.deleted_at is not None

    final_balance = client.get(
        f"/api/v1/leaves/balance/{employee['id']}?year={year}", headers=company_a.hr_headers
    ).json()
    used_after_cancel = next(
        b["used"] for b in final_balance if b["leave_type_id"] == leave_type["id"]
    )
    assert float(used_after_cancel) == 0.0


def test_employee_can_cancel_their_own_pending_leave_but_not_an_approved_one(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave_type = _create_leave_type(client, company_a.hr_headers, annual_allowance="10")
    monday, friday = _next_monday_through_friday()

    pending = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "Cancel while pending",
        },
    ).json()
    cancel_resp = client.delete(f"/api/v1/leaves/{pending['id']}", headers=own_headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    another_start = friday + timedelta(days=7)
    approved = client.post(
        "/api/v1/leaves",
        headers=own_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": another_start.isoformat(),
            "end_date": another_start.isoformat(),
            "is_half_day": True,
            "reason": "Approve then try to self-cancel",
        },
    ).json()
    client.put(
        f"/api/v1/leaves/{approved['id']}",
        headers=company_a.hr_headers,
        json={"status": "approved"},
    )
    forbidden_resp = client.delete(f"/api/v1/leaves/{approved['id']}", headers=own_headers)
    assert forbidden_resp.status_code == 403


def test_manager_can_approve_their_reports_leave_but_not_an_unrelated_employees(
    client, company_a, db, email_outbox
):
    manager_employee = _create_employee(client, company_a.hr_headers, email="mgr@leaveco.com")
    manager_headers = _link_user_to_employee(
        db, company_a.company_id, manager_employee["id"], UserRole.manager
    )
    report = _create_employee(
        client,
        company_a.hr_headers,
        email="report@leaveco.com",
        reporting_manager_id=manager_employee["id"],
    )
    outsider = _create_employee(client, company_a.hr_headers, email="outsider@leaveco.com")
    report_headers = _link_user_to_employee(
        db, company_a.company_id, report["id"], UserRole.employee
    )
    outsider_headers = _link_user_to_employee(
        db, company_a.company_id, outsider["id"], UserRole.employee
    )
    leave_type = _create_leave_type(client, company_a.hr_headers, annual_allowance="10")
    monday, friday = _next_monday_through_friday()

    report_leave = client.post(
        "/api/v1/leaves",
        headers=report_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "My report",
        },
    ).json()
    other_start = friday + timedelta(days=7)
    outsider_leave = client.post(
        "/api/v1/leaves",
        headers=outsider_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": other_start.isoformat(),
            "end_date": other_start.isoformat(),
            "is_half_day": True,
            "reason": "Not my report",
        },
    ).json()

    approve_own_report = client.put(
        f"/api/v1/leaves/{report_leave['id']}", headers=manager_headers, json={"status": "approved"}
    )
    assert approve_own_report.status_code == 200

    # Part 1: matches WP-11's in-app notification, now also by email.
    approved_emails = [
        e for e in email_outbox if e["to"] == "report@leaveco.com" and "approved" in e["subject"]
    ]
    assert approved_emails

    approve_outsider = client.put(
        f"/api/v1/leaves/{outsider_leave['id']}",
        headers=manager_headers,
        json={"status": "approved"},
    )
    assert approve_outsider.status_code == 403


def test_hr_rejecting_a_leave_requires_a_reason_and_sends_an_email(
    client, company_a, db, email_outbox
):
    employee = _create_employee(client, company_a.hr_headers, email="rejectee@leaveco.com")
    employee_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave_type = _create_leave_type(client, company_a.hr_headers, annual_allowance="10")
    monday, friday = _next_monday_through_friday()

    leave = client.post(
        "/api/v1/leaves",
        headers=employee_headers,
        json={
            "leave_type_id": leave_type["id"],
            "start_date": monday.isoformat(),
            "end_date": friday.isoformat(),
            "reason": "Vacation",
        },
    ).json()

    missing_reason = client.put(
        f"/api/v1/leaves/{leave['id']}", headers=company_a.hr_headers, json={"status": "rejected"}
    )
    assert missing_reason.status_code == 400
    assert missing_reason.json()["error"]["details"]["field"] == "rejection_reason"

    rejected = client.put(
        f"/api/v1/leaves/{leave['id']}",
        headers=company_a.hr_headers,
        json={"status": "rejected", "rejection_reason": "Team is short-staffed that week"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    rejected_emails = [
        e for e in email_outbox if e["to"] == "rejectee@leaveco.com" and "rejected" in e["subject"]
    ]
    assert rejected_emails
    assert "Team is short-staffed" in rejected_emails[-1]["text_body"]
