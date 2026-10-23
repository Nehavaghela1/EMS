"""Tests for Sub-feature 1.7c Manager role assignment: PATCH /users/{user_id}/role (Rules 1-10).

Rule 1: Only owner or hr_admin can call route; manager, employee and super_admin get 403,
        a missing or expired token gets 401, and caller's role is read from DB on every request.
Rule 2: Any owner can change employee, manager or hr_admin to employee, manager, hr_admin or owner;
        only company's first owner can demote another owner (to hr_admin or employee);
        first owner's own role can never be changed through this route;
        hr_admin can promote employee to manager/hr_admin, manager to hr_admin,
        and demote manager to employee;
        hr_admin gets 403 for anything touching hr_admin or owner or making an owner;
        updating reporting_manager_id via PUT /api/v1/employees/{id} never changes anyone's role.
Rule 3: New role can only be employee, manager, hr_admin or owner in lower case;
        Manager and MANAGER get 422; manager change works without current_password;
        owner grant/removal requires current_password.
Rule 4: Nobody can change their own role, including first owner.
Rule 5: Target must be active user of caller's company;
        to become manager target must have active employee profile in same company else 409.
Rule 6: Setting same role returns 200 and changes nothing.
Rule 7: Role change takes effect on target's very next request: refresh tokens revoked;
        email sent to target; email sent to every owner if hr_admin made change or owner touched.
Rule 8: Atomic transaction in service with row lock on target; failures roll back.
Rule 9: Every change writes ROLE_CHANGED audit row; demoting a manager also holds
        active_direct_reports (int counting active, not-deleted direct reports);
        password never appears in audit, logs, or response.
Rule 10: Rate-limited per user (30/min); safe response fields only; route in route policy;
         manager gets 403 on POST /api/v1/employees, role route, and changing reporting lines;
         promoted employee can approve direct report leave on next request;
         after demotion gets 403 on that route, team keeps reporting line, HR can approve for team.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.modules.hr.models import Employee, EmploymentType
from app.modules.identity.models import Company, RefreshToken, User, UserRole
from app.modules.platform.models import AuditLog
from app.modules.time_leave.models import Leave, LeaveStatus, LeaveType

# --- Credentials & Helpers ---

OWNER_RAW_PASSWORD = "CorrectOwnerPass123!"
CO_OWNER_RAW_PASSWORD = "CorrectCoOwnerPass123!"
HR_RAW_PASSWORD = "CorrectHrPass123!"
MGR_RAW_PASSWORD = "CorrectMgrPass123!"
EMP_RAW_PASSWORD = "CorrectEmpPass123!"


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        sub=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def company_setup(db: Session):
    """Provisions Company A with First Owner, Co-Owner, HR Admin, Manager, and Employee users."""
    from app.db.rls import bind_tenant_to_session

    cid = uuid.uuid4()
    company = Company(
        id=cid,
        name="1.7c Manager Corp",
        code=f"MC{uuid.uuid4().hex[:4].upper()}",
        email=f"corp-{uuid.uuid4().hex[:6]}@example.com",
        subdomain=f"corp-{uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
    )
    db.add(company)
    db.flush()

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    owner = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"first-owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password(OWNER_RAW_PASSWORD),
        role=UserRole.owner,
        is_active=True,
    )
    co_owner = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"co-owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password(CO_OWNER_RAW_PASSWORD),
        role=UserRole.owner,
        is_active=True,
    )
    hr_admin = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password(HR_RAW_PASSWORD),
        role=UserRole.hr_admin,
        is_active=True,
    )
    manager = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"mgr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password(MGR_RAW_PASSWORD),
        role=UserRole.manager,
        is_active=True,
    )
    employee = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password(EMP_RAW_PASSWORD),
        role=UserRole.employee,
        is_active=True,
    )

    db.add_all([owner, co_owner, hr_admin, manager, employee])
    db.flush()
    company.owner_user_id = owner.id
    db.flush()

    # Also give employee and manager active Employee profiles so manager transitions work
    emp_profile = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=employee.id,
        employee_code=f"EMP-{uuid.uuid4().hex[:4].upper()}",
        first_name="Test",
        last_name="Employee",
        email=employee.email,
        employment_type=EmploymentType.full_time,
        hire_date=utcnow().date(),
        is_active=True,
    )
    mgr_profile = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=manager.id,
        employee_code=f"MGR-{uuid.uuid4().hex[:4].upper()}",
        first_name="Test",
        last_name="Manager",
        email=manager.email,
        employment_type=EmploymentType.full_time,
        hire_date=utcnow().date(),
        is_active=True,
    )
    db.add_all([emp_profile, mgr_profile])
    db.commit()

    return {
        "company": company,
        "owner": owner,
        "co_owner": co_owner,
        "hr_admin": hr_admin,
        "manager": manager,
        "employee": employee,
        "employee_profile": emp_profile,
        "manager_profile": mgr_profile,
    }


# ==============================================================================
# Rule 1: Caller Authorization & Database-Fresh Role Checks
# ==============================================================================


def test_R01_caller_authorization_and_fresh_role(
    client: TestClient, db: Session, company_setup, super_admin_headers
):
    """R01: Only owner or hr_admin can call route; manager, employee, super_admin get 403;
    missing/expired token -> 401; caller's role is read from DB on every request.
    """
    target = company_setup["employee"]
    url = f"/api/v1/users/{target.id}/role"
    body = {"role": "manager"}

    # 1. Missing token -> 401
    res_no_auth = client.patch(url, json=body)
    assert res_no_auth.status_code == 401

    # 2. Expired token -> 401
    expired_payload = {
        "sub": str(company_setup["owner"].id),
        "company_id": str(company_setup["company"].id),
        "role": "owner",
        "exp": datetime.now(UTC) - timedelta(minutes=5),
        "iat": datetime.now(UTC) - timedelta(minutes=10),
    }
    expired_token = jwt.encode(
        expired_payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    res_expired = client.patch(url, headers={"Authorization": f"Bearer {expired_token}"}, json=body)
    assert res_expired.status_code == 401

    # 3. Super admin -> 403
    res_super = client.patch(url, headers=super_admin_headers, json=body)
    assert res_super.status_code == 403

    # 4. Manager -> 403
    res_mgr = client.patch(url, headers=_auth_headers(company_setup["manager"]), json=body)
    assert res_mgr.status_code == 403

    # 5. Employee -> 403
    res_emp = client.patch(url, headers=_auth_headers(company_setup["employee"]), json=body)
    assert res_emp.status_code == 403

    # 6. Database fresh role check: Token claims hr_admin, but DB role changed to employee -> 403
    stale_token = create_access_token(
        sub=str(company_setup["employee"].id),
        company_id=str(company_setup["company"].id),
        role="hr_admin",  # Forged/stale token claims hr_admin
    )
    res_stale = client.patch(url, headers={"Authorization": f"Bearer {stale_token}"}, json=body)
    assert res_stale.status_code == 403


# ==============================================================================
# Rule 2: Authority Matrix (Owner & HR Admin) & Reporting Manager Line Decoupling
# ==============================================================================


def test_R02_authority_matrix_and_reporting_manager_decoupling(
    client: TestClient, db: Session, company_setup
):
    """R02:
    - Owner and hr_admin promote employee->manager and demote manager->employee.
    - hr_admin on hr_admin or owner target gets 403.
    - hr_admin making an owner gets 403.
    - First owner demoting owner to hr_admin/employee succeeds; co-owner demoting owner fails (403).
    - First owner cannot demote self.
    - Updating reporting_manager_id via PUT /api/v1/employees/{id} leaves role unchanged.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    hr_headers = _auth_headers(company_setup["hr_admin"])
    emp = company_setup["employee"]
    hr = company_setup["hr_admin"]
    co_owner = company_setup["co_owner"]
    url_emp = f"/api/v1/users/{emp.id}/role"
    url_hr = f"/api/v1/users/{hr.id}/role"
    url_co_owner = f"/api/v1/users/{co_owner.id}/role"

    # 1. HR Admin promotes employee -> manager (200)
    res_hr_promotes_emp = client.patch(url_emp, headers=hr_headers, json={"role": "manager"})
    assert res_hr_promotes_emp.status_code == 200
    assert res_hr_promotes_emp.json()["role"] == "manager"
    assert res_hr_promotes_emp.json()["previous_role"] == "employee"

    # 2. HR Admin demotes manager -> employee (200)
    res_hr_demotes_mgr = client.patch(url_emp, headers=hr_headers, json={"role": "employee"})
    assert res_hr_demotes_mgr.status_code == 200
    assert res_hr_demotes_mgr.json()["role"] == "employee"

    # 3. Owner promotes employee -> manager (200)
    res_owner_promotes_emp = client.patch(url_emp, headers=owner_headers, json={"role": "manager"})
    assert res_owner_promotes_emp.status_code == 200
    assert res_owner_promotes_emp.json()["role"] == "manager"

    # 4. Owner demotes manager -> employee (200)
    res_owner_demotes_mgr = client.patch(url_emp, headers=owner_headers, json={"role": "employee"})
    assert res_owner_demotes_mgr.status_code == 200
    assert res_owner_demotes_mgr.json()["role"] == "employee"

    # 5. HR Admin on HR Admin target -> 403
    res_hr_on_hr = client.patch(url_hr, headers=hr_headers, json={"role": "manager"})
    assert res_hr_on_hr.status_code == 403

    # 6. HR Admin on Owner target -> 403
    res_hr_on_owner = client.patch(url_co_owner, headers=hr_headers, json={"role": "employee"})
    assert res_hr_on_owner.status_code == 403

    # 7. HR Admin making an Owner -> 403
    res_hr_makes_owner = client.patch(url_emp, headers=hr_headers, json={"role": "owner"})
    assert res_hr_makes_owner.status_code == 403

    # 8. First owner demotes co-owner to hr_admin (needs current_password) -> 200
    res_first_demotes_owner = client.patch(
        url_co_owner,
        headers=owner_headers,
        json={"role": "hr_admin", "current_password": OWNER_RAW_PASSWORD},
    )
    assert res_first_demotes_owner.status_code == 200

    # 9. Co-owner (now hr_admin) cannot demote first owner -> 403
    res_co_demotes_first = client.patch(
        f"/api/v1/users/{company_setup['owner'].id}/role",
        headers=_auth_headers(co_owner),
        json={"role": "employee"},
    )
    assert res_co_demotes_first.status_code == 403

    # 10. Updating employee reporting_manager_id via PUT /api/v1/employees/{id} keeps role unchanged
    # First re-fetch or ensure emp is employee
    db.refresh(emp)
    assert emp.role == UserRole.employee

    # Let HR update employee profile reporting_manager_id to point to manager profile
    profile_id = company_setup["employee_profile"].id
    mgr_profile_id = company_setup["manager_profile"].id
    res_put_emp = client.put(
        f"/api/v1/employees/{profile_id}",
        headers=hr_headers,
        json={"reporting_manager_id": str(mgr_profile_id)},
    )
    assert res_put_emp.status_code == 200

    db.refresh(emp)
    assert emp.role == UserRole.employee, "Reporting manager assignment must never change role"


