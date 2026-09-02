"""WP-03: routes 1-11 in full (Spec 15.3's non-negotiable auth checklist).
Routes 1-2 (login, refresh) were WP-01's; this file adds the missing
coverage for them alongside every route this package actually delivers.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings


def _register(client, name: str, email: str) -> dict:
    resp = client.post(
        "/api/v1/companies/register", json={"company_name": name, "company_email": email}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _approve(client, super_admin_headers, company_id: str) -> dict:
    resp = client.post(f"/api/v1/companies/{company_id}/approve", headers=super_admin_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _login(client, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _extract_temporary_password(email_outbox: list[dict], to_email: str) -> str:
    """The HR admin credentials email replaced the old
    CompanyApproveResponse.temporary_password field (Spec 13, WP-26) — this
    reconstructs a `temporary_password` for the many tests below that just
    need a valid password to log in with, not the delivery mechanism
    itself."""
    matches = [
        e for e in email_outbox if e["to"] == to_email and "Temporary password" in e["text_body"]
    ]
    assert matches, f"no HR admin credentials email found for {to_email}"
    match = re.search(r"Temporary password: (\S+)", matches[-1]["text_body"])
    assert match, matches[-1]["text_body"]
    return match.group(1)


def _extract_activation_token(email_outbox: list[dict], to_email: str) -> str:
    matches = [e for e in email_outbox if e["to"] == to_email and "/activate/" in e["text_body"]]
    assert matches, f"no activation email found for {to_email}"
    match = re.search(r"/activate/(\S+)", matches[-1]["text_body"])
    assert match, matches[-1]["text_body"]
    return match.group(1)


def _register_and_approve(
    client, super_admin_headers, name: str, email: str, email_outbox: list[dict]
) -> dict:
    company = _register(client, name, email)
    approve = _approve(client, super_admin_headers, company["id"])
    # Reassembled from the captured email so every test below that reads
    # approve["temporary_password"] keeps working unchanged — the API
    # response itself no longer carries it (CLAUDE.md rule 10).
    approve["temporary_password"] = _extract_temporary_password(
        email_outbox, approve["hr_admin_email"]
    )
    return approve


def _make_jwt(*, company_id, role: str, token_type: str, exp_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "company_id": str(company_id),
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + exp_delta,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# --- Routes 1-2: login, refresh (already built in WP-01; new coverage) ----


def test_login_returns_access_token_and_httponly_refresh_cookie(
    client, super_admin_headers, email_outbox
):
    approve = _register_and_approve(
        client, super_admin_headers, "Auth Co", "admin@authco.com", email_outbox
    )
    resp = _login(client, approve["hr_admin_email"], approve["temporary_password"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie


def test_protected_route_with_valid_token_returns_200(client, company_a):
    resp = client.get("/api/v1/auth/me", headers=company_a.hr_headers)
    assert resp.status_code == 200


def test_protected_route_with_invalid_token_returns_401(client):
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_protected_route_with_no_token_returns_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_protected_route_with_expired_token_returns_401(client, company_a):
    token = _make_jwt(
        company_id=company_a.company_id,
        role="hr_admin",
        token_type="access",
        exp_delta=timedelta(minutes=-15),
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_refresh_token_used_as_access_token_returns_401(client, company_a):
    """Spec 9.2: `type != "access"` must be rejected — the algorithm-
    confusion-adjacent check that a refresh-shaped JWT can never be used
    as a bearer token."""
    token = _make_jwt(
        company_id=company_a.company_id,
        role="hr_admin",
        token_type="refresh",
        exp_delta=timedelta(minutes=15),
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_a_token_signed_with_the_wrong_secret_is_rejected(client, company_a):
    """Attack: forge a super_admin token without knowing SECRET_KEY.
    is_platform_admin is derived entirely from the verified `role` claim
    (app/core/dependencies.py) — nothing a client sends can set it directly,
    so the only lever is smuggling `role: "super_admin"` into a token that
    still verifies. It doesn't, because the signature doesn't match."""
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "company_id": str(company_a.company_id),
            "role": "super_admin",
            "type": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=15),
            "jti": str(uuid.uuid4()),
        },
        "an-attacker-controlled-secret-not-settings.SECRET_KEY",
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


def test_an_unsigned_none_algorithm_token_is_rejected(client, company_a):
    """Attack: the classic JWT `alg: none` bypass. decode_access_token pins
    `algorithms=[settings.JWT_ALGORITHM]` explicitly rather than trusting
    the token's own header (9.2), so this must fail even though PyJWT can
    technically encode it."""
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "company_id": str(company_a.company_id),
            "role": "super_admin",
            "type": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=15),
            "jti": str(uuid.uuid4()),
        },
        key=None,
        algorithm="none",
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


def test_refresh_rotates_and_reuse_of_old_token_revokes_the_family(
    client, super_admin_headers, email_outbox
):
    approve = _register_and_approve(
        client, super_admin_headers, "Rotate Co", "admin@rotateco.com", email_outbox
    )
    login_resp = _login(client, approve["hr_admin_email"], approve["temporary_password"])
    old_refresh = login_resp.cookies["refresh_token"]

    refresh_resp = client.post("/api/v1/auth/refresh", cookies={"refresh_token": old_refresh})
    assert refresh_resp.status_code == 200
    new_refresh = refresh_resp.cookies["refresh_token"]
    assert new_refresh != old_refresh

    # Reuse of the now-rotated old token: rejected, and revokes the family.
    replay_resp = client.post("/api/v1/auth/refresh", cookies={"refresh_token": old_refresh})
    assert replay_resp.status_code == 401

    # The legitimately-issued new token is also dead now — proves the whole
    # family was revoked, not just the replayed token.
    second_use_resp = client.post("/api/v1/auth/refresh", cookies={"refresh_token": new_refresh})
    assert second_use_resp.status_code == 401

    # Hardening pass: reuse detection used to revoke the family silently —
    # a real theft signal with no forensic trail. It must now write an
    # audit row (the stale "once the table exists" TODO predated WP-11,
    # which built the table this session never came back to wire it into).
    fresh_login = _login(client, approve["hr_admin_email"], approve["temporary_password"])
    fresh_token = fresh_login.json()["access_token"]
    audit_resp = client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {fresh_token}"},
        params={"action": "REFRESH_TOKEN_REUSE_DETECTED"},
    )
    assert audit_resp.status_code == 200
    # Two rows, not one: the replay of old_refresh revokes the whole family
    # (including new_refresh), so the next call — presenting new_refresh,
    # itself now revoked too — is its own independent reuse event.
    assert audit_resp.json()["total"] == 2


def test_five_bad_passwords_lock_the_account_and_the_sixth_returns_423(
    client, super_admin_headers, email_outbox
):
    approve = _register_and_approve(
        client, super_admin_headers, "Lockout Co", "admin@lockoutco.com", email_outbox
    )
    email = approve["hr_admin_email"]
    correct = approve["temporary_password"]

    for _ in range(settings.MAX_LOGIN_ATTEMPTS):
        assert _login(client, email, "definitely-wrong").status_code == 401

    # Locked now — even the CORRECT password is rejected, and with 423, not 401.
    locked_resp = _login(client, email, correct)
    assert locked_resp.status_code == 423


def test_require_role_admits_the_right_role_and_rejects_the_wrong_one(client, company_a):
    hr_resp = client.post(
        "/api/v1/departments", headers=company_a.hr_headers, json={"name": "Role Check"}
    )
    assert hr_resp.status_code == 201

    employee_resp = client.post(
        "/api/v1/departments", headers=company_a.employee_headers, json={"name": "Should Fail"}
    )
    assert employee_resp.status_code == 403


# --- Route 3-4: logout, logout-all -----------------------------------------


def test_logout_revokes_the_presented_refresh_token(client, super_admin_headers, email_outbox):
    approve = _register_and_approve(
        client, super_admin_headers, "Logout Co", "admin@logoutco.com", email_outbox
    )
    login_resp = _login(client, approve["hr_admin_email"], approve["temporary_password"])
    access_token = login_resp.json()["access_token"]
    refresh_token = login_resp.cookies["refresh_token"]

    logout_resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        cookies={"refresh_token": refresh_token},
    )
    assert logout_resp.status_code == 204

    replay_resp = client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh_token})
    assert replay_resp.status_code == 401


def test_logout_all_revokes_every_refresh_token_for_the_user(
    client, super_admin_headers, email_outbox
):
    approve = _register_and_approve(
        client, super_admin_headers, "LogoutAll Co", "admin@logoutallco.com", email_outbox
    )
    email, password = approve["hr_admin_email"], approve["temporary_password"]
    session_a = _login(client, email, password)
    session_b = _login(client, email, password)

    logout_all_resp = client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {session_a.json()['access_token']}"},
    )
    assert logout_all_resp.status_code == 204

    for session in (session_a, session_b):
        resp = client.post(
            "/api/v1/auth/refresh", cookies={"refresh_token": session.cookies["refresh_token"]}
        )
        assert resp.status_code == 401


# --- Route 5: me -------------------------------------------------------


def test_get_me_returns_current_user_and_role_permissions(client, company_a):
    resp = client.get("/api/v1/auth/me", headers=company_a.hr_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "hr_admin"
    assert "manage_employees" in body["permissions"]
    assert body["employee"] is None  # this fixture's users have no linked Employee row


# --- Route 6: change-password -------------------------------------------


def test_change_password_revokes_other_sessions_and_updates_the_password(
    client, super_admin_headers, email_outbox
):
    approve = _register_and_approve(
        client, super_admin_headers, "ChangePw Co", "admin@changepwco.com", email_outbox
    )
    email, old_password = approve["hr_admin_email"], approve["temporary_password"]
    login_resp = _login(client, email, old_password)
    access_token = login_resp.json()["access_token"]
    old_refresh = login_resp.cookies["refresh_token"]

    change_resp = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"current_password": old_password, "new_password": "BrandNewPass123"},
    )
    assert change_resp.status_code == 204

    assert (
        client.post("/api/v1/auth/refresh", cookies={"refresh_token": old_refresh}).status_code
        == 401
    )
    assert _login(client, email, "BrandNewPass123").status_code == 200
    assert _login(client, email, old_password).status_code == 401

    # A confirmation email went out (Part 1) — the body never repeats the
    # new password (CLAUDE.md rule 10), only confirms the change happened.
    confirmations = [e for e in email_outbox if e["to"] == email and "was changed" in e["subject"]]
    assert confirmations
    assert "BrandNewPass123" not in confirmations[-1]["text_body"]
    assert "BrandNewPass123" not in confirmations[-1]["html_body"]


def test_change_password_rejects_a_wrong_current_password(
    client, super_admin_headers, email_outbox
):
    approve = _register_and_approve(
        client, super_admin_headers, "WrongCurrent Co", "admin@wrongcurrentco.com", email_outbox
    )
    login_resp = _login(client, approve["hr_admin_email"], approve["temporary_password"])
    resp = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {login_resp.json()['access_token']}"},
        json={"current_password": "not-the-real-one", "new_password": "BrandNewPass123"},
    )
    assert resp.status_code == 401


# --- Routes 7-8: forgot-password, reset-password (Redis OTP, 7.9) ---------


def _extract_otp(body: str) -> str:
    match = re.search(r"\b(\d{6})\b", body)
    assert match, f"no 6-digit OTP found in: {body}"
    return match.group(1)


def test_forgot_password_for_a_nonexistent_email_returns_200_with_the_same_body(
    client, super_admin_headers, email_outbox
):
    approve = _register_and_approve(
        client, super_admin_headers, "Forgot Co", "admin@forgotco.com", email_outbox
    )

    real_resp = client.post(
        "/api/v1/auth/forgot-password", json={"email": approve["hr_admin_email"]}
    )
    fake_resp = client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody-here@forgotco.com"}
    )

    assert real_resp.status_code == fake_resp.status_code == 200
    assert real_resp.json() == fake_resp.json()


def test_reset_password_with_the_correct_otp_succeeds_and_revokes_sessions(
    client, super_admin_headers, email_outbox
):
    approve = _register_and_approve(
        client, super_admin_headers, "Reset Co", "admin@resetco.com", email_outbox
    )
    email = approve["hr_admin_email"]
    old_login = _login(client, email, approve["temporary_password"])
    old_refresh = old_login.cookies["refresh_token"]

    client.post("/api/v1/auth/forgot-password", json={"email": email})
    otp_emails = [e for e in email_outbox if e["to"] == email and "reset code" in e["subject"]]
    otp = _extract_otp(otp_emails[-1]["text_body"])

    reset_resp = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": otp, "new_password": "ResetPass123"},
    )
    assert reset_resp.status_code == 204

    assert (
        client.post("/api/v1/auth/refresh", cookies={"refresh_token": old_refresh}).status_code
        == 401
    )
    assert _login(client, email, "ResetPass123").status_code == 200

    confirmations = [e for e in email_outbox if e["to"] == email and "was changed" in e["subject"]]
    assert confirmations


def test_otp_is_rejected_after_five_wrong_attempts_even_on_the_sixth_correct_one(
    client, super_admin_headers, email_outbox
):
    approve = _register_and_approve(
        client, super_admin_headers, "OtpCap Co", "admin@otpcapco.com", email_outbox
    )
    email = approve["hr_admin_email"]

    client.post("/api/v1/auth/forgot-password", json={"email": email})
    otp_emails = [e for e in email_outbox if e["to"] == email and "reset code" in e["subject"]]
    otp = _extract_otp(otp_emails[-1]["text_body"])
    wrong = "000000" if otp != "000000" else "111111"

    for _ in range(settings.OTP_MAX_ATTEMPTS):
        resp = client.post(
            "/api/v1/auth/reset-password",
            json={"email": email, "otp": wrong, "new_password": "WhateverPass123"},
        )
        assert resp.status_code == 400

    # The 6th call uses the CORRECT code, but the attempt cap is already spent.
    final_resp = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": otp, "new_password": "WhateverPass123"},
    )
    assert final_resp.status_code == 400


def test_otp_expires_after_its_ttl(client, super_admin_headers, email_outbox):
    """Spec 7.9: a 10-minute TTL. Simulated by deleting the exact Redis key
    app.core.otp stores it under — proving the same "key is gone" code path
    a real TTL expiry produces, without a 10-minute sleep in the suite."""
    import app.core.otp as otp_module

    approve = _register_and_approve(
        client, super_admin_headers, "OtpTtl Co", "admin@otpttlco.com", email_outbox
    )
    email = approve["hr_admin_email"]

    client.post("/api/v1/auth/forgot-password", json={"email": email})
    otp_emails = [e for e in email_outbox if e["to"] == email and "reset code" in e["subject"]]
    otp = _extract_otp(otp_emails[-1]["text_body"])

    otp_module._redis_client.delete(otp_module._otp_key(email))

    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": otp, "new_password": "WhateverPass123"},
    )
    assert resp.status_code == 400


def test_resetting_a_locked_accounts_password_clears_the_lockout(
    client, super_admin_headers, email_outbox
):
    """Part 3: an OTP-verified reset is a stronger proof of identity than
    the password just being replaced — a locked-out user who successfully
    resets should be able to log in immediately, not wait out the
    15-minute timer on an account they've already proven is theirs."""
    approve = _register_and_approve(
        client, super_admin_headers, "LockReset Co", "admin@lockresetco.com", email_outbox
    )
    email = approve["hr_admin_email"]

    for _ in range(settings.MAX_LOGIN_ATTEMPTS):
        assert _login(client, email, "definitely-wrong").status_code == 401
    assert _login(client, email, approve["temporary_password"]).status_code == 423

    client.post("/api/v1/auth/forgot-password", json={"email": email})
    otp_emails = [e for e in email_outbox if e["to"] == email and "reset code" in e["subject"]]
    otp = _extract_otp(otp_emails[-1]["text_body"])

    reset_resp = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": otp, "new_password": "FreshStart123"},
    )
    assert reset_resp.status_code == 204

    assert _login(client, email, "FreshStart123").status_code == 200


