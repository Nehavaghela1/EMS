"""Tests for Rules 1.5: Workspaces.
(GET /auth/workspaces, POST /auth/switch-workspace, POST /companies/workspaces).
Strictly tests first; no product code modified in this step.
"""

import hashlib
import logging
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, hash_token
from app.core.time import utcnow
from app.modules.hr.models import Department, Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import (
    Company,
    CompanyLocation,
    CompanySettings,
    CompanyStatus,
    RefreshToken,
    User,
    UserRole,
)
from app.modules.platform.models import AuditLog


def _make_headers(user_id: uuid.UUID, company_id: uuid.UUID, role: UserRole) -> dict[str, str]:
    token = create_access_token(sub=str(user_id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


def _create_company(
    db,
    name: str = "Test Corp",
    status: CompanyStatus = CompanyStatus.active,
    is_active: bool = True,
    email: str | None = None,
) -> Company:
    comp_email = email or f"comp-{uuid.uuid4().hex[:8]}@example.com"
    code = f"CMP{uuid.uuid4().hex[:4].upper()}"
    company = Company(
        name=name,
        code=code,
        email=comp_email,
        country="IN",
        currency="INR",
        status=status,
        is_active=is_active,
        admin_password_hash=hash_password("ValidPassword123!"),
    )
    db.add(company)
    db.flush()
    from app.db.rls import bind_tenant_to_session

    bind_tenant_to_session(db, company_id=company.id, is_platform_admin=True)
    db.add(CompanySettings(company_id=company.id))
    db.commit()
    return company


def _create_user_in_company(
    db,
    company_id: uuid.UUID,
    email: str,
    *,
    role: UserRole = UserRole.employee,
    is_active: bool = True,
    invitation_status: InvitationStatus = InvitationStatus.activated,
) -> tuple[User, Employee]:
    user = User(
        company_id=company_id,
        email=email,
        hashed_password=hash_password("ValidPassword123!"),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.flush()

    # Create associated employee under platform admin or tenant context
    from app.db.rls import bind_tenant_to_session

    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=True)
    emp_code = f"EMP-{uuid.uuid4().hex[:6].upper()}"
    employee = Employee(
        company_id=company_id,
        user_id=user.id if invitation_status == InvitationStatus.activated else None,
        employee_code=emp_code,
        first_name="Test",
        last_name="User",
        email=email,
        hire_date=date.today(),
        is_active=is_active,
        invitation_status=invitation_status,
        employment_type=EmploymentType.full_time,
    )
    db.add(employee)
    db.commit()
    return user, employee


# ── W01: List shows only usable memberships (case-insensitive email) ──────────
def test_W01_list_shows_only_usable_memberships(client, db):
    email = f"shared-{uuid.uuid4().hex[:8]}@example.com"

    # Usable workspace 1
    c1 = _create_company(db, name="Company One", status=CompanyStatus.active, is_active=True)
    u1, _ = _create_user_in_company(db, c1.id, email.upper(), is_active=True)

    # Usable workspace 2
    c2 = _create_company(db, name="Company Two", status=CompanyStatus.active, is_active=True)
    u2, _ = _create_user_in_company(db, c2.id, email.lower(), is_active=True)

    # Inactive company -> MUST NOT be listed
    c_inactive = _create_company(db, name="Inactive Co", status=CompanyStatus.active, is_active=False)
    _create_user_in_company(db, c_inactive.id, email, is_active=True)

    # Pending company -> MUST NOT be listed
    c_pending = _create_company(db, name="Pending Co", status=CompanyStatus.pending, is_active=True)
    _create_user_in_company(db, c_pending.id, email, is_active=True)

    # Rejected company -> MUST NOT be listed
    c_rejected = _create_company(db, name="Rejected Co", status=CompanyStatus.rejected, is_active=True)
    _create_user_in_company(db, c_rejected.id, email, is_active=True)

    # Deactivated user in active company -> MUST NOT be listed
    c_deact_user = _create_company(db, name="Deact User Co", status=CompanyStatus.active, is_active=True)
    _create_user_in_company(db, c_deact_user.id, email, is_active=False)

    # Not-activated employee in active company -> MUST NOT be listed
    c_unact = _create_company(db, name="Unactivated Co", status=CompanyStatus.active, is_active=True)
    _create_user_in_company(
        db, c_unact.id, email, is_active=True, invitation_status=InvitationStatus.sent
    )

    # Call /auth/workspaces as u1
    headers = _make_headers(u1.id, c1.id, u1.role)
    resp = client.get("/api/v1/auth/workspaces", headers=headers)
    assert resp.status_code == 200
    items = resp.json()

    returned_ids = {item["id"] for item in items}
    assert str(c1.id) in returned_ids
    assert str(c2.id) in returned_ids
    assert str(c_inactive.id) not in returned_ids
    assert str(c_pending.id) not in returned_ids
    assert str(c_rejected.id) not in returned_ids
    assert str(c_deact_user.id) not in returned_ids
    assert str(c_unact.id) not in returned_ids
    assert len(items) == 2


# ── W02: Switch 200; token claims match target; /me agrees ───────────────────
def test_W02_switch_success_and_me_agrees(client, db):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    c1 = _create_company(db, name="Company Alpha")
    c2 = _create_company(db, name="Company Beta")

    u1, _ = _create_user_in_company(db, c1.id, email, role=UserRole.employee)
    u2, _ = _create_user_in_company(db, c2.id, email, role=UserRole.hr_admin)

    headers = _make_headers(u1.id, c1.id, u1.role)
    resp = client.post(
        "/api/v1/auth/switch-workspace",
        headers=headers,
        json={"company_id": str(c2.id)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # Call /me with new token
    new_token = data["access_token"]
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert me_resp.status_code == 200
    me = me_resp.json()
    assert me["company_id"] == str(c2.id)
    assert me["id"] == str(u2.id)
    assert me["role"] == UserRole.hr_admin.value


# ── W03: Role comes from target account (HR in A, employee in B) ─────────────
def test_W03_role_comes_from_target_account(client, db):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    cA = _create_company(db, name="Company A")
    cB = _create_company(db, name="Company B")

    uA, _ = _create_user_in_company(db, cA.id, email, role=UserRole.hr_admin)
    uB, _ = _create_user_in_company(db, cB.id, email, role=UserRole.employee)

    # Start in Company A (as HR Admin)
    headersA = _make_headers(uA.id, cA.id, uA.role)

    # Switch to Company B (where role is Employee)
    resp = client.post(
        "/api/v1/auth/switch-workspace",
        headers=headersA,
        json={"company_id": str(cB.id)},
    )
    assert resp.status_code == 200
    new_token = resp.json()["access_token"]
    headersB = {"Authorization": f"Bearer {new_token}"}

    # Calling an HR-only route in Company B (e.g. POST /departments) must be rejected with 403
    dept_resp = client.post("/api/v1/departments", headers=headersB, json={"name": "New Dept"})
    assert dept_resp.status_code == 403


# ── W04: Not a member / random UUID / another tenant: identical 404 ──────────
def test_W04_unknown_or_non_member_company_identical_404(client, db, company_a, company_b):
    userA, _ = _create_user_in_company(db, company_a.company_id, f"u-{uuid.uuid4().hex[:6]}@example.com")
    headersA = _make_headers(userA.id, company_a.company_id, userA.role)

    # Random UUID
    random_id = str(uuid.uuid4())
    resp_rand = client.post(
        "/api/v1/auth/switch-workspace", headers=headersA, json={"company_id": random_id}
    )

    # Another tenant where user is NOT a member
    resp_b = client.post(
        "/api/v1/auth/switch-workspace",
        headers=headersA,
        json={"company_id": str(company_b.company_id)},
    )

    assert resp_rand.status_code == 404
    assert resp_b.status_code == 404

    # Body must match exactly ignoring request_id
    body_rand = resp_rand.json()["error"]
    body_b = resp_b.json()["error"]
    assert body_rand["code"] == "not_found"
    assert body_b["code"] == "not_found"
    assert body_rand["message"] == body_b["message"]


# ── W05: Inactive/pending/rejected/deactivated/unactivated: same 404 as W04 ────
def test_W05_ineligible_targets_identical_404(client, db):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    c_active = _create_company(db, name="Active Co")
    u_active, _ = _create_user_in_company(db, c_active.id, email)
    headers = _make_headers(u_active.id, c_active.id, u_active.role)

    # 1. Inactive company
    c_inactive = _create_company(db, status=CompanyStatus.active, is_active=False)
    _create_user_in_company(db, c_inactive.id, email)

    # 2. Pending company
    c_pending = _create_company(db, status=CompanyStatus.pending, is_active=True)
    _create_user_in_company(db, c_pending.id, email)

    # 3. Rejected company
    c_rejected = _create_company(db, status=CompanyStatus.rejected, is_active=True)
    _create_user_in_company(db, c_rejected.id, email)

    # 4. Deactivated user
    c_deact_user = _create_company(db)
    _create_user_in_company(db, c_deact_user.id, email, is_active=False)

    # 5. Not-activated user
    c_unact = _create_company(db)
    _create_user_in_company(
        db, c_unact.id, email, is_active=True, invitation_status=InvitationStatus.sent
    )

    targets = [
        ("inactive_company", c_inactive.id),
        ("pending_company", c_pending.id),
        ("rejected_company", c_rejected.id),
        ("deactivated_user", c_deact_user.id),
        ("not_activated_user", c_unact.id),
    ]

    for label, target_id in targets:
        resp = client.post(
            "/api/v1/auth/switch-workspace",
            headers=headers,
            json={"company_id": str(target_id)},
        )
        assert resp.status_code == 404, f"{label} expected 404, got {resp.status_code}"
        assert resp.json()["error"]["code"] == "not_found", f"{label} expected code not_found"


# ── W06: Malformed or missing company_id gives 422; extra fields ignored ──────
def test_W06_validation_error_and_extra_fields(client, db, company_a):
    user, _ = _create_user_in_company(db, company_a.company_id, f"u-{uuid.uuid4().hex[:6]}@example.com")
    headers = _make_headers(user.id, company_a.company_id, user.role)

    # Missing company_id
    r1 = client.post("/api/v1/auth/switch-workspace", headers=headers, json={})
    assert r1.status_code == 422

    # Non-UUID company_id
    r2 = client.post(
        "/api/v1/auth/switch-workspace", headers=headers, json={"company_id": "not-a-uuid"}
    )
    assert r2.status_code == 422

    # Extra fields ignored
    r3 = client.post(
        "/api/v1/auth/switch-workspace",
        headers=headers,
        json={"company_id": str(company_a.company_id), "role": "super_admin", "user_id": str(uuid.uuid4())},
    )
    assert r3.status_code == 200


# ── W07: No token / expired token / deactivated caller gives 401 ──────────────
def test_W07_unauthenticated_or_expired_or_deactivated_caller_gives_401(client, db, company_a):
    user, _ = _create_user_in_company(db, company_a.company_id, f"u-{uuid.uuid4().hex[:6]}@example.com")

    # No token
    r_no_token = client.post(
        "/api/v1/auth/switch-workspace", json={"company_id": str(company_a.company_id)}
    )
    assert r_no_token.status_code == 401

    # Expired token
    from app.core.config import settings

    with pytest.MonkeyPatch.context() as m:
        m.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -5)
        expired_token = create_access_token(
            sub=str(user.id), company_id=str(company_a.company_id), role=user.role.value
        )
    r_expired = client.post(
        "/api/v1/auth/switch-workspace",
        headers={"Authorization": f"Bearer {expired_token}"},
        json={"company_id": str(company_a.company_id)},
    )
    assert r_expired.status_code == 401

    # Deactivated caller
    user.is_active = False
    db.commit()
    active_token = create_access_token(
        sub=str(user.id), company_id=str(company_a.company_id), role=user.role.value
    )
    r_deact = client.post(
        "/api/v1/auth/switch-workspace",
        headers={"Authorization": f"Bearer {active_token}"},
        json={"company_id": str(company_a.company_id)},
    )
    assert r_deact.status_code == 401


# ── W08: Rate limits: switch 20/minute per user, create 5/hour per user ────────
def test_W08_rate_limits_on_switch_and_create(client, db, company_a):
    user, _ = _create_user_in_company(
        db, company_a.company_id, f"u-{uuid.uuid4().hex[:6]}@example.com", role=UserRole.hr_admin
    )
    headers = _make_headers(user.id, company_a.company_id, user.role)

    limiter.enabled = True
    try:
        limiter.reset()

        # Switch rate limit: 20/minute per user -> 21st must be 429
        for i in range(20):
            res = client.post(
                "/api/v1/auth/switch-workspace",
                headers=headers,
                json={"company_id": str(company_a.company_id)},
            )
            assert res.status_code == 200, f"switch #{i+1} failed with {res.status_code}"

        res_21 = client.post(
            "/api/v1/auth/switch-workspace",
            headers=headers,
            json={"company_id": str(company_a.company_id)},
        )
        assert res_21.status_code == 429

        # Create workspace rate limit: 5/hour per user -> 6th must be 429
        limiter.reset()
        for j in range(5):
            res_c = client.post(
                "/api/v1/companies/workspaces",
                headers=headers,
                json={"company_name": f"Rate Co {j}", "company_email": f"rate-{j}-{uuid.uuid4().hex[:6]}@example.com"},
            )
            assert res_c.status_code == 201, f"create #{j+1} failed with {res_c.status_code}"

        res_c_6 = client.post(
            "/api/v1/companies/workspaces",
            headers=headers,
            json={"company_name": "Rate Co 6", "company_email": f"rate-6-{uuid.uuid4().hex[:6]}@example.com"},
        )
        assert res_c_6.status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()


# ── W09: Refresh cookie attributes, refresh works for B, old works for A ──────
def test_W09_refresh_cookie_attributes_and_independence(client, db):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    cA = _create_company(db, name="Company Alpha")
    cB = _create_company(db, name="Company Beta")

    uA, _ = _create_user_in_company(db, cA.id, email)
    uB, _ = _create_user_in_company(db, cB.id, email)

    # Login to A to get A's tokens and refresh cookie
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "ValidPassword123!", "company_code": cA.code},
    )
    assert login_resp.status_code == 200
    tokenA = login_resp.json()["access_token"]
    cookie_A = login_resp.cookies.get("refresh_token")
    assert cookie_A is not None

    # Switch to B
    switch_resp = client.post(
        "/api/v1/auth/switch-workspace",
        headers={"Authorization": f"Bearer {tokenA}"},
        json={"company_id": str(cB.id)},
    )
    assert switch_resp.status_code == 200
    cookie_B = switch_resp.cookies.get("refresh_token")
    assert cookie_B is not None
    assert cookie_B != cookie_A

    # Assert cookie security attributes on set-cookie header
    set_cookie = switch_resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie or "httponly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie or "path=/api/v1/auth" in set_cookie
    assert "SameSite=lax" in set_cookie or "samesite=lax" in set_cookie

    # Ensure raw tokens are NOT in DB plaintext
    stored_hashes = db.scalars(select(RefreshToken.token_hash)).all()
    assert cookie_A not in stored_hashes
    assert cookie_B not in stored_hashes

    # Refresh works for B
    client.cookies.set("refresh_token", cookie_B)
    ref_b_resp = client.post("/api/v1/auth/refresh")
    assert ref_b_resp.status_code == 200
    new_token_b = ref_b_resp.json()["access_token"]
    me_b = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token_b}"}).json()
    assert me_b["company_id"] == str(cB.id)

    # Old refresh token for A still works for A!
    client.cookies.set("refresh_token", cookie_A)
    ref_a_resp = client.post("/api/v1/auth/refresh")
    assert ref_a_resp.status_code == 200
    new_token_a = ref_a_resp.json()["access_token"]
    me_a = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token_a}"}).json()
    assert me_a["company_id"] == str(cA.id)


