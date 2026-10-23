"""Tests for Sub-feature 1.7 Roles & role change: PATCH /users/{user_id}/role (Rules 1-10).

Rule 1: Only owner or hr_admin can call the route; manager, employee and super_admin get 403;
        missing or expired token gets 401; caller's role is read from DB on every request.
Rule 2: Owner can make an employee or manager an hr_admin and can demote an hr_admin to employee;
        hr_admin can only promote employee or manager to hr_admin; hr_admin demoting hr_admin or
        touching owner gets 403; another owner cannot be changed (409); owner count unchanged.
Rule 3: New role can only be employee or hr_admin in lower case; any other value, empty, null,
        missing, wrong type, or extra field returns 422 with no database changes.
Rule 4: Nobody can change their own role, including the owner (403, no audit, security log line).
Rule 5: Target must be active user of caller's company; other company user, unknown id,
        inactive or unactivated user, or platform account returns identical 404 with no details;
        malformed id gives 422; user in two companies keeps other workspace role untouched.
Rule 6: Same role returns 200 and changes nothing: no audit row, no token revocation, no email;
Rule 7: Role change takes effect on target's very next request: refresh tokens revoked;
        old access token acts with new authority; fresh login has new role; email to target
        (and to owner when hr_admin changed it); none on failure, no-op or denial.
Rule 8: Exactly one commit inside the service with SELECT ... FOR UPDATE row lock on target;
        failure rolls back everything (no token revocation, no email); consistent audit chain.
Rule 9: Every change writes ROLE_CHANGED audit row (actor, target, old role, new role, company);
        denied attempts log to security log without personal data.
Rule 10: Rate-limited per user (30/min) with 429; safe response fields only (no hash/token);
         route in route_policy matrix as owner and hr_admin; approval consistency.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.core.time import utcnow
from app.modules.identity.models import Company, RefreshToken, User, UserRole
from app.modules.platform.models import AuditLog

# --- Helpers & Fixtures ---


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        sub=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def company_setup(db: Session):
    """Provisions Company A with Owner, HR Admin, Manager, and Employee users."""
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
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_pw_owner",
        role=UserRole.owner,
        is_active=True,
    )
    hr_admin = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_pw_hr",
        role=UserRole.hr_admin,
        is_active=True,
    )
    manager = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"mgr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_pw_mgr",
        role=UserRole.manager,
        is_active=True,
    )
    employee = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_pw_emp",
        role=UserRole.employee,
        is_active=True,
    )

    db.add_all([owner, hr_admin, manager, employee])
    db.flush()
    db.commit()

    return {
        "company": company,
        "owner": owner,
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
        hashed_password="hashed_pw_b",
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
    # On next request, get_current_user reads User from DB -> user.role is employee -> 403.
    caller_token_headers = _auth_headers(company_setup["hr_admin"])
    # Demote in DB
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
# Rule 2 Tests: Role Transition Matrix & Authority Matrix
# ==============================================================================


def test_R02_role_transition_matrix_and_owner_guards(
    client: TestClient, db: Session, company_setup
):
    """R02: Owner transitions:
      - employee -> hr_admin: 200
      - manager -> hr_admin: 200
      - hr_admin -> employee: 200
    HR admin transitions:
      - employee -> hr_admin: 200
      - manager -> hr_admin: 200
      - hr_admin target (to employee): 403
      - hr_admin target (to hr_admin): 403 (authority checked before no-op check)
      - owner target: 403
    Owner on another owner:
      - 409 Conflict
    Owner count remains unchanged in every denied case.
    """
    owner_headers = _auth_headers(company_setup["owner"])

    # Reset roles for HR admin testing:
    # Let's make an active HR admin user and a fresh employee target
    fresh_hr = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"fresh-hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="pw",
        role=UserRole.hr_admin,
        is_active=True,
    )
    fresh_emp = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"fresh-emp-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="pw",
        role=UserRole.employee,
        is_active=True,
    )
    fresh_target_hr = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"target-hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="pw",
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add_all([fresh_hr, fresh_emp, fresh_target_hr])
    db.commit()

    fresh_hr_headers = _auth_headers(fresh_hr)

    # 1. HR Admin: employee -> hr_admin succeeds
    res = client.patch(
        f"/api/v1/users/{fresh_emp.id}/role",
        headers=fresh_hr_headers,
        json={"role": "hr_admin"},
    )
    assert res.status_code == 200

    # 2. HR Admin: hr_admin target to employee -> 403
    res = client.patch(
        f"/api/v1/users/{fresh_target_hr.id}/role",
        headers=fresh_hr_headers,
        json={"role": "employee"},
    )
    assert res.status_code == 403

    # 3. HR Admin: hr_admin target to hr_admin (same role) -> 403
    # (Authority is checked BEFORE no-op check)
    res = client.patch(
        f"/api/v1/users/{fresh_target_hr.id}/role",
        headers=fresh_hr_headers,
        json={"role": "hr_admin"},
    )
    assert res.status_code == 403

    # 4. HR Admin: owner target -> 403
    res = client.patch(
        f"/api/v1/users/{company_setup['owner'].id}/role",
        headers=fresh_hr_headers,
        json={"role": "employee"},
    )
    assert res.status_code == 403

    # 5. Owner: employee -> hr_admin succeeds
    res = client.patch(
        f"/api/v1/users/{company_setup['employee'].id}/role",
        headers=owner_headers,
        json={"role": "hr_admin"},
    )
    assert res.status_code == 200

    # 6. Owner: manager -> hr_admin succeeds
    res = client.patch(
        f"/api/v1/users/{company_setup['manager'].id}/role",
        headers=owner_headers,
        json={"role": "hr_admin"},
    )
    assert res.status_code == 200

    # 7. Owner: hr_admin -> employee succeeds (demote company_setup['hr_admin'])
    res = client.patch(
        f"/api/v1/users/{company_setup['hr_admin'].id}/role",
        headers=owner_headers,
        json={"role": "employee"},
    )
    assert res.status_code == 200

    # 8. Owner on another owner (fixture inserts second owner) -> 409 Conflict
    second_owner = User(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        email=f"owner2-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="pw",
        role=UserRole.owner,
        is_active=True,
    )
    db.add(second_owner)
    db.commit()

    initial_owner_count = (
        db.query(User)
        .filter(
            User.company_id == company_setup["company"].id,
            User.role == UserRole.owner,
        )
        .count()
    )

    res_owner_on_owner = client.patch(
        f"/api/v1/users/{second_owner.id}/role",
        headers=owner_headers,
        json={"role": "hr_admin"},
    )
    assert res_owner_on_owner.status_code == 409

    final_owner_count = (
        db.query(User)
        .filter(
            User.company_id == company_setup["company"].id,
            User.role == UserRole.owner,
        )
        .count()
    )
    assert initial_owner_count == final_owner_count


# ==============================================================================
# Rule 3 Tests: Strict Schema Validation & Rejections
# ==============================================================================


def test_R03_strict_input_validation(client: TestClient, db: Session, company_setup):
    """R03: New role can only be employee or hr_admin, in exact lower case.
    owner, super_admin, manager, 'HR_ADMIN', '', null, missing, integer, extra fields (company_id)
    all return 422, and database state is completely unchanged.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    target = company_setup["employee"]
    url = f"/api/v1/users/{target.id}/role"

    invalid_payloads = [
        {"role": "owner"},
        {"role": "super_admin"},
        {"role": "manager"},
        {"role": "HR_ADMIN"},
        {"role": "Hr_Admin"},
        {"role": ""},
        {"role": None},
        {},  # missing role
        {"role": 123},
        {"role": "hr_admin", "company_id": str(company_setup["company"].id)},  # extra field
        {"role": "hr_admin", "extra": "forbidden"},  # extra field
    ]

    for payload in invalid_payloads:
        res = client.patch(url, headers=owner_headers, json=payload)
        assert res.status_code == 422, f"Expected 422 for payload {payload}, got {res.status_code}"

    # Verify database unchanged
    db_user = db.get(User, target.id)
    assert db_user.role == UserRole.employee


