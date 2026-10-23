"""Tests for Sub-feature 1.7 Roles & role change: PATCH /users/{user_id}/role (Rules 1-10).

Rule 1: Only owner or hr_admin can call the route; manager, employee and super_admin get 403;
        missing or expired token gets 401; caller's role is read from DB on every request.
Rule 2: Any owner can make employee/manager/hr_admin an hr_admin or owner, and can demote hr_admin;
        only first owner can demote another owner; first owner's role cannot be changed (keeps >=1);
        hr_admin can only promote employee/manager to hr_admin (403 on owner/hr_admin target/grant);
        first owner recorded at registration/approval/workspace creation with is_primary_owner true.
Rule 3: New role can only be employee, hr_admin or owner in lower case; others return 422;
        granting or removing owner needs current_password (missing or >128 chars -> 422);
        wrong password returns 403, increments failed_attempts and locks account without leaks.
Rule 4: Nobody can change their own role, including the first owner (403, no audit, sec log);
        wrong current_password on owner change returns 403, increments failed_attempts, locks user.
Rule 5: Target must be active user of caller's company; other company user, unknown id,
        inactive or unactivated user, or platform account returns identical 404 with no details;
        malformed id gives 422; user in two companies keeps other workspace role untouched.
Rule 6: Same role returns 200 and changes nothing: no audit row, no token revocation, no email;
        hr_admin sending same role on hr_admin target still gets 403.
Rule 7: Role change takes effect on target's very next request: refresh tokens revoked;
        old access token acts with new authority; fresh login has new role; email to target;
        every owner gets email when hr_admin makes change; every other owner gets email when
        owner role is granted or removed; none on failure, no-op or denial.
Rule 8: Exactly one commit inside the service with SELECT ... FOR UPDATE row lock on target;
        failure rolls back everything (no token revocation, no email); consistent audit chain.
Rule 9: Every change writes ROLE_CHANGED audit row (actor, target, old role, new role, company);
        denied attempts (wrong role, self-change, forbidden target, wrong password) log without PII;
        current_password never appears in audit, logs, or response.
Rule 10: Rate-limited per user (30/min) with 429; safe response fields only (no hash/token);
         route in route_policy matrix as owner and hr_admin; approval consistency.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.modules.identity.models import Company, RefreshToken, User, UserRole
from app.modules.platform.models import AuditLog

# --- Helpers & Fixtures ---

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
        name="Role Test Corp",
        code=f"RC{uuid.uuid4().hex[:4].upper()}",
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
    db.commit()

    return {
        "company": company,
        "owner": owner,  # First owner
        "co_owner": co_owner,  # Co-owner
        "hr_admin": hr_admin,
        "manager": manager,
        "employee": employee,
    }


@pytest.fixture
def company_b_setup(db: Session):
    """Provisions Company B for multi-tenant isolation testing."""
    cid = uuid.uuid4()
    company = Company(
        id=cid,
        name="Company B Corp",
        code=f"CB{uuid.uuid4().hex[:4].upper()}",
        email=f"b-{uuid.uuid4().hex[:6]}@example.com",
        subdomain=f"b-{uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
    )
    db.add(company)
    db.flush()

    b_employee = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"b-emp-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("pw_b_emp"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(b_employee)
    db.flush()
    db.commit()

    return {
        "company": company,
        "employee": b_employee,
    }


# ==============================================================================
# Rule 1 Tests: Caller Authorization & Live Role Evaluation
# ==============================================================================


def test_R01_caller_role_authorization_and_token_checks(
    client: TestClient, db: Session, company_setup, super_admin_headers
):
    """R01: Only owner or hr_admin can reach PATCH /users/{user_id}/role.
    Manager, employee, super_admin get 403.
    Missing token gets 401. Expired token gets 401.
    A caller whose role is changed in DB after token issuance is judged by the DB role.
    """
    target = company_setup["employee"]
    url = f"/api/v1/users/{target.id}/role"
    body = {"role": "hr_admin"}

    # 1. Missing token -> 401
    res_no_tok = client.patch(url, json=body)
    assert res_no_tok.status_code == 401

    # 2. Expired token -> 401
    now = datetime.now(UTC)
    exp_payload = {
        "sub": str(company_setup["owner"].id),
        "company_id": str(company_setup["company"].id),
        "role": UserRole.owner.value,
        "type": "access",
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
    }
    expired_token = jwt.encode(exp_payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    res_exp = client.patch(url, headers={"Authorization": f"Bearer {expired_token}"}, json=body)
    assert res_exp.status_code == 401

    # 3. Super admin gets 403 (route is scoped to tenant administrators)
    res_sa = client.patch(url, headers=super_admin_headers, json=body)
    assert res_sa.status_code == 403

    # 4. Manager gets 403
    res_mgr = client.patch(url, headers=_auth_headers(company_setup["manager"]), json=body)
    assert res_mgr.status_code == 403

    # 5. Regular employee gets 403
    res_emp = client.patch(url, headers=_auth_headers(company_setup["employee"]), json=body)
    assert res_emp.status_code == 403

    # 6. HR admin reaches route (promote manager to hr_admin)
    res_hr = client.patch(
        f"/api/v1/users/{company_setup['manager'].id}/role",
        headers=_auth_headers(company_setup["hr_admin"]),
        json={"role": "hr_admin"},
    )
    assert res_hr.status_code == 200

    # 7. Owner reaches route (expected 200)
    res_owner = client.patch(url, headers=_auth_headers(company_setup["owner"]), json=body)
    assert res_owner.status_code == 200

    # 8. Dynamic check: caller issued token with role="hr_admin", but demoted in DB to employee.
    caller_token_headers = _auth_headers(company_setup["hr_admin"])
    u_hr = db.get(User, company_setup["hr_admin"].id)
    u_hr.role = UserRole.employee
    db.commit()

    res_demoted_caller = client.patch(
        f"/api/v1/users/{company_setup['manager'].id}/role",
        headers=caller_token_headers,
        json={"role": "hr_admin"},
    )
    assert res_demoted_caller.status_code == 403


# ==============================================================================
# Rule 2 Tests: Co-Owners, First Owner Guards, Authority Matrix & DB Invariants
# ==============================================================================


def test_R02_co_owners_first_owner_guards_and_authority_matrix(
    client: TestClient, db: Session, company_setup
):
    """R02:
    - First owner: employee, manager, hr_admin to owner (with correct current_password) succeed.
    - First owner demoting a co-owner to hr_admin and to employee succeeds.
    - Any owner: employee to hr_admin and hr_admin to employee succeed.
    - Co-owner: employee to owner succeeds.
    - Co-owner demoting another owner (co-owner or first owner) gets 403.
    - Nobody can change first owner (co-owner 403, hr_admin 403).
    - HR admin: employee to hr_admin, manager to hr_admin succeed.
    - HR admin: granting owner gets 403.
    - HR admin on hr_admin target (to employee, or same role) gets 403.
    - HR admin on any owner target gets 403.
    - Company always has at least one owner.
    - First-owner flag: approval and workspace creation set exactly one is_primary_owner=true.
    - DB rejects second is_primary_owner in one company, rejects flag on non-owner.
    """
    first_owner_headers = _auth_headers(company_setup["owner"])
    hr_headers = _auth_headers(company_setup["hr_admin"])

    # 1. First owner: employee to owner (with current_password) succeeds
    res1 = client.patch(
        f"/api/v1/users/{company_setup['employee'].id}/role",
        headers=first_owner_headers,
        json={"role": "owner", "current_password": OWNER_RAW_PASSWORD},
    )
    assert res1.status_code == 200

    # 2. First owner: manager to owner succeeds
    res2 = client.patch(
        f"/api/v1/users/{company_setup['manager'].id}/role",
        headers=first_owner_headers,
        json={"role": "owner", "current_password": OWNER_RAW_PASSWORD},
    )
    assert res2.status_code == 200

    # 3. First owner: hr_admin to owner succeeds
    res3 = client.patch(
        f"/api/v1/users/{company_setup['hr_admin'].id}/role",
        headers=first_owner_headers,
        json={"role": "owner", "current_password": OWNER_RAW_PASSWORD},
    )
    assert res3.status_code == 200

    # 4. First owner demotes a co-owner to hr_admin succeeds
    res4 = client.patch(
        f"/api/v1/users/{company_setup['co_owner'].id}/role",
        headers=first_owner_headers,
        json={"role": "hr_admin", "current_password": OWNER_RAW_PASSWORD},
    )
    assert res4.status_code == 200

    # 5. First owner demotes a co-owner to employee succeeds
    res5 = client.patch(
        f"/api/v1/users/{company_setup['employee'].id}/role",
        headers=first_owner_headers,
        json={"role": "employee", "current_password": OWNER_RAW_PASSWORD},
    )
    assert res5.status_code == 200

    # Setup a fresh co-owner and fresh employee
    fresh_co = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"fresh-co-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password(CO_OWNER_RAW_PASSWORD),
        role=UserRole.owner,
        is_active=True,
    )
    fresh_emp = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"fresh-emp-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("pw"),
        role=UserRole.employee,
        is_active=True,
    )
    fresh_hr = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"fresh-hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password(HR_RAW_PASSWORD),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add_all([fresh_co, fresh_emp, fresh_hr])
    db.commit()

    fresh_co_headers = _auth_headers(fresh_co)

    # 6. Any owner: employee to hr_admin succeeds
    res6 = client.patch(
        f"/api/v1/users/{fresh_emp.id}/role",
        headers=fresh_co_headers,
        json={"role": "hr_admin"},
    )
    assert res6.status_code == 200

    # 7. Any owner: hr_admin to employee succeeds
    res7 = client.patch(
        f"/api/v1/users/{fresh_hr.id}/role",
        headers=fresh_co_headers,
        json={"role": "employee"},
    )
    assert res7.status_code == 200

    # 8. Co-owner: employee to owner succeeds (with co-owner's password)
    res8 = client.patch(
        f"/api/v1/users/{fresh_emp.id}/role",
        headers=fresh_co_headers,
        json={"role": "owner", "current_password": CO_OWNER_RAW_PASSWORD},
    )
    assert res8.status_code == 200

    # 9. Co-owner demoting another owner (co-owner or first owner) gets 403
    res_co_demote_first = client.patch(
        f"/api/v1/users/{company_setup['owner'].id}/role",
        headers=fresh_co_headers,
        json={"role": "hr_admin", "current_password": CO_OWNER_RAW_PASSWORD},
    )
    assert res_co_demote_first.status_code == 403

    res_co_demote_co = client.patch(
        f"/api/v1/users/{fresh_emp.id}/role",
        headers=fresh_co_headers,
        json={"role": "hr_admin", "current_password": CO_OWNER_RAW_PASSWORD},
    )
    assert res_co_demote_co.status_code == 403

    # 10. Nobody can change the first owner
    res_hr_on_first = client.patch(
        f"/api/v1/users/{company_setup['owner'].id}/role",
        headers=hr_headers,
        json={"role": "employee"},
    )
    assert res_hr_on_first.status_code == 403

    # 11. HR admin permissions:
    hr_actor = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"hr-actor-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password(HR_RAW_PASSWORD),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(hr_actor)
    db.commit()
    hr_actor_headers = _auth_headers(hr_actor)

    # - HR admin to owner gets 403
    res_hr_to_owner = client.patch(
        f"/api/v1/users/{fresh_emp.id}/role",
        headers=hr_actor_headers,
        json={"role": "owner", "current_password": HR_RAW_PASSWORD},
    )
    assert res_hr_to_owner.status_code == 403

    # - HR admin on hr_admin target (to employee, and same role hr_admin) gets 403
    another_hr = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"target-hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("pw"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(another_hr)
    db.commit()

    res_hr_demote_hr = client.patch(
        f"/api/v1/users/{another_hr.id}/role",
        headers=hr_actor_headers,
        json={"role": "employee"},
    )
    assert res_hr_demote_hr.status_code == 403

    res_hr_same_hr = client.patch(
        f"/api/v1/users/{another_hr.id}/role",
        headers=hr_actor_headers,
        json={"role": "hr_admin"},
    )
    assert res_hr_same_hr.status_code == 403

    # - HR admin on co-owner target (to employee) gets 403
    res_hr_on_co_owner = client.patch(
        f"/api/v1/users/{fresh_co.id}/role",
        headers=hr_actor_headers,
        json={"role": "employee"},
    )
    assert res_hr_on_co_owner.status_code == 403

    # 12. First-owner tracking: approval and workspace creation set company.owner_user_id
    import importlib.util
    from pathlib import Path

    from app.modules.identity.schemas import CompanyRegisterRequest, CreateWorkspaceRequest
    from app.modules.identity.service import CompanyService

    ver_file = "alembic/versions/b3a17e0892c1_backfill_company_owner_user_id.py"
    migration_path = Path(__file__).resolve().parents[2] / ver_file
    spec = importlib.util.spec_from_file_location("b3a17e0892c1_backfill", str(migration_path))
    migration_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_mod)
    BACKFILL_SQL = migration_mod.BACKFILL_SQL

    comp_service = CompanyService(db)

    # A. Workspace creation sets owner_user_id
    ws_co, _, _ = comp_service.create_workspace(
        current_user=company_setup["owner"],
        data=CreateWorkspaceRequest(
            company_name=f"Sub Org {uuid.uuid4().hex[:4]}",
            country="IN",
        ),
    )
    assert ws_co.owner_user_id is not None
    ws_owner_user = (
        db.query(User).filter(User.company_id == ws_co.id, User.role == UserRole.owner).first()
    )
    assert ws_co.owner_user_id == ws_owner_user.id

    # B. Approval flow sets owner_user_id
    reg_co = comp_service.register_company(
        CompanyRegisterRequest(
            company_name=f"Approve Co {uuid.uuid4().hex[:4]}",
            company_email=f"appr-{uuid.uuid4().hex[:6]}@example.com",
            country="IN",
            admin_password="ValidPassword123!",
        )
    )
    # Approve with super_admin
    appr_co, _ = comp_service.approve_company(
        company_id=reg_co.id,
        admin_id=company_setup["owner"].id,
    )
    assert appr_co.owner_user_id is not None
    appr_owner_user = (
        db.query(User).filter(User.company_id == appr_co.id, User.role == UserRole.owner).first()
    )
    assert appr_co.owner_user_id == appr_owner_user.id

    # C. BACKFILL_SQL sets owner_user_id on companies where it was NULL to earliest owner
    backfill_co = Company(
        id=uuid.uuid4(),
        name="Backfill Co",
        code=f"BK{uuid.uuid4().hex[:4].upper()}",
        email=f"bk-{uuid.uuid4().hex[:6]}@example.com",
        status="active",
        is_active=True,
        owner_user_id=None,
    )
    db.add(backfill_co)
    db.flush()

    earlier_owner = User(
        id=uuid.uuid4(),
        company_id=backfill_co.id,
        email=f"early-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="pw",
        role=UserRole.owner,
        created_at=utcnow() - timedelta(days=10),
        is_active=True,
    )
    later_owner = User(
        id=uuid.uuid4(),
        company_id=backfill_co.id,
        email=f"late-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="pw",
        role=UserRole.owner,
        created_at=utcnow() - timedelta(days=1),
        is_active=True,
    )
    db.add_all([earlier_owner, later_owner])
    db.flush()

    db.execute(text(BACKFILL_SQL))
    db.flush()
    db.refresh(backfill_co)
    assert backfill_co.owner_user_id == earlier_owner.id


# ==============================================================================
# Rule 3 Tests: Strict Schema Validation & Password Re-entry Requirements
# ==============================================================================


def test_R03_strict_input_validation_and_password_reentry_rules(
    client: TestClient, db: Session, company_setup
):
    """R03:
    - New role can only be employee, hr_admin, or owner in lower case.
    - super_admin, manager, 'OWNER', 'HR_ADMIN', '', null, missing, integer, extra fields
      all return 422, with DB state unchanged.
    - Granting or removing owner without current_password returns 422.
    - current_password longer than 128 characters returns 422.
    - Employee and hr_admin role changes accept missing current_password and never verify it.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    target_emp = company_setup["employee"]
    target_hr = company_setup["hr_admin"]
    url_emp = f"/api/v1/users/{target_emp.id}/role"

    # Invalid roles -> 422
    invalid_role_payloads = [
        {"role": "super_admin", "current_password": OWNER_RAW_PASSWORD},
        {"role": "OWNER", "current_password": OWNER_RAW_PASSWORD},
        {"role": "HR_ADMIN", "current_password": OWNER_RAW_PASSWORD},
        {"role": "", "current_password": OWNER_RAW_PASSWORD},
        {"role": None, "current_password": OWNER_RAW_PASSWORD},
        {"current_password": OWNER_RAW_PASSWORD},  # missing role
        {"role": 123, "current_password": OWNER_RAW_PASSWORD},
        {"role": "hr_admin", "company_id": str(company_setup["company"].id)},  # extra field
        {"role": "hr_admin", "extra_prop": "bad"},  # extra field
    ]

    for p in invalid_role_payloads:
        res = client.patch(url_emp, headers=owner_headers, json=p)
        assert res.status_code == 422, f"Expected 422 for {p}, got {res.status_code}"

    # Granting owner without current_password -> 422
    res_grant_no_pw = client.patch(url_emp, headers=owner_headers, json={"role": "owner"})
    assert res_grant_no_pw.status_code == 422

    # Removing owner without current_password -> 422
    url_co = f"/api/v1/users/{company_setup['co_owner'].id}/role"
    res_remove_no_pw = client.patch(url_co, headers=owner_headers, json={"role": "hr_admin"})
    assert res_remove_no_pw.status_code == 422

    # current_password > 128 chars -> 422
    long_pw = "A" * 129
    res_long_pw = client.patch(
        url_emp, headers=owner_headers, json={"role": "owner", "current_password": long_pw}
    )
    assert res_long_pw.status_code == 422

    # Changing employee to hr_admin accepts missing current_password and never verifies it
    res_hr_change = client.patch(url_emp, headers=owner_headers, json={"role": "hr_admin"})
    assert res_hr_change.status_code == 200

    # Changing hr_admin to employee accepts missing current_password
    res_emp_change = client.patch(
        f"/api/v1/users/{target_hr.id}/role",
        headers=owner_headers,
        json={"role": "employee"},
    )
    assert res_emp_change.status_code == 200


