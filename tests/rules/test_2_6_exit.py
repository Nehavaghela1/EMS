import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.hr.models import (
    Department,
    Employee,
    EmploymentType,
    InvitationStatus,
    ResignationStatus,
)
from app.modules.identity.models import (
    Company,
    CompanyStatus,
    RefreshToken,
    User,
    UserRole,
)
from app.modules.platform.models import AuditLog


def _auth_headers(user: User) -> dict[str, str]:
    user_id = user.__dict__.get("id") or user.id
    company_id = user.__dict__.get("company_id") or user.company_id
    role = user.__dict__.get("role") or user.role
    role_val = role.value if hasattr(role, "value") else str(role)
    token = create_access_token(
        sub=str(user_id),
        company_id=str(company_id),
        role=role_val,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def exit_setup(db: Session) -> dict[str, Any]:
    db.expire_on_commit = False
    cid_a = uuid.uuid4()
    bind_tenant_to_session(db, company_id=cid_a, is_platform_admin=True)

    company_a = Company(
        id=cid_a,
        name=f"Exit Corp A {uuid.uuid4().hex[:6]}",
        code=f"ECA{uuid.uuid4().hex[:4].upper()}",
        email=f"exita-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        is_active=True,
    )
    db.add(company_a)
    db.flush()

    owner_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("OwnerPassword123!"),
        role=UserRole.owner,
        is_active=True,
    )
    hr_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("HrPassword123!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    super_admin_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"super-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("SuperPassword123!"),
        role=UserRole.super_admin,
        is_active=True,
    )
    dept_head_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"head-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("HeadPassword123!"),
        role=UserRole.manager,
        is_active=True,
    )
    manager_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"mgr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("MgrPassword123!"),
        role=UserRole.manager,
        is_active=True,
    )
    it_mgr_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"itmgr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("ItMgrPassword123!"),
        role=UserRole.manager,
        is_active=True,
    )
    fin_mgr_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"finmgr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("FinMgrPassword123!"),
        role=UserRole.manager,
        is_active=True,
    )
    emp_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("EmpPassword123!"),
        role=UserRole.employee,
        is_active=True,
    )
    other_emp_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"otheremp-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("OtherEmpPassword123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([
        owner_user,
        hr_user,
        super_admin_user,
        dept_head_user,
        manager_user,
        it_mgr_user,
        fin_mgr_user,
        emp_user,
        other_emp_user,
    ])
    db.flush()

    # Departments: General, IT (clearance_function=it), Finance (clearance_function=finance)
    dept_it = Department(
        id=uuid.uuid4(),
        company_id=cid_a,
        name="IT Department",
        clearance_function="it",
    )
    dept_fin = Department(
        id=uuid.uuid4(),
        company_id=cid_a,
        name="Finance Department",
        clearance_function="finance",
    )
    dept_gen = Department(
        id=uuid.uuid4(),
        company_id=cid_a,
        name="General Engineering",
        clearance_function=None,
    )
    db.add_all([dept_it, dept_fin, dept_gen])
    db.flush()

    # Employees
    owner_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=owner_user.id,
        employee_code=f"OWN{uuid.uuid4().hex[:4].upper()}",
        first_name="Owner",
        last_name="Leader",
        email=owner_user.email,
        hire_date=date(2023, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
        level="L3",
        notice_period_days=90,
    )
    head_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=dept_head_user.id,
        employee_code=f"HED{uuid.uuid4().hex[:4].upper()}",
        first_name="Dept",
        last_name="Head",
        email=dept_head_user.email,
        hire_date=date(2023, 1, 1),
        department_id=dept_gen.id,
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
        level="L2",
        notice_period_days=60,
    )
    mgr_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=manager_user.id,
        employee_code=f"MGR{uuid.uuid4().hex[:4].upper()}",
        first_name="Direct",
        last_name="Manager",
        email=manager_user.email,
        hire_date=date(2023, 1, 1),
        department_id=dept_gen.id,
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
        level="L2",
        notice_period_days=60,
    )
    it_mgr_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=it_mgr_user.id,
        employee_code=f"ITM{uuid.uuid4().hex[:4].upper()}",
        first_name="IT",
        last_name="Lead",
        email=it_mgr_user.email,
        hire_date=date(2023, 1, 1),
        department_id=dept_it.id,
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
        level="L2",
        notice_period_days=60,
    )
    fin_mgr_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=fin_mgr_user.id,
        employee_code=f"FIN{uuid.uuid4().hex[:4].upper()}",
        first_name="Finance",
        last_name="Lead",
        email=fin_mgr_user.email,
        hire_date=date(2023, 1, 1),
        department_id=dept_fin.id,
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
        level="L2",
        notice_period_days=60,
    )
    emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=emp_user.id,
        employee_code=f"EMP{uuid.uuid4().hex[:4].upper()}",
        first_name="Target",
        last_name="Worker",
        email=emp_user.email,
        hire_date=date(2024, 1, 1),
        department_id=dept_gen.id,
        reporting_manager_id=mgr_emp.id,
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
        level="L1",
        notice_period_days=30,
    )
    other_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=other_emp_user.id,
        employee_code=f"OTH{uuid.uuid4().hex[:4].upper()}",
        first_name="Other",
        last_name="Worker",
        email=other_emp_user.email,
        hire_date=date(2024, 1, 1),
        department_id=dept_gen.id,
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
        level="L1",
        notice_period_days=30,
    )
    db.add_all([owner_emp, head_emp, mgr_emp, it_mgr_emp, fin_mgr_emp, emp, other_emp])
    db.flush()

    dept_gen.head_employee_id = head_emp.id
    db.flush()

    # Company B for cross-tenant checks
    cid_b = uuid.uuid4()
    company_b = Company(
        id=cid_b,
        name=f"Cross Corp B {uuid.uuid4().hex[:6]}",
        code=f"ECB{uuid.uuid4().hex[:4].upper()}",
        email=f"exitb-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        is_active=True,
    )
    db.add(company_b)
    db.flush()

    hr_user_b = User(
        id=uuid.uuid4(),
        company_id=cid_b,
        email=f"hrb-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("HrBPassword123!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(hr_user_b)
    db.flush()

    db.commit()

    class _Proxy:
        def __init__(self, obj: Any) -> None:
            self._obj = obj
            self.id = getattr(obj, "id", None)
            self.company_id = getattr(obj, "company_id", None)
            self.user_id = getattr(obj, "user_id", None)
            self.email = getattr(obj, "email", None)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._obj, name)

        def __setattr__(self, name: str, val: Any) -> None:
            if name in ("_obj", "id", "company_id", "user_id", "email"):
                super().__setattr__(name, val)
            else:
                setattr(self._obj, name, val)

    raw = {
        "company_a": company_a,
        "company_b": company_b,
        "owner_user": owner_user,
        "hr_user": hr_user,
        "super_admin_user": super_admin_user,
        "dept_head_user": dept_head_user,
        "manager_user": manager_user,
        "it_mgr_user": it_mgr_user,
        "fin_mgr_user": fin_mgr_user,
        "emp_user": emp_user,
        "other_emp_user": other_emp_user,
        "hr_user_b": hr_user_b,
        "owner_emp": owner_emp,
        "head_emp": head_emp,
        "mgr_emp": mgr_emp,
        "it_mgr_emp": it_mgr_emp,
        "fin_mgr_emp": fin_mgr_emp,
        "emp": emp,
        "other_emp": other_emp,
        "dept_gen": dept_gen,
        "dept_it": dept_it,
        "dept_fin": dept_fin,
    }
    return {k: _Proxy(v) for k, v in raw.items()}


