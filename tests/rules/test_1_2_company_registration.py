"""Tests for Rules 1.2: Company registration & approval.
Strictly tests only; no app code modified.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog


def _make_headers_for_role(db, company_id: uuid.UUID, role: UserRole) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


# ── R01: Valid registration ───────────────────────────────────────────────────
def test_R01_valid_registration(client, db):
    email = f"valid-reg-{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "company_name": "Acme Widgets",
        "company_email": email,
        "password": "ValidPassword123!",
    }
    resp = client.post("/api/v1/companies/register", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert "access_token" not in body
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" not in set_cookie

    # Ensure no User row was created for that email
    user_row = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    assert user_row is None


# ── R02: No password hash or token in response ────────────────────────────────
def test_R02_no_password_hash_or_token_in_response(client):
    email = f"clean-resp-{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "company_name": "Clean Corp",
        "company_email": email,
        "password": "ValidPassword123!",
    }
    resp = client.post("/api/v1/companies/register", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert "admin_password_hash" not in body
    assert "password" not in body
    assert "password_hash" not in body
    assert "access_token" not in body
    assert "token" not in body


# ── R03: Password hash argon2 prefix and no plaintext in DB ───────────────────
def test_R03_argon2_prefix_and_no_plaintext(client, db):
    plain_pw = "PlainSecretPass123!"
    email = f"hash-check-{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "company_name": "Security Corp",
        "company_email": email,
        "password": plain_pw,
    }
    resp = client.post("/api/v1/companies/register", json=payload)
    assert resp.status_code == 201
    company_id = uuid.UUID(resp.json()["id"])

    company = db.get(Company, company_id)
    assert company is not None
    assert company.admin_password_hash is not None
    assert company.admin_password_hash.startswith("$argon2")

    # Plaintext password must appear nowhere in the company row
    row_values = [str(getattr(company, col.name)) for col in Company.__table__.columns]
    assert not any(plain_pw in val for val in row_values)


# ── R04: Email trimmed, lowercased, and duplicate rejection ───────────────────
@pytest.mark.xfail(strict=True, reason="R04 not met yet")
def test_R04_email_trimmed_lowercased_and_duplicate_rejected(client, db):
    email_base = f"duptest-{uuid.uuid4().hex[:8]}@example.com"
    email_variant = f"  {email_base.upper()}  "

    payload_1 = {
        "company_name": "First Corp",
        "company_email": email_variant,
        "password": "ValidPassword123!",
    }
    resp_1 = client.post("/api/v1/companies/register", json=payload_1)
    assert resp_1.status_code == 201
    assert resp_1.json()["email"] == email_base.lower()

    # Registering same email in different case -> 409
    payload_2 = {
        "company_name": "Second Corp",
        "company_email": email_base.lower(),
        "password": "ValidPassword123!",
    }
    resp_2 = client.post("/api/v1/companies/register", json=payload_2)
    assert resp_2.status_code == 409

    # Registering email of a REJECTED company -> 409
    rej_email = f"rejected-{uuid.uuid4().hex[:8]}@example.com"
    rej_comp = Company(
        name="Rejected Corp",
        code=f"REJ-{uuid.uuid4().hex[:4].upper()}",
        email=rej_email,
        status=CompanyStatus.rejected,
        rejection_reason="Duplicate",
    )
    db.add(rej_comp)
    db.commit()

    resp_3 = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Retry Corp",
            "company_email": rej_email,
            "password": "ValidPass123!",
        },
    )
    assert resp_3.status_code == 409

    # Exactly one company exists for each
    count_1 = db.scalar(
        select(func.count(Company.id)).where(func.lower(Company.email) == email_base.lower())
    )
    assert count_1 == 1
    count_rej = db.scalar(
        select(func.count(Company.id)).where(func.lower(Company.email) == rej_email.lower())
    )
    assert count_rej == 1


# ── R05: Password length validation ───────────────────────────────────────────
def test_R05_password_length_validation(client):
    # 7 characters -> 422
    resp_short = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Short Pass Corp",
            "company_email": f"short-{uuid.uuid4().hex[:6]}@example.com",
            "password": "Short1!",
        },
    )
    assert resp_short.status_code == 422

    # 64 characters -> 201
    long_pass = "ValidPass123!" + "a" * 51
    assert len(long_pass) == 64
    resp_long = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Long Pass Corp",
            "company_email": f"long-{uuid.uuid4().hex[:6]}@example.com",
            "password": long_pass,
        },
    )
    assert resp_long.status_code == 201


# ── R06: Extra fields in registration payload ignored or rejected ─────────────
def test_R06_extra_fields_cannot_privilege_escalate(client, db):
    fake_uuid = str(uuid.uuid4())
    payload = {
        "company_name": "Hacker Corp",
        "company_email": f"hacker-{uuid.uuid4().hex[:8]}@example.com",
        "password": "HackerPassword123!",
        "status": "approved",
        "code": "HACK",
        "role": "super_admin",
        "id": fake_uuid,
        "rejection_reason": "x",
    }
    resp = client.post("/api/v1/companies/register", json=payload)
    if resp.status_code == 422:
        pass  # Extra forbidden/rejected
    elif resp.status_code == 201:
        body = resp.json()
        assert body["status"] == "pending"
        assert body["code"] != "HACK"
        assert body["id"] != fake_uuid
    else:
        pytest.fail(f"Unexpected status code {resp.status_code}: {resp.text}")


# ── R07: Name and email input validation ──────────────────────────────────────
@pytest.mark.xfail(strict=True, reason="R07 not met yet")
def test_R07_name_and_email_input_validation(client, db):
    # Missing email -> 422
    assert (
        client.post(
            "/api/v1/companies/register",
            json={"company_name": "No Email Corp", "password": "Password123!"},
        ).status_code
        == 422
    )

    # Invalid email format -> 422
    assert (
        client.post(
            "/api/v1/companies/register",
            json={
                "company_name": "Bad Email",
                "company_email": "not-an-email",
                "password": "Password123!",
            },
        ).status_code
        == 422
    )

    # Empty name -> 422
    assert (
        client.post(
            "/api/v1/companies/register",
            json={
                "company_name": "",
                "company_email": f"e1-{uuid.uuid4().hex[:6]}@example.com",
                "password": "Password123!",
            },
        ).status_code
        == 422
    )

    # Whitespace-only name -> 422
    assert (
        client.post(
            "/api/v1/companies/register",
            json={
                "company_name": "   ",
                "company_email": f"e2-{uuid.uuid4().hex[:6]}@example.com",
                "password": "Password123!",
            },
        ).status_code
        == 422
    )

    # Name of 256 characters -> 422
    assert (
        client.post(
            "/api/v1/companies/register",
            json={
                "company_name": "A" * 256,
                "company_email": f"e3-{uuid.uuid4().hex[:6]}@example.com",
                "password": "Password123!",
            },
        ).status_code
        == 422
    )

    # Name with surrounding spaces is stored trimmed
    resp_trim = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "  Trimmed Corp  ",
            "company_email": f"trim-{uuid.uuid4().hex[:6]}@example.com",
            "password": "Password123!",
        },
    )
    assert resp_trim.status_code == 201
    assert resp_trim.json()["name"] == "Trimmed Corp"


# ── R08: Same company name gets different codes ───────────────────────────────
def test_R08_same_company_name_generates_different_codes(client):
    name = "Duplicate Name Corp"
    resp_1 = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": name,
            "company_email": f"n1-{uuid.uuid4().hex[:6]}@example.com",
            "password": "Password123!",
        },
    )
    resp_2 = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": name,
            "company_email": f"n2-{uuid.uuid4().hex[:6]}@example.com",
            "password": "Password123!",
        },
    )
    assert resp_1.status_code == 201
    assert resp_2.status_code == 201
    assert resp_1.json()["code"] != resp_2.json()["code"]


# ── R09: Rate limiting on registration ────────────────────────────────────────
@pytest.mark.xfail(strict=True, reason="R09 not met yet")
def test_R09_registration_rate_limiting(client):
    limiter.enabled = True
    try:
        limiter.reset()
        responses = [
            client.post(
                "/api/v1/companies/register",
                json={
                    "company_name": f"Rate Corp {i}",
                    "company_email": f"rate-{i}-{uuid.uuid4().hex[:6]}@example.com",
                    "password": "Password123!",
                },
            )
            for i in range(6)
        ]
        # If registration has a rate limit (e.g. 5/window), 6th must return 429
        assert responses[-1].status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()


# ── A01: Role guards on company endpoints ─────────────────────────────────────
def test_A01_role_guards_on_company_endpoints(client, db, company_a):
    comp_id = str(company_a.company_id)
    roles_headers = {
        "owner": _make_headers_for_role(db, company_a.company_id, UserRole.owner),
        "hr_admin": company_a.hr_headers,
        "manager": company_a.manager_headers,
        "employee": company_a.employee_headers,
    }

    # 1. Unauthenticated -> 401
    assert client.get("/api/v1/companies").status_code == 401
    assert client.post(f"/api/v1/companies/{comp_id}/approve").status_code == 401
    assert (
        client.post(f"/api/v1/companies/{comp_id}/reject", json={"reason": "test"}).status_code
        == 401
    )
    assert (
        client.post(
            f"/api/v1/companies/{comp_id}/deactivate", json={"reason": "test", "password": "x"}
        ).status_code
        == 401
    )

    # 2. Non-super_admin roles on list-pending (GET /api/v1/companies), approve, reject -> 403
    for role, headers in roles_headers.items():
        assert client.get("/api/v1/companies", headers=headers).status_code == 403, f"{role} list"
        assert (
            client.post(f"/api/v1/companies/{comp_id}/approve", headers=headers).status_code == 403
        ), f"{role} approve"
        assert (
            client.post(
                f"/api/v1/companies/{comp_id}/reject", headers=headers, json={"reason": "test"}
            ).status_code
            == 403
        ), f"{role} reject"

    # 3. Deactivate company: restricted to owner / super_admin; hr_admin, manager, employee -> 403
    for role in ["hr_admin", "manager", "employee"]:
        headers = roles_headers[role]
        res = client.post(
            f"/api/v1/companies/{comp_id}/deactivate",
            headers=headers,
            json={"reason": "test", "password": "wrong"},
        )
        assert res.status_code == 403, f"{role} deactivate"

    # Reactivate endpoint does not exist -> assert 404/405
    assert client.post(f"/api/v1/companies/{comp_id}/reactivate").status_code in (404, 405)


# ── A02: super_admin approves pending company ─────────────────────────────────
@pytest.mark.xfail(strict=True, reason="A02 not met yet")
def test_A02_super_admin_approves_creates_owner(client, db, super_admin_headers):
    email = f"approve-owner-{uuid.uuid4().hex[:8]}@example.com"
    reg_resp = client.post(
        "/api/v1/companies/register",
        json={"company_name": "Approve Co", "company_email": email, "password": "ValidPass123!"},
    )
    assert reg_resp.status_code == 201
    comp_id = reg_resp.json()["id"]

    approve_resp = client.post(f"/api/v1/companies/{comp_id}/approve", headers=super_admin_headers)
    assert approve_resp.status_code == 200
    assert approve_resp.json()["company"]["status"] == "active"

    # Exactly one User for company email with role owner, active, matching company_id
    users = db.scalars(select(User).where(func.lower(User.email) == email.lower())).all()
    assert len(users) == 1
    user = users[0]
    assert user.role == UserRole.owner
    assert user.is_active is True
    assert str(user.company_id) == str(comp_id)


# ── A03: Login with registration credentials after approval ───────────────────
def test_A03_login_works_after_approval(client, super_admin_headers):
    email = f"login-approved-{uuid.uuid4().hex[:8]}@example.com"
    pw = "ApprovedPass123!"
    reg_resp = client.post(
        "/api/v1/companies/register",
        json={"company_name": "Login Co", "company_email": email, "password": pw},
    )
    assert reg_resp.status_code == 201
    comp_id = reg_resp.json()["id"]

    approve_resp = client.post(f"/api/v1/companies/{comp_id}/approve", headers=super_admin_headers)
    assert approve_resp.status_code == 200

    login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()


# ── A04: Invalid state transitions return 409 ─────────────────────────────────
def test_A04_invalid_state_transitions_return_409(client, db, super_admin_headers):
    email = f"state-trans-{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/api/v1/companies/register",
        json={"company_name": "Transition Co", "company_email": email, "password": "ValidPass123!"},
    )
    comp_id = reg.json()["id"]

    # Approve once -> 200
    assert (
        client.post(f"/api/v1/companies/{comp_id}/approve", headers=super_admin_headers).status_code
        == 200
    )

    # 1. Approve an already-approved company -> 409 and still 1 user
    assert (
        client.post(f"/api/v1/companies/{comp_id}/approve", headers=super_admin_headers).status_code
        == 409
    )
    user_count = db.scalar(
        select(func.count(User.id)).where(func.lower(User.email) == email.lower())
    )
    assert user_count == 1

    # 2. Reject an approved company -> 409
    assert (
        client.post(
            f"/api/v1/companies/{comp_id}/reject",
            headers=super_admin_headers,
            json={"reason": "too late"},
        ).status_code
        == 409
    )

    # 3. Approve a rejected company -> 409
    rej_email = f"rej-then-app-{uuid.uuid4().hex[:8]}@example.com"
    reg_rej = client.post(
        "/api/v1/companies/register",
        json={"company_name": "Rej Co", "company_email": rej_email, "password": "ValidPass123!"},
    )
    rej_id = reg_rej.json()["id"]
    client.post(
        f"/api/v1/companies/{rej_id}/reject", headers=super_admin_headers, json={"reason": "bad"}
    )

    assert (
        client.post(f"/api/v1/companies/{rej_id}/approve", headers=super_admin_headers).status_code
        == 409
    )


# ── A05: Reject validation and outcome ────────────────────────────────────────
@pytest.mark.xfail(strict=True, reason="A05 not met yet")
def test_A05_reject_validation_and_outcome(client, db, super_admin_headers):
    email = f"reject-flow-{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Reject Flow Co",
            "company_email": email,
            "password": "ValidPass123!",
        },
    )
    comp_id = reg.json()["id"]

    # Empty reason -> 422
    assert (
        client.post(
            f"/api/v1/companies/{comp_id}/reject",
            headers=super_admin_headers,
            json={"reason": ""},
        ).status_code
        == 422
    )

    # Reason of 501 chars -> 422
    assert (
        client.post(
            f"/api/v1/companies/{comp_id}/reject",
            headers=super_admin_headers,
            json={"reason": "A" * 501},
        ).status_code
        == 422
    )

    # Valid reason -> stored on company, status rejected, no user created
    reason = "Incomplete incorporation documents"
    res = client.post(
        f"/api/v1/companies/{comp_id}/reject",
        headers=super_admin_headers,
        json={"reason": reason},
    )
    assert res.status_code == 200

    comp = db.get(Company, uuid.UUID(comp_id))
    assert comp.status == CompanyStatus.rejected
    assert comp.rejection_reason == reason

    users = db.scalars(select(User).where(func.lower(User.email) == email.lower())).all()
    assert len(users) == 0


# ── A06: Unknown and malformed IDs ────────────────────────────────────────────
def test_A06_unknown_and_malformed_ids(client, super_admin_headers):
    unknown_id = str(uuid.uuid4())
    # Unknown UUID -> 404
    assert (
        client.post(
            f"/api/v1/companies/{unknown_id}/approve", headers=super_admin_headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/companies/{unknown_id}/reject",
            headers=super_admin_headers,
            json={"reason": "test"},
        ).status_code
        == 404
    )

    # Malformed ID -> 422
    assert (
        client.post("/api/v1/companies/not-a-uuid/approve", headers=super_admin_headers).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/companies/not-a-uuid/reject",
            headers=super_admin_headers,
            json={"reason": "test"},
        ).status_code
        == 422
    )


# ── A07: IntegrityError on duplicate (company_id, email) in User ──────────────
def test_A07_duplicate_company_email_user_raises_integrity_error(db, company_a):
    user1 = User(
        company_id=company_a.company_id,
        email="unique-test@company.test",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(user1)
    db.commit()

    user2 = User(
        company_id=company_a.company_id,
        email="unique-test@company.test",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(user2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── A08: Atomicity of approve transaction ─────────────────────────────────────
def test_A08_approve_atomicity_on_failure(client, db, super_admin_headers, monkeypatch):
    import app.modules.identity.service as id_svc

    email = f"atomic-{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/api/v1/companies/register",
        json={"company_name": "Atomic Co", "company_email": email, "password": "ValidPass123!"},
    )
    comp_id = reg.json()["id"]

    def fail_create_user(self, *args, **kwargs):
        raise RuntimeError("Simulated DB failure during owner creation")

    monkeypatch.setattr(id_svc.UserRepository, "create", fail_create_user)

    with pytest.raises(RuntimeError, match="Simulated DB failure"):
        client.post(f"/api/v1/companies/{comp_id}/approve", headers=super_admin_headers)

    db.rollback()
    comp = db.get(Company, uuid.UUID(comp_id))
    assert comp.status == CompanyStatus.pending
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    assert user is None


# ── S01: Audit log created for approve and reject ──────────────────────────────
@pytest.mark.xfail(strict=True, reason="S01 not met yet")
def test_S01_audit_log_created_for_approve_and_reject(client, db, super_admin_headers):
    # Approve audit log
    reg_app = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Audit App Co",
            "company_email": f"audit-app-{uuid.uuid4().hex[:6]}@example.com",
            "password": "Password123!",
        },
    )
    app_id = reg_app.json()["id"]
    client.post(f"/api/v1/companies/{app_id}/approve", headers=super_admin_headers)

    log_app = db.scalar(
        select(AuditLog).where(
            AuditLog.company_id == uuid.UUID(app_id),
            AuditLog.action.in_(["COMPANY_APPROVED", "APPROVE_COMPANY", "COMPANY_APPROVE"]),
        )
    )
    assert log_app is not None

    # Reject audit log
    reg_rej = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Audit Rej Co",
            "company_email": f"audit-rej-{uuid.uuid4().hex[:6]}@example.com",
            "password": "Password123!",
        },
    )
    rej_id = reg_rej.json()["id"]
    client.post(
        f"/api/v1/companies/{rej_id}/reject",
        headers=super_admin_headers,
        json={"reason": "Fraudulent"},
    )

    log_rej = db.scalar(
        select(AuditLog).where(
            AuditLog.company_id == uuid.UUID(rej_id),
            AuditLog.action.in_(["COMPANY_REJECTED", "REJECT_COMPANY", "COMPANY_REJECT"]),
        )
    )
    assert log_rej is not None


# ── S02: Email queued on approve and reject ────────────────────────────────────
@pytest.mark.xfail(strict=True, reason="S02 not met yet")
def test_S02_emails_queued_on_approve_and_reject(client, super_admin_headers, email_outbox):
    email_app = f"app-mail-{uuid.uuid4().hex[:6]}@example.com"
    reg_app = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Mail App Co",
            "company_email": email_app,
            "password": "SecretPassword123!",
        },
    )
    app_id = reg_app.json()["id"]

    email_outbox.clear()
    client.post(f"/api/v1/companies/{app_id}/approve", headers=super_admin_headers)

    # Approve email sent to company email
    app_emails = [e for e in email_outbox if e["to"] == email_app]
    assert len(app_emails) == 1
    # Does not contain the password
    assert "SecretPassword123!" not in app_emails[0]["text_body"]

    # Reject email sent to company email with reason
    email_rej = f"rej-mail-{uuid.uuid4().hex[:6]}@example.com"
    reg_rej = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Mail Rej Co",
            "company_email": email_rej,
            "password": "SecretPassword123!",
        },
    )
    rej_id = reg_rej.json()["id"]

    email_outbox.clear()
    reason = "Invalid business license"
    client.post(
        f"/api/v1/companies/{rej_id}/reject", headers=super_admin_headers, json={"reason": reason}
    )

    rej_emails = [e for e in email_outbox if e["to"] == email_rej]
    assert len(rej_emails) == 1
    assert reason in rej_emails[0]["text_body"]


# ── S03: Company deactivation blocks login and access tokens ──────────────────
@pytest.mark.xfail(strict=True, reason="S03 not met yet")
def test_S03_company_deactivation_and_reactivation(client, db, super_admin_headers):
    email = f"deact-{uuid.uuid4().hex[:6]}@example.com"
    pw = "ActivePass123!"
    reg = client.post(
        "/api/v1/companies/register",
        json={"company_name": "Deact Co", "company_email": email, "password": pw},
    )
    comp_id = reg.json()["id"]
    client.post(f"/api/v1/companies/{comp_id}/approve", headers=super_admin_headers)

    # Login works initially
    login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    # Deactivate company via super_admin
    deact_resp = client.post(
        f"/api/v1/companies/{comp_id}/deactivate",
        headers=super_admin_headers,
        json={"reason": "Payment failure", "password": "Test1234pass!"},
    )
    assert deact_resp.status_code == 200

    # Existing token -> 401 on /auth/me
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401

    # Login refused
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": pw}).status_code == 401
    )

    # Reactivate company
    react_resp = client.post(f"/api/v1/companies/{comp_id}/reactivate", headers=super_admin_headers)
    assert react_resp.status_code == 200

    # Login works again
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": pw}).status_code == 200
    )


# ── S04: admin_password_hash never leaked in responses ─────────────────────────
def test_S04_admin_password_hash_never_in_company_responses(client, super_admin_headers):
    # 1. Register response
    reg = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Leak Check Co",
            "company_email": f"leak-{uuid.uuid4().hex[:6]}@example.com",
            "password": "Password123!",
        },
    )
    assert "admin_password_hash" not in reg.json()

    # 2. List pending response
    list_resp = client.get(
        "/api/v1/companies", headers=super_admin_headers, params={"status": "pending"}
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) > 0
    for item in items:
        assert "admin_password_hash" not in item
