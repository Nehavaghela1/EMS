"""Tests for Rules 1.4: Password reset & change password.
Strictly tests only; no app code modified. Red where code is missing.
"""

import uuid
from datetime import timedelta

import pytest
import redis
from sqlalchemy import select

import app.modules.identity.service as id_svc
from app.core.config import settings
from app.core.otp import _attempts_key, _hash, _otp_key
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.core.time import utcnow
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog


def _make_user_in_company(
    db, company_id: uuid.UUID, *, email: str | None = None, is_active: bool = True
) -> tuple[User, str]:
    pw = "ValidPassword123!"
    if email is None:
        email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        company_id=company_id,
        email=email,
        hashed_password=hash_password(pw),
        role=UserRole.employee,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    return user, pw


# ── T01: Same status and body for unknown, inactive, pending, rejected ────────
def test_T01_forgot_password_uniform_response(client, db, company_a):
    limiter.enabled = False
    limiter.reset()

    user_active, _ = _make_user_in_company(db, company_a.company_id, is_active=True)
    user_inactive, _ = _make_user_in_company(db, company_a.company_id, is_active=False)

    pending_email = f"pending-{uuid.uuid4().hex[:8]}@example.com"
    comp_pending = Company(
        name="Pending Corp",
        code=f"PEN{uuid.uuid4().hex[:4].upper()}",
        email=pending_email,
        status=CompanyStatus.pending,
        admin_password_hash=hash_password("PendingPass123!"),
    )
    db.add(comp_pending)

    rejected_email = f"rejected-{uuid.uuid4().hex[:8]}@example.com"
    comp_rejected = Company(
        name="Rejected Corp",
        code=f"REJ{uuid.uuid4().hex[:4].upper()}",
        email=rejected_email,
        status=CompanyStatus.rejected,
        rejection_reason="Unverified docs",
        admin_password_hash=hash_password("RejectedPass123!"),
    )
    db.add(comp_rejected)
    db.commit()

    unknown_email = f"unknown-{uuid.uuid4().hex[:8]}@example.com"

    resp_active = client.post("/api/v1/auth/forgot-password", json={"email": user_active.email})
    resp_unknown = client.post("/api/v1/auth/forgot-password", json={"email": unknown_email})
    resp_inactive = client.post("/api/v1/auth/forgot-password", json={"email": user_inactive.email})
    resp_pending = client.post("/api/v1/auth/forgot-password", json={"email": pending_email})
    resp_rejected = client.post("/api/v1/auth/forgot-password", json={"email": rejected_email})

    responses = [
        ("unknown", resp_unknown),
        ("inactive", resp_inactive),
        ("pending", resp_pending),
        ("rejected", resp_rejected),
    ]

    for label, resp in responses:
        assert resp.status_code == resp_active.status_code, (
            f"{label} status_code {resp.status_code} != {resp_active.status_code}"
        )
        assert resp.json() == resp_active.json(), (
            f"{label} json {resp.json()} != {resp_active.json()}"
        )
        assert resp.headers.get("content-type") == resp_active.headers.get("content-type"), (
            f"{label} content-type differs from active"
        )


# ── T02: Per-IP limit 3/hour and per-account limit 3/hour ─────────────────────
def test_T02_rate_limits_per_ip_and_per_account(client, db, company_a, email_outbox):
    user, _ = _make_user_in_company(db, company_a.company_id)
    email_outbox.clear()

    limiter.enabled = True
    try:
        limiter.reset()

        # 1. Per-IP limit: 3/hour allowed; 4th request must be 429
        resps_ip = [
            client.post(
                "/api/v1/auth/forgot-password",
                json={"email": f"ip-probe-{i}-{uuid.uuid4().hex[:6]}@example.com"},
            )
            for i in range(4)
        ]
        assert resps_ip[0].status_code == 200
        assert resps_ip[1].status_code == 200
        assert resps_ip[2].status_code == 200
        assert resps_ip[3].status_code == 429

        limiter.reset()
        email_outbox.clear()

        # 2. Per-account limit: 3/hour across different IPs
        # Extra requests: same reply, no email, no lockout
        account_resps = []
        for i in range(4):
            # Simulate requests from distinct client IPs
            r = client.post(
                "/api/v1/auth/forgot-password",
                json={"email": user.email},
                headers={"X-Forwarded-For": f"198.51.100.{10 + i}"},
            )
            account_resps.append(r)

        # Requests beyond 3 per account should return the same reply without extra emails
        user_emails = [e for e in email_outbox if e["to"] == user.email]
        assert len(user_emails) == 3, f"Expected exactly 3 emails, got {len(user_emails)}"

        db.refresh(user)
        assert user.failed_attempts == 0
        assert user.locked_until is None
    finally:
        limiter.enabled = False
        limiter.reset()