# --- Route 9: check-username -----------------------------------------------


def test_check_username_reports_availability(client):
    fresh = f"brand-new-{uuid.uuid4().hex[:10]}"
    resp = client.get(f"/api/v1/auth/check-username/{fresh}")
    assert resp.status_code == 200
    assert resp.json()["available"] is True


# --- Routes 10-11: activation — closes WP-07's open gate condition --------


def test_employee_created_by_hr_can_activate_and_log_in(client, super_admin_headers, email_outbox):
    approve = _register_and_approve(
        client, super_admin_headers, "Activate Co", "admin@activateco.com", email_outbox
    )
    hr_login = _login(client, approve["hr_admin_email"], approve["temporary_password"])
    hr_headers = {"Authorization": f"Bearer {hr_login.json()['access_token']}"}

    created = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={"first_name": "Nia", "email": "nia@activateco.com", "hire_date": "2024-01-01"},
    )
    assert created.status_code == 201
    assert created.json()["invite"]["sent_to"] == "nia@activateco.com"
    activation_token = _extract_activation_token(email_outbox, "nia@activateco.com")

    preview_resp = client.get(f"/api/v1/auth/activate/{activation_token}")
    assert preview_resp.status_code == 200
    preview = preview_resp.json()
    assert preview["first_name"] == "Nia"
    assert preview["company_name"] == "Activate Co"

    activate_resp = client.post(
        "/api/v1/auth/activate",
        json={"token": activation_token, "username": "nia123", "password": "NiaPass1234"},
    )
    assert activate_resp.status_code == 200
    assert activate_resp.json()["access_token"]

    # The token is consumed — cannot be redeemed twice.
    replay_resp = client.post(
        "/api/v1/auth/activate",
        json={"token": activation_token, "username": "nia456", "password": "NiaPass1234"},
    )
    assert replay_resp.status_code == 404

    # The employee's real credentials (their email + chosen password) work now.
    login_resp = client.post(
        "/api/v1/auth/login", json={"email": "nia@activateco.com", "password": "NiaPass1234"}
    )
    assert login_resp.status_code == 200


