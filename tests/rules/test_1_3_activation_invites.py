"""Tests for Rules 1.3: Activation & invites.
Tests through the real API, one assertion theme per test, positive controls where applicable.
"""

import html
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core import email_templates
from app.core.rate_limit import limiter
from app.core.security import hash_token
from app.modules.hr.models import Employee, InvitationStatus
from app.modules.identity.models import User, UserRole
from app.modules.platform.models import AuditLog


def _extract_token(email_outbox: list[dict], to_email: str) -> str:
    matches = [e for e in email_outbox if e["to"] == to_email and "/activate/" in e["text_body"]]
    assert matches, f"no activation email found for {to_email}"
    match = re.search(r"/activate/(\S+)", matches[-1]["text_body"])
    assert match, matches[-1]["text_body"]
    return match.group(1)


def _create_employee_via_api(
    client, hr_headers, email_outbox, to_email: str, first_name: str = "TestEmp"
):
    res = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={"first_name": first_name, "email": to_email, "hire_date": "2024-01-01"},
    )
    assert res.status_code == 201
    token = _extract_token(email_outbox, to_email)
    return res.json(), token


# ── I01: Token stored as sha256 hash (raw not in DB), expiry ~7 days ─────────
def test_I01_token_hashed_and_expiry_about_7_days(client, db, company_a, email_outbox):
    email = f"i01-{uuid.uuid4().hex[:6]}@example.com"
    emp_data, raw_token = _create_employee_via_api(
        client, company_a.hr_headers, email_outbox, email
    )
    emp_id = uuid.UUID(emp_data["id"])

    emp = db.get(Employee, emp_id)
    assert emp is not None

    # Raw token must NOT appear in the database row
    row_values = [str(getattr(emp, col.name)) for col in Employee.__table__.columns]
    assert not any(raw_token in val for val in row_values)

    # Stored token must equal sha256 hash of raw_token
    assert emp.activation_token_hash == hash_token(raw_token)

    # Expiry must be approximately 7 days from now (within 6 to 8 days)
    assert emp.activation_expires_at is not None
    now = datetime.now(UTC)
    expires_at = emp.activation_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    diff = expires_at - now
    assert timedelta(days=6) <= diff <= timedelta(days=8)


# ── I02: Token single-use; unknown, expired and used tokens give identical response
def test_I02_token_single_use_and_identical_error_responses(client, db, company_a, email_outbox):
    email = f"i02-{uuid.uuid4().hex[:6]}@example.com"
    emp_data, raw_token = _create_employee_via_api(
        client, company_a.hr_headers, email_outbox, email
    )
    emp_id = uuid.UUID(emp_data["id"])

    # Positive control: unknown token gives 404
    unknown_resp = client.get("/api/v1/auth/activate/unknown-token-12345")
    assert unknown_resp.status_code == 404
    unknown_body = unknown_resp.json()

    # Expired token gives identical status and body
    emp = db.get(Employee, emp_id)
    assert emp is not None
    emp.activation_expires_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()

    expired_resp = client.get(f"/api/v1/auth/activate/{raw_token}")
    assert expired_resp.status_code == unknown_resp.status_code
    assert expired_resp.json()["error"]["code"] == unknown_body["error"]["code"]
    assert expired_resp.json()["error"]["message"] == unknown_body["error"]["message"]

    # Reset expiry so it's valid again
    emp.activation_expires_at = datetime.now(UTC) + timedelta(days=7)
    db.commit()

    # Valid token can be previewed and activated
    preview_resp = client.get(f"/api/v1/auth/activate/{raw_token}")
    assert preview_resp.status_code == 200

    act_resp = client.post(
        "/api/v1/auth/activate",
        json={
            "token": raw_token,
            "username": f"user_{uuid.uuid4().hex[:6]}",
            "password": "ValidPassword123!",
        },
    )
    assert act_resp.status_code == 200

    # Used token gives identical status and body to unknown/expired
    used_resp = client.get(f"/api/v1/auth/activate/{raw_token}")
    assert used_resp.status_code == unknown_resp.status_code
    assert used_resp.json()["error"]["code"] == unknown_body["error"]["code"]
    assert used_resp.json()["error"]["message"] == unknown_body["error"]["message"]

    used_act_resp = client.post(
        "/api/v1/auth/activate",
        json={
            "token": raw_token,
            "username": f"user2_{uuid.uuid4().hex[:6]}",
            "password": "ValidPassword123!",
        },
    )
    assert used_act_resp.status_code == 404
    assert used_act_resp.json()["error"]["code"] == unknown_body["error"]["code"]
    assert used_act_resp.json()["error"]["message"] == unknown_body["error"]["message"]