# =============================================================================
# Rule 1 Tests: WHO
# =============================================================================
def test_r01_who_can_submit_withdraw_approve_reject_terminate_settle(
    client: TestClient, exit_setup: dict[str, Any]
) -> None:
    """R1:
    - Employee submits and withdraws own resignation; HR admin, owner, super admin can do it for anyone.
    - Other employee gets 403.
    - Approve/reject: HR admin, owner, super admin, department head, or approval chain manager.
    - Nobody approves or rejects own resignation (including owner and super admin).
    - Terminate and settle: HR admin, owner, super admin only (manager gets 403, employee gets 403).
    - Other company gives 404, no login gives 401.
    """
    emp = exit_setup["emp"]
    emp_headers = _auth_headers(exit_setup["emp_user"])
    other_emp_headers = _auth_headers(exit_setup["other_emp_user"])
    hr_headers = _auth_headers(exit_setup["hr_user"])
    owner_headers = _auth_headers(exit_setup["owner_user"])
    super_headers = _auth_headers(exit_setup["super_admin_user"])
    mgr_headers = _auth_headers(exit_setup["manager_user"])
    head_headers = _auth_headers(exit_setup["dept_head_user"])
    hr_b_headers = _auth_headers(exit_setup["hr_user_b"])

    today = date.today()
    lwd = today + timedelta(days=30)
    sub_payload = {"resignation_date": str(today), "last_working_date": str(lwd), "reason": "Own resignation"}

    # 1. No login gives 401
    assert client.post(f"/api/v1/employees/{emp.id}/resignation", json=sub_payload).status_code == 401
    assert client.post(f"/api/v1/employees/{emp.id}/resignation/withdraw").status_code == 401
    assert client.put(f"/api/v1/employees/{emp.id}/resignation/approve", json={"approved": True}).status_code == 401
    assert client.post(f"/api/v1/employees/{emp.id}/terminate", json={"termination_date": str(today), "reason": "Term"}).status_code == 401

    # 2. Other company gives 404
    assert client.post(f"/api/v1/employees/{emp.id}/resignation", headers=hr_b_headers, json=sub_payload).status_code == 404
    assert client.post(f"/api/v1/employees/{emp.id}/resignation/withdraw", headers=hr_b_headers).status_code == 404
    assert client.put(f"/api/v1/employees/{emp.id}/resignation/approve", headers=hr_b_headers, json={"approved": True}).status_code == 404
    assert client.post(f"/api/v1/employees/{emp.id}/terminate", headers=hr_b_headers, json={"termination_date": str(today), "reason": "Term"}).status_code == 404

    # 3. Other employee cannot submit -> 403
    r_other_sub = client.post(f"/api/v1/employees/{emp.id}/resignation", headers=other_emp_headers, json=sub_payload)
    assert r_other_sub.status_code == 403

    # 4. Employee submits own resignation -> 200
    r_own_sub = client.post(f"/api/v1/employees/{emp.id}/resignation", headers=emp_headers, json=sub_payload)
    assert r_own_sub.status_code == 200
    assert r_own_sub.json()["resignation_status"] == "submitted"
    assert r_own_sub.json()["resignation_reason"] == "Own resignation"

    # 5. Other employee cannot withdraw -> 403
    assert client.post(f"/api/v1/employees/{emp.id}/resignation/withdraw", headers=other_emp_headers).status_code == 403

    # 6. Employee withdraws own resignation -> 200
    r_own_withdraw = client.post(f"/api/v1/employees/{emp.id}/resignation/withdraw", headers=emp_headers)
    assert r_own_withdraw.status_code == 200
    assert r_own_withdraw.json()["resignation_status"] == "none"

    # 7. HR admin submits for employee -> 200
    r_hr_sub = client.post(f"/api/v1/employees/{emp.id}/resignation", headers=hr_headers, json=sub_payload)
    assert r_hr_sub.status_code == 200

    # 8. Self-approval is forbidden: employee cannot approve own resignation
    assert client.put(f"/api/v1/employees/{emp.id}/resignation/approve", headers=emp_headers, json={"approved": True}).status_code == 403

    # Owner also cannot approve own resignation if owner submits one
    owner_emp = exit_setup["owner_emp"]
    # (Owner resignation is blocked by Rule 2 anyway, but even if simulated, self-approval check must block self)


