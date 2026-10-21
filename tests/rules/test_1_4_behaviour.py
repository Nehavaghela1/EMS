"""Behaviour journeys for 1.4: Password reset & session management.
Strictly tests only; no app code modified. Red where code is missing.
"""

import uuid
from datetime import timedelta

import redis
from sqlalchemy import select

from app.core.config import settings
from app.core.otp import _otp_key
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.core.time import utcnow
from app.modules.hr.models import Employee, InvitationStatus
from app.modules.identity.models import User, UserRole


def _create_user(db, company_id: uuid.UUID, *, email: str, is_active: bool = True) -> str:
    pw = "InitialPass123!"
    user = User(
        company_id=company_id,
        email=email,
        hashed_password=hash_password(pw),
        role=UserRole.employee,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    return pw


# ── J01: Full journey ─────────────────────────────────────────────────────────
# A modern platform provides a seamless self-service recovery flow where the user
# requests a code, resets with the code from email, has their old password invalidated,
# receives a security notification, and is required to explicitly log in.
def test_J01_full_password_reset_journey(client, db, company_a, email_outbox):
    email = f"j01-{uuid.uuid4().hex[:8]}@example.com"
    old_pw = _create_user(db, company_a.company_id, email=email)

    # 1. Forgot password request
    email_outbox.clear()
    forgot_res = client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert forgot_res.status_code == 200

    # 2. Extract code from email
    assert len(email_outbox) == 1
    code = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 3. Reset password
    email_outbox.clear()
    new_pw = "NewSecurePass123!"
    reset_res = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": code, "new_password": new_pw},
    )
    assert reset_res.status_code == 204
    # The reset response did NOT log the user in (no tokens in body or cookie)
    assert not reset_res.content or reset_res.text == ""
    assert "access_token" not in reset_res.headers.get("set-cookie", "")

    # 4. Old password fails, new works
    fail_old = client.post("/api/v1/auth/login", json={"email": email, "password": old_pw})
    assert fail_old.status_code == 401

    login_new = client.post("/api/v1/auth/login", json={"email": email, "password": new_pw})
    assert login_new.status_code == 200

    # 5. Password-changed email arrives
    changed_emails = [e for e in email_outbox if e["to"] == email]
    assert len(changed_emails) == 1
    assert "password was changed" in changed_emails[0]["subject"].lower()


# ── J02: Multi-device session revocation ──────────────────────────────────────
# When a credential is changed, an enterprise identity provider terminates all existing
# sessions across all devices immediately to prevent unauthorized persistence.
def test_J02_multi_device_session_revocation(client, db, company_a, email_outbox):
    email = f"j02-{uuid.uuid4().hex[:8]}@example.com"
    old_pw = _create_user(db, company_a.company_id, email=email)

    # Device 1 login
    d1 = client.post("/api/v1/auth/login", json={"email": email, "password": old_pw})
    assert d1.status_code == 200
    token_d1 = d1.json()["access_token"]
    refresh_d1 = d1.cookies["refresh_token"]

    # Device 2 login
    d2 = client.post("/api/v1/auth/login", json={"email": email, "password": old_pw})
    assert d2.status_code == 200
    token_d2 = d2.json()["access_token"]
    refresh_d2 = d2.cookies["refresh_token"]

    # Ensure integer-second separation between initial token creation
    # and password reset (F5 1-second window)
    import time

    time.sleep(1.05)

    # Reset password
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    code = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    new_pw = "NewSecurePass123!"
    reset_res = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": code, "new_password": new_pw},
    )
    assert reset_res.status_code == 204

    # Both refresh tokens fail with 401
    assert (
        client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh_d1}).status_code
        == 401
    )
    assert (
        client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh_d2}).status_code
        == 401
    )

    # Both old access tokens fail with 401
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_d1}"}).status_code
        == 401
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_d2}"}).status_code
        == 401
    )


# ── J03: Latest code supersedes earlier codes ─────────────────────────────────
# Requesting a new verification code invalidates all previously issued codes, treating
# any older codes identically to an invalid code.
def test_J03_latest_code_supersedes_earlier(client, db, company_a, email_outbox):
    email = f"j03-{uuid.uuid4().hex[:8]}@example.com"
    _create_user(db, company_a.company_id, email=email)

    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    code1 = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    code2 = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )
    assert code1 != code2

    # Older code gets the SAME error status and body as an unknown code
    unknown_res = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": "999999", "new_password": "NewPassValid123!"},
    )
    old_res = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": code1, "new_password": "NewPassValid123!"},
    )
    assert old_res.status_code == unknown_res.status_code
    old_data = old_res.json().get("error", {})
    unknown_data = unknown_res.json().get("error", {})
    assert old_data.get("code") == unknown_data.get("code")
    assert old_data.get("message") == unknown_data.get("message")
    assert old_data.get("details") == unknown_data.get("details")

    # The newest code works
    succ = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": code2, "new_password": "NewPassValid123!"},
    )
    assert succ.status_code == 204