# ── W10: A's token cannot read B's data, B's token cannot read A's ────────────
def test_W10_cross_tenant_isolation(client, db):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    cA = _create_company(db, name="Company Alpha")
    cB = _create_company(db, name="Company Beta")

    uA, empA = _create_user_in_company(db, cA.id, email, role=UserRole.hr_admin)
    uB, empB = _create_user_in_company(db, cB.id, email, role=UserRole.hr_admin)

    empA_id = str(empA.id)
    empB_id = str(empB.id)

    headersA = _make_headers(uA.id, cA.id, uA.role)
    headersB = _make_headers(uB.id, cB.id, uB.role)

    # List employees with headers A: sees empA, NOT empB
    resA = client.get("/api/v1/employees", headers=headersA)
    assert resA.status_code == 200
    ids_in_A = {e["id"] for e in resA.json()["items"]}
    assert empA_id in ids_in_A
    assert empB_id not in ids_in_A

    # List employees with headers B: sees empB, NOT empA
    resB = client.get("/api/v1/employees", headers=headersB)
    assert resB.status_code == 200
    ids_in_B = {e["id"] for e in resB.json()["items"]}
    assert empB_id in ids_in_B
    assert empA_id not in ids_in_B


# ── W11: Switch to current workspace and back and forth work ─────────────────
def test_W11_switch_current_and_back_and_forth(client, db):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    cA = _create_company(db, name="Company Alpha")
    cB = _create_company(db, name="Company Beta")

    uA, _ = _create_user_in_company(db, cA.id, email)
    uB, _ = _create_user_in_company(db, cB.id, email)

    headersA = _make_headers(uA.id, cA.id, uA.role)

    # Switch to current workspace (A -> A)
    r_same = client.post(
        "/api/v1/auth/switch-workspace", headers=headersA, json={"company_id": str(cA.id)}
    )
    assert r_same.status_code == 200
    tokenA2 = r_same.json()["access_token"]

    # Switch A -> B
    r_ab = client.post(
        "/api/v1/auth/switch-workspace",
        headers={"Authorization": f"Bearer {tokenA2}"},
        json={"company_id": str(cB.id)},
    )
    assert r_ab.status_code == 200
    tokenB = r_ab.json()["access_token"]

    # Switch B -> A
    r_ba = client.post(
        "/api/v1/auth/switch-workspace",
        headers={"Authorization": f"Bearer {tokenB}"},
        json={"company_id": str(cA.id)},
    )
    assert r_ba.status_code == 200
    tokenA3 = r_ba.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokenA3}"}).json()
    assert me["company_id"] == str(cA.id)