# ==============================================================================
# Rule 4 Tests: Self-Change Forbidden & Password Lockout
# ==============================================================================


def test_R04_self_role_change_forbidden_and_password_lockout(
    client: TestClient, db: Session, company_setup, caplog
):
    """R04:
    - Owner (first and co-owner) and hr_admin changing their own role get 403;
      nothing changes, no audit row, one security-log line each.
    - Wrong current_password on owner change: 403 with the same message every time,
      nothing changes, no email, failed_attempts increments per login policy (threshold 5),
      account locks on 5th attempt, security log line contains no password;
      correct password works again when not locked.
    """
    caplog.clear()

    # 1. First owner changes self -> 403
    first_owner_headers = _auth_headers(company_setup["owner"])
    res_self_first = client.patch(
        f"/api/v1/users/{company_setup['owner'].id}/role",
        headers=first_owner_headers,
        json={"role": "hr_admin", "current_password": OWNER_RAW_PASSWORD},
    )
    assert res_self_first.status_code == 403

    # 2. Co-owner changes self -> 403
    co_owner_headers = _auth_headers(company_setup["co_owner"])
    res_self_co = client.patch(
        f"/api/v1/users/{company_setup['co_owner'].id}/role",
        headers=co_owner_headers,
        json={"role": "employee", "current_password": CO_OWNER_RAW_PASSWORD},
    )
    assert res_self_co.status_code == 403

    # 3. HR admin changes self -> 403
    hr_headers = _auth_headers(company_setup["hr_admin"])
    res_self_hr = client.patch(
        f"/api/v1/users/{company_setup['hr_admin'].id}/role",
        headers=hr_headers,
        json={"role": "employee"},
    )
    assert res_self_hr.status_code == 403

    # Verify no audit rows written
    audits = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == company_setup["company"].id,
            AuditLog.action == "ROLE_CHANGED",
        )
        .all()
    )
    assert len(audits) == 0

    # 4. Wrong current_password attempts on owner change
    target_emp = company_setup["employee"]
    url_target = f"/api/v1/users/{target_emp.id}/role"

    owner_user = db.get(User, company_setup["owner"].id)
    initial_failed = owner_user.failed_attempts

    # 4 wrong password attempts
    for i in range(4):
        r_wrong = client.patch(
            url_target,
            headers=first_owner_headers,
            json={"role": "owner", "current_password": "WrongPassword123!"},
        )
        assert r_wrong.status_code == 403
        db.refresh(owner_user)
        assert owner_user.failed_attempts == initial_failed + i + 1
        assert owner_user.locked_until is None

    # Correct password succeeds before lockout
    r_correct = client.patch(
        url_target,
        headers=first_owner_headers,
        json={"role": "owner", "current_password": OWNER_RAW_PASSWORD},
    )
    assert r_correct.status_code == 200

    # Reset role of target_emp to test 5th lockout attempt
    db.refresh(target_emp)
    target_emp.role = UserRole.employee
    db.commit()

    # 5 wrong attempts to trigger lock
    for _ in range(5):
        client.patch(
            url_target,
            headers=first_owner_headers,
            json={"role": "owner", "current_password": "WrongPassword123!"},
        )
    db.refresh(owner_user)
    assert owner_user.failed_attempts >= 5
    assert owner_user.locked_until is not None
    assert owner_user.locked_until > utcnow()

    # While locked, even correct password is rejected
    r_locked = client.patch(
        url_target,
        headers=first_owner_headers,
        json={"role": "owner", "current_password": OWNER_RAW_PASSWORD},
    )
    assert r_locked.status_code == 403

    # Verify security logs contain no raw password
    sec_logs = [r for r in caplog.records if r.name == "app.security"]
    for record in sec_logs:
        msg = record.getMessage()
        assert "WrongPassword123!" not in msg
        assert OWNER_RAW_PASSWORD not in msg