# ── I03: Resend invite role guards, token invalidation, and 409 on activated ──
def test_I03_resend_invite_guards_and_activated_conflict(
    client, db, company_a, company_b, email_outbox
):
    email = f"i03-{uuid.uuid4().hex[:6]}@example.com"
    emp_data, old_token = _create_employee_via_api(
        client, company_a.hr_headers, email_outbox, email
    )
    emp_id = emp_data["id"]

    # 1. Employee role from same company cannot resend -> 403
    res_emp = client.post(
        f"/api/v1/employees/{emp_id}/resend-invite", headers=company_a.employee_headers
    )
    assert res_emp.status_code == 403

    # 2. Other company's HR admin -> 404
    res_b = client.post(f"/api/v1/employees/{emp_id}/resend-invite", headers=company_b.hr_headers)
    assert res_b.status_code == 404

    # 3. Positive control: same company HR admin -> 200
    res_a = client.post(f"/api/v1/employees/{emp_id}/resend-invite", headers=company_a.hr_headers)
    assert res_a.status_code == 200
    new_token = _extract_token(email_outbox, email)
    assert new_token != old_token

    # 4. Old token is now 404
    assert client.get(f"/api/v1/auth/activate/{old_token}").status_code == 404

    # 5. New token works
    assert client.get(f"/api/v1/auth/activate/{new_token}").status_code == 200
    act_res = client.post(
        "/api/v1/auth/activate",
        json={
            "token": new_token,
            "username": f"user_{uuid.uuid4().hex[:6]}",
            "password": "ValidPassword123!",
        },
    )
    assert act_res.status_code == 200

    # 6. Resend on an ALREADY ACTIVATED employee -> 409
    res_conflict = client.post(
        f"/api/v1/employees/{emp_id}/resend-invite", headers=company_a.hr_headers
    )
    assert res_conflict.status_code == 409


# ── I04: Rate limits: preview 429 after 20/min, activate 429 after 10/min ─────
def test_I04_rate_limits_on_preview_and_activate(client, company_a, email_outbox):
    email = f"i04-{uuid.uuid4().hex[:6]}@example.com"
    _emp_data, token = _create_employee_via_api(client, company_a.hr_headers, email_outbox, email)

    limiter.enabled = True
    try:
        limiter.reset()

        # Preview: 20/min limit. The first request must NOT be 429. The 21st must be 429.
        preview_resps = [client.get(f"/api/v1/auth/activate/{token}") for _ in range(21)]
        assert preview_resps[0].status_code == 200
        assert preview_resps[-1].status_code == 429

        limiter.reset()

        # Activate: 10/min limit. The first request must NOT be 429. The 11th must be 429.
        activate_resps = [
            client.post(
                "/api/v1/auth/activate",
                json={
                    "token": "invalid_tok",
                    "username": f"probe_{i}",
                    "password": "ValidPassword123!",
                },
            )
            for i in range(11)
        ]
        assert activate_resps[0].status_code != 429
        assert activate_resps[-1].status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()


# ── I05: Username validation: invalid usernames return 422; token still works; normalized
def test_I05_username_validation_and_normalization(client, db, company_a, email_outbox):
    email = f"i05-{uuid.uuid4().hex[:6]}@example.com"
    _emp_data, token = _create_employee_via_api(client, company_a.hr_headers, email_outbox, email)

    invalid_usernames = ["", "ab", "a" * 31, "bad name!", 123, None]
    for bad_u in invalid_usernames:
        resp = client.post(
            "/api/v1/auth/activate",
            json={"token": token, "username": bad_u, "password": "ValidPassword123!"},
        )
        assert resp.status_code == 422, (
            f"Expected 422 for username {bad_u!r}, got {resp.status_code}"
        )

    # Token still works after 422 errors: normalize "  Ravi.S  " -> "ravi.s"
    act_resp = client.post(
        "/api/v1/auth/activate",
        json={"token": token, "username": "  Ravi.S  ", "password": "ValidPassword123!"},
    )
    assert act_resp.status_code == 200

    user = db.scalar(select(User).where(User.username == "ravi.s"))
    assert user is not None
    assert user.username == "ravi.s"


