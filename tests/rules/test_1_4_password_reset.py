"""Tests for Rules 1.4: Password reset & change password.
Strictly tests only; no app code modified. Red where code is missing.
"""

import logging
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


# ── T01: Same status and body; spy asserts identical execution steps ──────────
def test_T01_forgot_password_uniform_response(client, db, company_a, monkeypatch):
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

    # Spy assertion: assert both paths run the same steps (lookup, Redis store, email queue)
    steps_executed: dict[str, list[str]] = {"active": [], "unknown": []}

    orig_find = id_svc.UserRepository.find_by_email
    orig_store = id_svc.generate_and_store_otp
    orig_send = id_svc.send_email_task.delay

    current_tag = "active"

    def spy_find(self, *args, **kwargs):
        steps_executed[current_tag].append("lookup")
        return orig_find(self, *args, **kwargs)

    def spy_store(*args, **kwargs):
        steps_executed[current_tag].append("redis_store")
        return orig_store(*args, **kwargs)

    def spy_send(*args, **kwargs):
        steps_executed[current_tag].append("email_queue")
        return orig_send(*args, **kwargs)

    monkeypatch.setattr(id_svc.UserRepository, "find_by_email", spy_find)
    monkeypatch.setattr(id_svc, "generate_and_store_otp", spy_store)
    monkeypatch.setattr(id_svc.send_email_task, "delay", spy_send)

    current_tag = "active"
    client.post("/api/v1/auth/forgot-password", json={"email": user_active.email})

    current_tag = "unknown"
    client.post(
        "/api/v1/auth/forgot-password",
        json={"email": f"spy-unknown-{uuid.uuid4().hex[:6]}@example.com"},
    )

    # To eliminate timing side-channels, unknown email must execute identical pipeline
    assert steps_executed["unknown"] == steps_executed["active"], (
        f"Pipeline steps differ: unknown executed {steps_executed['unknown']}, "
        f"active executed {steps_executed['active']}"
    )


# ── T02a: Per-IP limit 3/hour ─────────────────────────────────────────────────
def test_T02a_rate_limits_per_ip(client):
    limiter.enabled = True
    try:
        limiter.reset()

        # Per-IP limit: 3/hour allowed; 4th request from same IP must be 429
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
    finally:
        limiter.enabled = False
        limiter.reset()


# ── T02b: Per-ACCOUNT limit 3/hour reached from different client IPs ──────────
def test_T02b_rate_limits_per_account(client, db, company_a, email_outbox, monkeypatch):
    from app.core.otp import verify_otp

    user, _ = _make_user_in_company(db, company_a.company_id)
    email_outbox.clear()

    # Configure trusted proxies so varying the X-Forwarded-For header varies the client IP
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["127.0.0.1/32", "testclient"])

    limiter.enabled = True
    try:
        limiter.reset()

        # Per-account limit: 3/hour across different IPs.
        # IP is varied via X-Forwarded-For: 198.51.100.{10+i}
        account_resps = []
        codes_sent = []
        for i in range(4):
            email_outbox.clear()
            r = client.post(
                "/api/v1/auth/forgot-password",
                json={"email": user.email},
                headers={"X-Forwarded-For": f"198.51.100.{10 + i}"},
            )
            account_resps.append(r)
            if email_outbox:
                body = email_outbox[-1]["text_body"]
                code = body.split("Your password reset code is ")[1].split(".")[0].strip()
                codes_sent.append(code)

        # 4th request: same reply status and body
        assert account_resps[3].status_code == 200
        assert account_resps[3].json() == account_resps[0].json()

        # Exactly 3 codes sent, 4th must not send email
        assert len(codes_sent) == 3, f"Expected 3 codes across 4 requests, got {len(codes_sent)}"

        # 4th request did not generate a new code (latest code remains the 3rd one)
        assert verify_otp(user.email, codes_sent[2]) is True

        # Account is not locked
        db.refresh(user)
        assert user.failed_attempts == 0
        assert user.locked_until is None
    finally:
        limiter.enabled = False
        limiter.reset()