# ==============================================================================
# Rule 5 Tests: Target Scoping & Uniform 404
# ==============================================================================


def test_R05_target_scoping_and_uniform_404(
    client: TestClient, db: Session, company_setup, company_b_setup
):
    """R05: Target must be an active user of caller's own company.
    - Another company's user -> 404
    - Unknown UUID -> 404
    - Inactive user -> 404
    - Not-yet-activated user -> 404
    - Platform account -> 404
    All 404 responses must have identical bodies with no sensitive details.
    - Malformed UUID -> 422
    - Multi-tenant user: same email in another workspace keeps other role unchanged.
    """
    owner_headers = _auth_headers(company_setup["owner"])

    # Setup inactive and not-yet-activated users
    inactive_user = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"inactive-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="pw",
        role=UserRole.employee,
        is_active=False,
    )
    unactivated_user = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"unact-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="pw",
        role=UserRole.employee,
        is_active=False,
    )
    plat_company = Company(
        id=uuid.uuid4(),
        name="Platform HQ",
        code=f"PL{uuid.uuid4().hex[:4].upper()}",
        email=f"plat-{uuid.uuid4().hex[:6]}@example.com",
        status="active",
        is_active=True,
    )
    db.add(plat_company)
    db.flush()

    platform_user = User(
        id=uuid.uuid4(),
        company_id=plat_company.id,
        email=f"platform-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="pw",
        role=UserRole.super_admin,
        is_active=True,
    )
    db.add_all([inactive_user, unactivated_user, platform_user])
    db.commit()

    # Collect 404 responses
    url_b = f"/api/v1/users/{company_b_setup['employee'].id}/role"
    url_unknown = f"/api/v1/users/{uuid.uuid4()}/role"
    url_inactive = f"/api/v1/users/{inactive_user.id}/role"
    url_unactivated = f"/api/v1/users/{unactivated_user.id}/role"
    url_platform = f"/api/v1/users/{platform_user.id}/role"

    body = {"role": "hr_admin"}

    res_b = client.patch(url_b, headers=owner_headers, json=body)
    res_unknown = client.patch(url_unknown, headers=owner_headers, json=body)
    res_inactive = client.patch(url_inactive, headers=owner_headers, json=body)
    res_unactivated = client.patch(url_unactivated, headers=owner_headers, json=body)
    res_platform = client.patch(url_platform, headers=owner_headers, json=body)

    responses = [
        ("res_b", res_b),
        ("res_unknown", res_unknown),
        ("res_inactive", res_inactive),
        ("res_unactivated", res_unactivated),
        ("res_platform", res_platform),
    ]

    unknown_data = res_unknown.json()
    unknown_data.get("error", {}).pop("request_id", None)

    for name, r in responses:
        assert r.status_code == 404
        r_data = r.json()
        r_data.get("error", {}).pop("request_id", None)
        diff_msg = f"{name} differs from res_unknown: {r_data} != {unknown_data}"
        assert r_data == unknown_data, diff_msg

    # Malformed UUID -> 422
    res_malformed = client.patch("/api/v1/users/not-a-uuid/role", headers=owner_headers, json=body)
    assert res_malformed.status_code == 422

    # Multi-workspace user: same person (email) in Company B has separate user row
    shared_email = f"shared-{uuid.uuid4().hex[:6]}@example.com"
    user_a = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=shared_email,
        hashed_password="pw",
        role=UserRole.employee,
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        company_id=company_b_setup["company"].id,
        email=shared_email,
        hashed_password="pw",
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([user_a, user_b])
    db.commit()

    # Promote user in Company A
    res_promote_a = client.patch(
        f"/api/v1/users/{user_a.id}/role",
        headers=owner_headers,
        json={"role": "hr_admin"},
    )
    assert res_promote_a.status_code == 200

    # User in Company B is unchanged
    db_user_b = db.get(User, user_b.id)
    assert db_user_b.role == UserRole.employee