# ── W12: Create workspace role restrictions, bad inputs, owner role, seeds ────
def test_W12_create_workspace_role_guards_validation_and_seeding(client, db, company_a):
    # Setup users with different roles
    u_owner, _ = _create_user_in_company(
        db, company_a.company_id, f"owner-{uuid.uuid4().hex[:6]}@example.com", role=UserRole.owner
    )
    u_hr, _ = _create_user_in_company(
        db, company_a.company_id, f"hr-{uuid.uuid4().hex[:6]}@example.com", role=UserRole.hr_admin
    )
    u_emp, _ = _create_user_in_company(
        db, company_a.company_id, f"emp-{uuid.uuid4().hex[:6]}@example.com", role=UserRole.employee
    )
    u_mgr, _ = _create_user_in_company(
        db, company_a.company_id, f"mgr-{uuid.uuid4().hex[:6]}@example.com", role=UserRole.manager
    )

    h_owner = _make_headers(u_owner.id, company_a.company_id, u_owner.role)
    h_hr = _make_headers(u_hr.id, company_a.company_id, u_hr.role)
    h_emp = _make_headers(u_emp.id, company_a.company_id, u_emp.role)
    h_mgr = _make_headers(u_mgr.id, company_a.company_id, u_mgr.role)

    # Employee and Manager -> 403
    r_emp = client.post(
        "/api/v1/companies/workspaces",
        headers=h_emp,
        json={"company_name": "Emp Co", "country": "IN"},
    )
    assert r_emp.status_code == 403

    r_mgr = client.post(
        "/api/v1/companies/workspaces",
        headers=h_mgr,
        json={"company_name": "Mgr Co", "country": "IN"},
    )
    assert r_mgr.status_code == 403

    # Validation: empty name -> 422
    r_empty = client.post(
        "/api/v1/companies/workspaces",
        headers=h_owner,
        json={"company_name": "   ", "country": "IN"},
    )
    assert r_empty.status_code == 422

    # Validation: name > 200 chars -> 422
    r_long = client.post(
        "/api/v1/companies/workspaces",
        headers=h_owner,
        json={"company_name": "A" * 201, "country": "IN"},
    )
    assert r_long.status_code == 422

    # Validation: country not ISO-2 -> 422
    r_bad_ctry = client.post(
        "/api/v1/companies/workspaces",
        headers=h_owner,
        json={"company_name": "Valid Co", "country": "IND"},
    )
    assert r_bad_ctry.status_code == 422

    # Success with HR Admin: creates workspace, creator becomes owner
    r_ok = client.post(
        "/api/v1/companies/workspaces",
        headers=h_hr,
        json={
            "company_name": "  New HR Co  ",
            "country": "IN",
            "seed_departments": True,
            "seed_shift": True,
        },
    )
    assert r_ok.status_code == 201
    res_data = r_ok.json()
    new_comp_id = res_data["company"]["id"]

    # Verify created company has stripped name
    assert res_data["company"]["name"] == "New HR Co"

    # Verify creator's user role in the new company is OWNER
    user_in_new = db.scalar(
        select(User).where(User.company_id == new_comp_id, User.email == u_hr.email)
    )
    assert user_in_new is not None
    assert user_in_new.role == UserRole.owner

    # Verify employee record has position "HR Admin / Org Head" and employee code "ADMIN-001"
    emp_in_new = db.scalar(
        select(Employee).where(Employee.company_id == new_comp_id, Employee.user_id == user_in_new.id)
    )
    assert emp_in_new is not None
    assert emp_in_new.position == "HR Admin / Org Head"
    assert emp_in_new.employee_code == "ADMIN-001"


