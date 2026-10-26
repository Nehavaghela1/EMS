import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole
from tests.conftest import TenantContext
from tests.integration.test_employees import _create_employee


def _link_user_to_employee(
    db: Session,
    company_id: uuid.UUID,
    employee_id: str,
    role: UserRole,
    is_active: bool = True,
) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    employee = db.get(Employee, uuid.UUID(employee_id))
    assert employee is not None
    employee.user_id = user.id
    if not is_active:
        employee.is_active = False
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# A. PUT /employees/{id}/fnf/clearance
# =============================================================================


def test_fnf_clearance_manager_scoping(client: TestClient, db: Session, company_a: TenantContext):
    """
    A. a manager whose department has NO clearance_function sends an empty body
       to the fnf/clearance route for another employee: expect 403, not 200 with salary data.
       A manager in a finance-function department can still adjust finance fields (unchanged).
       A manager in an it-function department still cannot touch finance fields (unchanged).
       hr_admin and owner unchanged.
    """
    # 1. Create departments:
    # - dept with NO clearance_function
    dept_ops_res = client.post(
        "/api/v1/departments",
        headers=company_a.hr_headers,
        json={"name": f"Operations-{uuid.uuid4().hex[:4]}", "clearance_function": None},
    )
    assert dept_ops_res.status_code == 201
    dept_ops_id = dept_ops_res.json()["id"]

    # - dept with clearance_function = 'finance'
    dept_fin_res = client.post(
        "/api/v1/departments",
        headers=company_a.hr_headers,
        json={"name": f"Finance-{uuid.uuid4().hex[:4]}", "clearance_function": "finance"},
    )
    assert dept_fin_res.status_code == 201
    dept_fin_id = dept_fin_res.json()["id"]

    # - dept with clearance_function = 'it'
    dept_it_res = client.post(
        "/api/v1/departments",
        headers=company_a.hr_headers,
        json={"name": f"IT-{uuid.uuid4().hex[:4]}", "clearance_function": "it"},
    )
    assert dept_it_res.status_code == 201
    dept_it_id = dept_it_res.json()["id"]

    # 2. Managers
    ops_mgr = _create_employee(
        client,
        company_a.hr_headers,
        email=f"opsmgr-{uuid.uuid4().hex[:6]}@example.com",
        department_id=dept_ops_id,
    )
    ops_mgr_headers = _link_user_to_employee(
        db, company_a.company_id, ops_mgr["id"], UserRole.manager
    )

    fin_mgr = _create_employee(
        client,
        company_a.hr_headers,
        email=f"finmgr-{uuid.uuid4().hex[:6]}@example.com",
        department_id=dept_fin_id,
    )
    fin_mgr_headers = _link_user_to_employee(
        db, company_a.company_id, fin_mgr["id"], UserRole.manager
    )

    it_mgr = _create_employee(
        client,
        company_a.hr_headers,
        email=f"itmgr-{uuid.uuid4().hex[:6]}@example.com",
        department_id=dept_it_id,
    )
    it_mgr_headers = _link_user_to_employee(
        db, company_a.company_id, it_mgr["id"], UserRole.manager
    )

    # Departing employee
    emp = _create_employee(
        client,
        company_a.hr_headers,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.com",
    )
    emp_headers = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    # Resignation
    res_post = client.post(
        f"/api/v1/employees/{emp['id']}/resignation",
        headers=emp_headers,
        json={"resignation_date": "2026-09-01", "last_working_date": "2026-10-01"},
    )
    assert res_post.status_code == 200
    client.put(
        f"/api/v1/employees/{emp['id']}/resignation/approve",
        headers=company_a.hr_headers,
        json={"approved": True},
    )

    # Test 1: Manager whose dept has NO clearance_function sends empty body -> 403
    res_ops_empty = client.put(
        f"/api/v1/employees/{emp['id']}/fnf/clearance",
        headers=ops_mgr_headers,
        json={},
    )
    assert res_ops_empty.status_code == 403, (
        f"Expected 403, got {res_ops_empty.status_code}: {res_ops_empty.text}"
    )

    # Test 2: Finance manager can adjust finance fields -> 200
    res_fin = client.put(
        f"/api/v1/employees/{emp['id']}/fnf/clearance",
        headers=fin_mgr_headers,
        json={"finance_clearance": True, "severance_pay": "5000.00"},
    )
    assert res_fin.status_code == 200, f"Expected 200, got {res_fin.status_code}: {res_fin.text}"

    # Test 3: IT manager cannot touch finance fields -> 403
    res_it_fin = client.put(
        f"/api/v1/employees/{emp['id']}/fnf/clearance",
        headers=it_mgr_headers,
        json={"severance_pay": "2000.00"},
    )
    assert res_it_fin.status_code == 403, (
        f"Expected 403, got {res_it_fin.status_code}: {res_it_fin.text}"
    )

    # Test 4: hr_admin unchanged -> 200
    res_hr = client.put(
        f"/api/v1/employees/{emp['id']}/fnf/clearance",
        headers=company_a.hr_headers,
        json={"hr_clearance": True},
    )
    assert res_hr.status_code == 200, f"Expected 200, got {res_hr.status_code}: {res_hr.text}"

    # Test 5: owner unchanged -> 200
    owner_user = User(
        company_id=company_a.company_id,
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.owner,
        is_active=True,
    )
    db.add(owner_user)
    db.commit()
    owner_token = create_access_token(
        sub=str(owner_user.id), company_id=str(company_a.company_id), role=UserRole.owner.value
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    res_owner = client.put(
        f"/api/v1/employees/{emp['id']}/fnf/clearance",
        headers=owner_headers,
        json={"it_clearance": True},
    )
    assert res_owner.status_code == 200, (
        f"Expected 200, got {res_owner.status_code}: {res_owner.text}"
    )


# =============================================================================
# B. list_performance_goals (GET /performance/goals/{employee_id})
# =============================================================================


def test_performance_goals_manager_scoping(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    """
    B. a manager reads their own goals: 200.
       A manager reads a direct report's goals: 200.
       A manager reads a skip-level report's goals: 200.
       A manager reads goals of an employee outside their chain: 403.
       An employee reading their own goals is unchanged, another employee's goals is 403.
       hr_admin and owner unchanged.
       A manager of another company: 403 or 404.
    """
    # Active cycle for company_a
    cycle_res = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": f"Cycle-{uuid.uuid4().hex[:4]}",
            "cycle_type": "quarterly",
            "start_date": "2026-07-01",
            "end_date": "2026-09-30",
        },
        headers=company_a.hr_headers,
    )
    assert cycle_res.status_code == 201
    cycle_id = cycle_res.json()["id"]
    client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=company_a.hr_headers,
    )

    # 1. Senior Manager
    senior_emp = _create_employee(
        client, company_a.hr_headers, email=f"senior-{uuid.uuid4().hex[:6]}@example.com"
    )
    senior_headers = _link_user_to_employee(
        db, company_a.company_id, senior_emp["id"], UserRole.manager
    )

    # 2. Direct Manager (reports to Senior)
    direct_mgr_emp = _create_employee(
        client,
        company_a.hr_headers,
        email=f"direct-{uuid.uuid4().hex[:6]}@example.com",
        reporting_manager_id=senior_emp["id"],
    )
    direct_mgr_headers = _link_user_to_employee(
        db, company_a.company_id, direct_mgr_emp["id"], UserRole.manager
    )

    # 3. Direct Report (reports to Direct Manager)
    rep_emp = _create_employee(
        client,
        company_a.hr_headers,
        email=f"rep-{uuid.uuid4().hex[:6]}@example.com",
        reporting_manager_id=direct_mgr_emp["id"],
    )
    rep_headers = _link_user_to_employee(db, company_a.company_id, rep_emp["id"], UserRole.employee)

    # 4. Peer Employee outside chain (reports to nobody)
    other_emp = _create_employee(
        client, company_a.hr_headers, email=f"other-{uuid.uuid4().hex[:6]}@example.com"
    )
    _link_user_to_employee(db, company_a.company_id, other_emp["id"], UserRole.employee)

    # 5. Peer Manager outside chain
    peer_mgr_emp = _create_employee(
        client, company_a.hr_headers, email=f"peermgr-{uuid.uuid4().hex[:6]}@example.com"
    )
    peer_mgr_headers = _link_user_to_employee(
        db, company_a.company_id, peer_mgr_emp["id"], UserRole.manager
    )

    # 6. Manager in company_b
    b_mgr_emp = _create_employee(
        client, company_b.hr_headers, email=f"bmgr-{uuid.uuid4().hex[:6]}@example.com"
    )
    b_mgr_headers = _link_user_to_employee(
        db, company_b.company_id, b_mgr_emp["id"], UserRole.manager
    )

    # Owner in company_a
    owner_user = User(
        company_id=company_a.company_id,
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.owner,
        is_active=True,
    )
    db.add(owner_user)
    db.commit()
    owner_token = create_access_token(
        sub=str(owner_user.id), company_id=str(company_a.company_id), role=UserRole.owner.value
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    # Setup goals for direct manager and report
    client.post(
        "/api/v1/performance/goals",
        headers=direct_mgr_headers,
        json={
            "cycle_id": cycle_id,
            "goals": [
                {
                    "title": "Goal 1",
                    "description": "Desc",
                    "weightage": "50.00",
                    "target_value": "V1",
                },
                {
                    "title": "Goal 2",
                    "description": "Desc",
                    "weightage": "50.00",
                    "target_value": "V2",
                },
            ],
        },
    )
    client.post(
        "/api/v1/performance/goals",
        headers=rep_headers,
        json={
            "cycle_id": cycle_id,
            "goals": [
                {
                    "title": "Goal 3",
                    "description": "Desc",
                    "weightage": "60.00",
                    "target_value": "V3",
                },
                {
                    "title": "Goal 4",
                    "description": "Desc",
                    "weightage": "40.00",
                    "target_value": "V4",
                },
            ],
        },
    )

    # 1. A manager reads their own goals: 200
    res_self = client.get(
        f"/api/v1/performance/goals/{direct_mgr_emp['id']}", headers=direct_mgr_headers
    )
    assert res_self.status_code == 200, f"Expected 200, got {res_self.status_code}: {res_self.text}"

    # 2. A manager reads a direct report's goals: 200
    res_direct = client.get(
        f"/api/v1/performance/goals/{rep_emp['id']}", headers=direct_mgr_headers
    )
    assert res_direct.status_code == 200, (
        f"Expected 200, got {res_direct.status_code}: {res_direct.text}"
    )

    # 3. A manager reads a skip-level report's goals: 200
    res_skip = client.get(f"/api/v1/performance/goals/{rep_emp['id']}", headers=senior_headers)
    assert res_skip.status_code == 200, f"Expected 200, got {res_skip.status_code}: {res_skip.text}"

    # 4. A manager reads goals of an employee outside their chain: 403
    res_outside = client.get(f"/api/v1/performance/goals/{rep_emp['id']}", headers=peer_mgr_headers)
    assert res_outside.status_code == 403, (
        f"Expected 403, got {res_outside.status_code}: {res_outside.text}"
    )

    # 5. An employee reading their own goals: 200
    res_emp_self = client.get(f"/api/v1/performance/goals/{rep_emp['id']}", headers=rep_headers)
    assert res_emp_self.status_code == 200, (
        f"Expected 200, got {res_emp_self.status_code}: {res_emp_self.text}"
    )

    # 6. An employee reading another employee's goals: 403
    res_emp_other = client.get(f"/api/v1/performance/goals/{other_emp['id']}", headers=rep_headers)
    assert res_emp_other.status_code == 403, (
        f"Expected 403, got {res_emp_other.status_code}: {res_emp_other.text}"
    )

    # 7. hr_admin unchanged: 200
    res_hr = client.get(f"/api/v1/performance/goals/{rep_emp['id']}", headers=company_a.hr_headers)
    assert res_hr.status_code == 200, f"Expected 200, got {res_hr.status_code}: {res_hr.text}"

    # 8. owner unchanged: 200
    res_owner = client.get(f"/api/v1/performance/goals/{rep_emp['id']}", headers=owner_headers)
    assert res_owner.status_code == 200, (
        f"Expected 200, got {res_owner.status_code}: {res_owner.text}"
    )

    # 9. A manager of another company: 403 or 404
    res_b_mgr = client.get(f"/api/v1/performance/goals/{rep_emp['id']}", headers=b_mgr_headers)
    assert res_b_mgr.status_code in (403, 404), (
        f"Expected 403 or 404, got {res_b_mgr.status_code}: {res_b_mgr.text}"
    )


# =============================================================================
# C. create_pip (POST /performance/pips)
# =============================================================================


def test_create_pip_manager_scoping(client: TestClient, db: Session, company_a: TenantContext):
    """
    C. a manager creates a PIP for a direct report: 201.
       For an employee outside their chain: 403.
       For themselves: 403.
       For an unknown employee id: 404.
       An existing active PIP still gives 409 but ONLY to an authorized caller
       (authority first, then state).
       hr_admin and owner unchanged.
    """
    # 1. Direct Manager
    mgr_emp = _create_employee(
        client, company_a.hr_headers, email=f"mgr-{uuid.uuid4().hex[:6]}@example.com"
    )
    mgr_headers = _link_user_to_employee(db, company_a.company_id, mgr_emp["id"], UserRole.manager)

    # 2. Direct Report
    rep_emp = _create_employee(
        client,
        company_a.hr_headers,
        email=f"rep-{uuid.uuid4().hex[:6]}@example.com",
        reporting_manager_id=mgr_emp["id"],
    )
    _link_user_to_employee(db, company_a.company_id, rep_emp["id"], UserRole.employee)

    # 3. Peer Employee (outside chain)
    other_emp = _create_employee(
        client, company_a.hr_headers, email=f"other-{uuid.uuid4().hex[:6]}@example.com"
    )
    _link_user_to_employee(db, company_a.company_id, other_emp["id"], UserRole.employee)

    # 4. Peer Manager (outside chain)
    peer_mgr_emp = _create_employee(
        client, company_a.hr_headers, email=f"peermgr-{uuid.uuid4().hex[:6]}@example.com"
    )
    peer_mgr_headers = _link_user_to_employee(
        db, company_a.company_id, peer_mgr_emp["id"], UserRole.manager
    )

    # Owner in company_a
    owner_user = User(
        company_id=company_a.company_id,
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.owner,
        is_active=True,
    )
    db.add(owner_user)
    db.commit()
    owner_token = create_access_token(
        sub=str(owner_user.id), company_id=str(company_a.company_id), role=UserRole.owner.value
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    # 1. Manager creates a PIP for an employee outside their chain: 403
    res_outside = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": other_emp["id"],
            "title": "Improvement Plan Outside",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_outside.status_code == 403, (
        f"Expected 403, got {res_outside.status_code}: {res_outside.text}"
    )

    # 2. Manager creates a PIP for themselves: 403
    res_self = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": mgr_emp["id"],
            "title": "Self PIP",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_self.status_code == 403, f"Expected 403, got {res_self.status_code}: {res_self.text}"

    # 3. Manager creates a PIP for unknown employee id: 404
    unknown_id = str(uuid.uuid4())
    res_unknown = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": unknown_id,
            "title": "Unknown Employee PIP",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_unknown.status_code == 404, (
        f"Expected 404, got {res_unknown.status_code}: {res_unknown.text}"
    )

    # 4. Manager creates a PIP for direct report: 201
    res_create = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": rep_emp["id"],
            "title": "Direct Report PIP",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_create.status_code == 201, (
        f"Expected 201, got {res_create.status_code}: {res_create.text}"
    )

    # 5. Existing active PIP:
    # Unauthorized manager (peer_mgr) tries to create PIP for rep_emp -> 403
    # (authority first, not 409!)
    res_unauth_conflict = client.post(
        "/api/v1/performance/pips",
        headers=peer_mgr_headers,
        json={
            "employee_id": rep_emp["id"],
            "title": "Unauthorized PIP attempt",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_unauth_conflict.status_code == 403, (
        f"Expected 403 (authority first), got {res_unauth_conflict.status_code}: "
        f"{res_unauth_conflict.text}"
    )

    # Authorized manager tries to create another PIP for rep_emp -> 409 Conflict
    res_auth_conflict = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": rep_emp["id"],
            "title": "Duplicate PIP",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_auth_conflict.status_code == 409, (
        f"Expected 409, got {res_auth_conflict.status_code}: {res_auth_conflict.text}"
    )

    # 6. hr_admin unchanged (can create PIP for other_emp): 201
    res_hr_pip = client.post(
        "/api/v1/performance/pips",
        headers=company_a.hr_headers,
        json={
            "employee_id": other_emp["id"],
            "title": "HR Initiated PIP",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_hr_pip.status_code == 201, (
        f"Expected 201, got {res_hr_pip.status_code}: {res_hr_pip.text}"
    )

    # Another employee for owner PIP
    owner_target = _create_employee(
        client, company_a.hr_headers, email=f"ownertarget-{uuid.uuid4().hex[:6]}@example.com"
    )
    # 7. owner unchanged: 201
    res_owner_pip = client.post(
        "/api/v1/performance/pips",
        headers=owner_headers,
        json={
            "employee_id": owner_target["id"],
            "title": "Owner Initiated PIP",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_owner_pip.status_code == 201, (
        f"Expected 201, got {res_owner_pip.status_code}: {res_owner_pip.text}"
    )