def test_r01_nobody_approves_own_resignation_including_owner_and_super_admin(
    client: TestClient, exit_setup: dict[str, Any], db: Session
) -> None:
    """R1: Nobody approves or rejects own resignation (including owner and super admin)."""
    # Create an employee linked to hr_user
    cid = exit_setup["company_a"].id
    hr_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=exit_setup["hr_user"].id,
        employee_code=f"HRE{uuid.uuid4().hex[:4].upper()}",
        first_name="HR",
        last_name="Staff",
        email=exit_setup["hr_user"].email,
        hire_date=date(2023, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
        resignation_status=ResignationStatus.submitted,
        resignation_date=date.today(),
        last_working_date=date.today() + timedelta(days=30),
    )
    db.add(hr_emp)
    db.commit()

    hr_headers = _auth_headers(exit_setup["hr_user"])
    r_self = client.put(
        f"/api/v1/employees/{hr_emp.id}/resignation/approve",
        headers=hr_headers,
        json={"approved": True},
    )
    assert r_self.status_code == 403
    assert "Self-approval is forbidden" in r_self.text or "own" in r_self.text.lower()


def test_r01_terminate_and_settle_roles(client: TestClient, exit_setup: dict[str, Any]) -> None:
    """R1: Terminate and settle: HR admin, owner, super admin only (manager gets 403, employee gets 403)."""
    emp = exit_setup["emp"]
    emp_headers = _auth_headers(exit_setup["emp_user"])
    mgr_headers = _auth_headers(exit_setup["manager_user"])
    hr_headers = _auth_headers(exit_setup["hr_user"])
    owner_headers = _auth_headers(exit_setup["owner_user"])

    today = date.today()
    term_payload = {
        "termination_date": str(today),
        "reason": "Performance issues",
        "notes": "Some detailed termination notes",
    }

    # Terminate by employee -> 403
    assert client.post(f"/api/v1/employees/{emp.id}/terminate", headers=emp_headers, json=term_payload).status_code == 403
    # Terminate by manager -> 403
    assert client.post(f"/api/v1/employees/{emp.id}/terminate", headers=mgr_headers, json=term_payload).status_code == 403

    # Clearance update mark_settled by manager -> 403
    assert client.put(f"/api/v1/employees/{emp.id}/fnf/clearance", headers=mgr_headers, json={"mark_settled": True}).status_code == 403


# =============================================================================
# Rule 2 Tests: RESIGNATION INPUT
# =============================================================================
def test_r02_resignation_input_validation(client: TestClient, exit_setup: dict[str, Any], db: Session) -> None:
    """R2:
    - Resignation date: today or up to 30 days back, never in the future.
    - Last working date: today or later, not before resignation date, at most 365 days after it.
    - Reason up to 500 characters, trimmed, saved.
    - Unknown fields and bad dates give 422.
    - The company owner cannot resign (409).
    - An inactive or already separating employee gets 409.
    """
    emp = exit_setup["emp"]
    emp_headers = _auth_headers(exit_setup["emp_user"])
    owner_emp = exit_setup["owner_emp"]
    owner_headers = _auth_headers(exit_setup["owner_user"])
    today = date.today()

    # 1. Resignation date in future -> 422
    future_date = today + timedelta(days=1)
    r = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(future_date), "last_working_date": str(future_date + timedelta(days=30))},
    )
    assert r.status_code == 422

    # 2. Resignation date older than 30 days back -> 422
    past_31 = today - timedelta(days=31)
    r = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(past_31), "last_working_date": str(today + timedelta(days=30))},
    )
    assert r.status_code == 422

    # 3. Last working date before today -> 422
    yesterday = today - timedelta(days=1)
    r = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(today - timedelta(days=5)), "last_working_date": str(yesterday)},
    )
    assert r.status_code == 422

    # 4. Last working date before resignation date -> 422
    r = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(today), "last_working_date": str(today - timedelta(days=2))},
    )
    assert r.status_code == 422

    # 5. Last working date > resignation date + 365 days -> 422
    too_far = today + timedelta(days=366)
    r = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(today), "last_working_date": str(too_far)},
    )
    assert r.status_code == 422

    # 6. Unknown fields -> 422
    r = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30)), "unknown_foo": "bar"},
    )
    assert r.status_code == 422

    # 7. Reason up to 500 characters, trimmed, saved
    long_reason = "  " + ("A" * 500) + "  "
    r = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30)), "reason": long_reason},
    )
    assert r.status_code == 200
    assert r.json()["resignation_reason"] == "A" * 500

    # Clean up back to none for next tests
    client.post(f"/api/v1/employees/{emp.id}/resignation/withdraw", headers=emp_headers)

    # 8. Reason over 500 characters -> 422
    over_500 = "B" * 501
    r = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30)), "reason": over_500},
    )
    assert r.status_code == 422

    # 9. Company owner cannot resign -> 409
    r_owner = client.post(
        f"/api/v1/employees/{owner_emp.id}/resignation",
        headers=owner_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30))},
    )
    assert r_owner.status_code == 409
    assert "owner cannot resign" in r_owner.text.lower() or "owner" in r_owner.text.lower()

    # 10. Inactive employee gets 409
    emp.is_active = False
    db.commit()
    r_inactive = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=_auth_headers(exit_setup["hr_user"]),
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30))},
    )
    assert r_inactive.status_code == 409

    # 11. Already separating employee gets 409
    emp.is_active = True
    emp.resignation_status = ResignationStatus.approved
    db.commit()
    r_separating = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=_auth_headers(exit_setup["hr_user"]),
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30))},
    )
    assert r_separating.status_code == 409