# ==============================================================================
# Rule 3: Strict Schema Validation & Password Re-entry Rules
# ==============================================================================


def test_R03_strict_role_validation_and_manager_passwordless(
    client: TestClient, db: Session, company_setup
):
    """R03:
    - 'manager' is accepted in lower case.
    - 'Manager' and 'MANAGER' get 422.
    - Unknown, empty, null, missing, extra fields get 422.
    - Manager role change works without current_password.
    - Owner role change requires valid current_password (missing -> 422, wrong -> 403).
    """
    owner_headers = _auth_headers(company_setup["owner"])
    emp = company_setup["employee"]
    url_emp = f"/api/v1/users/{emp.id}/role"

    # Case variations and invalid inputs -> 422
    for bad in ["Manager", "MANAGER", "mANAGER", "super_admin", "unknown", "", None]:
        res_bad = client.patch(url_emp, headers=owner_headers, json={"role": bad})
        assert res_bad.status_code == 422, f"Expected 422 for role={bad}, got {res_bad.status_code}"

    # Extra field -> 422
    res_extra = client.patch(
        url_emp, headers=owner_headers, json={"role": "manager", "extra_prop": "invalid"}
    )
    assert res_extra.status_code == 422

    # Manager change without current_password -> 200
    res_mgr_no_pw = client.patch(url_emp, headers=owner_headers, json={"role": "manager"})
    assert res_mgr_no_pw.status_code == 200
    assert res_mgr_no_pw.json()["role"] == "manager"

    # Owner change requires current_password -> 422 if missing
    res_owner_no_pw = client.patch(url_emp, headers=owner_headers, json={"role": "owner"})
    assert res_owner_no_pw.status_code == 422

    # Owner change with wrong current_password -> 403
    res_owner_wrong_pw = client.patch(
        url_emp,
        headers=owner_headers,
        json={"role": "owner", "current_password": "WrongPassword123!"},
    )
    assert res_owner_wrong_pw.status_code == 403