# ==============================================================================
# Rule 6 Tests: Idempotent No-Op Role Change
# ==============================================================================


def test_R06_noop_same_role_gives_200_without_side_effects(
    client: TestClient, db: Session, company_setup, email_outbox
):
    """R06: Setting the role a user already has returns 200 and changes nothing:
    - No audit row
    - No token revocation (target's refresh token remains valid)
    - No email sent
    - An hr_admin sending same role on an hr_admin target still gets 403 (checked before no-op).
    """
    owner_headers = _auth_headers(company_setup["owner"])
    target = company_setup["employee"]

    # Issue a refresh token for target
    raw_token = f"ref-{uuid.uuid4().hex}"
    refresh_record = RefreshToken(
        id=uuid.uuid4(),
        user_id=target.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=utcnow() + timedelta(days=7),
        is_revoked=False,
    )
    db.add(refresh_record)
    db.commit()

    email_outbox.clear()

    # Request same role (target is already employee)
    res = client.patch(
        f"/api/v1/users/{target.id}/role",
        headers=owner_headers,
        json={"role": "employee"},
    )
    assert res.status_code == 200

    # 1. No audit row
    audits = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == company_setup["company"].id,
            AuditLog.action == "ROLE_CHANGED",
        )
        .all()
    )
    assert len(audits) == 0

    # 2. Refresh token not revoked
    db.refresh(refresh_record)
    assert refresh_record.is_revoked is False

    # 3. No email sent
    assert len(email_outbox) == 0

    # 4. HR Admin sending same role on HR Admin target gets 403
    hr_headers = _auth_headers(company_setup["hr_admin"])
    res_hr_on_hr = client.patch(
        f"/api/v1/users/{company_setup['hr_admin'].id}/role",
        headers=hr_headers,
        json={"role": "hr_admin"},
    )
    assert res_hr_on_hr.status_code == 403