# ── J04: Uniform error response on all failure conditions ─────────────────────
# To avoid account enumeration and verification oracle leaks, all failed code validation
# attempts return an indistinguishable error response.
def test_J04_uniform_error_response_for_all_failed_codes(client, db, company_a, email_outbox):
    email = f"j04-{uuid.uuid4().hex[:8]}@example.com"
    _create_user(db, company_a.company_id, email=email)
    r_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    valid_code = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 1. Wrong code response
    wrong_res = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": "000000", "new_password": "ValidNewPass123!"},
    )
    wrong_err = wrong_res.json().get("error", {})

    # 2. Unknown email response
    unknown_res = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "nobody@example.com", "otp": valid_code, "new_password": "ValidNewPass123!"},
    )

    # 3. Used code response: consume code first
    succ = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": valid_code, "new_password": "ValidNewPass123!"},
    )
    assert succ.status_code == 204
    used_res = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": valid_code, "new_password": "ValidNewPass123!"},
    )

    # 4. Expired code response
    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    exp_code = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )
    # Manually expire the key in Redis
    r_client.delete(_otp_key(email, company_a.company_id))
    expired_res = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": exp_code, "new_password": "ValidNewPass123!"},
    )

    all_failures = [("unknown", unknown_res), ("used", used_res), ("expired", expired_res)]
    for label, res in all_failures:
        assert res.status_code == wrong_res.status_code, (
            f"{label} status {res.status_code} != {wrong_res.status_code}"
        )
        res_err = res.json().get("error", {})
        assert res_err.get("code") == wrong_err.get("code"), f"{label} error code differs"
        assert res_err.get("message") == wrong_err.get("message"), f"{label} error message differs"
        assert res_err.get("details") == wrong_err.get("details"), f"{label} error details differ"


# ── J05: Single use under concurrency / race condition ────────────────────────
# A verification code must be atomic and strictly single-use so race conditions cannot
# allow concurrent replay attacks.
def test_J05_single_use_sequential_replay(client, db, company_a, email_outbox):
    import concurrent.futures

    from app.core.otp import consume_otp_atomic, generate_and_store_otp, verify_otp_atomic

    email = f"j05-{uuid.uuid4().hex[:8]}@example.com"
    _create_user(db, company_a.company_id, email=email)

    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    code = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    # 1. API sequential replay: exactly one succeeds
    res1 = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": code, "new_password": "FirstNewPassword123!"},
    )
    res2 = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": code, "new_password": "SecondNewPassword123!"},
    )

    assert res1.status_code == 204
    assert res2.status_code in (400, 422)

    # 2. Concurrency test: 20 threads call verify_otp_atomic then consume_otp_atomic
    # on the same valid code; exactly one thread gets True from consume.
    conc_email = f"j05-conc-{uuid.uuid4().hex[:8]}@example.com"
    otp_code = generate_and_store_otp(conc_email, company_id=str(company_a.company_id))

    def _worker():
        valid, _ = verify_otp_atomic(conc_email, otp_code, company_id=str(company_a.company_id))
        if not valid:
            return False
        return consume_otp_atomic(conc_email, otp_code, company_id=str(company_a.company_id))

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(_worker) for _ in range(20)]
        results = [f.result() for f in futures]

    assert results.count(True) == 1, (
        f"Expected exactly 1 True, got {results.count(True)}: {results}"
    )
    assert results.count(False) == 19


# ── J06: Account and company status rules on reset ────────────────────────────
# A security reset clears lockouts for legitimate users upon identity proof, but inactive
# or suspended organization members remain denied access.
def test_J06_account_and_company_status_rules(client, db, company_a, email_outbox):
    # 1. Locked-out user resets and can log in at once
    email_locked = f"j06-lock-{uuid.uuid4().hex[:8]}@example.com"
    _create_user(db, company_a.company_id, email=email_locked)
    u_locked = db.scalar(select(User).where(User.email == email_locked))
    u_locked.failed_attempts = 5
    u_locked.locked_until = utcnow() + timedelta(minutes=15)
    db.commit()

    email_outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": email_locked})
    code_locked = (
        email_outbox[0]["text_body"].split("Your password reset code is ")[1].split(".")[0].strip()
    )

    new_pw_locked = "UnlockedPass123!"
    assert (
        client.post(
            "/api/v1/auth/reset-password",
            json={"email": email_locked, "otp": code_locked, "new_password": new_pw_locked},
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": email_locked, "password": new_pw_locked}
        ).status_code
        == 200
    )

    # 2. Deactivated user cannot log in even if reset is attempted
    email_deact = f"j06-deact-{uuid.uuid4().hex[:8]}@example.com"
    _create_user(db, company_a.company_id, email=email_deact, is_active=False)

    login_deact = client.post(
        "/api/v1/auth/login", json={"email": email_deact, "password": "InitialPass123!"}
    )
    assert login_deact.status_code in (401, 403)