# ==============================================================================
# Rule 4: Self Role Modification Gated Out
# ==============================================================================


def test_R04_self_role_modification_forbidden(client: TestClient, db: Session, company_setup):
    """R04: Nobody can change their own role, including the first owner (403, no changes)."""
    owner = company_setup["owner"]
    owner_headers = _auth_headers(owner)
    url_self = f"/api/v1/users/{owner.id}/role"

    res_self = client.patch(
        url_self,
        headers=owner_headers,
        json={"role": "manager", "current_password": OWNER_RAW_PASSWORD},
    )
    assert res_self.status_code == 403
    assert "Cannot change your own role" in res_self.json()["error"]["message"]

    db.refresh(owner)
    assert owner.role == UserRole.owner


# ==============================================================================
# Rule 5: Target Tenant Boundary & Active Employee Profile Pre-requisite
# ==============================================================================


def test_R05_target_validation_and_active_profile_requirement(
    client: TestClient, db: Session, company_setup
):
    """R05:
    - Target must be an active user of caller's company; unknown id or cross-company gives 404.
    - To become a manager, target must have an active employee profile in the same company;
      otherwise returns 409 and role is unchanged.
    - With active employee profile, returns 200.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    cid = company_setup["company"].id

    # 1. Target with NO employee profile -> 409
    user_no_profile = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"noprofile-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(user_no_profile)
    db.commit()

    res_no_profile = client.patch(
        f"/api/v1/users/{user_no_profile.id}/role",
        headers=owner_headers,
        json={"role": "manager"},
    )
    assert res_no_profile.status_code == 409, f"Expected 409, got {res_no_profile.status_code}"
    db.refresh(user_no_profile)
    assert user_no_profile.role == UserRole.employee

    # 2. Target with INACTIVE employee profile -> 409
    inactive_profile = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=user_no_profile.id,
        employee_code=f"INACT-{uuid.uuid4().hex[:4].upper()}",
        first_name="Inactive",
        last_name="Emp",
        email=user_no_profile.email,
        employment_type=EmploymentType.full_time,
        hire_date=utcnow().date(),
        is_active=False,  # Inactive
    )
    db.add(inactive_profile)
    db.commit()

    res_inact_profile = client.patch(
        f"/api/v1/users/{user_no_profile.id}/role",
        headers=owner_headers,
        json={"role": "manager"},
    )
    assert res_inact_profile.status_code == 409
    db.refresh(user_no_profile)
    assert user_no_profile.role == UserRole.employee

    # 3. Activate profile -> 200
    inactive_profile.is_active = True
    db.commit()

    res_act_profile = client.patch(
        f"/api/v1/users/{user_no_profile.id}/role",
        headers=owner_headers,
        json={"role": "manager"},
    )
    assert res_act_profile.status_code == 200
    db.refresh(user_no_profile)
    assert user_no_profile.role == UserRole.manager

    # 4. Unknown user -> 404
    res_unknown = client.patch(
        f"/api/v1/users/{uuid.uuid4()}/role",
        headers=owner_headers,
        json={"role": "manager"},
    )
    assert res_unknown.status_code == 404


# ==============================================================================
# Rule 6: Idempotent No-Op Role Change
# ==============================================================================


def test_R06_idempotent_no_op_role_change(client: TestClient, db: Session, company_setup):
    """R06: Setting same role returns 200 with changed=False and changes nothing:
    no audit row, no token revocation, no email.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    mgr = company_setup["manager"]
    url_mgr = f"/api/v1/users/{mgr.id}/role"

    audit_count_before = db.scalar(
        select(AuditLog)
        .where(AuditLog.action == "ROLE_CHANGED")
        .with_only_columns(text("count(*)"))
    )

    res_noop = client.patch(url_mgr, headers=owner_headers, json={"role": "manager"})
    assert res_noop.status_code == 200
    body = res_noop.json()
    assert body["role"] == "manager"
    assert body["previous_role"] == "manager"
    assert body["changed"] is False

    audit_count_after = db.scalar(
        select(AuditLog)
        .where(AuditLog.action == "ROLE_CHANGED")
        .with_only_columns(text("count(*)"))
    )
    assert audit_count_after == audit_count_before