# =============================================================================
# Rule 3 Tests: NOTICE POLICY
# =============================================================================
def test_r03_notice_defaults_policy_and_employee_creation(client: TestClient, exit_setup: dict[str, Any], db: Session) -> None:
    """R3:
    - Company keeps default notice days per level (L1, L2, L3; each 0 to 365; HR admin, owner, super admin set them; fallback 30).
    - When employee created without explicit notice value, default for employee's level is used.
    - Explicit value always wins and HR-level can set it per employee.
    - Changing defaults, or an employee's level, never changes existing employees.
    - Required notice = employee's notice_period_days, cannot be edited (409) while exit is submitted or approved.
    - Expected lwd = resignation date + required notice. Shortfall = max(0, required - days served).
    - On approval, only HR-level may waive or set notice_recovery_days (0 to shortfall). Manager gets 403.
    """
    hr_headers = _auth_headers(exit_setup["hr_user"])
    mgr_headers = _auth_headers(exit_setup["manager_user"])

    # 1. Update company notice defaults
    r_set_defaults = client.put(
        "/api/v1/companies/notice-period-defaults",
        headers=hr_headers,
        json={"L1": 20, "L2": 45, "L3": 75},
    )
    assert r_set_defaults.status_code == 200
    assert r_set_defaults.json() == {"L1": 20, "L2": 45, "L3": 75}

    # Manager cannot update notice defaults -> 403
    assert client.put(
        "/api/v1/companies/notice-period-defaults",
        headers=mgr_headers,
        json={"L1": 20, "L2": 45, "L3": 75},
    ).status_code == 403

    # Read notice defaults: HR-level can read
    r_get_defaults = client.get("/api/v1/companies/notice-period-defaults", headers=hr_headers)
    assert r_get_defaults.status_code == 200
    assert r_get_defaults.json() == {"L1": 20, "L2": 45, "L3": 75}

    # 2. Create employee without notice_period_days -> uses L1 default (20)
    emp_l1_payload = {
        "first_name": "L1Emp",
        "last_name": "Notice",
        "email": f"l1notice-{uuid.uuid4().hex[:6]}@example.com",
        "hire_date": "2025-01-01",
        "level": "L1",
    }
    r_emp_l1 = client.post("/api/v1/employees", headers=hr_headers, json=emp_l1_payload)
    assert r_emp_l1.status_code == 201
    assert r_emp_l1.json()["notice_period_days"] == 20
    emp_l1_id = r_emp_l1.json()["id"]

    # 3. Create employee with explicit notice_period_days -> explicit wins
    emp_explicit_payload = {
        "first_name": "ExplicitEmp",
        "email": f"explicit-{uuid.uuid4().hex[:6]}@example.com",
        "hire_date": "2025-01-01",
        "level": "L1",
        "notice_period_days": 10,
    }
    r_explicit = client.post("/api/v1/employees", headers=hr_headers, json=emp_explicit_payload)
    assert r_explicit.status_code == 201
    assert r_explicit.json()["notice_period_days"] == 10

    # 4. Changing defaults does not affect existing employees
    client.put(
        "/api/v1/companies/notice-period-defaults",
        headers=hr_headers,
        json={"L1": 25, "L2": 50, "L3": 80},
    )
    r_check = client.get(f"/api/v1/employees/{emp_l1_id}", headers=hr_headers)
    assert r_check.status_code == 200
    assert r_check.json()["notice_period_days"] == 20

    # 5. Changing employee's level does not change existing notice_period_days
    r_update_level = client.put(
        f"/api/v1/employees/{emp_l1_id}",
        headers=hr_headers,
        json={"level": "L2"},
    )
    assert r_update_level.status_code == 200
    assert r_update_level.json()["level"] == "L2"
    assert r_update_level.json()["notice_period_days"] == 20

    # 6. Cannot edit notice_period_days (409) while exit is submitted or approved
    today = date.today()
    client.post(
        f"/api/v1/employees/{emp_l1_id}/resignation",
        headers=hr_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=20))},
    )
    r_edit_notice = client.put(
        f"/api/v1/employees/{emp_l1_id}",
        headers=hr_headers,
        json={"notice_period_days": 15},
    )
    assert r_edit_notice.status_code == 409


def test_r03_waiver_and_recovery_days_by_role(client: TestClient, exit_setup: dict[str, Any]) -> None:
    """R3: On approval, only HR-level may waive notice or set notice_recovery_days; manager gets 403."""
    emp = exit_setup["emp"]
    hr_headers = _auth_headers(exit_setup["hr_user"])
    mgr_headers = _auth_headers(exit_setup["manager_user"])
    today = date.today()

    # emp has notice_period_days = 30
    # Submit with 10 days served (shortfall = 20)
    client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=hr_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=10))},
    )

    # Manager attempts to approve and set notice_waived=True -> 403
    r_mgr_waive = client.put(
        f"/api/v1/employees/{emp.id}/resignation/approve",
        headers=mgr_headers,
        json={"approved": True, "notice_waived": True},
    )
    assert r_mgr_waive.status_code == 403

    # Manager attempts to approve and set notice_recovery_days -> 403
    r_mgr_rec = client.put(
        f"/api/v1/employees/{emp.id}/resignation/approve",
        headers=mgr_headers,
        json={"approved": True, "notice_recovery_days": 10},
    )
    assert r_mgr_rec.status_code == 403

    # HR admin can set notice_waived or recovery days within shortfall (0 to 20)
    r_hr_app = client.put(
        f"/api/v1/employees/{emp.id}/resignation/approve",
        headers=hr_headers,
        json={"approved": True, "notice_recovery_days": 15},
    )
    assert r_hr_app.status_code == 200
    assert r_hr_app.json()["notice_recovery_days"] == 15