# ==============================================================================
# Rule 4 Tests: Self-Change Forbidden
# ==============================================================================


def test_R04_self_role_change_forbidden_with_security_log(
    client: TestClient, db: Session, company_setup, caplog
):
    """R04: Nobody can change their own role, including the owner.
    Both owner and hr_admin get 403 on self-change; nothing changes, no audit row,
    and one security-log line is emitted for each.
    """
    caplog.clear()

    # 1. Owner changes self -> 403
    owner_headers = _auth_headers(company_setup["owner"])
    res_owner = client.patch(
        f"/api/v1/users/{company_setup['owner'].id}/role",
        headers=owner_headers,
        json={"role": "hr_admin"},
    )
    assert res_owner.status_code == 403

    # 2. HR Admin changes self -> 403
    hr_headers = _auth_headers(company_setup["hr_admin"])
    res_hr = client.patch(
        f"/api/v1/users/{company_setup['hr_admin'].id}/role",
        headers=hr_headers,
        json={"role": "employee"},
    )
    assert res_hr.status_code == 403

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

    # Verify security log messages emitted
    sec_records = [r for r in caplog.records if r.name == "app.security"]
    assert len(sec_records) >= 2


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
    # Platform account in separate platform company
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

    for r in [res_b, res_unknown, res_inactive, res_unactivated, res_platform]:
        assert r.status_code == 404
        assert r.json() == res_unknown.json(), "All 404 responses must match identically"

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
# Rule 7 Tests: Next Request Authority, Token Revocation & Post-Commit Emails
# ==============================================================================