def test_activation_preview_rejects_an_unknown_token(client):
    assert client.get("/api/v1/auth/activate/not-a-real-token").status_code == 404


def test_activation_rejects_an_already_taken_username(client, super_admin_headers, email_outbox):
    approve = _register_and_approve(
        client, super_admin_headers, "DupUser Co", "admin@dupuserco.com", email_outbox
    )
    hr_login = _login(client, approve["hr_admin_email"], approve["temporary_password"])
    hr_headers = {"Authorization": f"Bearer {hr_login.json()['access_token']}"}

    client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={"first_name": "One", "email": "one@dupuserco.com", "hire_date": "2024-01-01"},
    )
    client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={"first_name": "Two", "email": "two@dupuserco.com", "hire_date": "2024-01-01"},
    )
    first_token = _extract_activation_token(email_outbox, "one@dupuserco.com")
    second_token = _extract_activation_token(email_outbox, "two@dupuserco.com")

    ok_resp = client.post(
        "/api/v1/auth/activate",
        json={"token": first_token, "username": "shared-name", "password": "SharedPass123"},
    )
    assert ok_resp.status_code == 200

    conflict_resp = client.post(
        "/api/v1/auth/activate",
        json={"token": second_token, "username": "shared-name", "password": "SharedPass123"},
    )
    assert conflict_resp.status_code == 409


# --- Rehash-on-login wiring (Spec 9.1) --------------------------------------


def test_rehash_on_login_upgrades_a_stale_hash(
    client, super_admin_headers, monkeypatch, db, email_outbox
):
    from app.modules.identity.models import User

    approve = _register_and_approve(
        client, super_admin_headers, "Rehash Co", "admin@rehashco.com", email_outbox
    )
    email, password = approve["hr_admin_email"], approve["temporary_password"]

    old_user = db.query(User).filter(User.email == email).one()
    old_hash = old_user.hashed_password

    monkeypatch.setattr("app.modules.identity.service.needs_rehash", lambda hashed: True)
    assert _login(client, email, password).status_code == 200

    db.expire_all()
    refreshed = db.query(User).filter(User.email == email).one()
    assert refreshed.hashed_password != old_hash
    # The new password still verifies against the rehashed value.
    from app.core.security import verify_password

    assert verify_password(password, refreshed.hashed_password)