# ── T03: Code stored as hash in Redis, 15m TTL, single-use, new request replaces old
def test_T03_code_hash_15m_ttl_single_use_and_replacement(client, db, company_a, email_outbox):
    user, _ = _make_user_in_company(db, company_a.company_id)
    r_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    email_outbox.clear()
    resp1 = client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    assert resp1.status_code == 200
    assert len(email_outbox) == 1
    otp1 = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    otp_key = _otp_key(user.email)
    raw_in_redis = r_client.get(otp_key)
    assert raw_in_redis is not None
    assert raw_in_redis != otp1
    assert raw_in_redis == _hash(otp1)

    ttl = r_client.ttl(otp_key)
    # Rule 3 specifies 15-minute expiry (900 seconds)
    assert 840 <= ttl <= 900, f"Expected 15m TTL (approx 900s), got {ttl}s"

    # A new request invalidates the old code
    email_outbox.clear()
    resp2 = client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    assert resp2.status_code == 200
    assert len(email_outbox) == 1
    otp2 = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )
    assert otp2 != otp1

    new_hash_in_redis = r_client.get(otp_key)
    assert new_hash_in_redis == _hash(otp2)

    # Trying old code fails
    fail_old = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp1, "new_password": "NewValidPassword123!"},
    )
    assert fail_old.status_code == 400

    # Single-use: using the new code succeeds and deletes the key
    succ = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp2, "new_password": "NewValidPassword123!"},
    )
    assert succ.status_code == 204
    assert r_client.get(otp_key) is None
    assert r_client.get(_attempts_key(user.email)) is None

    # Replaying the same code fails
    replay = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp2, "new_password": "AnotherPassword123!"},
    )
    assert replay.status_code == 400


# ── T04: 5 wrong tries kill code; right code afterwards fails; account not locked
def test_T04_five_wrong_tries_exhaust_code_without_account_lock(
    client, db, company_a, email_outbox
):
    user, orig_pw = _make_user_in_company(db, company_a.company_id)

    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    otp = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 5 wrong attempts
    for _ in range(5):
        r = client.post(
            "/api/v1/auth/reset-password",
            json={"email": user.email, "otp": "000000", "new_password": "NewPassword123!"},
        )
        assert r.status_code == 400

    # The right code afterwards fails
    r_right = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp, "new_password": "NewPassword123!"},
    )
    assert r_right.status_code == 400

    # The account is not locked
    db.refresh(user)
    assert user.failed_attempts == 0
    assert user.locked_until is None

    # User can still log in with original password
    login_resp = client.post("/api/v1/auth/login", json={"email": user.email, "password": orig_pw})
    assert login_resp.status_code == 200


# ── T05: Malformed & non-text inputs give 422; weak pw 422 leaves code usable; >128 422
def test_T05_validation_malformed_inputs_and_weak_password_preserves_code(
    client, db, company_a, email_outbox
):
    user, _ = _make_user_in_company(db, company_a.company_id)

    # 1. Malformed email in forgot-password
    for bad_email in ["not-an-email", 12345, None, ["a@b.com"]]:
        r = client.post("/api/v1/auth/forgot-password", json={"email": bad_email})
        assert r.status_code == 422

    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    otp = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 2. Malformed fields in reset-password
    malformed_payloads = [
        {"email": 123, "otp": otp, "new_password": "ValidPassword123!"},
        {"email": user.email, "otp": 999999, "new_password": "ValidPassword123!"},
        {"email": user.email, "otp": otp, "new_password": 1234567890},
    ]
    for p in malformed_payloads:
        r = client.post("/api/v1/auth/reset-password", json=p)
        assert r.status_code == 422

    # 3. Weak password returns 422 (too short, no digits, no letters)
    weak_passwords = ["short", "nouppernumbers!", "12345678901", "NoDigitsAtAll!"]
    for weak_pw in weak_passwords:
        r = client.post(
            "/api/v1/auth/reset-password",
            json={"email": user.email, "otp": otp, "new_password": weak_pw},
        )
        assert r.status_code == 422

    # 4. Password over 128 characters returns 422
    overlong_pw = "Valid1!" + "a" * 125
    r_long = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp, "new_password": overlong_pw},
    )
    assert r_long.status_code == 422

    # Verify that the code remains usable after 422 errors
    r_valid = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp, "new_password": "ValidPassword123!"},
    )
    assert r_valid.status_code == 204


# ── T06: Same email in two companies resets only targeted company ──────────────
def test_T06_same_email_in_two_companies_targeted_reset(
    client, db, company_a, company_b, email_outbox
):
    shared_email = f"shared-{uuid.uuid4().hex[:8]}@example.com"
    _user_a, pw_a = _make_user_in_company(db, company_a.company_id, email=shared_email)
    _user_b, pw_b = _make_user_in_company(db, company_b.company_id, email=shared_email)

    email_outbox.clear()
    comp_a = db.get(Company, company_a.company_id)
    # Target company A's account (via company_code or scoped payload if supported)
    resp = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": shared_email, "company_code": comp_a.code},
    )
    assert resp.status_code == 200

    # Ensure an email with code was sent for the targeted reset
    matching_emails = [e for e in email_outbox if e["to"] == shared_email]
    assert len(matching_emails) >= 1, "Expected reset OTP email to be queued for targeted company"
    otp = (
        matching_emails[0]["text_body"]
        .split("Your password reset code is ")[1]
        .split(".")[0]
        .strip()
    )

    new_pw_a = "NewPasswordA123!"
    reset_resp = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": shared_email,
            "company_code": comp_a.code,
            "otp": otp,
            "new_password": new_pw_a,
        },
    )
    assert reset_resp.status_code == 204

    # User A's password should be updated
    login_a_new = client.post(
        "/api/v1/auth/login",
        json={"email": shared_email, "password": new_pw_a, "company_code": comp_a.code},
    )
    assert login_a_new.status_code == 200

    # User B's password in company B must be unchanged
    comp_b = db.get(Company, company_b.company_id)
    login_b_old = client.post(
        "/api/v1/auth/login",
        json={"email": shared_email, "password": pw_b, "company_code": comp_b.code},
    )
    assert login_b_old.status_code == 200


# ── T07: After reset: new pw works, old fails, lockout cleared, refresh revoked, access 401
def test_T07_post_reset_token_invalidation_and_lockout_cleared(client, db, company_a, email_outbox):
    user, old_pw = _make_user_in_company(db, company_a.company_id)

    # 1. User logs in, gets access & refresh token
    login_resp = client.post("/api/v1/auth/login", json={"email": user.email, "password": old_pw})
    assert login_resp.status_code == 200
    access_token = login_resp.json()["access_token"]
    refresh_token = login_resp.cookies["refresh_token"]

    # Access token works initially
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_resp.status_code == 200

    # 2. Simulate account locked out
    user.failed_attempts = 5
    user.locked_until = utcnow() + timedelta(minutes=15)
    db.commit()

    # 3. Request reset and obtain OTP
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    otp = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 4. Perform reset
    new_pw = "BrandNewPass123!"
    reset_resp = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp, "new_password": new_pw},
    )
    assert reset_resp.status_code == 204
    # No tokens in response body
    assert not reset_resp.content or reset_resp.text == ""
    assert "access_token" not in reset_resp.headers.get("set-cookie", "")

    # 5. Old password fails, new password works
    fail_old = client.post("/api/v1/auth/login", json={"email": user.email, "password": old_pw})
    assert fail_old.status_code == 401

    succ_new = client.post("/api/v1/auth/login", json={"email": user.email, "password": new_pw})
    assert succ_new.status_code == 200

    # 6. Lockout cleared
    db.refresh(user)
    assert user.failed_attempts == 0
    assert user.locked_until is None

    # 7. Refresh token revoked
    ref_resp = client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh_token})
    assert ref_resp.status_code == 401

    # 8. ACCESS token issued BEFORE the reset now gives 401
    me_after = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_after.status_code == 401


# ── T08: Password-changed email queued only after commit, no code/pw, HTML-escaped
def test_T08_password_changed_email_queued_safely(client, db, company_a, email_outbox):
    user, _ = _make_user_in_company(db, company_a.company_id)

    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    otp = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    email_outbox.clear()
    new_pw = "BrandNewPass123!"
    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp, "new_password": new_pw},
    )
    assert resp.status_code == 204

    # Password-changed email was queued
    changed_emails = [e for e in email_outbox if e["to"] == user.email]
    assert len(changed_emails) == 1
    email_data = changed_emails[0]

    # Contains neither the code nor the new password
    assert otp not in email_data["text_body"]
    assert new_pw not in email_data["text_body"]
    assert otp not in email_data["html_body"]
    assert new_pw not in email_data["html_body"]

    # HTML is escaped
    assert "<script>" not in email_data["html_body"]