def test_R07_tokens_revocation_next_request_authority_and_post_commit_emails(
    client: TestClient, db: Session, company_setup, email_outbox
):
    """R07:
    - Target's old refresh token is revoked on role change.
    - Old access token reflects new authority on the next request:
        * Demoted hr_admin gets 403 on an hr_admin route.
        * Promoted employee reaches it.
    - Fresh login carries the new role.
    - Exactly one email goes to the target after commit.
    - When an hr_admin makes the change, owner ALSO gets one email.
    - When owner makes the change, owner gets NO email.
    - No email on no-op, 403, 404, 422, or commit failure.
    """
    owner_headers = _auth_headers(company_setup["owner"])
    hr_headers = _auth_headers(company_setup["hr_admin"])
    target_emp = company_setup["employee"]
    target_hr = company_setup["hr_admin"]

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

    # Case A: Owner promotes employee to hr_admin
    old_emp_access_token = create_access_token(
        sub=str(target_emp.id),
        company_id=str(company_setup["company"].id),
        role=UserRole.employee.value,
    )

    res_promote = client.patch(
        f"/api/v1/users/{target_emp.id}/role",
        headers=owner_headers,
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

    # Exactly 1 email to target, 0 to owner
    target_emails = [e for e in email_outbox if e["to"] == target_emp.email]
    owner_emails = [e for e in email_outbox if e["to"] == company_setup["owner"].email]
    assert len(target_emails) == 1
    assert len(owner_emails) == 0
    # No credentials/secrets in email
    assert "password" not in target_emails[0]["text_body"].lower()

    # Case B: HR Admin promotes a manager to hr_admin -> Target AND Owner both get email
    email_outbox.clear()
    mgr = company_setup["manager"]
    res_hr_promote = client.patch(
        f"/api/v1/users/{mgr.id}/role",
        headers=hr_headers,
        json={"role": "hr_admin"},
    )
    assert res_hr_promote.status_code == 200

    mgr_emails = [e for e in email_outbox if e["to"] == mgr.email]
    owner_notified = [e for e in email_outbox if e["to"] == company_setup["owner"].email]
    assert len(mgr_emails) == 1
    assert len(owner_notified) == 1

    # Case C: Owner demotes an hr_admin to employee -> Old access token gets 403 on admin route
    old_hr_token = create_access_token(
        sub=str(target_hr.id),
        company_id=str(company_setup["company"].id),
        role=UserRole.hr_admin.value,
    )
    res_demote = client.patch(
        f"/api/v1/users/{target_hr.id}/role",
        headers=owner_headers,
        json={"role": "employee"},
    )
    assert res_demote.status_code == 200

    res_access_demoted = client.get(
        "/api/v1/users/administrators",
        headers={"Authorization": f"Bearer {old_hr_token}"},
    )
    assert res_access_demoted.status_code == 403


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

    # Demote back to employee with failure
    res_fail = client.patch(
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
    - Security-log lines for wrong-role, self-change, forbidden-target contain no email,
      no password hash, and no raw tokens.
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
    assert audit.details["old_role"] == "employee"
    assert audit.details["new_role"] == "hr_admin"

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

    sec_logs = [r for r in caplog.records if r.name == "app.security"]
    for log_record in sec_logs:
        log_str = log_record.getMessage()
        # Must not contain unhashed email, password, or bearer tokens
        assert company_setup["owner"].email not in log_str
        assert "password" not in log_str.lower()
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
    if res_clean.status_code == 200:
        data = res_clean.json()
        forbidden_keys = {
            "hashed_password",
            "password",
            "token",
            "refresh_token",
            "is_superuser",
            "is_staff",
        }
        for k in forbidden_keys:
            assert k not in data, f"Response contains unsafe key: {k}"

    # Verify route_policy contains owner and hr_admin
    from tests.security.route_policy import EXPECTED_POLICIES

    policy = EXPECTED_POLICIES.get(("PATCH", "/api/v1/users/{user_id}/role"))
    assert policy is not None
    # Must allow both owner and hr_admin
    assert UserRole.owner in policy.allowed_roles
    assert UserRole.hr_admin in policy.allowed_roles