# ── W13: Forced failure in seed/emp step leaves no partial records ────────────
def test_W13_create_workspace_all_or_nothing(client, db, company_a, monkeypatch):
    u_owner, _ = _create_user_in_company(
        db, company_a.company_id, f"owner-{uuid.uuid4().hex[:6]}@example.com", role=UserRole.owner
    )
    headers = _make_headers(u_owner.id, company_a.company_id, u_owner.role)

    counts_before = {
        "companies": db.scalar(select(func.count(Company.id))),
        "users": db.scalar(select(func.count(User.id))),
        "employees": db.scalar(select(func.count(Employee.id))),
        "locations": db.scalar(select(func.count(CompanyLocation.id))),
        "audit_logs": db.scalar(select(func.count(AuditLog.id))),
    }

    # Force failure in seed step
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app
    from app.modules.hr.repository import DepartmentRepository

    def failing_create(*args, **kwargs):
        raise RuntimeError("Seed simulation boom!")

    client_no_raise = TestClient(fastapi_app, raise_server_exceptions=False)

    with pytest.MonkeyPatch.context() as m:
        m.setattr(DepartmentRepository, "create", failing_create)
        resp = client_no_raise.post(
            "/api/v1/companies/workspaces",
            headers=headers,
            json={"company_name": "Failing Seed Co", "country": "IN", "seed_departments": True},
        )
        assert resp.status_code == 500
        # No internal error text leaked
        assert "RuntimeError" not in resp.text
        assert "Seed simulation boom" not in resp.text

    counts_after = {
        "companies": db.scalar(select(func.count(Company.id))),
        "users": db.scalar(select(func.count(User.id))),
        "employees": db.scalar(select(func.count(Employee.id))),
        "locations": db.scalar(select(func.count(CompanyLocation.id))),
        "audit_logs": db.scalar(select(func.count(AuditLog.id))),
    }

    assert counts_before == counts_after


