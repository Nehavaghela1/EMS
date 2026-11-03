"""Module 4, sub-feature 4.4: Monthly attendance calendar. One test per rule line (R1..R10).

Dates are computed from utcnow().
"""

import calendar as py_calendar
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import Department, Employee
from app.modules.identity.models import CompanySettings, User, UserRole
from app.modules.time_leave.models import Attendance, AttendanceStatus, Holiday, Leave, LeaveStatus, LeaveType
from tests.conftest import TenantContext, _make_user_headers

CALENDAR = "/api/v1/attendance/calendar"


def _create_employee(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload = {
        "first_name": "Test",
        "last_name": "Employee",
        "email": f"{uuid.uuid4().hex[:10]}@calco.com",
        "hire_date": "2024-01-15",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/employees", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _link_user_to_employee(
    db: Session, company_id: uuid.UUID, employee_id: str, role: UserRole
) -> tuple[dict[str, str], User]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@calco.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    employee = db.get(Employee, uuid.UUID(employee_id))
    assert employee is not None
    employee.user_id = user.id
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}, user


# --- Rule 4.4.1: Login needed, scoping, manager asking for own id works ---


def test_R1_calendar_scoping_and_manager_own_id(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
) -> None:
    now = utcnow()
    m = now.month
    y = now.year

    # 1. Unauthenticated -> 401
    res_no_auth = client.get(f"{CALENDAR}?month={m}&year={y}")
    assert res_no_auth.status_code == 401, "R1: Unauthenticated calendar request must return 401"

    # Manager M, Report R, Other O
    emp_m = _create_employee(client, company_a.hr_headers)
    m_headers, _ = _link_user_to_employee(db, company_a.company_id, emp_m["id"], UserRole.manager)

    emp_r = _create_employee(client, company_a.hr_headers, reporting_manager_id=emp_m["id"])
    r_headers, _ = _link_user_to_employee(db, company_a.company_id, emp_r["id"], UserRole.employee)

    emp_o = _create_employee(client, company_a.hr_headers)
    o_headers, _ = _link_user_to_employee(db, company_a.company_id, emp_o["id"], UserRole.employee)

    # 2. Employee sees own calendar (implicit and explicit)
    res_r_impl = client.get(f"{CALENDAR}?month={m}&year={y}", headers=r_headers)
    assert res_r_impl.status_code == 200
    assert res_r_impl.json()["employee_id"] == emp_r["id"]

    res_r_expl = client.get(f"{CALENDAR}?month={m}&year={y}&employee_id={emp_r['id']}", headers=r_headers)
    assert res_r_expl.status_code == 200

    # 3. Employee asking for someone else -> 403
    res_r_other = client.get(f"{CALENDAR}?month={m}&year={y}&employee_id={emp_o['id']}", headers=r_headers)
    assert res_r_other.status_code == 403, "R1: Employee reading other calendar must return 403"

    # 4. Manager asking for direct report -> 200
    res_m_r = client.get(f"{CALENDAR}?month={m}&year={y}&employee_id={emp_r['id']}", headers=m_headers)
    assert res_m_r.status_code == 200

    # 5. Manager asking for non-report -> 403
    res_m_o = client.get(f"{CALENDAR}?month={m}&year={y}&employee_id={emp_o['id']}", headers=m_headers)
    assert res_m_o.status_code == 403, "R1: Manager reading non-report must return 403"

    # 6. Manager asking for THEIR OWN employee id -> 200 (BUGFIX check)
    res_m_own = client.get(f"{CALENDAR}?month={m}&year={y}&employee_id={emp_m['id']}", headers=m_headers)
    assert res_m_own.status_code == 200, f"R1: Manager asking for own employee_id must work: {res_m_own.text}"

    # 7. HR-level asking for anyone in company -> 200
    res_hr = client.get(f"{CALENDAR}?month={m}&year={y}&employee_id={emp_o['id']}", headers=company_a.hr_headers)
    assert res_hr.status_code == 200

    # 8. Another company employee or missing employee -> 404
    emp_b = _create_employee(client, company_b.hr_headers)
    res_cross = client.get(f"{CALENDAR}?month={m}&year={y}&employee_id={emp_b['id']}", headers=company_a.hr_headers)
    assert res_cross.status_code == 404, "R1: Other company employee must return 404"

    res_missing = client.get(f"{CALENDAR}?month={m}&year={y}&employee_id={uuid.uuid4()}", headers=company_a.hr_headers)
    assert res_missing.status_code == 404


# --- Rule 4.4.2: Month 1 to 12 and year 2000 to 2100, otherwise 422 ---