# ── T09: Audit rows PASSWORD_RESET_REQUESTED and PASSWORD_RESET_COMPLETED ──────
def test_T09_audit_rows_for_password_reset(client, db, company_a, email_outbox):
    user, _ = _make_user_in_company(db, company_a.company_id)

    # 1. Unknown email should produce NO audit rows
    email_outbox.clear()
    unknown_email = f"unknown-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/v1/auth/forgot-password", json={"email": unknown_email})

    unknown_logs = db.scalars(
        select(AuditLog).where(AuditLog.action == "PASSWORD_RESET_REQUESTED")
    ).all()
    assert not any(log.actor_email == unknown_email for log in unknown_logs)

    # 2. Real account produces PASSWORD_RESET_REQUESTED row
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    otp = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    req_logs = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action == "PASSWORD_RESET_REQUESTED",
        )
    ).all()
    assert len(req_logs) == 1
    req_log = req_logs[0]
    assert req_log.actor_user_id == user.id
    # Details without code
    details_str = str(req_log.details or {})
    assert otp not in details_str

    # 3. Reset produces PASSWORD_RESET_COMPLETED row
    new_pw = "NewSecuredPassword123!"
    client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp, "new_password": new_pw},
    )

    comp_logs = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action == "PASSWORD_RESET_COMPLETED",
        )
    ).all()
    assert len(comp_logs) == 1
    comp_log = comp_logs[0]
    assert comp_log.actor_user_id == user.id
    comp_details_str = str(comp_log.details or {})
    assert otp not in comp_details_str
    assert new_pw not in comp_details_str


# ── T10: Atomicity on failure and change-password requirements ────────────────
def test_T10_atomicity_and_change_password(client, db, company_a, email_outbox, monkeypatch):
    user, orig_pw = _make_user_in_company(db, company_a.company_id)

    # 1. Atomicity: if token revoke or audit write fails, password is unchanged
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    otp = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    def fail_revoke(*args, **kwargs):
        raise RuntimeError("Simulated token revoke failure during reset")

    monkeypatch.setattr(id_svc.RefreshTokenRepository, "revoke", fail_revoke)

    with pytest.raises(RuntimeError, match="Simulated token revoke failure"):
        client.post(
            "/api/v1/auth/reset-password",
            json={"email": user.email, "otp": otp, "new_password": "ShouldNotBeSaved123!"},
        )

    db.rollback()
    # Password must remain the original password
    db.refresh(user)
    login_orig = client.post("/api/v1/auth/login", json={"email": user.email, "password": orig_pw})
    assert login_orig.status_code == 200

    # Undo monkeypatch for change-password tests
    monkeypatch.undo()

    # 2. Change password flow:
    # Requires current password, ends other sessions, writes audit row, sends email
    login_1 = client.post("/api/v1/auth/login", json={"email": user.email, "password": orig_pw})
    token_1 = login_1.json()["access_token"]

    login_2 = client.post("/api/v1/auth/login", json={"email": user.email, "password": orig_pw})
    refresh_2 = login_2.cookies["refresh_token"]

    email_outbox.clear()
    # Bad current password fails
    bad_cp = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token_1}"},
        json={"current_password": "WrongPassword123!", "new_password": "BrandNewPass123!"},
    )
    assert bad_cp.status_code in (400, 401)

    # Correct current password succeeds
    good_cp = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token_1}"},
        json={"current_password": orig_pw, "new_password": "BrandNewPass123!"},
    )
    assert good_cp.status_code == 204

    # Ends other sessions (refresh_2 revoked)
    ref2_resp = client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh_2})
    assert ref2_resp.status_code == 401

    # Sends password-changed email
    cp_emails = [e for e in email_outbox if e["to"] == user.email]
    assert len(cp_emails) == 1
    assert "BrandNewPass123!" not in cp_emails[0]["text_body"]

    # Writes audit row
    cp_audit = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action.in_(["PASSWORD_CHANGED", "PASSWORD_RESET_COMPLETED"]),
        )
    ).all()
    assert len(cp_audit) >= 1