# ── W14: Audit rows for create and switch; denied switch logs on app.security ──
def test_W14_audit_rows_for_create_and_switch_and_denied_log(client, db, company_a, caplog):
    u_owner, _ = _create_user_in_company(
        db, company_a.company_id, f"owner-{uuid.uuid4().hex[:6]}@example.com", role=UserRole.owner
    )
    headers = _make_headers(u_owner.id, company_a.company_id, u_owner.role)

    # 1. Create workspace writes WORKSPACE_CREATED audit row
    res_c = client.post(
        "/api/v1/companies/workspaces",
        headers=headers,
        json={"company_name": "Audit Co", "country": "IN"},
    )
    assert res_c.status_code == 201
    new_cid = uuid.UUID(res_c.json()["company"]["id"])

    audit_created = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "WORKSPACE_CREATED",
            AuditLog.entity_id == new_cid,
        )
    )
    assert audit_created is not None
    assert audit_created.actor_user_id == u_owner.id
    # No tokens in details
    assert "token" not in str(audit_created.details or {}).lower()

    # 2. Switch workspace writes WORKSPACE_SWITCHED audit row
    res_s = client.post(
        "/api/v1/auth/switch-workspace",
        headers=headers,
        json={"company_id": str(new_cid)},
    )
    assert res_s.status_code == 200

    audit_switched = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "WORKSPACE_SWITCHED",
            AuditLog.entity_id == new_cid,
        )
    )
    assert audit_switched is not None
    assert audit_switched.actor_user_id == u_owner.id
    assert "token" not in str(audit_switched.details or {}).lower()

    # 3. Denied switch writes NO audit row in DB, but logs structured record on app.security
    db_audit_count_before = db.scalar(select(func.count(AuditLog.id)))
    caplog.clear()

    random_id = str(uuid.uuid4())
    with caplog.at_level(logging.WARNING):
        res_denied = client.post(
            "/api/v1/auth/switch-workspace",
            headers=headers,
            json={"company_id": random_id},
        )
    assert res_denied.status_code == 404

    db_audit_count_after = db.scalar(select(func.count(AuditLog.id)))
    assert db_audit_count_before == db_audit_count_after

    sec_records = [
        r for r in caplog.records if r.name == "app.security" and r.levelno == logging.WARNING
    ]
    assert len(sec_records) >= 1
    rec = sec_records[-1]
    assert getattr(rec, "event", None) == "workspace_switch_failed"
    assert getattr(rec, "reason", None) is not None
    assert getattr(rec, "email_hash", None) is not None
    # No raw email leaked
    assert u_owner.email not in str(rec.__dict__)