def test_R2_month_and_year_validation(
    client: TestClient, company_a: TenantContext
) -> None:
    # Month out of bounds
    res_m0 = client.get(f"{CALENDAR}?month=0&year=2026", headers=company_a.hr_headers)
    assert res_m0.status_code == 422, "R2: month < 1 must return 422"

    res_m13 = client.get(f"{CALENDAR}?month=13&year=2026", headers=company_a.hr_headers)
    assert res_m13.status_code == 422, "R2: month > 12 must return 422"

    # Year out of bounds
    res_y1999 = client.get(f"{CALENDAR}?month=5&year=1999", headers=company_a.hr_headers)
    assert res_y1999.status_code == 422, "R2: year < 2000 must return 422"

    res_y2101 = client.get(f"{CALENDAR}?month=5&year=2101", headers=company_a.hr_headers)
    assert res_y2101.status_code == 422, "R2: year > 2100 must return 422"


# --- Rule 4.4.3: Priority order of day states ---


def test_R3_day_states_fixed_priority_order(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    # Test month: October 2026
    # Oct 1 2026 is Thursday
    m = 10
    y = 2026
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    d1 = date(2026, 10, 1)

    # 1. Real attendance beats weekend or blank
    att = Attendance(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        date=d1,
        check_in=utcnow().replace(year=2026, month=10, day=1, hour=9, minute=0),
        check_out=utcnow().replace(year=2026, month=10, day=1, hour=18, minute=0),
        hours_worked=Decimal("8.00"),
        status=AttendanceStatus.present,
    )
    db.add(att)

    # 2. Approved leave
    lt = LeaveType(
        company_id=company_a.company_id,
        name="Casual",
        code=f"C{uuid.uuid4().hex[:6].upper()}",
        annual_allowance=Decimal("10"),
    )
    db.add(lt)
    db.flush()

    d2 = date(2026, 10, 2)
    lv = Leave(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        leave_type_id=lt.id,
        start_date=d2,
        end_date=d2,
        total_days=Decimal("1"),
        status=LeaveStatus.approved,
        reason="Vacation",
    )
    db.add(lv)

    # 3. Mandatory Holiday
    d5 = date(2026, 10, 5)
    hol = Holiday(
        company_id=company_a.company_id,
        name="National Day",
        date=d5,
        is_optional=False,
    )
    db.add(hol)
    db.commit()

    res = client.get(f"{CALENDAR}?month={m}&year={y}", headers=emp_headers)
    assert res.status_code == 200
    days = {d["date"]: d for d in res.json()["days"]}

    assert days["2026-10-01"]["status"] == "present"
    assert days["2026-10-02"]["status"] == "on_leave"
    assert days["2026-10-05"]["status"] == "holiday"


# --- Rule 4.4.4: Holidays department check & Optional holiday marked optional and NOT day off ---


def test_R4_department_holidays_and_optional_holidays(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    m = 11
    y = 2026
    # Create departments
    dept1 = Department(company_id=company_a.company_id, name=f"Dept 1 {uuid.uuid4().hex[:6]}")
    dept2 = Department(company_id=company_a.company_id, name=f"Dept 2 {uuid.uuid4().hex[:6]}")
    db.add_all([dept1, dept2])
    db.flush()

    emp = _create_employee(client, company_a.hr_headers, department_id=str(dept1.id))
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    # Holiday for Dept 1 on Nov 10
    d_dept1 = date(2026, 11, 10)
    h_dept1 = Holiday(
        company_id=company_a.company_id,
        name="Dept 1 Day",
        date=d_dept1,
        applies_to_department_id=dept1.id,
        is_optional=False,
    )
    # Holiday for Dept 2 on Nov 11
    d_dept2 = date(2026, 11, 11)
    h_dept2 = Holiday(
        company_id=company_a.company_id,
        name="Dept 2 Day",
        date=d_dept2,
        applies_to_department_id=dept2.id,
        is_optional=False,
    )
    # Optional holiday on Nov 12
    d_opt = date(2026, 11, 12)
    h_opt = Holiday(
        company_id=company_a.company_id,
        name="Optional Fest",
        date=d_opt,
        is_optional=True,
    )
    db.add_all([h_dept1, h_dept2, h_opt])
    db.commit()

    res = client.get(f"{CALENDAR}?month={m}&year={y}", headers=emp_headers)
    assert res.status_code == 200
    days = {d["date"]: d for d in res.json()["days"]}

    # Dept 1 holiday applies
    assert days["2026-11-10"]["status"] == "holiday"
    assert days["2026-11-10"]["holiday_name"] == "Dept 1 Day"

    # Dept 2 holiday does NOT apply to dept1 employee
    assert days["2026-11-11"]["holiday_name"] != "Dept 2 Day"

    # Optional holiday on Nov 12: must NOT be day off (status holiday), but badge or info shows optional
    assert days["2026-11-12"]["status"] != "holiday", "R4: Optional holiday is NOT a day off"
    assert days["2026-11-12"]["badge_label"] == "Optional Holiday" or "Optional" in (days["2026-11-12"]["badge_label"] or ""), (
        f"R4: Optional holiday should be labeled as optional, got {days['2026-11-12']}"
    )


# --- Rule 4.4.5: Weekends come from company's weekend setting ---


def test_R5_weekends_from_company_settings(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    now = utcnow()
    m = now.month
    y = now.year
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    res = client.get(f"{CALENDAR}?month={m}&year={y}", headers=emp_headers)
    assert res.status_code == 200
    # Every Saturday and Sunday should be weekend status unless other events exist
    for d in res.json()["days"]:
        if d["day_of_week"] in (5, 6) and not d["check_in"] and not d["leave_type_name"] and not d["holiday_name"]:
            assert d["status"] == "weekend"


# --- Rule 4.4.6: Pending leave looks different from approved leave ---


def test_R6_pending_leave_looks_different(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    m = 12
    y = 2026
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    lt = LeaveType(
        company_id=company_a.company_id,
        name="Sick",
        code=f"S{uuid.uuid4().hex[:6].upper()}",
        annual_allowance=Decimal("10"),
    )
    db.add(lt)
    db.flush()

    # Approved leave Dec 1
    lv_app = Leave(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        leave_type_id=lt.id,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 1),
        total_days=Decimal("1"),
        status=LeaveStatus.approved,
        reason="Sick",
    )
    # Pending leave Dec 2
    lv_pend = Leave(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        leave_type_id=lt.id,
        start_date=date(2026, 12, 2),
        end_date=date(2026, 12, 2),
        total_days=Decimal("1"),
        status=LeaveStatus.pending,
        reason="Sick",
    )
    db.add_all([lv_app, lv_pend])
    db.commit()

    res = client.get(f"{CALENDAR}?month={m}&year={y}", headers=emp_headers)
    assert res.status_code == 200
    days = {d["date"]: d for d in res.json()["days"]}

    # Status or badge for pending must differ from approved
    app_day = days["2026-12-01"]
    pend_day = days["2026-12-02"]

    assert app_day["status"] == "on_leave"
    assert pend_day["status"] == "pending_leave" or "Pending" in (pend_day["badge_label"] or ""), (
        f"R6: Pending leave must look different from approved leave: {pend_day}"
    )


# --- Rule 4.4.7: Future days never absent; today in progress while punch open ---


def test_R7_future_days_and_in_progress(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    now = utcnow()
    m = now.month
    y = now.year
    today = now.date()
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    # Check in today without checkout
    client.post("/api/v1/attendance/check-in", headers=emp_headers)

    res = client.get(f"{CALENDAR}?month={m}&year={y}", headers=emp_headers)
    assert res.status_code == 200
    days = {d["date"]: d for d in res.json()["days"]}

    # Today is in_progress
    assert days[today.isoformat()]["status"] == "in_progress"

    # Future day is never absent
    num_days = py_calendar.monthrange(y, m)[1]
    last_day = date(y, m, num_days)
    if last_day > today:
        assert days[last_day.isoformat()]["status"] != "absent", "R7: Future days cannot be absent"


# --- Rule 4.4.8: Attendance-exempt employees show as exempt, never absent ---


def test_R8_attendance_exempt_employees_never_absent(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    now = utcnow()
    m = now.month
    y = now.year
    emp = _create_employee(client, company_a.hr_headers, is_attendance_exempt=True)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    res = client.get(f"{CALENDAR}?month={m}&year={y}", headers=emp_headers)
    assert res.status_code == 200
    for d in res.json()["days"]:
        assert d["status"] != "absent", f"R8: Exempt employee cannot have absent status on day {d['date']}"


# --- Rule 4.4.9: Reads limited to 60/min and not audited ---


@pytest.fixture
def limits_on():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


def test_R9_calendar_rate_limit(
    client: TestClient, company_a: TenantContext, limits_on
) -> None:
    now = utcnow()
    m = now.month
    y = now.year
    codes = []
    for _ in range(61):
        res = client.get(f"{CALENDAR}?month={m}&year={y}", headers=company_a.hr_headers)
        codes.append(res.status_code)
    assert 429 in codes, f"R9: 61st read must return 429, got {codes[-1]}"


# --- Rule 4.4.10: Summary counts add up to total days of the month ---


def test_R10_summary_counts_add_up_to_days_of_month(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    m = 2
    y = 2024  # Leap year: 29 days
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    res = client.get(f"{CALENDAR}?month={m}&year={y}", headers=emp_headers)
    assert res.status_code == 200
    data = res.json()
    summary = data["summary"]
    total_in_summary = sum(summary.values())
    assert total_in_summary == 29, f"R10: Feb 2024 summary must equal 29 days, got {total_in_summary}"
    assert len(data["days"]) == 29
