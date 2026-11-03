"""Module 4, sub-feature 4.2: Punch in/out. One test per rule line (R1..R10).

Dates and times are computed from utcnow().
"""

import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import Employee
from app.modules.identity.models import (
    Company,
    CompanyLocation,
    CompanySettings,
    CompanyStatus,
    User,
    UserRole,
)
from app.modules.time_leave.models import (
    Attendance,
    AttendanceStatus,
    Holiday,
    Leave,
    LeaveStatus,
    LeaveType,
)
from tests.conftest import TenantContext

CHECK_IN = "/api/v1/attendance/check-in"
CHECK_OUT = "/api/v1/attendance/check-out"
ATTENDANCE = "/api/v1/attendance"


def _create_employee(
    client: TestClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    payload = {
        "first_name": "Test",
        "last_name": "Employee",
        "email": f"{uuid.uuid4().hex[:10]}@punchco.com",
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
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@punchco.com",
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


# --- Rule 4.2.1: Punch for self only; no employee gives 404; Mgr/HR/Owner for self only ---


def test_R1_punch_for_self_only_and_no_employee_is_404(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    # 1. Unlinked user has no employee record -> 404
    unlinked_headers = company_a.employee_headers
    res = client.post(CHECK_IN, headers=unlinked_headers)
    assert res.status_code == 404, "R1: Punch without employee record must give 404"

    # 2. Linked employee punches for self
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)
    in_res = client.post(CHECK_IN, headers=emp_headers)
    assert in_res.status_code == 201, f"R1: Check in failed {in_res.text}"
    assert in_res.json()["employee_id"] == emp["id"]

    # 3. Manager punches for self only (cannot punch on behalf of employee via body)
    mgr_emp = _create_employee(client, company_a.hr_headers)
    mgr_headers, _ = _link_user_to_employee(
        db, company_a.company_id, mgr_emp["id"], UserRole.manager
    )
    mgr_res = client.post(CHECK_IN, headers=mgr_headers)
    assert mgr_res.status_code == 201
    assert mgr_res.json()["employee_id"] == mgr_emp["id"]


# --- Rule 4.2.2: Server clock UTC; request cannot carry a time; extra fields 422 ---


def test_R2_server_time_only_and_extra_fields_give_422(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    # 1. Body trying to supply time / timestamp
    res_time = client.post(CHECK_IN, headers=emp_headers, json={"check_in": "2026-11-03T10:00:00Z"})
    assert res_time.status_code == 422, "R2: check-in cannot carry a time (422)"

    # 2. Unknown field in body
    res_extra = client.post(CHECK_IN, headers=emp_headers, json={"unknown_param": "foo"})
    assert res_extra.status_code == 422, "R2: unknown field in body must give 422"


# --- Rule 4.2.3: One record per day; 2nd punch 409; approved leave message ---


def test_R3_second_punch_in_is_409(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    first = client.post(CHECK_IN, headers=emp_headers)
    assert first.status_code == 201

    second = client.post(CHECK_IN, headers=emp_headers)
    assert second.status_code == 409, "R3: Second punch-in must return 409"


def test_R3_punch_on_approved_leave_gives_specific_message(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)
    today = utcnow().date()

    # Create leave type and an approved leave for today
    lt = LeaveType(
        company_id=company_a.company_id,
        name="Casual",
        code=f"C{uuid.uuid4().hex[:6].upper()}",
        annual_allowance=Decimal("10"),
    )
    db.add(lt)
    db.flush()

    leave = Leave(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        leave_type_id=lt.id,
        start_date=today,
        end_date=today,
        total_days=Decimal("1"),
        status=LeaveStatus.approved,
        reason="Vacation",
    )
    db.add(leave)
    # Also system puts an attendance record on_leave
    att = Attendance(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        date=today,
        status=AttendanceStatus.on_leave,
    )
    db.add(att)
    db.commit()

    res = client.post(CHECK_IN, headers=emp_headers)
    assert res.status_code == 409, "R3: Punch on approved leave must return 409"
    assert "You are on approved leave today" in res.text, (
        f"R3: Expected 'You are on approved leave today', got {res.text}"
    )


def test_R3_punch_in_on_a_weekend_is_allowed_and_recorded(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    today = utcnow().date()
    # ISO weekday: Mon=1, Sun=7
    today_iso_weekday = today.isoweekday()

    # Set company settings so that today is configured as a weekend day
    settings_row = (
        db.query(CompanySettings)
        .filter(CompanySettings.company_id == company_a.company_id)
        .one()
    )
    settings_row.weekend_days = [today_iso_weekday]
    db.commit()

    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    res = client.post(CHECK_IN, headers=emp_headers)
    assert res.status_code == 201, f"R3: Punch on weekend must return 201, got {res.status_code}: {res.text}"

    records = (
        db.query(Attendance)
        .filter(
            Attendance.company_id == company_a.company_id,
            Attendance.employee_id == uuid.UUID(emp["id"]),
            Attendance.date == today,
        )
        .all()
    )
    assert len(records) == 1, f"R3: Expected exactly 1 attendance record for today, found {len(records)}"


def test_R3_punch_in_on_a_holiday_is_allowed_and_recorded(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    today = utcnow().date()

    # Create a mandatory holiday for today
    holiday = Holiday(
        company_id=company_a.company_id,
        name="Mandatory Test Holiday",
        date=today,
        is_optional=False,
    )
    db.add(holiday)
    db.commit()

    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    res = client.post(CHECK_IN, headers=emp_headers)
    assert res.status_code == 201, f"R3: Punch on holiday must return 201, got {res.status_code}: {res.text}"

    records = (
        db.query(Attendance)
        .filter(
            Attendance.company_id == company_a.company_id,
            Attendance.employee_id == uuid.UUID(emp["id"]),
            Attendance.date == today,
        )
        .all()
    )
    assert len(records) == 1, f"R3: Expected exactly 1 attendance record for today, found {len(records)}"


# --- Rule 4.2.4: Punch-out needs open punch-in, after it, works once, closes after midnight ---


def test_R4_punch_out_requirements(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    # 1. Punch out without open check-in gives 400
    res_no_in = client.post(CHECK_OUT, headers=emp_headers)
    assert res_no_in.status_code == 400, "R4: Punch-out without open check-in must return 400"

    # 2. Check in then check out
    in_res = client.post(CHECK_IN, headers=emp_headers)
    assert in_res.status_code == 201

    out_res = client.post(CHECK_OUT, headers=emp_headers)
    assert out_res.status_code == 200
    assert out_res.json()["check_out"] is not None

    # 3. Second check-out gives 400 (already closed)
    out_again = client.post(CHECK_OUT, headers=emp_headers)
    assert out_again.status_code == 400, "R4: Second punch-out must return 400"


def test_R4_punch_out_closes_open_record_after_midnight(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)
    yesterday = utcnow().date() - timedelta(days=1)
    yesterday_time = utcnow() - timedelta(hours=10)

    # Directly create an open attendance record from yesterday night
    att = Attendance(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        date=yesterday,
        check_in=yesterday_time,
        status=AttendanceStatus.present,
    )
    db.add(att)
    db.commit()

    # Now checking out today should close yesterday's record
    out_res = client.post(CHECK_OUT, headers=emp_headers)
    assert out_res.status_code == 200
    assert out_res.json()["id"] == str(att.id)
    assert out_res.json()["check_out"] is not None


# --- Rule 4.2.5: Hours worked calculation and status thresholds ---


def test_R5_hours_worked_and_status_thresholds(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    # 1. Under 1 hour worked -> status absent
    today = utcnow().date()
    att = Attendance(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        date=today,
        check_in=utcnow() - timedelta(minutes=45),
        status=AttendanceStatus.present,
    )
    db.add(att)
    db.commit()

    out_res = client.post(CHECK_OUT, headers=emp_headers)
    assert out_res.status_code == 200
    assert out_res.json()["status"] == "absent", "R5: Under 1 hour worked must be marked absent"

    # Reset attendance record to test half-day (2.5 hours)
    db.delete(att)
    db.commit()

    att2 = Attendance(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        date=today,
        check_in=utcnow() - timedelta(hours=2, minutes=30),
        status=AttendanceStatus.present,
    )
    db.add(att2)
    db.commit()

    out_res2 = client.post(CHECK_OUT, headers=emp_headers)
    assert out_res2.status_code == 200
    assert out_res2.json()["status"] == "half_day", (
        "R5: Under 4 hours worked must be marked half_day"
    )

    # 3. Test exact half-up rounding (59m 42s = 3582s / 3600 = 0.995h -> rounds to 1.00)
    db.delete(att2)
    db.commit()
    att3 = Attendance(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        date=today,
        check_in=utcnow() - timedelta(seconds=3582),
        status=AttendanceStatus.present,
    )
    db.add(att3)
    db.commit()
    out_res3 = client.post(CHECK_OUT, headers=emp_headers)
    assert out_res3.status_code == 200
    # 0.995 with ROUND_HALF_UP is 1.00 (half_day), with ROUND_DOWN it is 0.99 (absent)
    assert Decimal(str(out_res3.json()["hours_worked"])) == Decimal("1.00")
    assert out_res3.json()["status"] == "half_day", "R5: 0.995 must round half up to 1.00"


# --- Rule 4.2.6: Geofence validation ---


def test_R6_geofence_validations(client: TestClient, db: Session, company_a: TenantContext) -> None:
    # 1. Location with geofence
    loc = CompanyLocation(
        company_id=company_a.company_id,
        name="HQ Office",
        code=f"HQ{uuid.uuid4().hex[:4].upper()}",
        country="IN",
        latitude=Decimal("12.9716"),
        longitude=Decimal("77.5946"),
        geofence_radius_meters=100,
        is_remote_exempt=False,
    )
    db.add(loc)
    db.flush()

    emp = _create_employee(client, company_a.hr_headers, location_id=str(loc.id))
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    # 1. Missing GPS coordinates when geofence active -> 403
    res_no_gps = client.post(CHECK_IN, headers=emp_headers)
    assert res_no_gps.status_code == 403, (
        "R6: Missing GPS coordinates with active geofence must give 403"
    )

    # 2. Invalid GPS range values -> 422
    res_bad_lat = client.post(
        CHECK_IN, headers=emp_headers, json={"latitude": 95.0, "longitude": 77.0}
    )
    assert res_bad_lat.status_code == 422, "R6: Latitude > 90 must give 422"

    res_bad_lon = client.post(
        CHECK_IN, headers=emp_headers, json={"latitude": 12.0, "longitude": 185.0}
    )
    assert res_bad_lon.status_code == 422, "R6: Longitude > 180 must give 422"

    res_bad_acc = client.post(
        CHECK_IN,
        headers=emp_headers,
        json={"latitude": 12.0, "longitude": 77.0, "device_accuracy": -5.0},
    )
    assert res_bad_acc.status_code == 422, "R6: Accuracy < 0 must give 422"

    # 3. GPS coordinates outside radius -> 403
    res_outside = client.post(
        CHECK_IN,
        headers=emp_headers,
        json={"latitude": 13.0000, "longitude": 77.6000, "device_accuracy": 10.0},
    )
    assert res_outside.status_code == 403, "R6: Outside geofence radius must return 403"

    # 4. GPS coordinates inside radius -> 201
    res_inside = client.post(
        CHECK_IN,
        headers=emp_headers,
        json={"latitude": 12.9716, "longitude": 77.5946, "device_accuracy": 5.0},
    )
    assert res_inside.status_code == 201, (
        f"R6: Inside geofence radius must succeed: {res_inside.text}"
    )


# --- Rule 4.2.7: Past day left open marked mispunch at next punch-in ---


def test_R7_past_day_left_open_marked_mispunch_at_next_punch_in(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)
    past_date = utcnow().date() - timedelta(days=2)

    past_open = Attendance(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp["id"]),
        date=past_date,
        check_in=utcnow() - timedelta(days=2),
        status=AttendanceStatus.present,
    )
    db.add(past_open)
    db.commit()

    # Next punch-in today
    res = client.post(CHECK_IN, headers=emp_headers)
    assert res.status_code == 201

    # Reload past_open
    db.refresh(past_open)
    assert past_open.status == AttendanceStatus.mispunch, (
        f"R7: Past open attendance must be updated to mispunch, got {past_open.status}"
    )


# --- Rule 4.2.8: Scoping of attendance records (own, direct reports, HR-level, 403) ---


def test_R8_attendance_scoping(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
) -> None:
    # Manager M, Report R, Other O
    emp_m = _create_employee(client, company_a.hr_headers)
    m_headers, _ = _link_user_to_employee(db, company_a.company_id, emp_m["id"], UserRole.manager)

    emp_r = _create_employee(client, company_a.hr_headers, reporting_manager_id=emp_m["id"])
    r_headers, _ = _link_user_to_employee(db, company_a.company_id, emp_r["id"], UserRole.employee)

    emp_o = _create_employee(client, company_a.hr_headers)
    o_headers, _ = _link_user_to_employee(db, company_a.company_id, emp_o["id"], UserRole.employee)

    # Create attendance for R and O
    r_in = client.post(CHECK_IN, headers=r_headers)
    assert r_in.status_code == 201
    r_att_id = r_in.json()["id"]

    o_in = client.post(CHECK_IN, headers=o_headers)
    assert o_in.status_code == 201
    o_att_id = o_in.json()["id"]

    # 1. Employee sees own
    res_r_own = client.get(f"{ATTENDANCE}/{r_att_id}", headers=r_headers)
    assert res_r_own.status_code == 200

    # 2. Employee cannot see other's (403)
    res_r_other = client.get(f"{ATTENDANCE}/{o_att_id}", headers=r_headers)
    assert res_r_other.status_code == 403, "R8: Employee reading other record must return 403"

    # 3. Manager sees direct report's
    res_m_report = client.get(f"{ATTENDANCE}/{r_att_id}", headers=m_headers)
    assert res_m_report.status_code == 200, "R8: Manager must see direct report's record"

    # 4. Manager cannot see non-report's (403)
    res_m_other = client.get(f"{ATTENDANCE}/{o_att_id}", headers=m_headers)
    assert res_m_other.status_code == 403, "R8: Manager reading non-report must return 403"

    # 5. HR sees all
    res_hr = client.get(f"{ATTENDANCE}/{o_att_id}", headers=company_a.hr_headers)
    assert res_hr.status_code == 200

    # 6. Another company record is 404
    emp_b = _create_employee(client, company_b.hr_headers)
    b_headers, _ = _link_user_to_employee(db, company_b.company_id, emp_b["id"], UserRole.employee)
    b_in = client.post(CHECK_IN, headers=b_headers)
    b_att_id = b_in.json()["id"]

    cross_res = client.get(f"{ATTENDANCE}/{b_att_id}", headers=company_a.hr_headers)
    assert cross_res.status_code == 404, "R8: Other company record must return 404"


# --- Rule 4.2.9: Rate limits (punches 10/min, reads 60/min; punches not audited) ---


@pytest.fixture
def limits_on():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


def test_R9_punch_rate_limits(
    client: TestClient, db: Session, company_a: TenantContext, limits_on
) -> None:
    emp = _create_employee(client, company_a.hr_headers)
    emp_headers, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    # 10 punch-in calls per minute; 11th must return 429
    codes = []
    for _ in range(11):
        res = client.post(CHECK_IN, headers=emp_headers)
        codes.append(res.status_code)
    assert 429 in codes, f"R9: 11th punch call must return 429, got {codes}"


# --- Rule 4.2.10: Two simultaneous punch-ins give one 201 and one 409 ---


def test_R10_concurrent_punch_ins_give_one_201_and_one_409() -> None:
    assert settings.TEST_DATABASE_URL is not None
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    cid = uuid.uuid4()
    today = utcnow().date()
    try:
        with Session(engine) as setup:
            setup.add(
                Company(
                    id=cid,
                    name="Punch Race Co",
                    code=f"PRC{uuid.uuid4().hex[:4].upper()}",
                    email=f"prc-{uuid.uuid4().hex[:6]}@example.com",
                    status=CompanyStatus.active,
                    is_active=True,
                )
            )
            setup.flush()
            bind_tenant_to_session(setup, company_id=cid, is_platform_admin=False)
            emp = Employee(
                id=uuid.uuid4(),
                company_id=cid,
                employee_code=f"EMP{uuid.uuid4().hex[:4].upper()}",
                first_name="Punch",
                last_name="Racer",
                email=f"punch-{uuid.uuid4().hex[:6]}@example.com",
                hire_date=today,
                is_active=True,
            )
            setup.add(emp)
            user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"user-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.employee,
                is_active=True,
            )
            setup.add(user)
            setup.flush()
            emp.user_id = user.id
            user_id = user.id
            setup.commit()
            token = create_access_token(sub=str(user_id), company_id=str(cid), role="employee")
        headers = {"Authorization": f"Bearer {token}"}

        def _get_test_db():
            session = Session(engine)
            try:
                yield session
            finally:
                session.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db
        barrier = threading.Barrier(2)
        results: list[int] = []

        def _worker() -> None:
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                res = c.post(CHECK_IN, headers=headers)
                results.append(res.status_code)
            except Exception:
                results.append(999)

        t1 = threading.Thread(target=_worker)
        t2 = threading.Thread(target=_worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert 500 not in results and 999 not in results, (
            f"R10: race gave unexpected error: {results}"
        )
        assert sorted(results) == [201, 409], (
            f"R10: Expected exactly one 201 and one 409, got {results}"
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        owner_engine = create_engine(settings.TEST_MIGRATION_URL)
        with owner_engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
            conn.execute(text("DELETE FROM audit_logs WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM attendance WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM employees WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM users WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": cid})
        owner_engine.dispose()
