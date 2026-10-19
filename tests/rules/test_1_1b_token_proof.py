"""Tests for Rules 1.1b: Token proof tests.
Strictly tests only; no app or existing test files modified.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings
from app.core.security import hash_password
from app.modules.identity.models import User, UserRole


def _login(client, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _create_test_user(
    db, company_id: uuid.UUID, *, role: UserRole = UserRole.employee, is_active: bool = True
) -> tuple[User, str]:
    password = "CorrectPassword123!"
    user = User(
        company_id=company_id,
        email=f"tokenproof-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    return user, password


def test_T1_signature_tampered_token_returns_401(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id)
    resp = _login(client, user.email, password)
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    parts = token.split(".")
    assert len(parts) == 3
    sig = parts[2]
    # Alter the first char: the last base64url char has unused bits in a 32-byte HS256 signature
    tampered_char = "B" if sig[0] == "A" else "A"
    tampered_sig = tampered_char + sig[1:]
    tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_T2_different_secret_key_returns_401(client, db, company_a):
    user, _ = _create_test_user(db, company_a.company_id)
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "company_id": str(company_a.company_id),
        "role": user.role.value,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
    }
    forged_token = jwt.encode(
        payload,
        "completely_different_secret_key_for_testing_only_32_chars!",
        algorithm="HS256",
    )
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_T3_alg_none_token_returns_401(client, db, company_a):
    user, _ = _create_test_user(db, company_a.company_id)
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "company_id": str(company_a.company_id),
        "role": user.role.value,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
    }
    forged_token = jwt.encode(payload, key=None, algorithm="none")
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_T4_expired_access_token_returns_401(client, db, company_a):
    user, _ = _create_test_user(db, company_a.company_id)
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "company_id": str(company_a.company_id),
        "role": user.role.value,
        "type": "access",
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
    }
    expired_token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_T5_refresh_cookie_value_as_bearer_token_returns_401(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id)
    resp = _login(client, user.email, password)
    assert resp.status_code == 200
    refresh_token = resp.cookies.get("refresh_token")
    assert refresh_token

    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_T6_refresh_rotation_and_reuse_revocation(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id)
    login_resp = _login(client, user.email, password)
    assert login_resp.status_code == 200
    old_refresh = login_resp.cookies.get("refresh_token")
    assert old_refresh

    # 1. Refresh once -> 200 and a NEW refresh token
    client.cookies.set("refresh_token", old_refresh)
    refresh_resp = client.post("/api/v1/auth/refresh")
    assert refresh_resp.status_code == 200
    new_refresh = refresh_resp.cookies.get("refresh_token")
    assert new_refresh
    assert new_refresh != old_refresh

    # 2. Reuse of the OLD one -> 401
    client.cookies.set("refresh_token", old_refresh)
    reuse_resp = client.post("/api/v1/auth/refresh")
    assert reuse_resp.status_code == 401

    # 3. After that reuse, the NEW one also fails with 401
    client.cookies.set("refresh_token", new_refresh)
    after_reuse_resp = client.post("/api/v1/auth/refresh")
    assert after_reuse_resp.status_code == 401


def test_T7_refresh_after_logout_returns_401(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id)
    login_resp = _login(client, user.email, password)
    assert login_resp.status_code == 200
    access_token = login_resp.json()["access_token"]
    refresh_token = login_resp.cookies.get("refresh_token")
    assert refresh_token

    # Logout
    client.cookies.set("refresh_token", refresh_token)
    logout_resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_resp.status_code == 204

    # Refresh with that cookie -> 401
    client.cookies.set("refresh_token", refresh_token)
    refresh_resp = client.post("/api/v1/auth/refresh")
    assert refresh_resp.status_code == 401


def test_T8_token_expiry_settings():
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 15
    assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 7


def test_T9_role_change_affects_role_restricted_route(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id, role=UserRole.employee)
    login_resp = _login(client, user.email, password)
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    dept_payload = {"name": f"Dept-{uuid.uuid4().hex[:6]}"}

    # 1. As employee, POST /api/v1/departments returns 403
    res_emp = client.post("/api/v1/departments", headers=headers, json=dept_payload)
    assert res_emp.status_code == 403

    # 2. Change role in DB to hr_admin -> same old token now gets 201 (or 200)
    user.role = UserRole.hr_admin
    db.commit()

    dept_payload_2 = {"name": f"Dept-{uuid.uuid4().hex[:6]}"}
    res_hr = client.post("/api/v1/departments", headers=headers, json=dept_payload_2)
    assert res_hr.status_code == 201

    # 3. Change role back to employee -> same token gets 403 again
    user.role = UserRole.employee
    db.commit()

    dept_payload_3 = {"name": f"Dept-{uuid.uuid4().hex[:6]}"}
    res_back = client.post("/api/v1/departments", headers=headers, json=dept_payload_3)
    assert res_back.status_code == 403