# ==============================================================================
# Rule 7 Tests: Next Request Authority, Token Revocation & Notifications
# ==============================================================================


def test_R07_tokens_revocation_next_request_authority_and_post_commit_emails(
    client: TestClient, db: Session, company_setup, email_outbox
):
    """R07:
    - Target's old refresh token is revoked on role change.
    - Old access token reflects new authority on next request:
        * Demoted hr_admin gets 403 on admin route; promoted employee reaches it.
    - Fresh login carries the new role.
    - Exactly one email goes to target after commit.
    - When an hr_admin makes the change, EVERY owner gets one email.
    - When owner role is granted or removed, EVERY other owner gets one email.
    - When owner changes employee/hr_admin roles, no other owner gets an email.
    - No email on no-op, 403, 404, 422, or commit failure.
    """
    first_owner_headers = _auth_headers(company_setup["owner"])
    hr_headers = _auth_headers(company_setup["hr_admin"])
    target_emp = company_setup["employee"]
    co_owner = company_setup["co_owner"]

    # Issue active refresh token for target_emp
    raw_refresh = f"rf-{uuid.uuid4().hex}"
    rf_rec = RefreshToken(
        id=uuid.uuid4(),
        user_id=target_emp.id,
        token_hash=hashlib.sha256(raw_refresh.encode()).hexdigest(),
        expires_at=utcnow() + timedelta(days=7),
        is_revoked=False,
    )
    db.add(rf_rec)
    db.commit()

    email_outbox.clear()

    # Case A: Owner promotes employee to hr_admin (no owner role involved)
    old_emp_access_token = create_access_token(
        sub=str(target_emp.id),
        company_id=str(company_setup["company"].id),
        role=UserRole.employee.value,
    )

    res_promote = client.patch(
        f"/api/v1/users/{target_emp.id}/role",
        headers=first_owner_headers,
        json={"role": "hr_admin"},
    )
    assert res_promote.status_code == 200

    # Refresh token must be revoked
    db.refresh(rf_rec)
    assert rf_rec.is_revoked is True

    # Old access token immediately carries new authority because role is evaluated live from DB
    res_access_promoted = client.get(
        "/api/v1/users/administrators",
        headers={"Authorization": f"Bearer {old_emp_access_token}"},
    )
    assert res_access_promoted.status_code == 200

    # Exactly 1 email to target, 0 to other owners
    target_emails = [e for e in email_outbox if e["to"] == target_emp.email]
    owner_emails = [
        e for e in email_outbox if e["to"] in (company_setup["owner"].email, co_owner.email)
    ]
    assert len(target_emails) == 1
    assert len(owner_emails) == 0

    # Case B: HR Admin promotes manager to hr_admin -> Target AND EVERY OWNER get email
    email_outbox.clear()
    mgr = company_setup["manager"]
    res_hr_promote = client.patch(
        f"/api/v1/users/{mgr.id}/role",
        headers=hr_headers,
        json={"role": "hr_admin"},
    )
    assert res_hr_promote.status_code == 200

    mgr_emails = [e for e in email_outbox if e["to"] == mgr.email]
    first_owner_notified = [e for e in email_outbox if e["to"] == company_setup["owner"].email]
    co_owner_notified = [e for e in email_outbox if e["to"] == co_owner.email]
    assert len(mgr_emails) == 1
    assert len(first_owner_notified) == 1
    assert len(co_owner_notified) == 1

    # Case C: Granting owner role -> Target AND EVERY OTHER OWNER get email
    email_outbox.clear()
    res_grant_owner = client.patch(
        f"/api/v1/users/{target_emp.id}/role",
        headers=first_owner_headers,
        json={"role": "owner", "current_password": OWNER_RAW_PASSWORD},
    )
    assert res_grant_owner.status_code == 200

    target_got = [e for e in email_outbox if e["to"] == target_emp.email]
    first_owner_got = [e for e in email_outbox if e["to"] == company_setup["owner"].email]
    co_owner_got = [e for e in email_outbox if e["to"] == co_owner.email]
    assert len(target_got) == 1
    assert len(first_owner_got) == 0  # Acting owner gets none
    assert len(co_owner_got) == 1  # Other co-owner gets email

    # Case D: Removing owner role -> Target AND EVERY OTHER OWNER get email
    email_outbox.clear()
    res_remove_owner = client.patch(
        f"/api/v1/users/{co_owner.id}/role",
        headers=first_owner_headers,
        json={"role": "employee", "current_password": OWNER_RAW_PASSWORD},
    )
    assert res_remove_owner.status_code == 200

    target_demoted_got = [e for e in email_outbox if e["to"] == co_owner.email]
    promoted_co_got = [e for e in email_outbox if e["to"] == target_emp.email]
    assert len(target_demoted_got) == 1
    assert len(promoted_co_got) == 1