# ── W15: Deactivating company or user after switch makes next call fail ────────
def test_W15_deactivation_after_switch_blocks_next_call(client, db):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    cA = _create_company(db, name="Company A")
    cB = _create_company(db, name="Company B")

    uA, _ = _create_user_in_company(db, cA.id, email)
    uB, _ = _create_user_in_company(db, cB.id, email)

    headersA = _make_headers(uA.id, cA.id, uA.role)

    # Switch to B
    res = client.post(
        "/api/v1/auth/switch-workspace",
        headers=headersA,
        json={"company_id": str(cB.id)},
    )
    assert res.status_code == 200
    tokenB = res.json()["access_token"]
    headersB = {"Authorization": f"Bearer {tokenB}"}

    # Verify B token works
    assert client.get("/api/v1/auth/me", headers=headersB).status_code == 200

    # 1. Deactivate company B -> next call must fail with 401
    cB.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=headersB).status_code == 401

    # Reactivate company B, deactivate user B -> next call must fail with 401
    cB.is_active = True
    uB.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=headersB).status_code == 401


# ── W16: Journey: create B, switch to B, create employee in B, switch to A ───
def test_W16_journey_create_switch_create_emp_switch_back(client, db, company_a):
    userA, _ = _create_user_in_company(
        db, company_a.company_id, f"owner-{uuid.uuid4().hex[:6]}@example.com", role=UserRole.owner
    )
    headersA = _make_headers(userA.id, company_a.company_id, userA.role)

    # 1. Create B
    res_b = client.post(
        "/api/v1/companies/workspaces",
        headers=headersA,
        json={"company_name": "Workspace Beta", "country": "IN"},
    )
    assert res_b.status_code == 201
    compB_id = res_b.json()["company"]["id"]
    tokenB = res_b.json()["access_token"]
    headersB = {"Authorization": f"Bearer {tokenB}"}

    # 2. In Workspace B, create employee
    emp_email = f"emp-beta-{uuid.uuid4().hex[:6]}@example.com"
    res_emp = client.post(
        "/api/v1/employees",
        headers=headersB,
        json={"first_name": "BetaEmp", "email": emp_email, "hire_date": "2024-01-01"},
    )
    assert res_emp.status_code == 201
    empB_id = res_emp.json()["id"]

    # 3. Switch back to A
    res_sw = client.post(
        "/api/v1/auth/switch-workspace",
        headers=headersB,
        json={"company_id": str(company_a.company_id)},
    )
    assert res_sw.status_code == 200
    tokenA_back = res_sw.json()["access_token"]
    headersA_back = {"Authorization": f"Bearer {tokenA_back}"}

    # 4. Verify B's employee is NOT visible in A
    list_a = client.get("/api/v1/employees", headers=headersA_back)
    assert list_a.status_code == 200
    emp_ids_in_a = {e["id"] for e in list_a.json()["items"]}
    assert empB_id not in emp_ids_in_a


