import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole
from tests.conftest import TEST_PASSWORD


def _create_user_and_token(db: Session, company_id: uuid.UUID, role: UserRole) -> dict[str, str]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"{role.value}_{uuid.uuid4().hex[:6]}@{company_id}.test",
        hashed_password=hash_password(TEST_PASSWORD),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


def _create_test_emp(db: Session, company_id: uuid.UUID, prefix: str) -> uuid.UUID:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    emp = Employee(
        company_id=company_id,
        employee_code=f"E-{uuid.uuid4().hex[:6].upper()}",
        first_name=prefix,
        last_name="Target",
        email=f"{prefix.lower()}_{uuid.uuid4().hex[:6]}@example.com",
        hire_date=date(2025, 1, 1),
        notice_period_days=30,
        is_active=True,
    )
    db.add(emp)
    db.commit()
    return emp.id


def test_documents_access_owner_consistency(client: TestClient, db: Session, company_a, company_b):
    """Platform documents: owner of same company allowed, other company blocked."""
    emp_a_id = _create_test_emp(db, company_a.company_id, "Doc")

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)
    employee_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.employee)

    # 1. Employee who is not the target gets 403
    res_emp = client.get(f"/api/v1/documents/{emp_a_id}", headers=employee_a_headers)
    assert res_emp.status_code == 403

    # 2. Owner of company_b gets 403 or 404
    res_owner_b = client.get(f"/api/v1/documents/{emp_a_id}", headers=owner_b_headers)
    assert res_owner_b.status_code in (403, 404)

    # 3. Owner of company_a gets 200
    res_owner_a = client.get(f"/api/v1/documents/{emp_a_id}", headers=owner_a_headers)
    assert res_owner_a.status_code == 200


def test_resignation_submission_owner_consistency(
    client: TestClient, db: Session, company_a, company_b
):
    """HR resignation: owner allowed to submit for employee, other company blocked."""
    emp_a_id = _create_test_emp(db, company_a.company_id, "Resign")

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)
    employee_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.employee)

    payload = {
        "resignation_date": "2026-10-01",
        "last_working_date": "2026-10-31",
        "reason": "Relocating",
    }

    # 1. Employee who is not target gets 403
    url = f"/api/v1/employees/{emp_a_id}/resignation"
    res_emp = client.post(url, json=payload, headers=employee_a_headers)
    assert res_emp.status_code == 403

    # 2. Owner of company_b gets 403 or 404
    res_owner_b = client.post(url, json=payload, headers=owner_b_headers)
    assert res_owner_b.status_code in (403, 404)

    # 3. Owner of company_a gets 200
    res_owner_a = client.post(url, json=payload, headers=owner_a_headers)
    assert res_owner_a.status_code == 200


def test_calculate_fnf_owner_consistency(client: TestClient, db: Session, company_a, company_b):
    """HR calculate_fnf: owner of same company allowed, other company blocked."""
    emp_a_id = _create_test_emp(db, company_a.company_id, "FnF")

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)
    employee_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.employee)

    # 1. Employee gets 403
    res_emp = client.get(f"/api/v1/employees/{emp_a_id}/fnf", headers=employee_a_headers)
    assert res_emp.status_code == 403

    # 2. Owner of company_b gets 403 or 404
    res_owner_b = client.get(f"/api/v1/employees/{emp_a_id}/fnf", headers=owner_b_headers)
    assert res_owner_b.status_code in (403, 404)

    # 3. Owner of company_a gets 200
    res_owner_a = client.get(f"/api/v1/employees/{emp_a_id}/fnf", headers=owner_a_headers)
    assert res_owner_a.status_code == 200


def test_shift_lookup_owner_consistency(client: TestClient, db: Session, company_a, company_b):
    """Time/Leave assigned shift lookup: owner allowed, other company blocked."""
    emp_a_id = _create_test_emp(db, company_a.company_id, "Shift")

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)
    employee_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.employee)

    # 1. Other employee gets 403
    res_emp = client.get(f"/api/v1/shifts/assigned/{emp_a_id}", headers=employee_a_headers)
    assert res_emp.status_code == 403

    # 2. Owner of company_b gets 403 or 404
    res_owner_b = client.get(f"/api/v1/shifts/assigned/{emp_a_id}", headers=owner_b_headers)
    assert res_owner_b.status_code in (403, 404)

    # 3. Owner of company_a gets 200
    res_owner_a = client.get(f"/api/v1/shifts/assigned/{emp_a_id}", headers=owner_a_headers)
    assert res_owner_a.status_code == 200