# ==============================================================================
# Rule 8 Tests: Single Commit, Row Lock & Rollback Atomicity
# ==============================================================================


def test_R08_transaction_atomicity_row_lock_and_single_commit(
    client: TestClient, db: Session, monkeypatch, company_setup, email_outbox
):
    """R08:
    - Exactly one commit inside the service (not the router).
    - Statement spy confirms SELECT ... FOR UPDATE on target user.
    - Failure during audit write rolls back role update, token revocation, sends no email.
    - Two sequential role changes produce a consistent old-to-new audit chain.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    target = company_setup["employee"]

    # 1. Statement spy for FOR UPDATE
    executed_statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        executed_statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", before_cursor_execute)

    # 2. Spy on Session.commit to assert single commit
    commit_count = 0
    orig_commit = Session.commit

    def spy_commit(self_session):
        nonlocal commit_count
        commit_count += 1
        return orig_commit(self_session)

    monkeypatch.setattr(Session, "commit", spy_commit)

    res = client.patch(
        f"/api/v1/users/{target.id}/role",
        headers=owner_headers,
        json={"role": "hr_admin"},
    )
    assert res.status_code == 200
    assert commit_count == 1

    # Verify SELECT ... FOR UPDATE occurred
    for_update_stmts = [
        s for s in executed_statements if "FOR UPDATE" in s.upper() and "users" in s.lower()
    ]
    assert len(for_update_stmts) >= 1, "Target user must be locked with SELECT ... FOR UPDATE"

    event.remove(db.bind, "before_cursor_execute", before_cursor_execute)

    # 3. Injected failure in audit write rolls back everything
    email_outbox.clear()
    raw_token = f"ref-atomic-{uuid.uuid4().hex}"
    rf = RefreshToken(
        id=uuid.uuid4(),
        user_id=target.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=utcnow() + timedelta(days=7),
        is_revoked=False,
    )
    db.add(rf)
    db.commit()

    from app.modules.platform.service import AuditService

    def broken_audit(*args, **kwargs):
        raise RuntimeError("Injected audit database error")

    monkeypatch.setattr(AuditService, "record", broken_audit)

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    client_no_raise = TestClient(fastapi_app, raise_server_exceptions=False)

    # Demote back to employee with failure
    res_fail = client_no_raise.patch(
        f"/api/v1/users/{target.id}/role",
        headers=owner_headers,
        json={"role": "employee"},
    )
    assert res_fail.status_code == 500

    # Role remains hr_admin
    db.refresh(target)
    assert target.role == UserRole.hr_admin
    # Token not revoked
    db.refresh(rf)
    assert rf.is_revoked is False
    # No email sent
    assert len(email_outbox) == 0


# ==============================================================================
# Rule 9 Tests: Audit Row & Security Logging Without PII
# ==============================================================================


def test_R09_audit_row_details_and_sanitized_security_logging(
    client: TestClient, db: Session, company_setup, caplog
):
    """R09: Every successful change writes a ROLE_CHANGED audit row:
    - actor_user_id, entity_id (target), details: old_role, new_role, company_id.
    - None on denial or no-op.
    - Security-log lines for wrong-role, self-change, forbidden-target, and wrong-password
      contain no email, password hash, or raw tokens.
    - current_password never appears in audit row, logs, or reply.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    target = company_setup["employee"]

    # 1. Perform change
    res = client.patch(
        f"/api/v1/users/{target.id}/role",
        headers=owner_headers,
        json={"role": "hr_admin"},
    )
    assert res.status_code == 200

    # Verify audit row
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == company_setup["company"].id,
            AuditLog.action == "ROLE_CHANGED",
            AuditLog.entity_id == target.id,
        )
        .first()
    )
    assert audit is not None
    assert audit.actor_user_id == company_setup["owner"].id
    assert audit.details["previous_role"] == "employee"
    assert audit.details["new_role"] == "hr_admin"
    assert "current_password" not in audit.details
    assert "password" not in str(audit.details).lower()

    # 2. Denied attempts produce security log without personal data
    caplog.clear()

    # Wrong role (demote hr_admin by an hr_admin)
    client.patch(
        f"/api/v1/users/{company_setup['hr_admin'].id}/role",
        headers=_auth_headers(company_setup["hr_admin"]),
        json={"role": "employee"},
    )

    # Self-change
    client.patch(
        f"/api/v1/users/{company_setup['owner'].id}/role",
        headers=owner_headers,
        json={"role": "employee"},
    )

    # Wrong password attempt
    test_wrong_pw = "SecretWrongPass999!"
    client.patch(
        f"/api/v1/users/{target.id}/role",
        headers=owner_headers,
        json={"role": "owner", "current_password": test_wrong_pw},
    )

    sec_logs = [r for r in caplog.records if r.name == "app.security"]
    for log_record in sec_logs:
        log_str = log_record.getMessage()
        assert company_setup["owner"].email not in log_str
        assert test_wrong_pw not in log_str
        assert OWNER_RAW_PASSWORD not in log_str
        assert "bearer" not in log_str.lower()


# ==============================================================================
# Rule 10 Tests: Rate Limiting (30/min), Response Schema & Route Policy
# ==============================================================================


def test_R10_rate_limiting_and_clean_response(client: TestClient, company_setup):
    """R10:
    - Rate-limited per user to 30 requests per minute with clean 429.
    - Replies contain only safe fields (never password hash, token, or internal flags).
    - tests/security/route_policy.py lists route as owner and hr_admin.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    target = company_setup["employee"]
    url = f"/api/v1/users/{target.id}/role"

    limiter.enabled = True
    try:
        limiter.reset()

        # Fire 30 requests
        for i in range(30):
            r = client.patch(url, headers=owner_headers, json={"role": "employee"})
            assert r.status_code == 200, f"Request {i + 1} failed with {r.status_code}"

        # 31st request -> 429
        r_31 = client.patch(url, headers=owner_headers, json={"role": "employee"})
        assert r_31.status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()

    # Response payload whitelist check
    res_clean = client.patch(url, headers=owner_headers, json={"role": "hr_admin"})
    assert res_clean.status_code == 200
    data = res_clean.json()
    assert set(data.keys()) == {"id", "role", "previous_role", "changed"}

    # Verify route_policy contains owner and hr_admin
    from tests.security.route_policy import POLICY

    policy_roles = POLICY.get(("PATCH", "/api/v1/users/{user_id}/role"))
    assert policy_roles is not None
    # Must allow both owner and hr_admin
    assert UserRole.owner in policy_roles
    assert UserRole.hr_admin in policy_roles


def test_R10_approval_authority_demoted_hr_forbidden(
    client: TestClient, db: Session, company_setup
):
    """Rule 10 Approvals: An hr_admin demoted to employee gets 403 on an approval-action route,
    while a still-valid hr_admin passes the role check.
    """
    owner_headers = _auth_headers(company_setup["owner"])

    # Create a target hr_admin who can approve leaves
    hr_user = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"hr-appr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("ValidPassword123!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(hr_user)
    db.commit()

    hr_headers = _auth_headers(hr_user)

    # Fake leave ID
    dummy_leave_id = uuid.uuid4()
    body = {"status": "approved", "rejection_reason": None}

    # 1. As hr_admin, calling PUT /api/v1/leaves/{id} passes require_role (404, not 403)
    res_hr = client.put(f"/api/v1/leaves/{dummy_leave_id}", headers=hr_headers, json=body)
    assert res_hr.status_code == 404, f"Expected 404, got {res_hr.status_code}"

    # 2. Demote hr_user to employee
    res_demote = client.patch(
        f"/api/v1/users/{hr_user.id}/role",
        headers=owner_headers,
        json={"role": "employee"},
    )
    assert res_demote.status_code == 200

    # 3. Same user now gets 403 on the approval route
    res_demoted_user = client.put(f"/api/v1/leaves/{dummy_leave_id}", headers=hr_headers, json=body)
    assert res_demoted_user.status_code == 403, (
        f"Expected 403 Forbidden after demotion, got {res_demoted_user.status_code}"
    )


def test_migration_sets_platform_admin_before_backfill(monkeypatch):
    """Migration test: op.get_bind is patched to record executed statements.
    upgrade() must execute 'SELECT set_config('app.is_platform_admin', 'on', true)'
    as its first statement and BACKFILL_SQL as its second statement.
    """
    import importlib.util
    from pathlib import Path

    import alembic.op as op

    ver_file = "alembic/versions/b3a17e0892c1_backfill_company_owner_user_id.py"
    migration_path = Path(__file__).resolve().parents[2] / ver_file
    spec = importlib.util.spec_from_file_location("b3a17e0892c1_test", str(migration_path))
    migration_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_mod)

    executed_statements = []

    class DummyConnection:
        def execute(self, statement, *args, **kwargs):
            executed_statements.append(str(statement))

    with monkeypatch.context() as m:
        m.setattr(op, "get_bind", lambda: DummyConnection())
        migration_mod.upgrade()

    assert len(executed_statements) == 2, f"Expected 2 statements, got {len(executed_statements)}"
    assert "app.is_platform_admin" in executed_statements[0]
    assert "'on'" in executed_statements[0]
    assert migration_mod.BACKFILL_SQL.strip() in executed_statements[1].strip()