# ── T03: Code stored as hash in Redis, TTL, single-use, new request replaces old
def test_T03_code_hash_ttl_single_use_and_replacement(client, db, company_a, email_outbox):
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

    # Assertion 1: Hash only (Redis value != raw code)
    assert raw_in_redis != otp1
    assert raw_in_redis == _hash(otp1)

    # Assertion 2: TTL equals settings.OTP_TTL_MINUTES * 60 (10 minutes)
    expected_ttl = settings.OTP_TTL_MINUTES * 60
    ttl = r_client.ttl(otp_key)
    assert expected_ttl - 60 <= ttl <= expected_ttl, (
        f"Expected TTL near {expected_ttl}s, got {ttl}s"
    )

    # Assertion 3: Replacement — a new request invalidates the old code
    email_outbox.clear()
    resp2 = client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    assert resp2.status_code == 200
    assert len(email_outbox) == 1
    otp2 = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )
    assert otp2 != otp1
    assert r_client.get(otp_key) == _hash(otp2)

    fail_old = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp1, "new_password": "NewValidPassword123!"},
    )
    assert fail_old.status_code == 400

    # Assertion 4: Single-use — using new code consumes and deletes key
    succ = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp2, "new_password": "NewValidPassword123!"},
    )
    assert succ.status_code == 204
    assert r_client.get(otp_key) is None
    assert r_client.get(_attempts_key(user.email)) is None

    # Replay fails
    replay = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp2, "new_password": "AnotherPassword123!"},
    )
    assert replay.status_code == 400


# ── T04: 5 wrong tries kill code; structured warning log; account not locked ───
def test_T04_five_wrong_tries_exhaust_code_without_account_lock(
    client, db, company_a, email_outbox, caplog
):
    user, orig_pw = _make_user_in_company(db, company_a.company_id)

    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    otp = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 5 wrong attempts; assert a wrong code emits a structured warning log with reason code
    caplog.clear()
    wrong_code = "000000"
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            r = client.post(
                "/api/v1/auth/reset-password",
                json={"email": user.email, "otp": wrong_code, "new_password": "NewPassword123!"},
            )
            assert r.status_code == 400

    # Structured log check: emits warning log with reason code, without OTP or email
    otp_warning_logs = [
        rec
        for rec in caplog.records
        if rec.levelno == logging.WARNING
        and (
            "otp" in rec.getMessage().lower()
            or (hasattr(rec, "reason") and "otp" in str(rec.reason).lower())
        )
    ]
    assert len(otp_warning_logs) >= 1
    for rec in otp_warning_logs:
        msg = rec.getMessage()
        assert wrong_code not in msg
        assert otp not in msg
        assert user.email not in msg

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


# ── T06: Multi-company password reset with company code ───────────────────────
def test_T06_multi_company_password_reset(client, db, company_a, company_b, email_outbox):
    shared_email = f"shared-{uuid.uuid4().hex[:8]}@example.com"
    _user_a, pw_a = _make_user_in_company(db, company_a.company_id, email=shared_email)
    _user_b, pw_b = _make_user_in_company(db, company_b.company_id, email=shared_email)

    comp_a = db.get(Company, company_a.company_id)
    comp_b = db.get(Company, company_b.company_id)

    # (a) Email in two companies + company_code resets only that company
    email_outbox.clear()
    resp_a = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": shared_email, "company_code": comp_a.code},
    )
    assert resp_a.status_code == 200
    matching_emails_a = [e for e in email_outbox if e["to"] == shared_email]
    assert len(matching_emails_a) == 1
    otp_a = (
        matching_emails_a[0]["text_body"]
        .split("Your password reset code is ")[1]
        .split(".")[0]
        .strip()
    )

    new_pw_a = "NewPasswordA123!"
    reset_a = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": shared_email,
            "company_code": comp_a.code,
            "otp": otp_a,
            "new_password": new_pw_a,
        },
    )
    assert reset_a.status_code == 204

    # User A login with new pw succeeds; User B login with old pw in comp B succeeds
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": shared_email, "password": new_pw_a, "company_code": comp_a.code},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": shared_email, "password": pw_b, "company_code": comp_b.code},
        ).status_code
        == 200
    )

    # (b) No company code: same generic reply, no code created, exactly ONE guidance email queued
    email_outbox.clear()
    resp_no_code = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": shared_email},
    )
    assert resp_no_code.status_code == 200
    assert resp_no_code.json() == resp_a.json()

    guidance_emails = [e for e in email_outbox if e["to"] == shared_email]
    assert len(guidance_emails) == 1
    assert "company code" in guidance_emails[0]["text_body"].lower()
    assert "Your password reset code is" not in guidance_emails[0]["text_body"]

    # (c) Wrong company code: same generic reply, nothing queued
    email_outbox.clear()
    resp_wrong_code = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": shared_email, "company_code": "NONEXISTENT_CODE"},
    )
    assert resp_wrong_code.status_code == 200
    assert resp_wrong_code.json() == resp_a.json()
    assert len(email_outbox) == 0


