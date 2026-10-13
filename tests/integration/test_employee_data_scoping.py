import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole
from app.modules.performance.models import PerformancePIP
from tests.conftest import TenantContext
from tests.integration.test_employees import _create_employee


def _link_user_to_employee(
    db: Session, company_id: uuid.UUID, employee_id: str, role: UserRole
) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
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
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────────────────────
# 1. GET /api/v1/shifts/assigned/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────


def test_assigned_shift_colleague_forbidden_or_safe(
    client: TestClient, db: Session, company_a: TenantContext
):
    """1. GET /api/v1/shifts/assigned/{employee_id} - colleague access check"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp_colleague = _create_employee(
        client, company_a.hr_headers, email=f"emp-col-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    # Assign a shift to colleague
    shift_res = client.post(
        "/api/v1/shifts",
        headers=company_a.hr_headers,
        json={
            "name": f"Shift-{uuid.uuid4().hex[:4]}",
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    assert shift_res.status_code == 201
    shift_id = shift_res.json()["id"]

    assign_res = client.post(
        f"/api/v1/shifts/{shift_id}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": emp_colleague["id"], "effective_from": date.today().isoformat()},
    )
    assert assign_res.status_code == 201

    # Caller asks for colleague's assigned shift
    res = client.get(f"/api/v1/shifts/assigned/{emp_colleague['id']}", headers=headers_own)
    # Expected safe behavior: 403, or None/empty, or not returning colleague's shift details.
    # Returning 200 with the colleague's assigned shift is a LEAK!
    assert res.status_code == 403 or (res.status_code == 200 and res.json() is None), (
        f"Colleague assigned shift leaked: {res.status_code} {res.text}"
    )


def test_assigned_shift_own_allowed(client: TestClient, db: Session, company_a: TenantContext):
    """1. GET /api/v1/shifts/assigned/{employee_id} - own access allowed"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    shift_res = client.post(
        "/api/v1/shifts",
        headers=company_a.hr_headers,
        json={
            "name": f"Shift-{uuid.uuid4().hex[:4]}",
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    assert shift_res.status_code == 201
    shift_id = shift_res.json()["id"]

    client.post(
        f"/api/v1/shifts/{shift_id}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": emp_own["id"], "effective_from": date.today().isoformat()},
    )

    res = client.get(f"/api/v1/shifts/assigned/{emp_own['id']}", headers=headers_own)
    assert res.status_code == 200, res.text
    assert res.json() is not None


def test_assigned_shift_hr_admin_own_company_allowed(client: TestClient, company_a: TenantContext):
    """1. GET /api/v1/shifts/assigned/{employee_id} - hr_admin reads shift in own company allowed"""
    emp = _create_employee(
        client, company_a.hr_headers, email=f"emp-{uuid.uuid4().hex[:6]}@example.com"
    )
    shift_res = client.post(
        "/api/v1/shifts",
        headers=company_a.hr_headers,
        json={
            "name": f"Shift-{uuid.uuid4().hex[:4]}",
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    assert shift_res.status_code == 201
    shift_id = shift_res.json()["id"]

    client.post(
        f"/api/v1/shifts/{shift_id}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": emp["id"], "effective_from": date.today().isoformat()},
    )

    res = client.get(f"/api/v1/shifts/assigned/{emp['id']}", headers=company_a.hr_headers)
    assert res.status_code == 200, res.text
    assert res.json() is not None


def test_assigned_shift_hr_admin_cross_company_denied(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
):
    """1. GET /api/v1/shifts/assigned/{employee_id} -
    hr_admin from another company denied (403 or 404)
    """
    emp_b = _create_employee(
        client, company_b.hr_headers, email=f"emp-b-{uuid.uuid4().hex[:6]}@example.com"
    )
    res = client.get(f"/api/v1/shifts/assigned/{emp_b['id']}", headers=company_a.hr_headers)
    assert res.status_code in (403, 404), res.text


def test_assigned_shift_unauthenticated_denied(client: TestClient, company_a: TenantContext):
    """1. GET /api/v1/shifts/assigned/{employee_id} - unauthenticated denied (401)"""
    emp = _create_employee(
        client, company_a.hr_headers, email=f"emp-{uuid.uuid4().hex[:6]}@example.com"
    )
    res = client.get(f"/api/v1/shifts/assigned/{emp['id']}")
    assert res.status_code == 401, res.text


# ─────────────────────────────────────────────────────────────────────────────
# 2. GET /api/v1/performance/pips?employee_id=
# ─────────────────────────────────────────────────────────────────────────────


def test_performance_pips_query_colleague_forbidden_or_safe(
    client: TestClient, db: Session, company_a: TenantContext
):
    """2. GET /api/v1/performance/pips?employee_id= - colleague access check"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp_colleague = _create_employee(
        client, company_a.hr_headers, email=f"emp-col-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    # Seed PIP directly into database for colleague to test endpoint scoping
    colleague_pip = PerformancePIP(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp_colleague["id"]),
        title="Colleague Improvement Plan",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
        status="active",
    )
    db.add(colleague_pip)
    db.commit()
    colleague_pip_id = str(colleague_pip.id)

    # Caller asks for colleague's pips
    res = client.get(
        f"/api/v1/performance/pips?employee_id={emp_colleague['id']}", headers=headers_own
    )
    assert res.status_code in (200, 403), res.text
    if res.status_code == 200:
        returned_ids = [p["id"] for p in res.json()]
        assert colleague_pip_id not in returned_ids, "Colleague PIP leaked!"


def test_performance_pips_query_own_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """2. GET /api/v1/performance/pips?employee_id= - own access allowed"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    own_pip = PerformancePIP(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp_own["id"]),
        title="Own Improvement Plan",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
        status="active",
    )
    db.add(own_pip)
    db.commit()
    own_pip_id = str(own_pip.id)

    res = client.get(f"/api/v1/performance/pips?employee_id={emp_own['id']}", headers=headers_own)
    assert res.status_code == 200, res.text
    returned_ids = [p["id"] for p in res.json()]
    assert own_pip_id in returned_ids


# ─────────────────────────────────────────────────────────────────────────────
# 3. GET /api/v1/projects/time-entries?employee_id=
# ─────────────────────────────────────────────────────────────────────────────


def test_projects_time_entries_query_colleague_forbidden_or_safe(
    client: TestClient, db: Session, company_a: TenantContext
):
    """3. GET /api/v1/projects/time-entries?employee_id= - colleague access check"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp_colleague = _create_employee(
        client, company_a.hr_headers, email=f"emp-col-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)
    headers_colleague = _link_user_to_employee(
        db, company_a.company_id, emp_colleague["id"], UserRole.employee
    )

    proj_res = client.post(
        "/api/v1/projects",
        headers=company_a.hr_headers,
        json={
            "name": f"Project-{uuid.uuid4().hex[:4]}",
            "code": f"PRJ-{uuid.uuid4().hex[:4]}",
            "status": "active",
        },
    )
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    # Colleague logs a time entry
    entry_res = client.post(
        "/api/v1/projects/time-entries",
        headers=headers_colleague,
        json={
            "project_id": project_id,
            "date": date.today().isoformat(),
            "hours": "4.00",
            "description": "Colleague secret work",
        },
    )
    assert entry_res.status_code == 201, entry_res.text
    colleague_entry_id = entry_res.json()["id"]

    # Caller employee requests colleague's entries
    res = client.get(
        f"/api/v1/projects/time-entries?employee_id={emp_colleague['id']}", headers=headers_own
    )
    assert res.status_code in (200, 403), res.text
    if res.status_code == 200:
        returned_ids = [e["id"] for e in res.json()]
        assert colleague_entry_id not in returned_ids, "Colleague time entry leaked!"


def test_projects_time_entries_query_own_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """3. GET /api/v1/projects/time-entries?employee_id= - own access allowed"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    proj_res = client.post(
        "/api/v1/projects",
        headers=company_a.hr_headers,
        json={
            "name": f"Project-{uuid.uuid4().hex[:4]}",
            "code": f"PRJ-{uuid.uuid4().hex[:4]}",
            "status": "active",
        },
    )
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    entry_res = client.post(
        "/api/v1/projects/time-entries",
        headers=headers_own,
        json={
            "project_id": project_id,
            "date": date.today().isoformat(),
            "hours": "5.00",
            "description": "Own time entry",
        },
    )
    assert entry_res.status_code == 201, entry_res.text
    own_entry_id = entry_res.json()["id"]

    res = client.get(
        f"/api/v1/projects/time-entries?employee_id={emp_own['id']}", headers=headers_own
    )
    assert res.status_code == 200, res.text
    returned_ids = [e["id"] for e in res.json()]
    assert own_entry_id in returned_ids


# ─────────────────────────────────────────────────────────────────────────────
# 4. GET /api/v1/attendance?employee_id=
# ─────────────────────────────────────────────────────────────────────────────


def test_attendance_query_colleague_forbidden_or_safe(
    client: TestClient, db: Session, company_a: TenantContext
):
    """4. GET /api/v1/attendance?employee_id= - colleague access check"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp_colleague = _create_employee(
        client, company_a.hr_headers, email=f"emp-col-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)
    headers_colleague = _link_user_to_employee(
        db, company_a.company_id, emp_colleague["id"], UserRole.employee
    )

    checkin_res = client.post("/api/v1/attendance/check-in", headers=headers_colleague)
    assert checkin_res.status_code == 201
    colleague_att_id = checkin_res.json()["id"]

    # Caller requests colleague's attendance
    res = client.get(f"/api/v1/attendance?employee_id={emp_colleague['id']}", headers=headers_own)
    assert res.status_code in (200, 403), res.text
    if res.status_code == 200:
        returned_ids = [r["id"] for r in res.json()["items"]]
        assert colleague_att_id not in returned_ids, "Colleague attendance record leaked!"


def test_attendance_query_own_allowed(client: TestClient, db: Session, company_a: TenantContext):
    """4. GET /api/v1/attendance?employee_id= - own access allowed"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    checkin_res = client.post("/api/v1/attendance/check-in", headers=headers_own)
    assert checkin_res.status_code == 201
    own_att_id = checkin_res.json()["id"]

    res = client.get(f"/api/v1/attendance?employee_id={emp_own['id']}", headers=headers_own)
    assert res.status_code == 200, res.text
    returned_ids = [r["id"] for r in res.json()["items"]]
    assert own_att_id in returned_ids


# Note: Route 5 'GET /api/v1/attendance/records' does not exist in the codebase;
# attendance records are listed via 'GET /api/v1/attendance?employee_id=' (tested in Route 4).


# ─────────────────────────────────────────────────────────────────────────────
# 6. GET /api/v1/leaves?employee_id=
# ─────────────────────────────────────────────────────────────────────────────


def test_leaves_query_colleague_forbidden_or_safe(
    client: TestClient, db: Session, company_a: TenantContext
):
    """6. GET /api/v1/leaves?employee_id= - colleague access check"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp_colleague = _create_employee(
        client, company_a.hr_headers, email=f"emp-col-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)
    headers_colleague = _link_user_to_employee(
        db, company_a.company_id, emp_colleague["id"], UserRole.employee
    )

    # Colleague applies for leave
    lt_res = client.post(
        "/api/v1/leave-types",
        headers=company_a.hr_headers,
        json={
            "name": f"LT-{uuid.uuid4().hex[:4]}",
            "code": f"lt_{uuid.uuid4().hex[:4]}",
            "annual_allowance": "10",
        },
    )
    assert lt_res.status_code == 201
    leave_type_id = lt_res.json()["id"]

    leave_res = client.post(
        "/api/v1/leaves",
        headers=headers_colleague,
        json={
            "leave_type_id": leave_type_id,
            "start_date": "2030-05-10",
            "end_date": "2030-05-12",
            "reason": "Colleague vacation",
        },
    )
    assert leave_res.status_code == 201, leave_res.text
    colleague_leave_id = leave_res.json()["id"]

    # Caller requests colleague's leaves
    res = client.get(f"/api/v1/leaves?employee_id={emp_colleague['id']}", headers=headers_own)
    assert res.status_code in (200, 403), res.text
    if res.status_code == 200:
        returned_ids = [item["id"] for item in res.json()["items"]]
        assert colleague_leave_id not in returned_ids, "Colleague leave record leaked!"


def test_leaves_query_own_allowed(client: TestClient, db: Session, company_a: TenantContext):
    """6. GET /api/v1/leaves?employee_id= - own access allowed"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    lt_res = client.post(
        "/api/v1/leave-types",
        headers=company_a.hr_headers,
        json={
            "name": f"LT-{uuid.uuid4().hex[:4]}",
            "code": f"lt_{uuid.uuid4().hex[:4]}",
            "annual_allowance": "10",
        },
    )
    assert lt_res.status_code == 201
    leave_type_id = lt_res.json()["id"]

    leave_res = client.post(
        "/api/v1/leaves",
        headers=headers_own,
        json={
            "leave_type_id": leave_type_id,
            "start_date": "2030-06-10",
            "end_date": "2030-06-12",
            "reason": "Own vacation",
        },
    )
    assert leave_res.status_code == 201, leave_res.text
    own_leave_id = leave_res.json()["id"]

    res = client.get(f"/api/v1/leaves?employee_id={emp_own['id']}", headers=headers_own)
    assert res.status_code == 200, res.text
    returned_ids = [item["id"] for item in res.json()["items"]]
    assert own_leave_id in returned_ids


# ─────────────────────────────────────────────────────────────────────────────
# 7. GET /api/v1/payroll/employees/{employee_id}/salary
# ─────────────────────────────────────────────────────────────────────────────


def test_payroll_salary_colleague_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """7. GET /api/v1/payroll/employees/{employee_id}/salary - colleague access forbidden"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp_colleague = _create_employee(
        client, company_a.hr_headers, email=f"emp-col-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    # Assign salary to colleague
    struct_res = client.post(
        "/api/v1/payroll/structures",
        headers=company_a.hr_headers,
        json={
            "name": f"Struct-{uuid.uuid4().hex[:4]}",
            "components": [
                {
                    "name": "Basic",
                    "code": "BASIC",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "value": "100.00",
                    "percentage_of": "ctc",
                    "is_taxable": True,
                    "is_statutory": False,
                    "display_order": 1,
                }
            ],
        },
    )
    assert struct_res.status_code == 201
    struct_id = struct_res.json()["id"]

    client.post(
        f"/api/v1/payroll/employees/{emp_colleague['id']}/assign",
        headers=company_a.hr_headers,
        json={
            "structure_id": struct_id,
            "ctc": "600000.00",
            "effective_from": date.today().isoformat(),
            "revision_reason": "Hired",
        },
    )

    res = client.get(f"/api/v1/payroll/employees/{emp_colleague['id']}/salary", headers=headers_own)
    assert res.status_code == 403, res.text


def test_payroll_salary_own_allowed(client: TestClient, db: Session, company_a: TenantContext):
    """7. GET /api/v1/payroll/employees/{employee_id}/salary - own access allowed"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    struct_res = client.post(
        "/api/v1/payroll/structures",
        headers=company_a.hr_headers,
        json={
            "name": f"Struct-{uuid.uuid4().hex[:4]}",
            "components": [
                {
                    "name": "Basic",
                    "code": "BASIC",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "value": "100.00",
                    "percentage_of": "ctc",
                    "is_taxable": True,
                    "is_statutory": False,
                    "display_order": 1,
                }
            ],
        },
    )
    assert struct_res.status_code == 201
    struct_id = struct_res.json()["id"]

    client.post(
        f"/api/v1/payroll/employees/{emp_own['id']}/assign",
        headers=company_a.hr_headers,
        json={
            "structure_id": struct_id,
            "ctc": "600000.00",
            "effective_from": date.today().isoformat(),
            "revision_reason": "Hired",
        },
    )

    res = client.get(f"/api/v1/payroll/employees/{emp_own['id']}/salary", headers=headers_own)
    assert res.status_code == 200, res.text
    assert res.json()["ctc"] == "600000.00"


# ─────────────────────────────────────────────────────────────────────────────
# 8. GET /api/v1/leaves/balance/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────


def test_leaves_balance_colleague_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """8. GET /api/v1/leaves/balance/{employee_id} - colleague access forbidden"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp_colleague = _create_employee(
        client, company_a.hr_headers, email=f"emp-col-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    res = client.get(f"/api/v1/leaves/balance/{emp_colleague['id']}", headers=headers_own)
    assert res.status_code == 403, res.text


def test_leaves_balance_own_allowed(client: TestClient, db: Session, company_a: TenantContext):
    """8. GET /api/v1/leaves/balance/{employee_id} - own access allowed"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    res = client.get(f"/api/v1/leaves/balance/{emp_own['id']}", headers=headers_own)
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), list)


# ─────────────────────────────────────────────────────────────────────────────
# 9. GET /api/v1/performance/pips/active/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────


def test_performance_pips_active_colleague_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """9. GET /api/v1/performance/pips/active/{employee_id} - colleague access forbidden"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp_colleague = _create_employee(
        client, company_a.hr_headers, email=f"emp-col-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    # Seed active PIP for colleague
    colleague_pip = PerformancePIP(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp_colleague["id"]),
        title="Colleague Active PIP",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
        status="active",
    )
    db.add(colleague_pip)
    db.commit()

    res = client.get(f"/api/v1/performance/pips/active/{emp_colleague['id']}", headers=headers_own)
    assert res.status_code == 403, res.text


def test_performance_pips_active_own_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """9. GET /api/v1/performance/pips/active/{employee_id} - own access allowed"""
    emp_own = _create_employee(
        client, company_a.hr_headers, email=f"emp-own-{uuid.uuid4().hex[:6]}@example.com"
    )
    headers_own = _link_user_to_employee(db, company_a.company_id, emp_own["id"], UserRole.employee)

    own_pip = PerformancePIP(
        company_id=company_a.company_id,
        employee_id=uuid.UUID(emp_own["id"]),
        title="Own Active PIP",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
        status="active",
    )
    db.add(own_pip)
    db.commit()

    res = client.get(f"/api/v1/performance/pips/active/{emp_own['id']}", headers=headers_own)
    assert res.status_code == 200, res.text
    assert res.json() is not None