# ── J07: Unactivated invites and deactivated users receive no email ────────────
# System resources and external emails are never dispatched to accounts that have never
# been activated or are marked deactivated.
def test_J07_invited_or_deactivated_users_no_email(client, db, company_a, email_outbox):
    # Invited-but-never-activated employee (Employee row exists, no User row)
    invited_email = f"j07-invited-{uuid.uuid4().hex[:8]}@example.com"
    emp = Employee(
        company_id=company_a.company_id,
        employee_code=f"EMP-{uuid.uuid4().hex[:6].upper()}",
        first_name="Invited",
        last_name="Emp",
        email=invited_email,
        invitation_status=InvitationStatus.sent,
        hire_date=utcnow().date(),
    )
    db.add(emp)

    # Deactivated user
    deact_email = f"j07-deact-{uuid.uuid4().hex[:8]}@example.com"
    _create_user(db, company_a.company_id, email=deact_email, is_active=False)
    db.commit()

    email_outbox.clear()
    r_inv = client.post("/api/v1/auth/forgot-password", json={"email": invited_email})
    assert r_inv.status_code == 200
    assert len(email_outbox) == 0

    r_deact = client.post("/api/v1/auth/forgot-password", json={"email": deact_email})
    assert r_deact.status_code == 200
    assert len(email_outbox) == 0


# ── J08: Failure in email infrastructure does not leak internal 500 ────────────
# When background communications fail, the public interface preserves a safe, uniform
# acknowledgment without leaking failure specifics or internal server errors.
def test_J08_email_failure_preserves_uniform_reply(client, db, company_a, monkeypatch):
    import app.modules.identity.service as id_svc

    email = f"j08-{uuid.uuid4().hex[:8]}@example.com"
    _create_user(db, company_a.company_id, email=email)

    def raise_email_error(*args, **kwargs):
        raise RuntimeError("Outbox unreachable")

    monkeypatch.setattr(id_svc.send_email_task, "delay", raise_email_error)

    resp = client.post("/api/v1/auth/forgot-password", json={"email": email})
    # Must not return 500
    assert resp.status_code == 200
    assert "If that email exists" in resp.json().get("message", "")


# ── J09: Rate-limited requester can finish with latest code ────────────────────
# Reaching a request throttling threshold must not lock the account or prevent the user
# from successfully completing recovery with the code already in hand.
def test_J09_rate_limited_requester_can_finish(client, db, company_a, email_outbox, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    # TestClient with client=("127.0.0.1", 50000) so X-Forwarded-For is trusted
    client = TestClient(fastapi_app, client=("127.0.0.1", 50000))

    user_email = f"j09-{uuid.uuid4().hex[:8]}@example.com"
    _create_user(db, company_a.company_id, email=user_email)

    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["127.0.0.1/32"])

    limiter.enabled = True
    try:
        limiter.reset()

        # Simulate user sending 3 requests and receiving codes
        latest_code = None
        for i in range(3):
            email_outbox.clear()
            r = client.post(
                "/api/v1/auth/forgot-password",
                json={"email": user_email},
                headers={"X-Forwarded-For": f"198.51.100.{20 + i}"},
            )
            assert r.status_code == 200
            if email_outbox:
                latest_code = (
                    email_outbox[-1]["text_body"]
                    .split("Your password reset code is ")[1]
                    .split(".")[0]
                    .strip()
                )

        assert latest_code is not None

        # 4th request: per-account limit is exhausted; receives same reply, no new code
        email_outbox.clear()
        r4 = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": user_email},
            headers={"X-Forwarded-For": "198.51.100.25"},
        )
        assert r4.status_code == 200
        assert len(email_outbox) == 0

        # With per-account limit exhausted, complete reset with the latest code already received
        new_pw = "FinishedPass123!"
        reset_res = client.post(
            "/api/v1/auth/reset-password",
            json={"email": user_email, "otp": latest_code, "new_password": new_pw},
        )
        assert reset_res.status_code == 204

        # Sign in succeeds
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": user_email, "password": new_pw}
            ).status_code
            == 200
        )
    finally:
        limiter.enabled = False
        limiter.reset()


# ── J10: Changing password invalidates active sessions requiring re-login ──────
# Proactively changing an account password terminates existing sessions and tokens,
# guaranteeing that any compromised device must re-authenticate.
def test_J10_change_password_invalidates_sessions(client, db, company_a):
    email = f"j10-{uuid.uuid4().hex[:8]}@example.com"
    pw = _create_user(db, company_a.company_id, email=email)

    login_res = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    token = login_res.json()["access_token"]
    refresh = login_res.cookies["refresh_token"]

    # Ensure integer-second separation between initial token creation
    # and password change (F5 1-second window)
    import time

    time.sleep(1.05)

    new_pw = "ChangedPassword123!"
    change_res = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": pw, "new_password": new_pw},
    )
    assert change_res.status_code == 204

    # Refresh token fails with 401
    assert (
        client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh}).status_code == 401
    )

    # Old access token fails with 401
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )
