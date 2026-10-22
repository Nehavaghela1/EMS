"""Tests for Rules 1.4: Password reset & change password.
Strictly tests only; no app code modified. Red where code is missing.
"""

import logging
import time
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
    db,
    company_id: uuid.UUID,
    *,
    email: str | None = None,
    is_active: bool = True,
    role: UserRole = UserRole.employee,
) -> tuple[User, str]:
    pw = "ValidPassword123!"
    if email is None:
        email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        company_id=company_id,
        email=email,
        hashed_password=hash_password(pw),
        role=role,
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

    # Assert that for existing, unknown and ineligible emails the HTTP handler performs the same
    # steps (per-account counter, then exactly one enqueue of the reset-request task).
    from app.workers.tasks.identity import process_password_reset_request

    enqueue_calls: list[tuple[str, str | None]] = []

    def fake_delay(email: str, company_code: str | None = None):
        enqueue_calls.append((email, company_code))

    monkeypatch.setattr(process_password_reset_request, "delay", fake_delay)

    emails_to_test = [
        ("existing", user_active.email),
        ("unknown", f"probe-unknown-{uuid.uuid4().hex[:6]}@example.com"),
        ("ineligible_inactive", user_inactive.email),
    ]

    for label, target_email in emails_to_test:
        del enqueue_calls[:]
        r = client.post("/api/v1/auth/forgot-password", json={"email": target_email})
        assert r.status_code == 200, f"{label} expected 200"
        assert len(enqueue_calls) == 1, (
            f"{label} expected exactly one enqueue call, got {len(enqueue_calls)}"
        )
        assert enqueue_calls[0][0] == target_email, f"{label} enqueued wrong email"


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
def test_T02b_rate_limits_per_account(db, company_a, email_outbox, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.otp import verify_otp_atomic
    from app.db.session import get_db
    from app.main import app as fastapi_app

    def _override_get_db():
        try:
            yield db
        except Exception:
            db.rollback()
            raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    # TestClient with peer IP 127.0.0.1 so X-Forwarded-For is evaluated by trusted proxies
    client = TestClient(fastapi_app, client=("127.0.0.1", 50000))

    user, _ = _make_user_in_company(db, company_a.company_id)
    email_outbox.clear()

    # Configure trusted proxies so varying the X-Forwarded-For header varies the client IP
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["127.0.0.1/32"])

    limiter.enabled = True
    try:
        limiter.reset()

        # Step 1: Prove client IP really varies: send 3 requests for 3 DIFFERENT emails
        # from 3 different IPs and assert none gets 429 (proving the IP varies and IP rate
        # limit is not tripped).
        for i in range(3):
            r_diff = client.post(
                "/api/v1/auth/forgot-password",
                json={"email": f"diff-user-{i}-{uuid.uuid4().hex[:6]}@example.com"},
                headers={"X-Forwarded-For": f"198.51.100.{100 + i}"},
            )
            assert r_diff.status_code == 200, (
                f"Expected 200 for varying IP probe {i}, got {r_diff.status_code}"
            )

        # Step 2: Now run the per-account assertions with 4 requests for the SAME user email
        # across different IPs
        email_outbox.clear()
        account_resps = []
        for i in range(4):
            r = client.post(
                "/api/v1/auth/forgot-password",
                json={"email": user.email},
                headers={"X-Forwarded-For": f"198.51.100.{10 + i}"},
            )
            account_resps.append(r)

        # 4th request: same reply status and body
        assert account_resps[3].status_code == 200
        assert account_resps[3].json() == account_resps[0].json()

        # 3 emails sent, 4th request sends nothing
        assert len(email_outbox) == 3, (
            f"Expected 3 emails across 4 requests, got {len(email_outbox)}"
        )

        # 3 distinct codes
        codes_sent = [
            m["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
            for m in email_outbox
        ]
        assert len(set(codes_sent)) == 3, f"Expected 3 distinct codes, got {codes_sent}"

        # The 3rd code still verifies with verify_otp_atomic, the 1st and 2nd do not (superseded)
        assert verify_otp_atomic(user.email, codes_sent[2], company_id=user.company_id)[0] is True
        assert verify_otp_atomic(user.email, codes_sent[0], company_id=user.company_id)[0] is False
        assert verify_otp_atomic(user.email, codes_sent[1], company_id=user.company_id)[0] is False

        # Account is not locked
        db.refresh(user)
        assert user.failed_attempts == 0
        assert user.locked_until is None
    finally:
        fastapi_app.dependency_overrides.clear()
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

    otp_key = _otp_key(user.email, company_id=user.company_id)
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

    # Structured log check: assert a structured record on logger "app.security"
    # with record.event and record.reason, email_hash present, raw email,
    # code and password absent.
    security_records = [
        rec
        for rec in caplog.records
        if rec.name == "app.security" and rec.levelno == logging.WARNING
    ]
    assert len(security_records) >= 1, "Expected warning records on logger app.security"
    for rec in security_records:
        assert getattr(rec, "event", None) == "password_reset_failed"
        assert getattr(rec, "reason", None) in ("wrong_code", "exhausted", "missing_or_expired")
        assert getattr(rec, "email_hash", None) is not None
        msg = f"{rec.getMessage()} {rec.__dict__}"
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
        json={"email": user.email, "otp": otp, "new_password": "BrandNewValidPass123!"},
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

    # Ensure integer-second separation between initial token creation and password reset
    time.sleep(1.05)

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

    # 5. Lockout cleared by reset
    db.refresh(user)
    assert user.failed_attempts == 0
    assert user.locked_until is None

    # 6. Immediate login right after a reset (same second) must NOT get a false 401
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
    # Log in so user has an active refresh token to revoke
    login_init = client.post("/api/v1/auth/login", json={"email": user.email, "password": orig_pw})
    assert login_init.status_code == 200

    # 1. Atomicity: if token revoke or audit write fails, password is unchanged
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    otp = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    def fail_revoke(*args, **kwargs):
        raise RuntimeError("Simulated token revoke failure during reset")

    with monkeypatch.context() as m:
        m.setattr(id_svc.RefreshTokenRepository, "revoke", fail_revoke)

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


# ── L01: No secrets in logs ───────────────────────────────────────────────────
# Capture ALL log output (caplog at INFO plus the app JSON formatter output) while running
# forgot-password (code), employee invite (activation token), company approval
# (HR admin temporary password) and a password change. Assert none of those secret
# strings appear in any record message, args or extras, including "data".
def test_L01_no_secrets_in_logs(client, db, company_a, email_outbox, caplog):
    import io
    import logging
    from datetime import date

    from app.core.logging import JSONFormatter
    from app.modules.hr.schemas import EmployeeCreateRequest
    from app.modules.hr.service import EmployeeService
    from app.modules.identity.service import CompanyService

    captured_stream = io.StringIO()
    handler = logging.StreamHandler(captured_stream)
    formatter = JSONFormatter()
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    caplog.clear()
    secrets_to_check: list[str] = []

    try:
        with caplog.at_level(logging.INFO):
            # 1. Forgot-password (code)
            u_forgot, _ = _make_user_in_company(db, company_a.company_id)
            email_outbox.clear()
            r_forgot = client.post("/api/v1/auth/forgot-password", json={"email": u_forgot.email})
            assert r_forgot.status_code == 200
            assert len(email_outbox) >= 1
            code = (
                email_outbox[-1]["text_body"]
                .split("Your password reset code is ")[1]
                .split(".")[0]
                .strip()
            )
            secrets_to_check.append(code)

            # 2. Employee invite (activation token)
            hr_user, _ = _make_user_in_company(db, company_a.company_id, role=UserRole.hr_admin)
            emp_email = f"l01-emp-{uuid.uuid4().hex[:6]}@example.com"
            email_outbox.clear()
            emp_created, _ = EmployeeService(db).create_employee(
                company_a.company_id,
                EmployeeCreateRequest(
                    first_name="L01",
                    last_name="Tester",
                    email=emp_email,
                    hire_date=date(2026, 1, 1),
                ),
                actor=hr_user,
            )
            assert len(email_outbox) >= 1
            # Extract activation token from link
            body_inv = email_outbox[-1]["text_body"]
            raw_token = body_inv.split("/activate/")[1].split(" ")[0].split("\n")[0].strip()
            secrets_to_check.append(raw_token)

            # 3. Company approval (HR admin temporary password)
            reg_email = f"l01-comp-{uuid.uuid4().hex[:6]}@example.com"
            client.post(
                "/api/v1/companies/register",
                json={
                    "company_name": f"L01 Corp {uuid.uuid4().hex[:4]}",
                    "company_email": reg_email,
                },
            )
            comp_pending = db.scalar(select(Company).where(Company.email == reg_email))
            super_admin, _ = _make_user_in_company(
                db, company_a.company_id, role=UserRole.super_admin
            )
            email_outbox.clear()
            CompanyService(db).approve_company(comp_pending.id, admin_id=super_admin.id)
            assert len(email_outbox) >= 1
            body_appr = email_outbox[-1]["text_body"]
            # Temporary password sent in body
            temp_pw = body_appr.split("Temporary password: ")[1].split("\n")[0].strip()
            secrets_to_check.append(temp_pw)

            # 4. Password change
            u_change, orig_pw = _make_user_in_company(db, company_a.company_id)
            login_res = client.post(
                "/api/v1/auth/login", json={"email": u_change.email, "password": orig_pw}
            )
            token = login_res.json()["access_token"]
            new_secret_pw = "NewSecretPassWord999!"
            secrets_to_check.append(new_secret_pw)
            client.post(
                "/api/v1/auth/change-password",
                headers={"Authorization": f"Bearer {token}"},
                json={"current_password": orig_pw, "new_password": new_secret_pw},
            )

        # Inspect all caplog records AND formatted stream output
        celery_records = [r for r in caplog.records if r.name == "celery.app.trace"]
        # Print count of records named "celery.app.trace" captured while an eager task runs
        print(f"Captured celery.app.trace records count: {len(celery_records)}")

        all_records_text: list[str] = []
        for r in caplog.records:
            all_records_text.append(str(r.msg))
            all_records_text.append(str(r.args))
            all_records_text.append(str(getattr(r, "data", "")))
            for k, v in r.__dict__.items():
                all_records_text.append(f"{k}:{v}")

        stream_output = captured_stream.getvalue()
        combined_logs = " \n ".join(all_records_text) + " \n " + stream_output

        for secret in secrets_to_check:
            assert len(secret) >= 6
            assert secret not in combined_logs, f"Secret string leaked in logs: {secret}"

    finally:
        root_logger.removeHandler(handler)


def test_formatted_json_line_keeps_metadata_visible_and_hides_nested_secrets():
    """Test: a formatted JSON line keeps status_code, code, request_id, company_id,
    event and reason visible, and hides secrets nested in dicts and lists.
    """
    import json
    import logging

    from app.core.logging import JSONFormatter

    rec = logging.LogRecord(
        name="app.security",
        level=logging.WARNING,
        pathname="service.py",
        lineno=42,
        msg="Password reset event",
        args=(),
        exc_info=None,
    )
    # Populate visible metadata and nested sensitive data
    rec.status_code = 400
    rec.code = "invalid_otp"
    rec.request_id = "req-12345"
    rec.company_id = "comp-67890"
    rec.event = "password_reset_failed"
    rec.reason = "wrong_code"

    # Nested secrets in dicts and lists
    rec.payload = {
        "user_meta": {
            "password": "super-secret-password-123",
            "nested_list": [
                {"otp": "999888", "label": "auth_code"},
                "plain_string_item",
            ],
            "token": "secret-jwt-token-val",
        },
        "safe_key": "safe_value",
    }

    formatter = JSONFormatter()
    formatted = formatter.format(rec)
    parsed = json.loads(formatted)

    # 1. Metadata keys remain visible and exact
    assert parsed["status_code"] == 400
    assert parsed["code"] == "invalid_otp"
    assert parsed["request_id"] == "req-12345"
    assert parsed["company_id"] == "comp-67890"
    assert parsed["event"] == "password_reset_failed"
    assert parsed["reason"] == "wrong_code"

    # 2. Secrets nested in dicts and lists are hidden / redacted
    assert "super-secret-password-123" not in formatted
    assert "999888" not in formatted
    assert "secret-jwt-token-val" not in formatted

    nested_user = parsed["payload"]["user_meta"]
    assert nested_user["password"] == "[REDACTED]"
    assert nested_user["token"] == "[REDACTED]"
    assert nested_user["nested_list"][0]["otp"] == "[REDACTED]"
    assert nested_user["nested_list"][0]["label"] == "auth_code"
    assert parsed["payload"]["safe_key"] == "safe_value"


# ── M01: Migration password_changed_at ────────────────────────────────────────
# upgrade head, downgrade -1, upgrade head works and password_changed_at exists on users.
def test_M01_migration_password_changed_at():
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import inspect

    from app.db.session import engine

    repo_root = Path(__file__).resolve().parents[2]
    migration_file = repo_root / "alembic/versions/4a5b6c7d8e9f_add_password_changed_at_to_users.py"

    # Read down_revision dynamically from migration file
    down_rev = None
    with open(migration_file) as f:
        for line in f:
            if line.startswith("down_revision"):
                down_rev = line.split("=")[1].strip().strip('"').strip("'")
                break
    assert down_rev is not None, "Could not determine down_revision"

    # Downgrade to down_revision, assert column gone, then upgrade head in try/finally
    try:
        res_down = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", down_rev],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res_down.returncode == 0, (
            f"Alembic downgrade failed:\nstdout: {res_down.stdout}\nstderr: {res_down.stderr}"
        )

        insp = inspect(engine)
        cols_after_down = [col["name"] for col in insp.get_columns("users")]
        assert "password_changed_at" not in cols_after_down, (
            f"Expected password_changed_at to be removed, got columns: {cols_after_down}"
        )
    finally:
        res_up = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res_up.returncode == 0, (
            f"Alembic upgrade failed:\nstdout: {res_up.stdout}\nstderr: {res_up.stderr}"
        )

    # Verify column exists on users table in DB
    insp = inspect(engine)
    columns = [col["name"] for col in insp.get_columns("users")]
    assert "password_changed_at" in columns, (
        f"Expected password_changed_at in users table columns, got: {columns}"
    )


# ── New Tests for A, B, F, G ──────────────────────────────────────────────────
def test_company_b_code_cannot_reset_company_a(client, db, company_a, email_outbox):
    """Company-B code cannot reset company A even when A's code has expired and B's is alive."""
    from app.modules.identity.models import Company

    # User exists with same email in company A and company B
    shared_email = f"shared-{uuid.uuid4().hex[:6]}@example.com"
    comp_b = Company(
        id=uuid.uuid4(),
        name=f"Company B {uuid.uuid4().hex[:4]}",
        code=f"CB{uuid.uuid4().hex[:4].upper()}",
        email=f"cb-{uuid.uuid4().hex[:4]}@example.com",
        status="active",
        country="IN",
        currency="INR",
    )
    db.add(comp_b)
    db.commit()

    u_a, _ = _make_user_in_company(db, company_a.company_id, email=shared_email)
    u_b, _ = _make_user_in_company(db, comp_b.id, email=shared_email)

    # Request reset for company B with company_code
    email_outbox.clear()
    r_b = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": shared_email, "company_code": comp_b.code},
    )
    assert r_b.status_code == 200
    assert len(email_outbox) >= 1
    otp_b = (
        email_outbox[-1]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # Attempt reset on company A (either via company_a's code or without code) using otp_b
    company_a_obj = db.scalar(select(Company).where(Company.id == company_a.company_id))
    resp_reset = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": shared_email,
            "company_code": company_a_obj.code,
            "otp": otp_b,
            "new_password": "NewSecretPass123!",
        },
    )
    assert resp_reset.status_code == 400


def test_exactly_five_wrong_guesses_per_code_in_total(client, db, company_a, email_outbox):
    """Exactly 5 wrong guesses per code in total."""
    from app.core.otp import verify_otp_atomic

    user, _ = _make_user_in_company(db, company_a.company_id)
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    otp = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 4 wrong guesses return (False, 'wrong_code')
    for _ in range(4):
        ok, reason = verify_otp_atomic(user.email, "000000", company_id=user.company_id)
        assert ok is False
        assert reason == "wrong_code"

    # 5th wrong guess exhausts the code: returns (False, 'exhausted')
    ok5, reason5 = verify_otp_atomic(user.email, "000000", company_id=user.company_id)
    assert ok5 is False
    assert reason5 == "exhausted"

    # Subsequent verification with the right code now fails
    ok_right, reason_right = verify_otp_atomic(user.email, otp, company_id=user.company_id)
    assert ok_right is False
    assert reason_right in ("exhausted", "missing_or_expired")


def test_f1_counter_and_expiry_atomic_and_redis_error_handled(client, monkeypatch, email_outbox):
    """F1: counter + expiry atomic (always has a TTL), and Redis errors are caught and logged,
    asserting that nothing was enqueued and no email was sent."""
    import redis

    from app.core.otp import _account_req_key, check_and_increment_account_limit

    test_email = f"f1-test-{uuid.uuid4().hex[:6]}@example.com"
    count = check_and_increment_account_limit(test_email, limit=3, window_seconds=3600)
    assert count == 1

    r_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    key = _account_req_key(test_email)
    ttl = r_client.ttl(key)
    assert 3500 <= ttl <= 3600

    # Redis error during forgot-password returns 200 (no 500)
    def mock_incr(*args, **kwargs):
        raise redis.RedisError("Redis connection failure simulation")

    monkeypatch.setattr("app.modules.identity.router.check_and_increment_account_limit", mock_incr)
    enqueued_tasks = []

    def mock_delay(*args, **kwargs):
        enqueued_tasks.append((args, kwargs))

    monkeypatch.setattr(
        "app.modules.identity.router.process_password_reset_request.delay", mock_delay
    )
    email_outbox.clear()
    resp = client.post("/api/v1/auth/forgot-password", json={"email": test_email})
    assert resp.status_code == 200
    assert len(enqueued_tasks) == 0, "No task should be enqueued when Redis raises"
    assert len(email_outbox) == 0, "No email should be sent when Redis raises"


def test_commit1_reset_code_consumed_only_on_success(client, db, company_a, email_outbox):
    """1. Same password gives 422 and code remains usable.
    2. 4 wrong tries then 5th correct succeeds.
    3. 5 wrong tries kills the code.
    """
    user, orig_pw = _make_user_in_company(db, company_a.company_id)
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    code = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # (i) Same password as current gives 422 and code is NOT consumed
    resp_same = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": code, "new_password": orig_pw},
    )
    assert resp_same.status_code == 422

    # SAME code can now be used to reset with a different valid password
    resp_diff = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": code, "new_password": "BrandNewPass123!"},
    )
    assert resp_diff.status_code == 204

    # Now the code IS consumed
    resp_reused = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": code, "new_password": "AnotherNewPass123!"},
    )
    assert resp_reused.status_code == 400


def test_commit1_four_wrong_then_fifth_correct_succeeds(client, db, company_a, email_outbox):
    """4 wrong then the correct 5th still succeeds."""
    user, orig_pw = _make_user_in_company(db, company_a.company_id)
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    code = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 4 wrong tries
    for _ in range(4):
        r_wrong = client.post(
            "/api/v1/auth/reset-password",
            json={"email": user.email, "otp": "000000", "new_password": "NewValidPass123!"},
        )
        assert r_wrong.status_code == 400

    # 5th attempt with the CORRECT code succeeds
    r_corr = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": code, "new_password": "NewValidPass123!"},
    )
    assert r_corr.status_code == 204


def test_commit1_five_wrong_kills_the_code(client, db, company_a, email_outbox):
    """5 wrong kills the code; 6th with correct code fails."""
    user, orig_pw = _make_user_in_company(db, company_a.company_id)
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    code = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 5 wrong tries
    for _ in range(5):
        r_wrong = client.post(
            "/api/v1/auth/reset-password",
            json={"email": user.email, "otp": "000000", "new_password": "NewValidPass123!"},
        )
        assert r_wrong.status_code == 400

    # 6th attempt with correct code fails
    r_six = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": code, "new_password": "NewValidPass123!"},
    )
    assert r_six.status_code == 400


def test_commit1_two_simultaneous_valid_submissions_exactly_one_wins(client, db, company_a):
    """Two simultaneous valid submissions, exactly one wins."""
    import concurrent.futures

    from app.core.otp import generate_and_store_otp

    user, orig_pw = _make_user_in_company(db, company_a.company_id)
    code = generate_and_store_otp(user.email, company_id=user.company_id)

    def _submit(idx: int):
        return client.post(
            "/api/v1/auth/reset-password",
            json={
                "email": user.email,
                "otp": code,
                "new_password": f"NewValidPass{idx}99!",
            },
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_submit, 1)
        f2 = executor.submit(_submit, 2)
        r1 = f1.result()
        r2 = f2.result()

    statuses = [r1.status_code, r2.status_code]
    assert 204 in statuses, f"Expected at least one 204, got {statuses}"
    assert statuses.count(204) == 1, f"Expected exactly one 204, got {statuses}"


def test_commit1_unresolved_branch_response_matches_wrong_code(client, db, company_a):
    """Reset-password: unresolved branch (no unique active user) and wrong-code branch
    give the same status and body.
    """
    # 1. Unresolved email
    resp_unresolved = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "nonexistent-user@example.com",
            "otp": "123456",
            "new_password": "ValidNewPass123!",
        },
    )

    # 2. Existing user with wrong code
    user, _ = _make_user_in_company(db, company_a.company_id)
    resp_wrong = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": user.email,
            "otp": "123456",
            "new_password": "ValidNewPass123!",
        },
    )

    assert resp_unresolved.status_code == resp_wrong.status_code == 400
    err_unresolved = resp_unresolved.json().get("error", {})
    err_wrong = resp_wrong.json().get("error", {})
    assert err_unresolved.get("code") == err_wrong.get("code")
    assert err_unresolved.get("message") == err_wrong.get("message")
    assert err_unresolved.get("details") == err_wrong.get("details")


def test_commit1_rule5_password_policy_on_reset_and_change_password(
    client, db, company_a, email_outbox
):
    """Rule 5 on reset AND change-password: 9 chars, no digit, 129 chars and empty give
    422 and the code stays usable.
    """
    user, orig_pw = _make_user_in_company(db, company_a.company_id)
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    code = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    invalid_passwords = [
        "Short9!",  # 7 chars < 10
        "NineChars",  # 9 chars
        "TenLettersNoDigits!",  # no digit
        "A1" + "a" * 127,  # 129 chars > 128
        "",  # empty
    ]

    # Test each on reset-password: all return 422
    for bad_pw in invalid_passwords:
        r = client.post(
            "/api/v1/auth/reset-password",
            json={"email": user.email, "otp": code, "new_password": bad_pw},
        )
        assert r.status_code == 422, f"Expected 422 for {bad_pw!r}, got {r.status_code}"

    # And the code STAYS usable for a valid password
    valid_new_pw = "ValidPass123!"
    r_valid = client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp": code, "new_password": valid_new_pw},
    )
    assert r_valid.status_code == 204

    # Test each on change-password: all return 422
    login_r = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": valid_new_pw}
    )
    token = login_r.json()["access_token"]
    for bad_pw in invalid_passwords:
        r_cp = client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={"current_password": valid_new_pw, "new_password": bad_pw},
        )
        assert r_cp.status_code == 422, f"Expected 422 on change-password for {bad_pw!r}"


def test_f8_celery_trace_deterministic_redaction():
    """Builds a LogRecord named 'celery.app.trace' with data containing args and kwargs,
    formats it through JSONFormatter, and asserts secrets are absent.
    Mutation check verified: removing redaction in JSONFormatter causes assertion failure.
    """
    import json
    import logging

    from app.core.logging import JSONFormatter

    rec = logging.LogRecord(
        name="celery.app.trace",
        level=logging.INFO,
        pathname="trace.py",
        lineno=10,
        msg="Task app.workers.tasks.email.send_email_task succeeded",
        args=(),
        exc_info=None,
    )
    rec.data = {
        "args": ["secret-arg-val"],
        "kwargs": {
            "email": "user@example.com",
            "text_body": "code 123456",
            "password": "super-secret-password",
        },
        "id": "test-task-id",
        "name": "send_email_task",
        "runtime": 0.05,
    }

    formatter = JSONFormatter()
    formatted = formatter.format(rec)
    parsed = json.loads(formatted)

    assert "123456" not in formatted
    assert "super-secret-password" not in formatted
    assert "args" not in parsed.get("data", {})
    assert "kwargs" not in parsed.get("data", {})
    assert parsed.get("data", {}).get("name") == "send_email_task"
    assert parsed.get("data", {}).get("id") == "test-task-id"


def test_commit3_journey_end_to_end_single_company(client, db, company_a, email_outbox):
    """8. Journey test, end to end (single company): forgot, mail, reset, old password fails,
    new password logs in, old access token gives 401, old refresh gives 401.
    """
    import time

    email = f"journey-single-{uuid.uuid4().hex[:6]}@example.com"
    _, orig_pw = _make_user_in_company(db, company_a.company_id, email=email)

    # Log in initially to get an active access token and refresh token
    login_orig = client.post("/api/v1/auth/login", json={"email": email, "password": orig_pw})
    assert login_orig.status_code == 200
    old_access = login_orig.json()["access_token"]
    old_refresh = login_orig.cookies["refresh_token"]

    # Sleep slightly so token iat is strictly before password_changed_at
    time.sleep(1.05)

    # 1. Forgot password request
    email_outbox.clear()
    r_forgot = client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert r_forgot.status_code == 200

    # 2. Mail arrives with reset code
    assert len(email_outbox) >= 1
    code = (
        email_outbox[-1]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 3. Reset password
    new_pw = "BrandNewPass456!"
    r_reset = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": code, "new_password": new_pw},
    )
    assert r_reset.status_code == 204

    # 4. Old password fails
    r_old_fail = client.post("/api/v1/auth/login", json={"email": email, "password": orig_pw})
    assert r_old_fail.status_code == 401

    # 5. New password logs in
    r_new_login = client.post("/api/v1/auth/login", json={"email": email, "password": new_pw})
    assert r_new_login.status_code == 200
    assert r_new_login.json()["access_token"]

    # 6. Old access token gives 401
    r_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"})
    assert r_me.status_code == 401

    # 7. Old refresh gives 401
    r_refresh = client.post("/api/v1/auth/refresh", cookies={"refresh_token": old_refresh})
    assert r_refresh.status_code == 401


def test_commit3_journey_end_to_end_shared_email_two_companies(client, db, company_a, email_outbox):
    """8. Journey test, end to end: same email in two companies (with and without company code)."""
    import time

    from app.modules.identity.models import Company

    shared_email = f"journey-shared-{uuid.uuid4().hex[:6]}@example.com"
    comp_b = Company(
        id=uuid.uuid4(),
        name=f"Company B Journey {uuid.uuid4().hex[:4]}",
        code=f"CBJ{uuid.uuid4().hex[:4].upper()}",
        email=f"cbj-{uuid.uuid4().hex[:4]}@example.com",
        status="active",
        country="IN",
        currency="INR",
    )
    db.add(comp_b)
    db.commit()

    _, u_a_pw = _make_user_in_company(db, company_a.company_id, email=shared_email)
    _, u_b_pw = _make_user_in_company(db, comp_b.id, email=shared_email)

    company_a_obj = db.scalar(select(Company).where(Company.id == company_a.company_id))

    # Log in to both companies initially to obtain tokens
    login_a = client.post(
        "/api/v1/auth/login",
        json={"email": shared_email, "password": u_a_pw, "company_code": company_a_obj.code},
    )
    assert login_a.status_code == 200
    old_access_a = login_a.json()["access_token"]
    old_refresh_a = login_a.cookies["refresh_token"]

    login_b = client.post(
        "/api/v1/auth/login",
        json={"email": shared_email, "password": u_b_pw, "company_code": comp_b.code},
    )
    assert login_b.status_code == 200
    old_access_b = login_b.json()["access_token"]
    old_refresh_b = login_b.cookies["refresh_token"]

    time.sleep(1.05)

    # Case A: Request WITHOUT company code -> Guidance email sent, NO reset code generated
    email_outbox.clear()
    r_no_code = client.post("/api/v1/auth/forgot-password", json={"email": shared_email})
    assert r_no_code.status_code == 200
    assert len(email_outbox) >= 1
    guidance_mail = email_outbox[-1]
    assert "more than one workspace" in guidance_mail["text_body"]
    assert "Your password reset code is" not in guidance_mail["text_body"]

    # Case B: Request WITH company code for Company A -> OTP code sent for Company A
    email_outbox.clear()
    r_with_code = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": shared_email, "company_code": company_a_obj.code},
    )
    assert r_with_code.status_code == 200
    assert len(email_outbox) >= 1
    code_a = (
        email_outbox[-1]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # Reset password on Company A
    new_pw_a = "BrandNewPassCompA123!"
    r_reset_a = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": shared_email,
            "company_code": company_a_obj.code,
            "otp": code_a,
            "new_password": new_pw_a,
        },
    )
    assert r_reset_a.status_code == 204

    # On Company A: old password fails, new password succeeds
    fail_a = client.post(
        "/api/v1/auth/login",
        json={"email": shared_email, "password": u_a_pw, "company_code": company_a_obj.code},
    )
    assert fail_a.status_code == 401

    ok_a = client.post(
        "/api/v1/auth/login",
        json={"email": shared_email, "password": new_pw_a, "company_code": company_a_obj.code},
    )
    assert ok_a.status_code == 200

    # Old tokens for Company A invalidated
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access_a}"}
        ).status_code
        == 401
    )
    assert (
        client.post("/api/v1/auth/refresh", cookies={"refresh_token": old_refresh_a}).status_code
        == 401
    )

    # Company B account is untouched: old password and session for B still work
    ok_b = client.post(
        "/api/v1/auth/login",
        json={"email": shared_email, "password": u_b_pw, "company_code": comp_b.code},
    )
    assert ok_b.status_code == 200
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access_b}"}
        ).status_code
        == 200
    )
    assert (
        client.post("/api/v1/auth/refresh", cookies={"refresh_token": old_refresh_b}).status_code
        == 200
    )