def test_leave_balance_owner_consistency(
    client: TestClient, db: Session, company_a, company_b, super_admin_headers
):
    """Time/Leave balance lookup: owner and super_admin allowed, other company blocked."""
    emp_a_id = _create_test_emp(db, company_a.company_id, "Leave")

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)
    employee_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.employee)

    # 1. Other employee gets 403
    res_emp = client.get(f"/api/v1/leaves/balance/{emp_a_id}?year=2026", headers=employee_a_headers)
    assert res_emp.status_code == 403

    # 2. Owner of company_b gets 403 or 404
    res_owner_b = client.get(
        f"/api/v1/leaves/balance/{emp_a_id}?year=2026", headers=owner_b_headers
    )
    assert res_owner_b.status_code in (403, 404)

    # 3. Super admin gets 200
    res_sa = client.get(f"/api/v1/leaves/balance/{emp_a_id}?year=2026", headers=super_admin_headers)
    assert res_sa.status_code == 200

    # 4. Owner of company_a gets 200
    res_owner_a = client.get(
        f"/api/v1/leaves/balance/{emp_a_id}?year=2026", headers=owner_a_headers
    )
    assert res_owner_a.status_code == 200


def test_salary_view_owner_consistency(
    client: TestClient, db: Session, company_a, company_b, super_admin_headers
):
    """Payroll salary lookup: owner and super_admin allowed, other company blocked."""
    emp_a_id = _create_test_emp(db, company_a.company_id, "Salary")

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

    assign_res = client.post(
        f"/api/v1/payroll/employees/{emp_a_id}/assign",
        headers=company_a.hr_headers,
        json={
            "structure_id": struct_id,
            "ctc": "600000.00",
            "effective_from": date.today().isoformat(),
            "revision_reason": "Hired",
        },
    )
    assert assign_res.status_code == 201

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)
    employee_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.employee)

    # 1. Other employee gets 403
    res_emp = client.get(f"/api/v1/payroll/employees/{emp_a_id}/salary", headers=employee_a_headers)
    assert res_emp.status_code == 403

    # 2. Owner of company_b gets 403 or 404
    res_owner_b = client.get(
        f"/api/v1/payroll/employees/{emp_a_id}/salary", headers=owner_b_headers
    )
    assert res_owner_b.status_code in (403, 404)

    # 3. Super admin gets 200
    res_sa = client.get(f"/api/v1/payroll/employees/{emp_a_id}/salary", headers=super_admin_headers)
    assert res_sa.status_code == 200

    # 4. Owner of company_a gets 200
    res_owner_a = client.get(
        f"/api/v1/payroll/employees/{emp_a_id}/salary", headers=owner_a_headers
    )
    assert res_owner_a.status_code == 200


def _create_test_leave_type(client: TestClient, hr_headers: dict[str, str]) -> str:
    res = client.post(
        "/api/v1/leave-types",
        headers=hr_headers,
        json={
            "name": f"Annual Leave {uuid.uuid4().hex[:6]}",
            "code": f"AL-{uuid.uuid4().hex[:6]}",
            "annual_allowance": "20",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_apply_leave_owner_consistency(client: TestClient, db: Session, company_a, company_b):
    """LeaveService.apply_leave (on behalf of employee):
    Owner of same company allowed, other company blocked.
    """
    emp_a_id = _create_test_emp(db, company_a.company_id, "Apply")
    leave_type_id = _create_test_leave_type(client, company_a.hr_headers)

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)
    employee_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.employee)

    payload = {
        "employee_id": str(emp_a_id),
        "leave_type_id": leave_type_id,
        "start_date": "2026-11-02",
        "end_date": "2026-11-03",
        "reason": "Applying on behalf",
    }

    # 1. Other employee applying on behalf of emp_a gets 403
    res_emp = client.post("/api/v1/leaves", json=payload, headers=employee_a_headers)
    assert res_emp.status_code == 403

    # 2. Owner of company_b gets 403 or 404
    res_owner_b = client.post("/api/v1/leaves", json=payload, headers=owner_b_headers)
    assert res_owner_b.status_code in (403, 404)

    # 3. Owner of company_a gets 201 (fails before fix: 403)
    res_owner_a = client.post("/api/v1/leaves", json=payload, headers=owner_a_headers)
    assert res_owner_a.status_code == 201


def test_get_leave_owner_consistency(client: TestClient, db: Session, company_a, company_b):
    """LeaveService.get_leave: owner of same company allowed, other company blocked."""
    emp_a_id = _create_test_emp(db, company_a.company_id, "GetLeave")
    leave_type_id = _create_test_leave_type(client, company_a.hr_headers)

    # Apply leave via HR headers
    apply_res = client.post(
        "/api/v1/leaves",
        json={
            "employee_id": str(emp_a_id),
            "leave_type_id": leave_type_id,
            "start_date": "2026-11-09",
            "end_date": "2026-11-10",
            "reason": "Vacation",
        },
        headers=company_a.hr_headers,
    )
    assert apply_res.status_code == 201
    leave_id = apply_res.json()["id"]

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)
    employee_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.employee)

    # 1. Other employee gets 403
    res_emp = client.get(f"/api/v1/leaves/{leave_id}", headers=employee_a_headers)
    assert res_emp.status_code == 403

    # 2. Owner of company_b gets 403 or 404
    res_owner_b = client.get(f"/api/v1/leaves/{leave_id}", headers=owner_b_headers)
    assert res_owner_b.status_code in (403, 404)

    # 3. Owner of company_a gets 200 (fails before fix: 403)
    res_owner_a = client.get(f"/api/v1/leaves/{leave_id}", headers=owner_a_headers)
    assert res_owner_a.status_code == 200