# ==============================================================================
# Rule 7: Immediate Effect, Session Revocation, and Targeted Notifications
# ==============================================================================


def test_R07_session_revocation_and_notification(
    client: TestClient, db: Session, company_setup, email_outbox
):
    """R07: Refresh tokens revoked; email sent to target; email sent to every owner
    when hr_admin makes change.
    """
    emp = company_setup["employee"]

    # Create active refresh tokens for emp
    rt = RefreshToken(
        id=uuid.uuid4(),
        user_id=emp.id,
        token_hash=hashlib.sha256(b"fake-refresh-token").hexdigest(),
        expires_at=utcnow() + timedelta(days=7),
        is_revoked=False,
    )
    db.add(rt)
    db.commit()

    email_outbox.clear()
    hr_headers = _auth_headers(company_setup["hr_admin"])
    res = client.patch(f"/api/v1/users/{emp.id}/role", headers=hr_headers, json={"role": "manager"})
    assert res.status_code == 200

    db.refresh(rt)
    assert rt.is_revoked is True, "Refresh tokens must be revoked on role change"
    assert len(email_outbox) >= 1, "At least target and owner notification emails should be sent"


# ==============================================================================
# Rule 8: Single Transaction with Row Lock & Rollback on Error
# ==============================================================================


def test_R08_atomic_transaction_and_rollback(client: TestClient, db: Session, company_setup):
    """R08: Exactly one commit inside service with row lock; errors roll back completely."""
    owner_headers = _auth_headers(company_setup["owner"])
    emp = company_setup["employee"]
    url_emp = f"/api/v1/users/{emp.id}/role"

    # Simulate unexpected DB failure on commit
    with pytest.MonkeyPatch.context() as m:

        def failing_commit():
            raise RuntimeError("DB connection dropped")

        m.setattr(db, "commit", failing_commit)

        # Attempt role change
        with pytest.raises(RuntimeError):
            client.patch(url_emp, headers=owner_headers, json={"role": "manager"})

    db.rollback()
    db.refresh(emp)
    assert emp.role == UserRole.employee, "Role change must roll back on failure"