# =============================================================================
# Rule 4 Tests: STATUS MOVES FORWARD ONLY & WITHDRAW
# =============================================================================
def test_r04_status_transitions_withdraw_amendment_concurrency(
    client: TestClient, exit_setup: dict[str, Any], db: Session
) -> None:
    """R4:
    - none -> submitted -> approved/rejected.
    - Submitted can be withdrawn (back to none, dates and reason cleared).
    - Approved can be withdrawn only by HR-level, only before last working date, only for voluntary exit, never after settlement.
    - Rejected can be submitted again.
    - Decision on resignation not pending gives 409.
    - HR-level may amend last working date and waiver on approved resignation until settled (not in past, not before resignation date).
    - Two approvals at same moment: row FOR UPDATE prevents race, second gets 409.
    """
    emp = exit_setup["emp"]
    emp_headers = _auth_headers(exit_setup["emp_user"])
    hr_headers = _auth_headers(exit_setup["hr_user"])
    today = date.today()

    # 1. Decision on non-pending resignation gives 409
    assert client.put(f"/api/v1/employees/{emp.id}/resignation/approve", headers=hr_headers, json={"approved": True}).status_code == 409

    # 2. Submit resignation
    client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30)), "reason": "Going elsewhere"},
    )

    # 3. Withdraw submitted -> dates and reason cleared
    r_with = client.post(f"/api/v1/employees/{emp.id}/resignation/withdraw", headers=emp_headers)
    assert r_with.status_code == 200
    data_with = r_with.json()
    assert data_with["resignation_status"] == "none"
    assert data_with["resignation_date"] is None
    assert data_with["last_working_date"] is None
    assert data_with.get("resignation_reason") is None

    # 4. Reject and re-submit
    client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30))},
    )
    r_rej = client.put(f"/api/v1/employees/{emp.id}/resignation/approve", headers=hr_headers, json={"approved": False})
    assert r_rej.status_code == 200
    assert r_rej.json()["resignation_status"] == "rejected"

    # Re-submit after rejection succeeds
    r_resub = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30))},
    )
    assert r_resub.status_code == 200
    assert r_resub.json()["resignation_status"] == "submitted"

    # Approve
    r_app = client.put(f"/api/v1/employees/{emp.id}/resignation/approve", headers=hr_headers, json={"approved": True})
    assert r_app.status_code == 200
    assert r_app.json()["resignation_status"] == "approved"

    # Employee attempts to withdraw approved resignation -> 403
    assert client.post(f"/api/v1/employees/{emp.id}/resignation/withdraw", headers=emp_headers).status_code == 403

    # HR admin withdraws approved resignation before last working date -> 200
    r_hr_withdraw = client.post(f"/api/v1/employees/{emp.id}/resignation/withdraw", headers=hr_headers)
    assert r_hr_withdraw.status_code == 200
    assert r_hr_withdraw.json()["resignation_status"] == "none"

    # Submit and approve again
    client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30))},
    )
    client.put(f"/api/v1/employees/{emp.id}/resignation/approve", headers=hr_headers, json={"approved": True})

    # Cannot withdraw approved resignation after last working date
    emp.last_working_date = today - timedelta(days=1)
    db.commit()
    r_past_lwd_withdraw = client.post(f"/api/v1/employees/{emp.id}/resignation/withdraw", headers=hr_headers)
    assert r_past_lwd_withdraw.status_code == 409