# ── W17: No leak: list and error bodies contain no hash, token or foreign data ──
def test_W17_no_secret_or_data_leak_in_responses(client, db):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    cA = _create_company(db, name="Company Alpha")
    cB = _create_company(db, name="Company Beta")

    uA, _ = _create_user_in_company(db, cA.id, email)
    _create_user_in_company(db, cB.id, email)

    headersA = _make_headers(uA.id, cA.id, uA.role)

    # Check /auth/workspaces
    resp = client.get("/api/v1/auth/workspaces", headers=headersA)
    assert resp.status_code == 200
    body_text = resp.text
    assert "hashed_password" not in body_text
    assert "token_hash" not in body_text
    assert "admin_password_hash" not in body_text

    # Check 404 error response
    resp_err = client.post(
        "/api/v1/auth/switch-workspace",
        headers=headersA,
        json={"company_id": str(uuid.uuid4())},
    )
    assert resp_err.status_code == 404
    err_text = resp_err.text
    assert "exception" not in err_text.lower()
    assert "traceback" not in err_text.lower()


# ── W18: Duplicate company email gives 409 and nothing is created ─────────────
def test_W18_duplicate_company_email_gives_409(client, db, company_a):
    u_owner, _ = _create_user_in_company(
        db, company_a.company_id, f"owner-{uuid.uuid4().hex[:6]}@example.com", role=UserRole.owner
    )
    headers = _make_headers(u_owner.id, company_a.company_id, u_owner.role)

    existing_email = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    _create_company(db, name="Existing Co", email=existing_email)

    counts_before = {
        "companies": db.scalar(select(func.count(Company.id))),
        "users": db.scalar(select(func.count(User.id))),
    }

    resp = client.post(
        "/api/v1/companies/workspaces",
        headers=headers,
        json={"company_name": "Another Co", "company_email": existing_email, "country": "IN"},
    )
    assert resp.status_code == 409

    counts_after = {
        "companies": db.scalar(select(func.count(Company.id))),
        "users": db.scalar(select(func.count(User.id))),
    }
    assert counts_before == counts_after