# ── I06: Duplicate username in same company gives 409, no second user row, token valid
def test_I06_duplicate_username_conflict(client, db, company_a, email_outbox):
    email1 = f"i06-1-{uuid.uuid4().hex[:6]}@example.com"
    email2 = f"i06-2-{uuid.uuid4().hex[:6]}@example.com"
    _emp1, token1 = _create_employee_via_api(client, company_a.hr_headers, email_outbox, email1)
    _emp2, token2 = _create_employee_via_api(client, company_a.hr_headers, email_outbox, email2)

    shared_username = f"dup_{uuid.uuid4().hex[:6]}"

    # Activate user 1
    resp1 = client.post(
        "/api/v1/auth/activate",
        json={"token": token1, "username": shared_username, "password": "ValidPassword123!"},
    )
    assert resp1.status_code == 200

    # User 2 tries duplicate username in same company -> 409
    resp2 = client.post(
        "/api/v1/auth/activate",
        json={"token": token2, "username": shared_username, "password": "ValidPassword123!"},
    )
    assert resp2.status_code == 409

    # Exactly one user row exists with that username
    users = db.scalars(select(User).where(User.username == shared_username.lower())).all()
    assert len(users) == 1

    # Token 2 is still valid and can be activated with a unique username
    resp2_retry = client.post(
        "/api/v1/auth/activate",
        json={
            "token": token2,
            "username": f"{shared_username}_unique",
            "password": "ValidPassword123!",
        },
    )
    assert resp2_retry.status_code == 200


# ── I07: Weak password gives 422, token still valid ───────────────────────────
def test_I07_weak_password_validation(client, company_a, email_outbox):
    email = f"i07-{uuid.uuid4().hex[:6]}@example.com"
    _emp, token = _create_employee_via_api(client, company_a.hr_headers, email_outbox, email)

    weak_passwords = ["short", "allletterspassword", "1234567890", "   "]
    for pw in weak_passwords:
        resp = client.post(
            "/api/v1/auth/activate",
            json={"token": token, "username": f"u_{uuid.uuid4().hex[:6]}", "password": pw},
        )
        assert resp.status_code == 422

    # Positive control: token still valid with strong password
    resp_ok = client.post(
        "/api/v1/auth/activate",
        json={
            "token": token,
            "username": f"u_{uuid.uuid4().hex[:6]}",
            "password": "ValidPassword123!",
        },
    )
    assert resp_ok.status_code == 200


# ── I08: Extra fields ignored; employee role, tokens returned, token cleared ──
def test_I08_extra_fields_ignored_and_tokens_issued(client, db, company_a, email_outbox):
    email = f"i08-{uuid.uuid4().hex[:6]}@example.com"
    emp_data, token = _create_employee_via_api(client, company_a.hr_headers, email_outbox, email)
    emp_id = uuid.UUID(emp_data["id"])

    # Try privilege escalation in activation body
    resp = client.post(
        "/api/v1/auth/activate",
        json={
            "token": token,
            "username": f"u_{uuid.uuid4().hex[:6]}",
            "password": "ValidPassword123!",
            "role": "hr_admin",
            "is_active": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in resp.cookies

    # Employee linked, status activated, token hash cleared
    emp = db.get(Employee, emp_id)
    assert emp is not None
    assert emp.invitation_status == InvitationStatus.activated
    assert emp.activation_token_hash is None
    assert emp.activation_expires_at is None
    assert emp.user_id is not None

    # Created user has role employee and is_active True
    user = db.get(User, emp.user_id)
    assert user is not None
    assert user.role == UserRole.employee
    assert user.is_active is True

    # Exactly one user row for this email
    user_count = db.scalar(select(func.count(User.id)).where(User.email == email))
    assert user_count == 1


# ── I09: Atomicity on activation failure ──────────────────────────────────────
def test_I09_activation_atomicity_on_failure(client, db, company_a, email_outbox, monkeypatch):
    import app.modules.identity.service as id_svc

    email = f"i09-{uuid.uuid4().hex[:6]}@example.com"
    emp_data, token = _create_employee_via_api(client, company_a.hr_headers, email_outbox, email)
    emp_id = uuid.UUID(emp_data["id"])

    def fail_token_create(self, *args, **kwargs):
        raise RuntimeError("Simulated failure creating refresh token")

    monkeypatch.setattr(id_svc.RefreshTokenRepository, "create", fail_token_create)

    with pytest.raises(RuntimeError, match="Simulated failure"):
        client.post(
            "/api/v1/auth/activate",
            json={
                "token": token,
                "username": f"u_{uuid.uuid4().hex[:6]}",
                "password": "ValidPassword123!",
            },
        )

    db.rollback()

    # No user row exists
    user_row = db.scalar(select(User).where(User.email == email))
    assert user_row is None

    # Employee not activated
    emp = db.get(Employee, emp_id)
    assert emp is not None
    assert emp.invitation_status == InvitationStatus.sent
    assert emp.activation_token_hash is not None
    assert emp.user_id is None

    # Token still works afterwards
    monkeypatch.undo()
    retry_resp = client.post(
        "/api/v1/auth/activate",
        json={
            "token": token,
            "username": f"u_{uuid.uuid4().hex[:6]}",
            "password": "ValidPassword123!",
        },
    )
    assert retry_resp.status_code == 200


# ── I10: Audit logging for activation and resend ───────────────────────────────
def test_I10_audit_logging_activation_and_resend(client, db, company_a, email_outbox):
    email = f"i10-{uuid.uuid4().hex[:6]}@example.com"
    emp_data, token = _create_employee_via_api(client, company_a.hr_headers, email_outbox, email)
    emp_id = emp_data["id"]

    # 1. Resend invite writes EMPLOYEE_INVITE_RESENT audit row
    res_resend = client.post(
        f"/api/v1/employees/{emp_id}/resend-invite", headers=company_a.hr_headers
    )
    assert res_resend.status_code == 200
    new_token = _extract_token(email_outbox, email)

    hr_me = client.get("/api/v1/auth/me", headers=company_a.hr_headers)
    assert hr_me.status_code == 200
    hr_user_id = hr_me.json()["id"]

    resend_logs = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == uuid.UUID(emp_id),
            AuditLog.action == "EMPLOYEE_INVITE_RESENT",
        )
    ).all()
    assert len(resend_logs) == 1
    resend_log = resend_logs[0]
    assert resend_log.actor_user_id == uuid.UUID(hr_user_id)
    assert resend_log.created_at is not None
    # Details contain no token
    details_str = str(resend_log.details)
    assert token not in details_str
    assert new_token not in details_str

    # 2. Activation writes EMPLOYEE_ACTIVATED audit row
    pw = "ValidPassword123!"
    act_resp = client.post(
        "/api/v1/auth/activate",
        json={"token": new_token, "username": f"u_{uuid.uuid4().hex[:6]}", "password": pw},
    )
    assert act_resp.status_code == 200

    emp = db.get(Employee, uuid.UUID(emp_id))
    assert emp is not None and emp.user_id is not None

    act_logs = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == uuid.UUID(emp_id),
            AuditLog.action == "EMPLOYEE_ACTIVATED",
        )
    ).all()
    assert len(act_logs) == 1
    act_log = act_logs[0]
    assert act_log.actor_user_id == emp.user_id
    assert act_log.created_at is not None
    act_details_str = str(act_log.details)
    assert new_token not in act_details_str
    assert pw not in act_details_str


# ── I11: HTML email escaping ──────────────────────────────────────────────────
def test_I11_email_html_escaping():
    xss_name = "<script>alert('xss')</script>"
    xss_company = 'Acme & <b style="color:red">Co</b>'
    now = datetime.now(UTC)

    # 1. employee_invitation_email
    _sub, text, html_part = email_templates.employee_invitation_email(
        first_name=xss_name,
        company_name=xss_company,
        activation_link="http://localhost:5173/activate/testtoken",
        expires_at=now,
    )
    # Plain text should contain the unescaped strings
    assert xss_name in text
    assert xss_company in text
    # HTML must NOT contain unescaped script tag or unescaped HTML injection
    assert "<script>" not in html_part
    assert html.escape(xss_name) in html_part
    assert html.escape(xss_company) in html_part

    # 2. company_rejected_email
    _sub_rej, text_rej, html_rej = email_templates.company_rejected_email(
        company_name=xss_company,
        rejection_reason="Reason with <img src=x onerror=alert(1)>",
    )
    assert xss_company in text_rej
    assert "<img src=x" in text_rej
    assert "<img src=x" not in html_rej
    assert html.escape(xss_company) in html_rej
    assert html.escape("Reason with <img src=x onerror=alert(1)>") in html_rej


# ── I12: Invitation link escaping inside button href ──────────────────────────
def test_I12_invitation_link_escaping_inside_href():
    xss_link = 'http://localhost:5173/activate/"><script>alert(1)</script>'
    now = datetime.now(UTC)
    _sub, text, html_part = email_templates.employee_invitation_email(
        first_name="Ravi",
        company_name="Acme Corp",
        activation_link=xss_link,
        expires_at=now,
    )
    # Unescaped raw string must be in text, but NOT in html_part anywhere
    assert xss_link in text
    assert '"><script>alert(1)</script>' not in html_part
    assert "<script>" not in html_part
    assert html.escape(xss_link, quote=True) in html_part


# ── I13: Escaping in remaining email templates ─────────────────────────────────
def test_I13_password_reset_otp_email_escaping():
    payload = "<script>alert(1)</script>"
    _sub, text, html_part = email_templates.password_reset_otp_email(
        otp=payload, expires_minutes=15
    )
    assert payload in text
    assert payload not in html_part
    assert "<script>" not in html_part
    assert html.escape(payload, quote=True) in html_part


def test_I13_hr_admin_credentials_email_escaping():
    payload = "<script>alert(1)</script>"
    link_payload = f"http://localhost:5173/login?x={payload}"
    # With temporary password
    _sub1, text1, html_part1 = email_templates.hr_admin_credentials_email(
        company_name=payload,
        email=f"admin+{payload}@example.com",
        temporary_password=payload,
        login_link=link_payload,
    )
    assert payload in text1
    assert payload not in html_part1
    assert "<script>" not in html_part1
    assert html.escape(payload, quote=True) in html_part1
    assert html.escape(link_payload, quote=True) in html_part1

    # Without temporary password
    _sub2, text2, html_part2 = email_templates.hr_admin_credentials_email(
        company_name=payload,
        email=f"admin+{payload}@example.com",
        temporary_password=None,
        login_link=link_payload,
    )
    assert payload in text2
    assert payload not in html_part2
    assert "<script>" not in html_part2
    assert html.escape(payload, quote=True) in html_part2
    assert html.escape(link_payload, quote=True) in html_part2


def test_I13_password_changed_email_escaping():
    payload = "<script>alert(1)</script>"
    _sub, text, html_part = email_templates.password_changed_email(first_name=payload)
    assert payload in text
    assert payload not in html_part
    assert "<script>" not in html_part
    assert html.escape(payload, quote=True) in html_part


def test_I13_leave_decision_email_escaping():
    payload = "<script>alert(1)</script>"
    _sub, text, html_part = email_templates.leave_decision_email(
        first_name=payload,
        status="rejected",
        start_date="2026-01-01",
        end_date="2026-01-02",
        rejection_reason=payload,
    )
    assert payload in text
    assert payload not in html_part
    assert "<script>" not in html_part
    assert html.escape(payload, quote=True) in html_part


# ── I14: EmployeeService.resend_invite requires actor parameter ───────────────
def test_I14_resend_invite_requires_actor_parameter(db, company_a):
    from app.modules.hr.service import EmployeeService

    emp_id = uuid.uuid4()
    with pytest.raises(TypeError):
        # Calling without actor argument must raise TypeError
        EmployeeService(db).resend_invite(company_a.company_id, emp_id)  # type: ignore[call-arg]
