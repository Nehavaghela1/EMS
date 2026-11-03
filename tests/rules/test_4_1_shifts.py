"""Module 4, sub-feature 4.1: Shifts. One test per rule line (R1..R10).

Dates that a rule compares with today are computed from utcnow().
"""

import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import Employee
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog
from app.modules.time_leave.models import Shift
from tests.conftest import REPO_ROOT, TenantContext, _make_user_headers

SHIFTS = "/api/v1/shifts"
MIGRATION_REVISION = "7fe2862a3b33"
PREVIOUS_REVISION = "c4d5e6f7a8b9"


def _owner_headers(db: Session, ctx: TenantContext) -> dict[str, str]:
    headers = _make_user_headers(db, ctx.company_id, UserRole.owner)
    db.commit()
    return headers


def _create_employee(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload = {
        "first_name": "Test",
        "last_name": "Employee",
        "email": f"{uuid.uuid4().hex[:10]}@shiftco.com",
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
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@shiftco.com",
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


def _shift_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": f"Shift {uuid.uuid4().hex[:8]}",
        "start_time": "09:00:00",
        "end_time": "18:00:00",
        "break_minutes": 60,
        "night_allowance": "0.00",
    }
    payload.update(overrides)
    return payload


def _create_shift(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    resp = client.post(SHIFTS, headers=headers, json=_shift_payload(**overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _audit_rows(db: Session, ctx: TenantContext, action: str) -> list[AuditLog]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    return (
        db.query(AuditLog)
        .filter(AuditLog.company_id == ctx.company_id, AuditLog.action == action)
        .all()
    )


# --- Rule 4.1.1: Only owner and HR admin create, edit, deactivate, delete and assign shifts ---


def test_R1_no_login_gets_401(client: TestClient) -> None:
    res = client.post(SHIFTS, json=_shift_payload())
    assert res.status_code == 401, "R1: Unauthenticated shift create must return 401"


def test_R1_manager_and_employee_writes_get_403(
    client: TestClient, company_a: TenantContext
) -> None:
    shift = _create_shift(client, company_a.hr_headers)
    emp = _create_employee(client, company_a.hr_headers)
    today = utcnow().date()

    for headers in (company_a.manager_headers, company_a.employee_headers):
        # Create
        c_res = client.post(SHIFTS, headers=headers, json=_shift_payload())
        assert c_res.status_code == 403, f"R1: Non-HR create must return 403, got {c_res.status_code}"

        # Edit
        u_res = client.put(f"{SHIFTS}/{shift['id']}", headers=headers, json={"name": "New Name"})
        assert u_res.status_code == 403, f"R1: Non-HR update must return 403, got {u_res.status_code}"

        # Deactivate
        d_res = client.put(f"{SHIFTS}/{shift['id']}", headers=headers, json={"is_active": False})
        assert d_res.status_code == 403, f"R1: Non-HR deactivate must return 403, got {d_res.status_code}"

        # Assign
        a_res = client.post(
            f"{SHIFTS}/{shift['id']}/assign",
            headers=headers,
            json={"employee_id": emp["id"], "effective_from": today.isoformat()},
        )
        assert a_res.status_code == 403, f"R1: Non-HR assign must return 403, got {a_res.status_code}"

        # Delete
        del_res = client.delete(f"{SHIFTS}/{shift['id']}", headers=headers)
        assert del_res.status_code == 403, f"R1: Non-HR delete must return 403, got {del_res.status_code}"


def test_R1_owner_and_hr_admin_create_edit_deactivate_delete_and_assign(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    owner_headers = _owner_headers(db, company_a)
    today = utcnow().date()

    for headers in (company_a.hr_headers, owner_headers):
        s = _create_shift(client, headers)
        assert s["id"]

        # Edit
        edit_res = client.put(
            f"{SHIFTS}/{s['id']}", headers=headers, json={"break_minutes": 45}
        )
        assert edit_res.status_code == 200
        assert edit_res.json()["break_minutes"] == 45

        # Deactivate
        deact_res = client.put(
            f"{SHIFTS}/{s['id']}", headers=headers, json={"is_active": False}
        )
        assert deact_res.status_code == 200
        assert deact_res.json()["is_active"] is False

        # Reactivate so we can assign
        client.put(f"{SHIFTS}/{s['id']}", headers=headers, json={"is_active": True})

        # Assign
        emp = _create_employee(client, company_a.hr_headers)
        # Assign with effective_from yesterday so ending today or yesterday works
        yesterday = today - timedelta(days=2)
        assign_res = client.post(
            f"{SHIFTS}/{s['id']}/assign",
            headers=headers,
            json={"employee_id": emp["id"], "effective_from": yesterday.isoformat()},
        )
        assert assign_res.status_code == 201

        # End assignment so it can be deleted (effective_to in past, but not before effective_from)
        assign_id = assign_res.json()["id"]
        end_res = client.put(
            f"{SHIFTS}/assignments/{assign_id}",
            headers=headers,
            json={"effective_to": (today - timedelta(days=1)).isoformat()},
        )
        assert end_res.status_code == 200

        # Delete
        del_res = client.delete(f"{SHIFTS}/{s['id']}", headers=headers)
        assert del_res.status_code == 204


# --- Rule 4.1.2: Any logged-in user can list shift definitions (name and times only) ---


def test_R2_any_logged_in_user_can_list_shift_definitions(
    client: TestClient, company_a: TenantContext
) -> None:
    s = _create_shift(client, company_a.hr_headers, name="General Shift")

    for headers in (
        company_a.employee_headers,
        company_a.manager_headers,
        company_a.hr_headers,
    ):
        res = client.get(SHIFTS, headers=headers)
        assert res.status_code == 200, f"R2: Logged-in user list shifts returned {res.status_code}"
        items = res.json()["items"]
        found = [item for item in items if item["id"] == s["id"]]
        assert len(found) == 1, "R2: Shift should be present in list"
        # Assert name and times are present
        assert "name" in found[0] and "start_time" in found[0] and "end_time" in found[0]


# --- Rule 4.1.3: Employee sees own assigned; Manager sees own and reports; HR sees all; other 403; other co 404 ---


def test_R3_assigned_shift_scoping_and_not_found(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
) -> None:
    today = utcnow().date()
    shift_a = _create_shift(client, company_a.hr_headers)

    # Manager M, Direct Report R, Unrelated Colleague U
    emp_m = _create_employee(client, company_a.hr_headers)
    m_headers, _ = _link_user_to_employee(db, company_a.company_id, emp_m["id"], UserRole.manager)

    emp_r = _create_employee(client, company_a.hr_headers, reporting_manager_id=emp_m["id"])
    r_headers, _ = _link_user_to_employee(db, company_a.company_id, emp_r["id"], UserRole.employee)

    emp_u = _create_employee(client, company_a.hr_headers)
    u_headers, _ = _link_user_to_employee(db, company_a.company_id, emp_u["id"], UserRole.employee)

    # Assign shift to R and U and M
    for emp_id in (emp_m["id"], emp_r["id"], emp_u["id"]):
        client.post(
            f"{SHIFTS}/{shift_a['id']}/assign",
            headers=company_a.hr_headers,
            json={"employee_id": emp_id, "effective_from": today.isoformat()},
        )

    # 1. Employee sees own
    r_res = client.get(f"{SHIFTS}/assigned/{emp_r['id']}", headers=r_headers)
    assert r_res.status_code == 200
    assert r_res.json()["shift"]["id"] == shift_a["id"]

    # 2. Employee cannot see colleague's
    r_u_res = client.get(f"{SHIFTS}/assigned/{emp_u['id']}", headers=r_headers)
    assert r_u_res.status_code == 403, "R3: Employee cannot see colleague's assigned shift"

    # 3. Manager sees own
    m_own_res = client.get(f"{SHIFTS}/assigned/{emp_m['id']}", headers=m_headers)
    assert m_own_res.status_code == 200, "R3: Manager should see own assigned shift"

    # 4. Manager sees direct report's
    m_r_res = client.get(f"{SHIFTS}/assigned/{emp_r['id']}", headers=m_headers)
    assert m_r_res.status_code == 200, "R3: Manager should see direct report's assigned shift"

    # 5. Manager cannot see unrelated colleague's
    m_u_res = client.get(f"{SHIFTS}/assigned/{emp_u['id']}", headers=m_headers)
    assert m_u_res.status_code == 403, "R3: Manager cannot see non-direct-report's assigned shift"

    # 6. HR admin sees all in company
    hr_u_res = client.get(f"{SHIFTS}/assigned/{emp_u['id']}", headers=company_a.hr_headers)
    assert hr_u_res.status_code == 200

    # 7. Another company's employee gives 404 (same as non-existent)
    emp_b = _create_employee(client, company_b.hr_headers)
    cross_res = client.get(f"{SHIFTS}/assigned/{emp_b['id']}", headers=company_a.hr_headers)
    assert cross_res.status_code == 404, "R3: Cross-company employee must give 404"
    cross_mgr_res = client.get(f"{SHIFTS}/assigned/{emp_b['id']}", headers=m_headers)
    assert cross_mgr_res.status_code == 404, "R3: Cross-company employee from manager must give 404"

    missing_res = client.get(f"{SHIFTS}/assigned/{uuid.uuid4()}", headers=company_a.hr_headers)
    assert missing_res.status_code == 404


# --- Rule 4.1.4: Shift input validation ---


def test_R4_shift_input_validation(client: TestClient, company_a: TenantContext) -> None:
    # 1. Name trimmed 1 to 100 characters
    res_empty = client.post(SHIFTS, headers=company_a.hr_headers, json=_shift_payload(name="   "))
    assert res_empty.status_code == 422, "R4: Empty/whitespace name must give 422"

    res_long = client.post(SHIFTS, headers=company_a.hr_headers, json=_shift_payload(name="A" * 101))
    assert res_long.status_code == 422, "R4: Name > 100 chars must give 422"

    # 2. Name trimmed and unique per company ignoring case (409)
    name_base = f"Unique Shift {uuid.uuid4().hex[:6]}"
    res1 = client.post(SHIFTS, headers=company_a.hr_headers, json=_shift_payload(name=f"  {name_base}  "))
    assert res1.status_code == 201
    assert res1.json()["name"] == name_base

    res2 = client.post(SHIFTS, headers=company_a.hr_headers, json=_shift_payload(name=name_base.lower()))
    assert res2.status_code == 409, "R4: Duplicate shift name case-insensitive must return 409"

    # 3. Start and end times differ
    res_same = client.post(
        SHIFTS,
        headers=company_a.hr_headers,
        json=_shift_payload(start_time="09:00:00", end_time="09:00:00"),
    )
    assert res_same.status_code == 422, "R4: Start and end time cannot be identical (422)"

    # End before start means overnight shift (valid)
    res_overnight = client.post(
        SHIFTS,
        headers=company_a.hr_headers,
        json=_shift_payload(start_time="22:00:00", end_time="06:00:00", break_minutes=30),
    )
    assert res_overnight.status_code == 201, "R4: Overnight shift (end < start) is allowed"

    # 4. Break 0 to 240 minutes and shorter than the shift duration
    res_neg_break = client.post(
        SHIFTS, headers=company_a.hr_headers, json=_shift_payload(break_minutes=-1)
    )
    assert res_neg_break.status_code == 422, "R4: Negative break minutes must give 422"

    res_too_long_break = client.post(
        SHIFTS, headers=company_a.hr_headers, json=_shift_payload(break_minutes=241)
    )
    assert res_too_long_break.status_code == 422, "R4: Break minutes > 240 must give 422"

    # Normal day 9 to 11 = 120 mins duration, break 120 mins must fail (< shift duration)
    res_break_eq_shift = client.post(
        SHIFTS,
        headers=company_a.hr_headers,
        json=_shift_payload(start_time="09:00:00", end_time="11:00:00", break_minutes=120),
    )
    assert res_break_eq_shift.status_code == 422, "R4: Break minutes must be shorter than shift duration"

    # 5. Night allowance 0 to 99,999.99 as Decimal
    res_neg_allowance = client.post(
        SHIFTS, headers=company_a.hr_headers, json=_shift_payload(night_allowance="-1.00")
    )
    assert res_neg_allowance.status_code == 422, "R4: Negative night allowance must give 422"

    res_large_allowance = client.post(
        SHIFTS, headers=company_a.hr_headers, json=_shift_payload(night_allowance="100000.00")
    )
    assert res_large_allowance.status_code == 422, "R4: Night allowance > 99999.99 must give 422"

    # 6. Unknown fields and nulls on required fields give 422
    res_unknown = client.post(
        SHIFTS, headers=company_a.hr_headers, json=_shift_payload(extra_param="illegal")
    )
    assert res_unknown.status_code == 422, "R4: Unknown fields must give 422"

    res_null = client.post(
        SHIFTS, headers=company_a.hr_headers, json=_shift_payload(name=None)
    )
    assert res_null.status_code == 422, "R4: Null on required field must give 422"


# --- Rule 4.1.5: Assignment validations & race safety ---


def test_R5_assignment_validations(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
) -> None:
    today = utcnow().date()
    shift = _create_shift(client, company_a.hr_headers)
    emp = _create_employee(client, company_a.hr_headers)

    # 1. effective_to is not before effective_from
    res_bad_dates = client.post(
        f"{SHIFTS}/{shift['id']}/assign",
        headers=company_a.hr_headers,
        json={
            "employee_id": emp["id"],
            "effective_from": today.isoformat(),
            "effective_to": (today - timedelta(days=1)).isoformat(),
        },
    )
    assert res_bad_dates.status_code == 422, "R5: effective_to before effective_from must return 422"

    # 2. Employee in different company is 404
    emp_b = _create_employee(client, company_b.hr_headers)
    res_cross_emp = client.post(
        f"{SHIFTS}/{shift['id']}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": emp_b["id"], "effective_from": today.isoformat()},
    )
    assert res_cross_emp.status_code == 404, "R5: Assigning employee of another company must return 404"

    # 3. Deactivated shift cannot be newly assigned
    deact_shift = _create_shift(client, company_a.hr_headers)
    client.put(f"{SHIFTS}/{deact_shift['id']}", headers=company_a.hr_headers, json={"is_active": False})
    res_deact = client.post(
        f"{SHIFTS}/{deact_shift['id']}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": emp["id"], "effective_from": today.isoformat()},
    )
    assert res_deact.status_code == 409 or res_deact.status_code == 422, (
        f"R5: Deactivated shift cannot be newly assigned, got {res_deact.status_code}"
    )

    # 4. Overlapping assignments for one employee gives 409 naming the dates
    res1 = client.post(
        f"{SHIFTS}/{shift['id']}/assign",
        headers=company_a.hr_headers,
        json={
            "employee_id": emp["id"],
            "effective_from": today.isoformat(),
            "effective_to": (today + timedelta(days=10)).isoformat(),
        },
    )
    assert res1.status_code == 201

    res_overlap = client.post(
        f"{SHIFTS}/{shift['id']}/assign",
        headers=company_a.hr_headers,
        json={
            "employee_id": emp["id"],
            "effective_from": (today + timedelta(days=5)).isoformat(),
            "effective_to": (today + timedelta(days=15)).isoformat(),
        },
    )
    assert res_overlap.status_code == 409, "R5: Overlapping assignment must return 409"
    assert today.isoformat() in res_overlap.text or (today + timedelta(days=10)).isoformat() in res_overlap.text


def test_R5_concurrent_shift_assignments_race_safe() -> None:
    assert settings.TEST_DATABASE_URL is not None
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    cid = uuid.uuid4()
    today = utcnow().date()
    try:
        with Session(engine) as setup:
            setup.add(
                Company(
                    id=cid,
                    name="Shift Race Co",
                    code=f"SRC{uuid.uuid4().hex[:4].upper()}",
                    email=f"src-{uuid.uuid4().hex[:6]}@example.com",
                    status=CompanyStatus.active,
                    is_active=True,
                )
            )
            setup.flush()
            bind_tenant_to_session(setup, company_id=cid, is_platform_admin=False)
            hr_user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.hr_admin,
                is_active=True,
            )
            setup.add(hr_user)
            emp = Employee(
                id=uuid.uuid4(),
                company_id=cid,
                employee_code=f"EMP{uuid.uuid4().hex[:4].upper()}",
                first_name="Race",
                last_name="Employee",
                email=f"emp-{uuid.uuid4().hex[:6]}@example.com",
                hire_date=today,
                is_active=True,
            )
            setup.add(emp)
            shift1 = Shift(
                id=uuid.uuid4(),
                company_id=cid,
                name="Shift Race 1",
                start_time=utcnow().time().replace(hour=9, minute=0, second=0),
                end_time=utcnow().time().replace(hour=18, minute=0, second=0),
                break_minutes=60,
                is_active=True,
            )
            shift2 = Shift(
                id=uuid.uuid4(),
                company_id=cid,
                name="Shift Race 2",
                start_time=utcnow().time().replace(hour=10, minute=0, second=0),
                end_time=utcnow().time().replace(hour=19, minute=0, second=0),
                break_minutes=60,
                is_active=True,
            )
            setup.add_all([shift1, shift2])
            shift1_id = shift1.id
            shift2_id = shift2.id
            emp_id = emp.id
            hr_user_id = hr_user.id
            setup.commit()
            token = create_access_token(sub=str(hr_user_id), company_id=str(cid), role="hr_admin")
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

        def _worker(s_id: str) -> None:
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                res = c.post(
                    f"{SHIFTS}/{s_id}/assign",
                    headers=headers,
                    json={
                        "employee_id": str(emp_id),
                        "effective_from": today.isoformat(),
                        "effective_to": (today + timedelta(days=5)).isoformat(),
                    },
                )
                results.append(res.status_code)
            except Exception:
                results.append(999)

        t1 = threading.Thread(target=_worker, args=(str(shift1_id),))
        t2 = threading.Thread(target=_worker, args=(str(shift2_id),))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert 500 not in results and 999 not in results, f"R5: race gave unexpected error: {results}"
        assert sorted(results) == [201, 409], f"R5: Expected exactly one 201 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        owner_engine = create_engine(settings.TEST_MIGRATION_URL)
        with owner_engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
            conn.execute(text("DELETE FROM audit_logs WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM employee_shifts WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM shifts WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM employees WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM users WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": cid})
        owner_engine.dispose()


# --- Rule 4.1.6: End assignment route, edit future only, delete blocked on current/future ---


def test_R6_end_assignment_edit_and_delete_blocks(
    client: TestClient, company_a: TenantContext
) -> None:
    today = utcnow().date()
    shift = _create_shift(client, company_a.hr_headers)
    emp = _create_employee(client, company_a.hr_headers)

    # Assign current shift
    yesterday = today - timedelta(days=2)
    assign_res = client.post(
        f"{SHIFTS}/{shift['id']}/assign",
        headers=company_a.hr_headers,
        json={
            "employee_id": emp["id"],
            "effective_from": yesterday.isoformat(),
        },
    )
    assert assign_res.status_code == 201
    assign_id = assign_res.json()["id"]

    # Delete blocked while current assignment exists (409 with count)
    del_res = client.delete(f"{SHIFTS}/{shift['id']}", headers=company_a.hr_headers)
    assert del_res.status_code == 409, "R6: Delete blocked with current assignments"
    assert del_res.json()["error"]["details"]["assignment_count"] >= 1

    # End assignment by setting effective_to (PUT /shifts/assignments/{id})
    end_res = client.put(
        f"{SHIFTS}/assignments/{assign_id}",
        headers=company_a.hr_headers,
        json={"effective_to": (today + timedelta(days=2)).isoformat()},
    )
    assert end_res.status_code == 200
    assert end_res.json()["effective_to"] == (today + timedelta(days=2)).isoformat()

    # Now ending it in past (yesterday, which is >= effective_from)
    end_past = client.put(
        f"{SHIFTS}/assignments/{assign_id}",
        headers=company_a.hr_headers,
        json={"effective_to": (today - timedelta(days=1)).isoformat()},
    )
    assert end_past.status_code == 200

    # Now delete succeeds and is soft delete
    del_res2 = client.delete(f"{SHIFTS}/{shift['id']}", headers=company_a.hr_headers)
    assert del_res2.status_code == 204

    # Getting deleted shift gives 404
    get_res = client.get(f"{SHIFTS}/{shift['id']}", headers=company_a.hr_headers)
    assert get_res.status_code == 404 or get_res.status_code == 405


# --- Rule 4.1.7: Audit rows for Shift operations ---


def test_R7_audit_rows_for_shift_operations(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    today = utcnow().date()
    # 1. SHIFT_CREATED
    shift = _create_shift(client, company_a.hr_headers)
    created_audits = _audit_rows(db, company_a, "SHIFT_CREATED")
    assert any(a.entity_id == uuid.UUID(shift["id"]) for a in created_audits)

    # 2. SHIFT_UPDATED
    client.put(f"{SHIFTS}/{shift['id']}", headers=company_a.hr_headers, json={"break_minutes": 30})
    updated_audits = _audit_rows(db, company_a, "SHIFT_UPDATED")
    assert any(a.entity_id == uuid.UUID(shift["id"]) for a in updated_audits)

    # 3. SHIFT_ASSIGNED
    emp = _create_employee(client, company_a.hr_headers)
    yesterday = today - timedelta(days=2)
    assign_res = client.post(
        f"{SHIFTS}/{shift['id']}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": emp["id"], "effective_from": yesterday.isoformat()},
    )
    assign_id = assign_res.json()["id"]
    assigned_audits = _audit_rows(db, company_a, "SHIFT_ASSIGNED")
    assert any(a.entity_id == uuid.UUID(assign_id) for a in assigned_audits)

    # 4. SHIFT_ASSIGNMENT_ENDED
    client.put(
        f"{SHIFTS}/assignments/{assign_id}",
        headers=company_a.hr_headers,
        json={"effective_to": (today - timedelta(days=1)).isoformat()},
    )
    ended_audits = _audit_rows(db, company_a, "SHIFT_ASSIGNMENT_ENDED")
    assert any(a.entity_id == uuid.UUID(assign_id) for a in ended_audits)

    # 5. SHIFT_DELETED
    client.delete(f"{SHIFTS}/{shift['id']}", headers=company_a.hr_headers)
    deleted_audits = _audit_rows(db, company_a, "SHIFT_DELETED")
    assert any(a.entity_id == uuid.UUID(shift["id"]) for a in deleted_audits)


# --- Rule 4.1.8: Rate limits (writes 30/min, reads 60/min) ---


@pytest.fixture
def limits_on():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


def test_R8_rate_limits(client: TestClient, company_a: TenantContext, limits_on) -> None:
    # 30 writes per minute
    # Perform 30 creations then 31st gives 429
    status_codes = []
    for _ in range(31):
        res = client.post(SHIFTS, headers=company_a.hr_headers, json=_shift_payload())
        status_codes.append(res.status_code)
    assert 429 in status_codes, f"R8: 31st write must return 429, got {status_codes[-1]}"


# --- Rule 4.1.9: Managers get no shift write power ---


def test_R9_manager_has_no_shift_write_power(
    client: TestClient, company_a: TenantContext
) -> None:
    # Confirms manager cannot write even if parameters look valid
    res = client.post(SHIFTS, headers=company_a.manager_headers, json=_shift_payload())
    assert res.status_code == 403, "R9: Manager must have no shift write power (403)"


# --- Rule 4.1.10: Migration test round trip ---


def test_R10_migration_round_trip() -> None:
    assert settings.TEST_MIGRATION_URL is not None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        engine = create_engine(settings.TEST_MIGRATION_URL)
        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        company_id = uuid.uuid4()
        code = f"MC{uuid.uuid4().hex[:6].upper()}"

        def _add(name: str) -> None:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE shifts NO FORCE ROW LEVEL SECURITY"))
                conn.execute(
                    text(
                        "INSERT INTO shifts (id, company_id, name, start_time, end_time, break_minutes, night_allowance, is_active, created_at, updated_at) "
                        "VALUES (:i, :c, :n, '09:00:00', '18:00:00', 60, 0, true, NOW(), NOW())"
                    ),
                    {"i": uuid.uuid4(), "c": company_id, "n": name},
                )
                conn.execute(text("ALTER TABLE shifts FORCE ROW LEVEL SECURITY"))

        def _clean() -> None:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE shifts NO FORCE ROW LEVEL SECURITY"))
                conn.execute(text("DELETE FROM shifts WHERE company_id = :c"), {"c": company_id})
                conn.execute(text("ALTER TABLE shifts FORCE ROW LEVEL SECURITY"))

        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO companies (id, name, code, email, status, country, currency,"
                        " last_employee_seq, created_at, updated_at) VALUES (:i, 'Mig Shift Co', :c,"
                        " :e, 'active', 'IN', 'INR', 0, NOW(), NOW())"
                    ),
                    {"i": company_id, "c": code, "e": f"{code.lower()}@test.test"},
                )

            # Check downgrade and duplicate catch
            command.downgrade(cfg, PREVIOUS_REVISION)

            # Insert duplicate shift names under NO FORCE RLS
            _add("General")
            _add("general")

            with pytest.raises(RuntimeError) as exc_info:
                command.upgrade(cfg, MIGRATION_REVISION)
            assert "duplicate" in str(exc_info.value).lower() and "general" in str(exc_info.value).lower()

            # Clean duplicates and upgrade
            _clean()
            command.upgrade(cfg, MIGRATION_REVISION)
            indexes = {i["name"] for i in inspect(engine).get_indexes("shifts")}
            assert "uq_shifts_company_lower_name" in indexes

            # Downgrade again cleanly
            command.downgrade(cfg, PREVIOUS_REVISION)
            indexes_after_down = {i["name"] for i in inspect(engine).get_indexes("shifts")}
            assert "uq_shifts_company_lower_name" not in indexes_after_down

            command.upgrade(cfg, "head")
        finally:
            _clean()
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": company_id})
            engine.dispose()