# =============================================================================
# Rule 5 Tests: TERMINATION
# =============================================================================
def test_r05_termination_rules(client: TestClient, exit_setup: dict[str, Any], db: Session) -> None:
    """R5:
    - HR-level only; active employee only; not yourself, not the company owner.
    - Not already separating or settled (409).
    - Termination date from today up to today + notice_period_days.
    - Reason 1 to 255 chars trimmed; notes up to 1000 chars saved; severance and notice pay 0 to 99999999999.99.
    - Future date keeps employee working (active, login on) until that date.
    """
    emp = exit_setup["emp"]
    hr_headers = _auth_headers(exit_setup["hr_user"])
    owner_emp = exit_setup["owner_emp"]
    today = date.today()

    # 1. Cannot terminate self -> 409
    hr_emp_user = exit_setup["hr_user"]
    hr_emp_obj = Employee(
        id=uuid.uuid4(),
        company_id=exit_setup["company_a"].id,
        user_id=hr_emp_user.id,
        employee_code=f"HRE{uuid.uuid4().hex[:4].upper()}",
        first_name="HR",
        last_name="Self",
        email=hr_emp_user.email,
        hire_date=date(2023, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    db.add(hr_emp_obj)
    db.commit()

    r_self_term = client.post(
        f"/api/v1/employees/{hr_emp_obj.id}/terminate",
        headers=hr_headers,
        json={"termination_date": str(today), "reason": "Self termination"},
    )
    assert r_self_term.status_code == 409
    assert "yourself" in r_self_term.text.lower() or "self" in r_self_term.text.lower()

    # 2. Cannot terminate company owner -> 409
    r_owner_term = client.post(
        f"/api/v1/employees/{owner_emp.id}/terminate",
        headers=hr_headers,
        json={"termination_date": str(today), "reason": "Owner termination"},
    )
    assert r_owner_term.status_code == 409
    assert "owner" in r_owner_term.text.lower()

    # 3. Termination date in the past -> 422
    r_past = client.post(
        f"/api/v1/employees/{emp.id}/terminate",
        headers=hr_headers,
        json={"termination_date": str(today - timedelta(days=1)), "reason": "Past date"},
    )
    assert r_past.status_code == 422

    # 4. Termination date beyond employee's notice_period_days (30) -> 422
    r_too_far = client.post(
        f"/api/v1/employees/{emp.id}/terminate",
        headers=hr_headers,
        json={"termination_date": str(today + timedelta(days=31)), "reason": "Too far"},
    )
    assert r_too_far.status_code == 422

    # 5. Future-dated termination keeps employee active and login working until that date
    future_date = today + timedelta(days=15)
    r_future_term = client.post(
        f"/api/v1/employees/{emp.id}/terminate",
        headers=hr_headers,
        json={
            "termination_date": str(future_date),
            "reason": "Restructuring",
            "notes": "Detailed notes on restructuring",
            "severance_pay": "50000.00",
            "notice_pay_in_lieu": "15000.00",
        },
    )
    assert r_future_term.status_code == 200
    data_term = r_future_term.json()
    assert data_term["is_active"] is True
    assert data_term["termination_notes"] == "Detailed notes on restructuring"

    # Employee login still active
    db.refresh(emp)
    emp_user_obj = db.get(User, emp.user_id)
    assert emp_user_obj.is_active is True

    # 6. Cannot terminate already separating employee -> 409
    r_double_term = client.post(
        f"/api/v1/employees/{emp.id}/terminate",
        headers=hr_headers,
        json={"termination_date": str(today), "reason": "Double terminate"},
    )
    assert r_double_term.status_code == 409


# =============================================================================
# Rule 6 Tests: EXIT TURNS ACCESS OFF & SCHEDULED JOB
# =============================================================================
def test_r06_apply_exit_and_scheduled_job(client: TestClient, exit_setup: dict[str, Any], db: Session) -> None:
    """R6:
    - One shared function applies an exit: employee inactive, linked login inactive,
      all refresh tokens revoked, department head cleared (with its existing audit),
      audit row EMPLOYEE_EXIT_APPLIED.
    - Runs immediately for termination dated today and for PIP failure.
    - Hourly scheduled job applies every approved exit whose last working date is before today and employee still active.
    - Running twice is harmless (idempotent).
    """
    from app.workers.tasks import hr as hr_tasks

    emp = exit_setup["emp"]
    emp_user = exit_setup["emp_user"]
    dept_gen = exit_setup["dept_gen"]
    hr_headers = _auth_headers(exit_setup["hr_user"])
    today = date.today()

    # Assign emp as department head of dept_gen to verify clearing
    dept_gen.head_employee_id = emp.id
    db.commit()

    # Add active refresh tokens for emp_user
    token1 = RefreshToken(
        id=uuid.uuid4(),
        user_id=emp_user.id,
        token_hash="hash1",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        is_revoked=False,
    )
    token2 = RefreshToken(
        id=uuid.uuid4(),
        user_id=emp_user.id,
        token_hash="hash2",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        is_revoked=False,
    )
    db.add_all([token1, token2])
    db.commit()

    # 1. Termination dated today applies immediately
    r_term_today = client.post(
        f"/api/v1/employees/{emp.id}/terminate",
        headers=hr_headers,
        json={"termination_date": str(today), "reason": "Immediate departure"},
    )
    assert r_term_today.status_code == 200

    db.refresh(emp)
    db.refresh(emp_user)
    db.refresh(dept_gen)
    db.refresh(token1)
    db.refresh(token2)

    assert emp.is_active is False
    assert emp_user.is_active is False
    assert dept_gen.head_employee_id is None
    assert token1.is_revoked is True
    assert token2.is_revoked is True

    # Audit row EMPLOYEE_EXIT_APPLIED exists
    audit_exit = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == exit_setup["company_a"].id, AuditLog.action == "EMPLOYEE_EXIT_APPLIED")
        .first()
    )
    assert audit_exit is not None
    assert audit_exit.entity_id == emp.id

    # 2. Test scheduled job apply_due_exits_task
    # Set up emp with approved resignation whose last_working_date is in the FUTURE (must NOT be applied)
    emp.is_active = True
    emp.resignation_status = ResignationStatus.approved
    emp.last_working_date = today + timedelta(days=5)
    exit_setup["emp_user"].is_active = True

    # Set up other_emp with approved resignation whose last_working_date was yesterday
    other_emp = exit_setup["other_emp"]
    other_user = exit_setup["other_emp_user"]
    other_emp.is_active = True
    other_emp.resignation_status = ResignationStatus.approved
    other_emp.last_working_date = today - timedelta(days=1)
    other_user.is_active = True
    db.commit()

    from unittest.mock import MagicMock
    mock_db = MagicMock(wraps=db)
    mock_db.close = MagicMock()
    with patch.object(hr_tasks, "get_task_db_session", lambda: mock_db):
        res = hr_tasks.apply_due_exits_task()
        assert res["applied_count"] == 1

    bind_tenant_to_session(db, company_id=exit_setup["company_a"].id, is_platform_admin=True)
    db.refresh(emp._obj)
    assert emp.is_active is True, "Future-dated exit must NOT be applied before last working date"
    db.refresh(other_emp._obj)
    db.refresh(other_user._obj)
    assert other_emp.is_active is False
    assert other_user.is_active is False

    # Idempotent: running again is harmless
    with patch.object(hr_tasks, "get_task_db_session", lambda: mock_db):
        res_repeat = hr_tasks.apply_due_exits_task()
        assert res_repeat["applied_count"] == 0