# ── T07: After reset: tokens revoked, lockout cleared, immediate login succeeds
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

    # 5. Immediate login right after a reset (same second) must NOT get a false 401
    succ_new = client.post("/api/v1/auth/login", json={"email": user.email, "password": new_pw})
    assert succ_new.status_code == 200
    new_token = succ_new.json()["access_token"]
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code
        == 200
    )

    # Old password fails
    fail_old = client.post("/api/v1/auth/login", json={"email": user.email, "password": old_pw})
    assert fail_old.status_code == 401

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


# ── T11: Length limits over 128 chars give 422; empty login password gives 422 ─
def test_T11_length_limits_over_128_and_empty_login_password(client, db, company_a):
    user, orig_pw = _make_user_in_company(db, company_a.company_id)
    overlong = "P" + "a" * 128 + "1!"

    # 1. Login password over 128 characters gives 422
    resp_login_long = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": overlong},
    )
    assert resp_login_long.status_code == 422

    # Empty login password gives 422
    resp_login_empty = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": ""},
    )
    assert resp_login_empty.status_code == 422

    # 2. Change-password current_password over 128 characters gives 422
    login_res = client.post("/api/v1/auth/login", json={"email": user.email, "password": orig_pw})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp_cp_long = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": overlong, "new_password": "ValidNewPassword123!"},
    )
    assert resp_cp_long.status_code == 422

    # 3. Deactivate password over 128 characters gives 422
    owner, owner_pw = _make_user_in_company(db, company_a.company_id, role=UserRole.owner)
    login_owner = client.post(
        "/api/v1/auth/login", json={"email": owner.email, "password": owner_pw}
    )
    owner_token = login_owner.json()["access_token"]
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    resp_deact_long = client.post(
        f"/api/v1/companies/{company_a.company_id}/deactivate",
        headers=owner_headers,
        json={"reason": "Testing limits", "password": overlong},
    )
    assert resp_deact_long.status_code == 422


# ── T12: Change-password is limited to 5/minute; wrong current password counts ─
def test_T12_change_password_rate_limited_to_5_per_minute(client, db, company_a):
    user, orig_pw = _make_user_in_company(db, company_a.company_id)
    login_res = client.post("/api/v1/auth/login", json={"email": user.email, "password": orig_pw})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    limiter.enabled = True
    try:
        limiter.reset()
        resps = []
        for i in range(6):
            r = client.post(
                "/api/v1/auth/change-password",
                headers=headers,
                json={"current_password": "WrongPassword123!", "new_password": f"NewPass{i}123!"},
            )
            resps.append(r)

        assert resps[0].status_code in (400, 401)
        assert resps[-1].status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()


# ── T13: New password equal to current password gives 422 ──────────────────────
def test_T13_new_password_equal_to_current_gives_422(client, db, company_a, email_outbox):
    user, orig_pw = _make_user_in_company(db, company_a.company_id)

    # 1. Reset password with new password == current password gives 422
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    otp = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    resp_reset_same = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": otp, "new_password": orig_pw},
    )
    assert resp_reset_same.status_code == 422

    # 2. Change password with new password == current password gives 422
    login_res = client.post("/api/v1/auth/login", json={"email": user.email, "password": orig_pw})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp_cp_same = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": orig_pw, "new_password": orig_pw},
    )
    assert resp_cp_same.status_code == 422