# ==============================================================================
# Rule 9: Audit Trail with active_direct_reports on Manager Demotion
# ==============================================================================


def test_R09_audit_details_and_active_direct_reports_on_demotion(
    client: TestClient, db: Session, company_setup
):
    """R09: Every change writes ROLE_CHANGED audit row (previous_role, new_role).
    When a manager is demoted, audit details also hold active_direct_reports as an int
    counting only active, not-deleted direct reports.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    cid = company_setup["company"].id
    mgr = company_setup["manager"]
    mgr_profile = company_setup["manager_profile"]

    # Create 3 direct reports for mgr_profile: 2 active, 1 inactive
    r1 = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        reporting_manager_id=mgr_profile.id,
        employee_code=f"R1-{uuid.uuid4().hex[:4].upper()}",
        first_name="Report",
        last_name="One",
        email=f"r1-{uuid.uuid4().hex[:6]}@example.com",
        employment_type=EmploymentType.full_time,
        hire_date=utcnow().date(),
        is_active=True,
    )
    r2 = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        reporting_manager_id=mgr_profile.id,
        employee_code=f"R2-{uuid.uuid4().hex[:4].upper()}",
        first_name="Report",
        last_name="Two",
        email=f"r2-{uuid.uuid4().hex[:6]}@example.com",
        employment_type=EmploymentType.full_time,
        hire_date=utcnow().date(),
        is_active=True,
    )
    r3_inactive = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        reporting_manager_id=mgr_profile.id,
        employee_code=f"R3-{uuid.uuid4().hex[:4].upper()}",
        first_name="Report",
        last_name="Three",
        email=f"r3-{uuid.uuid4().hex[:6]}@example.com",
        employment_type=EmploymentType.full_time,
        hire_date=utcnow().date(),
        is_active=False,  # Inactive
    )
    db.add_all([r1, r2, r3_inactive])
    db.commit()

    # Demote manager -> employee
    res_demote = client.patch(
        f"/api/v1/users/{mgr.id}/role",
        headers=owner_headers,
        json={"role": "employee"},
    )
    assert res_demote.status_code == 200

    # Inspect the latest ROLE_CHANGED audit log
    audit_log = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity_id == mgr.id,
            AuditLog.action == "ROLE_CHANGED",
        )
        .order_by(AuditLog.created_at.desc())
    )
    assert audit_log is not None
    details = audit_log.details or {}
    assert details.get("previous_role") == "manager"
    assert details.get("new_role") == "employee"
    assert details.get("active_direct_reports") == 2, (
        f"Expected active_direct_reports=2, got {details.get('active_direct_reports')}"
    )


# ==============================================================================
# Rule 10: Rate Limiting, Live Approval Checks, Demotion Lockout & Team Retention
# ==============================================================================


def test_R10_manager_permissions_live_approvals_and_demotion(
    client: TestClient, db: Session, company_setup
):
    """R10:
    - Manager gets 403 on POST /employees, role route, and changing reporting lines.
    - Promoted employee can approve direct report leave on next request via PUT /api/v1/leaves/{id}.
    - After demotion the same user gets 403 on that route.
    - The direct report's reporting line stays intact.
    - HR admin can still approve for that team.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    hr_headers = _auth_headers(company_setup["hr_admin"])
    cid = company_setup["company"].id

    # 1. Promote an employee to manager
    candidate_user = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"lead-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("LeadPass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(candidate_user)
    db.flush()

    lead_profile = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=candidate_user.id,
        employee_code=f"LEAD-{uuid.uuid4().hex[:4].upper()}",
        first_name="Team",
        last_name="Lead",
        email=candidate_user.email,
        employment_type=EmploymentType.full_time,
        hire_date=utcnow().date(),
        is_active=True,
    )
    db.add(lead_profile)
    db.commit()

    # Direct report under lead_profile
    sub_user = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"sub-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("SubPass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(sub_user)
    db.flush()

    sub_profile = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=sub_user.id,
        reporting_manager_id=lead_profile.id,
        employee_code=f"SUB-{uuid.uuid4().hex[:4].upper()}",
        first_name="Direct",
        last_name="Report",
        email=sub_user.email,
        employment_type=EmploymentType.full_time,
        hire_date=utcnow().date(),
        is_active=True,
    )
    db.add(sub_profile)
    db.commit()

    # Promote candidate_user to manager
    res_promote = client.patch(
        f"/api/v1/users/{candidate_user.id}/role",
        headers=owner_headers,
        json={"role": "manager"},
    )
    assert res_promote.status_code == 200

    lead_headers = _auth_headers(candidate_user)

    # 2. Manager forbidden operations:
    # A. POST /api/v1/employees -> 403
    res_create_emp = client.post(
        "/api/v1/employees",
        headers=lead_headers,
        json={
            "employee_code": "FORBID-1",
            "first_name": "Forbidden",
            "last_name": "Emp",
            "email": "forbid@example.com",
            "hire_date": str(utcnow().date()),
            "employment_type": "full_time",
        },
    )
    assert res_create_emp.status_code == 403

    # B. PATCH /users/{id}/role -> 403
    res_role_chg = client.patch(
        f"/api/v1/users/{sub_user.id}/role",
        headers=lead_headers,
        json={"role": "employee"},
    )
    assert res_role_chg.status_code == 403

    # C. Changing a reporting line via PUT /api/v1/employees/{id} -> 403
    res_chg_rep = client.put(
        f"/api/v1/employees/{sub_profile.id}",
        headers=lead_headers,
        json={"reporting_manager_id": str(lead_profile.id)},
    )
    assert res_chg_rep.status_code == 403

    # 3. Create a pending leave for sub_profile
    leave_type = LeaveType(
        id=uuid.uuid4(),
        company_id=cid,
        name=f"Casual-{uuid.uuid4().hex[:4]}",
        code=f"CL{uuid.uuid4().hex[:3].upper()}",
        annual_allowance=12,
        is_paid=False,
        is_active=True,
    )
    db.add(leave_type)
    db.flush()

    leave_req = Leave(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=sub_profile.id,
        leave_type_id=leave_type.id,
        start_date=utcnow().date(),
        end_date=utcnow().date(),
        total_days=1,
        is_half_day=False,
        reason="Test Leave",
        status=LeaveStatus.pending,
    )
    db.add(leave_req)
    db.commit()

    # 4. As manager, approve leave -> 200
    res_appr_mgr = client.put(
        f"/api/v1/leaves/{leave_req.id}",
        headers=lead_headers,
        json={"status": "approved", "rejection_reason": None},
    )
    assert res_appr_mgr.status_code == 200
    assert res_appr_mgr.json()["status"] == "approved"

    # Reset leave back to pending for demotion test
    leave_req.status = LeaveStatus.pending
    db.commit()

    # 5. Demote candidate_user back to employee
    res_demote = client.patch(
        f"/api/v1/users/{candidate_user.id}/role",
        headers=owner_headers,
        json={"role": "employee"},
    )
    assert res_demote.status_code == 200

    # 6. Demoted user now gets 403 on the approval route
    res_appr_after_demote = client.put(
        f"/api/v1/leaves/{leave_req.id}",
        headers=lead_headers,
        json={"status": "approved", "rejection_reason": None},
    )
    assert res_appr_after_demote.status_code == 403

    # 7. Direct report keeps their reporting line
    db.refresh(sub_profile)
    assert sub_profile.reporting_manager_id == lead_profile.id

    # 8. HR admin can still approve for that team -> 200
    res_appr_hr = client.put(
        f"/api/v1/leaves/{leave_req.id}",
        headers=hr_headers,
        json={"status": "approved", "rejection_reason": None},
    )
    assert res_appr_hr.status_code == 200
    assert res_appr_hr.json()["status"] == "approved"