def test_cancel_leave_owner_consistency(client: TestClient, db: Session, company_a, company_b):
    """LeaveService.cancel_leave:
    Owner of same company allowed to cancel approved leave, other company blocked.
    """
    emp_a_id = _create_test_emp(db, company_a.company_id, "Cancel")
    leave_type_id = _create_test_leave_type(client, company_a.hr_headers)

    # Apply leave via HR headers (pending)
    apply_res = client.post(
        "/api/v1/leaves",
        json={
            "employee_id": str(emp_a_id),
            "leave_type_id": leave_type_id,
            "start_date": "2026-11-16",
            "end_date": "2026-11-17",
            "reason": "Personal",
        },
        headers=company_a.hr_headers,
    )
    assert apply_res.status_code == 201
    leave_id = apply_res.json()["id"]

    # Approve leave via HR headers
    app_res = client.put(
        f"/api/v1/leaves/{leave_id}",
        json={"status": "approved"},
        headers=company_a.hr_headers,
    )
    assert app_res.status_code == 200

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)
    employee_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.employee)

    # 1. Other employee gets 403 when trying to cancel approved leave
    res_emp = client.delete(f"/api/v1/leaves/{leave_id}", headers=employee_a_headers)
    assert res_emp.status_code == 403

    # 2. Owner of company_b gets 403 or 404
    res_owner_b = client.delete(f"/api/v1/leaves/{leave_id}", headers=owner_b_headers)
    assert res_owner_b.status_code in (403, 404)

    # 3. Owner of company_a gets 200 (fails before fix: 403)
    res_owner_a = client.delete(f"/api/v1/leaves/{leave_id}", headers=owner_a_headers)
    assert res_owner_a.status_code == 200


def test_update_performance_goal_owner_consistency(
    client: TestClient, db: Session, company_a, company_b
):
    """PUT /api/v1/performance/goals/{id}:
    Owner of same company updates employee's goal and gets 200,
    Owner of other company gets 403 or 404,
    Ordinary employee who does not own the goal gets 403.
    """
    # 1. Create active performance cycle in company_a
    cycle_res = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": f"Cycle {uuid.uuid4().hex[:6]}",
            "cycle_type": "quarterly",
            "start_date": "2026-07-01",
            "end_date": "2026-09-30",
        },
        headers=company_a.hr_headers,
    )
    assert cycle_res.status_code == 201, cycle_res.text
    cycle_id = cycle_res.json()["id"]

    client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=company_a.hr_headers,
    )

    # 2. Create target employee with associated user account
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    target_user = User(
        company_id=company_a.company_id,
        email=f"target_goal_{uuid.uuid4().hex[:6]}@{company_a.company_id}.test",
        hashed_password=hash_password(TEST_PASSWORD),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(target_user)
    db.flush()

    target_emp = Employee(
        company_id=company_a.company_id,
        user_id=target_user.id,
        employee_code=f"E-{uuid.uuid4().hex[:6].upper()}",
        first_name="GoalTarget",
        last_name="Emp",
        email=target_user.email,
        hire_date=date(2025, 1, 1),
        notice_period_days=30,
        is_active=True,
    )
    db.add(target_emp)
    db.commit()

    target_token = create_access_token(
        sub=str(target_user.id),
        company_id=str(company_a.company_id),
        role=UserRole.employee.value,
    )
    target_headers = {"Authorization": f"Bearer {target_token}"}

    # Target employee creates their own goal
    goals_res = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": cycle_id,
            "goals": [
                {
                    "title": "Initial Goal",
                    "description": "Initial Description",
                    "weightage": "100.00",
                    "target_value": "Initial Target",
                }
            ],
        },
        headers=target_headers,
    )
    assert goals_res.status_code == 201, goals_res.text
    goal_id = goals_res.json()[0]["id"]

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)
    other_employee_headers = _create_user_and_token(db, company_a.company_id, UserRole.employee)

    update_payload = {"title": "Updated by Someone"}

    # 3. Ordinary employee who does not own the goal gets 403
    res_emp = client.put(
        f"/api/v1/performance/goals/{goal_id}",
        json=update_payload,
        headers=other_employee_headers,
    )
    assert res_emp.status_code == 403

    # 4. Owner of company_b gets 403 or 404
    res_owner_b = client.put(
        f"/api/v1/performance/goals/{goal_id}",
        json=update_payload,
        headers=owner_b_headers,
    )
    assert res_owner_b.status_code in (403, 404)

    # 5. Owner of same company updates another employee's goal and gets 200 (fails before fix: 403)
    res_owner_a = client.put(
        f"/api/v1/performance/goals/{goal_id}",
        json={"title": "Updated by Owner A"},
        headers=owner_a_headers,
    )
    assert res_owner_a.status_code == 200
    assert res_owner_a.json()["title"] == "Updated by Owner A"