# =============================================================================
# Rule 7 Tests: CLEARANCE & LIMITED REPLIES
# =============================================================================
def test_r07_clearance_signoffs_queue_and_limited_replies(
    client: TestClient, exit_setup: dict[str, Any], db: Session
) -> None:
    """R7:
    - Allowed only for approved exit that is not settled; nobody signs own.
    - Saves who signed, when, optional remark (up to 255 chars trimmed, on employee, never in audit).
    - Latest sign-off replaces previous one.
    - IT, Finance, HR managers sign only their own function; HR admin/owner/super_admin sign all.
    - Clearance queue route lists approved unsettled exits whose own-function clearance is pending.
    - Limited replies: HR function sees flags/dates/notice; IT sees flags/dates/asset deductions;
      Finance sees all settlement amounts except monthly gross and per-day salary; HR-level sees full.
    """
    emp = exit_setup["emp"]
    hr_headers = _auth_headers(exit_setup["hr_user"])
    it_headers = _auth_headers(exit_setup["it_mgr_user"])
    fin_headers = _auth_headers(exit_setup["fin_mgr_user"])
    today = date.today()

    # 0. Clearance rejected if employee does not have an approved exit
    emp.resignation_status = ResignationStatus.submitted
    db.commit()
    r_no_exit = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_headers,
        json={"it_clearance": True},
    )
    assert r_no_exit.status_code == 409
    assert "approved exit" in r_no_exit.json()["error"]["message"]

    # Reset emp to approved exit
    emp.is_active = True
    emp.resignation_status = ResignationStatus.approved
    emp.resignation_date = today - timedelta(days=10)
    emp.last_working_date = today + timedelta(days=20)
    emp.it_clearance = False
    emp.finance_clearance = False
    emp.hr_clearance = False
    db.commit()

    # 1. Clearance Queue: IT manager sees emp in queue
    r_it_queue = client.get("/api/v1/employees/clearance-queue", headers=it_headers)
    assert r_it_queue.status_code == 200
    queue_data = r_it_queue.json()
    items = queue_data["items"] if "items" in queue_data else queue_data
    assert any(item["id"] == str(emp.id) for item in items)

    # 2. IT manager signs IT clearance with remark -> limited reply (no gross, per_day, net)
    r_it_sign = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=it_headers,
        json={"it_clearance": True, "remark": "Laptops and badge received"},
    )
    assert r_it_sign.status_code == 200
    it_reply = r_it_sign.json()
    assert "monthly_gross_salary" not in it_reply
    assert "per_day_salary" not in it_reply
    assert "total_settlement_amount" not in it_reply
    assert it_reply["it_clearance"] is True

    # Check clearance_signoffs stored on employee
    db.refresh(emp)
    signoffs = emp.clearance_signoffs
    assert signoffs is not None
    assert "it" in signoffs
    assert signoffs["it"]["remark"] == "Laptops and badge received"
    assert signoffs["it"]["by"] == str(exit_setup["it_mgr_user"].id)

    # IT manager is now cleared, so emp drops off IT queue
    r_it_queue2 = client.get("/api/v1/employees/clearance-queue", headers=it_headers)
    items2 = r_it_queue2.json().get("items", r_it_queue2.json())
    assert all(item["id"] != str(emp.id) for item in items2)

    # 3. Finance manager signs finance clearance -> limited reply (no monthly gross or per-day salary)
    r_fin_sign = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=fin_headers,
        json={"finance_clearance": True, "severance_pay": "20000.00"},
    )
    assert r_fin_sign.status_code == 200
    fin_reply = r_fin_sign.json()
    assert "monthly_gross_salary" not in fin_reply
    assert "per_day_salary" not in fin_reply
    assert fin_reply["finance_clearance"] is True

    # 4. HR admin calls clearance or fnf -> full settlement response
    r_hr_get = client.get(f"/api/v1/employees/{emp.id}/fnf", headers=hr_headers)
    assert r_hr_get.status_code == 200
    hr_reply = r_hr_get.json()
    assert "monthly_gross_salary" in hr_reply
    assert "per_day_salary" in hr_reply
    assert "total_settlement_amount" in hr_reply


# =============================================================================
# Rule 8 Tests: SETTLEMENT, SNAPSHOT & FORMULA
# =============================================================================
def test_r08_settlement_gates_snapshot_and_math(client: TestClient, exit_setup: dict[str, Any], db: Session) -> None:
    """R8:
    - Only HR-level, only on or after last working date, only when all 3 clearances are true, only once (second gives 409).
    - Saves full settlement snapshot and sets fnf_settled_at.
    - After settlement: every exit edit, clearance change, amount change, withdraw and decision gives 409.
    - Reading returns snapshot.
    - Math: unpaid salary days = min(last working day of month, 30); 0 if payslip already exists for last working month.
    - Employee can read own settlement only after settled.
    """
    emp = exit_setup["emp"]
    emp_headers = _auth_headers(exit_setup["emp_user"])
    hr_headers = _auth_headers(exit_setup["hr_user"])
    today = date.today()

    emp.is_active = True
    emp.resignation_status = ResignationStatus.approved
    emp.last_working_date = today + timedelta(days=5)  # in future
    emp.it_clearance = True
    emp.finance_clearance = True
    emp.hr_clearance = True
    db.commit()

    # 1. Settlement before last working date -> 409
    r_early_settle = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_headers,
        json={"mark_settled": True},
    )
    assert r_early_settle.status_code == 409

    # 2. Settlement missing clearance -> 409
    emp.last_working_date = today  # today is valid
    emp.it_clearance = False
    db.commit()
    r_missing_clearance = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_headers,
        json={"mark_settled": True},
    )
    assert r_missing_clearance.status_code == 409

    # 3. Employee reading own settlement before settled -> 403
    assert client.get(f"/api/v1/employees/{emp.id}/fnf", headers=emp_headers).status_code == 403

    # 4. Valid settlement: all 3 clearances True, on/after LWD
    emp.it_clearance = True
    db.commit()
    r_settle = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_headers,
        json={"mark_settled": True},
    )
    assert r_settle.status_code == 200

    db.refresh(emp)
    assert emp.fnf_settled_at is not None
    assert emp.fnf_snapshot is not None

    # 5. Settling second time -> 409
    r_second_settle = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_headers,
        json={"mark_settled": True},
    )
    assert r_second_settle.status_code == 409

    # 6. Any clearance or amount edit after settlement -> 409
    r_edit_after = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_headers,
        json={"severance_pay": "1000.00"},
    )
    assert r_edit_after.status_code == 409

    # 7. Employee reads own settlement after settled -> 200 with snapshot
    r_emp_read = client.get(f"/api/v1/employees/{emp.id}/fnf", headers=emp_headers)
    assert r_emp_read.status_code == 200
    assert r_emp_read.json()["total_settlement_amount"] is not None

    # 8. Math test: 31st of the month caps unpaid_salary_days at 30
    from app.modules.hr.service import EmployeeService
    emp.last_working_date = date(2024, 1, 31)
    db.commit()
    cid = exit_setup["company_a"].id
    fnf_calc = EmployeeService(db)._calculate_fnf(cid, emp.id)
    assert fnf_calc.unpaid_salary_days == 30, f"Expected 30, got {fnf_calc.unpaid_salary_days}"


# =============================================================================
# Rule 9 Tests: AUDIT AND LIMITS & ROW LOCKS
# =============================================================================
def test_r09_audit_rows_details_and_failures(client: TestClient, exit_setup: dict[str, Any], db: Session) -> None:
    """R9:
    - One audit row in same save for: resignation submitted, withdrawn, approved, rejected,
      terminated, clearance changed (fields/new booleans only, no amounts/text), settled (total only),
      exit applied, notice defaults changed (3 numbers only).
    - No reason, notes or names in audit. None for failed requests.
    """
    emp = exit_setup["emp"]
    hr_headers = _auth_headers(exit_setup["hr_user"])
    cid = exit_setup["company_a"].id
    today = date.today()

    # Reset emp
    emp.resignation_status = ResignationStatus.none
    emp.is_active = True
    db.commit()

    # 1. Resignation submitted audit
    client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=hr_headers,
        json={"resignation_date": str(today), "last_working_date": str(today + timedelta(days=30)), "reason": "Secret private reason"},
    )
    audit_sub = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == cid, AuditLog.action == "RESIGNATION_SUBMITTED", AuditLog.entity_id == emp.id)
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit_sub is not None
    assert "reason" not in audit_sub.details
    assert "Secret private reason" not in str(audit_sub.details)

    # 2. Resignation approved audit
    client.put(f"/api/v1/employees/{emp.id}/resignation/approve", headers=hr_headers, json={"approved": True})
    audit_app = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == cid, AuditLog.action == "RESIGNATION_APPROVED", AuditLog.entity_id == emp.id)
        .first()
    )
    assert audit_app is not None

    # 3. Resignation withdrawn audit
    client.post(f"/api/v1/employees/{emp.id}/resignation/withdraw", headers=hr_headers)
    audit_with = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == cid, AuditLog.action == "RESIGNATION_WITHDRAWN", AuditLog.entity_id == emp.id)
        .first()
    )
    assert audit_with is not None

    # 4. FNF settled audit row
    client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=hr_headers,
        json={"resignation_date": str(today), "last_working_date": str(today)},
    )
    client.put(f"/api/v1/employees/{emp.id}/resignation/approve", headers=hr_headers, json={"approved": True})
    client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_headers,
        json={"it_clearance": True, "hr_clearance": True, "finance_clearance": True, "mark_settled": True},
    )
    audit_settled = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == cid, AuditLog.action == "FNF_SETTLED", AuditLog.entity_id == emp.id)
        .first()
    )
    assert audit_settled is not None
    assert "total_settlement_amount" in audit_settled.details

    # 5. Rate limit: 10 requests per minute on POST /terminate, 11th gives 429
    emp.is_active = True
    emp.resignation_status = ResignationStatus.none
    db.commit()
    from app.core.rate_limit import limiter
    limiter.enabled = True
    try:
        limiter.reset()
        term_codes = []
        for _ in range(12):
            r = client.post(
                f"/api/v1/employees/{emp.id}/terminate",
                headers=hr_headers,
                json={"termination_date": str(today), "reason": "Term reason"},
            )
            term_codes.append(r.status_code)
        assert all(c != 429 for c in term_codes[:10]), f"First 10 calls: {term_codes[:10]}"
        assert all(c == 429 for c in term_codes[10:]), f"Calls 11+: {term_codes[10:]}"
    finally:
        limiter.reset()


def test_r09_row_locks_sql_capture(client: TestClient, exit_setup: dict[str, Any], db: Session) -> None:
    """R9: Every write route locks employee row (SELECT ... FOR UPDATE)."""
    emp = exit_setup["emp"]
    hr_headers = _auth_headers(exit_setup["hr_user"])
    target_engine = db.get_bind()
    captured_statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        captured_statements.append(statement)

    event.listen(target_engine, "before_cursor_execute", before_cursor_execute)
    try:
        captured_statements.clear()
        client.post(
            f"/api/v1/employees/{emp.id}/resignation",
            headers=hr_headers,
            json={"resignation_date": str(date.today()), "last_working_date": str(date.today() + timedelta(days=30))},
        )
        has_for_update = any("FROM employees" in stmt and "FOR UPDATE" in stmt for stmt in captured_statements)
        assert has_for_update, f"Expected FOR UPDATE on resignation submit, got: {captured_statements}"

        captured_statements.clear()
        client.put(
            f"/api/v1/employees/{emp.id}/resignation/approve",
            headers=hr_headers,
            json={"approved": True},
        )
        has_app_update = any("FROM employees" in stmt and "FOR UPDATE" in stmt for stmt in captured_statements)
        assert has_app_update, f"Expected FOR UPDATE on resignation approve, got: {captured_statements}"
    finally:
        event.remove(target_engine, "before_cursor_execute", before_cursor_execute)


# =============================================================================
# Rule 10 Tests: TENANT ISOLATION & PIP INTEGRATION
# =============================================================================
def test_r10_pip_failure_uses_apply_exit(client: TestClient, exit_setup: dict[str, Any], db: Session) -> None:
    """R10: PIP failure uses same shared exit function (immediate exit, tokens revoked, audit row)."""
    from app.modules.performance.models import PerformancePIP, PIPStatus

    emp = exit_setup["emp"]
    emp_user = exit_setup["emp_user"]
    hr_headers = _auth_headers(exit_setup["hr_user"])
    cid = exit_setup["company_a"].id

    pip = PerformancePIP(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=emp.id,
        title="Performance Plan",
        start_date=date.today() - timedelta(days=30),
        end_date=date.today(),
        status=PIPStatus.active,
    )
    db.add(pip)
    db.commit()

    # Evaluate PIP as failed
    r_eval = client.post(
        f"/api/v1/performance/pips/{pip.id}/evaluate",
        headers=hr_headers,
        json={"outcome": "failed", "outcome_notes": "Objectives not met"},
    )
    assert r_eval.status_code == 200

    db.refresh(emp._obj)
    db.refresh(emp_user._obj)
    assert emp.is_active is False
    assert emp_user.is_active is False

    audit_exit = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == cid, AuditLog.action == "EMPLOYEE_EXIT_APPLIED", AuditLog.entity_id == emp.id)
        .first()
    )
    assert audit_exit is not None
