"""Tests for Rules 1.1: Login & tokens.
Strictly tests only; no app or existing test files modified.
"""

import uuid
from datetime import timedelta

import jwt
import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.config import Settings, settings
from app.core.security import create_access_token, hash_password, hash_token
from app.core.time import utcnow
from app.modules.identity.models import Company, CompanyStatus, RefreshToken, User, UserRole
from app.modules.identity.service import (
    INVALID_CREDENTIALS_MESSAGE,
)


def _login(client, email: str, password: str, company_code: str | None = None):
    payload = {"email": email, "password": password}
    if company_code is not None:
        payload["company_code"] = company_code
    return client.post("/api/v1/auth/login", json=payload)


def _create_test_user(
    db, company_id: uuid.UUID, *, role: UserRole = UserRole.employee, is_active: bool = True
) -> tuple[User, str]:
    password = "CorrectPassword123!"
    user = User(
        company_id=company_id,
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    return user, password


def test_P02_wrong_password_returns_invalid_credentials(client, db, company_a):
    user, _ = _create_test_user(db, company_a.company_id)
    resp = _login(client, user.email, "WrongPassword123!")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["message"] == INVALID_CREDENTIALS_MESSAGE


def test_P03_unknown_email_identical_to_P02(client, db, company_a):
    user, _ = _create_test_user(db, company_a.company_id)
    resp_p02 = _login(client, user.email, "WrongPassword123!")
    resp_unknown = _login(client, f"unknown-{uuid.uuid4().hex[:8]}@example.com", "SomePassword123!")

    assert resp_unknown.status_code == resp_p02.status_code
    # Request IDs are unique per request, compare code, message and details
    assert resp_unknown.json()["error"]["code"] == resp_p02.json()["error"]["code"]
    assert resp_unknown.json()["error"]["message"] == resp_p02.json()["error"]["message"]
    assert resp_unknown.json()["error"]["details"] == resp_p02.json()["error"]["details"]


@pytest.mark.xfail(strict=True, reason="P04 not met yet")
def test_P04_pending_company_admin_email_identical_to_P03(client, db):
    # Base reference response from unknown email (P03)
    resp_p03 = _login(client, f"unknown-{uuid.uuid4().hex[:8]}@example.com", "SomePassword123!")

    # Case (a): pending company with no admin_password_hash, no user row
    email_a = f"pending-nohash-{uuid.uuid4().hex[:8]}@example.com"
    comp_a = Company(
        name="Pending Corp A",
        code=f"PCA-{uuid.uuid4().hex[:4].upper()}",
        email=email_a,
        status=CompanyStatus.pending,
        admin_password_hash=None,
    )
    db.add(comp_a)
    db.commit()

    resp_a = _login(client, email_a, "AnyPassword123!")
    assert resp_a.status_code == resp_p03.status_code
    assert resp_a.json()["error"]["code"] == resp_p03.json()["error"]["code"]
    assert resp_a.json()["error"]["message"] == resp_p03.json()["error"]["message"]
    assert resp_a.json()["error"]["details"] == resp_p03.json()["error"]["details"]

    # Case (b): pending company with admin_password_hash, wrong password
    email_b = f"pending-hash-{uuid.uuid4().hex[:8]}@example.com"
    comp_b = Company(
        name="Pending Corp B",
        code=f"PCB-{uuid.uuid4().hex[:4].upper()}",
        email=email_b,
        status=CompanyStatus.pending,
        admin_password_hash=hash_password("Secret1234!"),
    )
    db.add(comp_b)
    db.commit()

    resp_b = _login(client, email_b, "WrongSecret1234!")
    assert resp_b.status_code == resp_p03.status_code
    assert resp_b.json()["error"]["code"] == resp_p03.json()["error"]["code"]
    assert resp_b.json()["error"]["message"] == resp_p03.json()["error"]["message"]
    assert resp_b.json()["error"]["details"] == resp_p03.json()["error"]["details"]


@pytest.mark.xfail(strict=True, reason="P05 not met yet")
def test_P05_rejected_company_wrong_password_identical_to_P03(client, db):
    resp_p03 = _login(client, f"unknown-{uuid.uuid4().hex[:8]}@example.com", "SomePassword123!")

    email_rej = f"rejected-{uuid.uuid4().hex[:8]}@example.com"
    comp_rej = Company(
        name="Rejected Corp",
        code=f"REJ-{uuid.uuid4().hex[:4].upper()}",
        email=email_rej,
        status=CompanyStatus.rejected,
        rejection_reason="Duplicate registration attempt",
        admin_password_hash=hash_password("Secret1234!"),
    )
    db.add(comp_rej)
    db.commit()

    resp = _login(client, email_rej, "WrongPassword123!")
    assert resp.status_code == resp_p03.status_code
    assert resp.json()["error"]["code"] == resp_p03.json()["error"]["code"]
    assert resp.json()["error"]["message"] == resp_p03.json()["error"]["message"]
    assert resp.json()["error"]["details"] == resp_p03.json()["error"]["details"]

    # Body must not leak company name or rejection reason
    body_text = resp.text
    assert "Rejected Corp" not in body_text
    assert "Duplicate registration attempt" not in body_text


def test_P06_max_login_attempts_locks_account(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id)

    # Fail MAX_LOGIN_ATTEMPTS times
    for _ in range(settings.MAX_LOGIN_ATTEMPTS):
        resp = _login(client, user.email, "WrongPassword123!")
        assert resp.status_code == 401

    # Now attempt with the CORRECT password while locked
    resp_locked = _login(client, user.email, password)
    assert resp_locked.status_code == 423
    assert resp_locked.json()["error"]["code"] == "account_locked"
    assert "locked until" in resp_locked.json()["error"]["message"].lower()


def test_P07_inactive_user_correct_password_refused(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id, is_active=False)

    resp = _login(client, user.email, password)
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "account_inactive"
    assert "access_token" not in body
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" not in set_cookie


def test_P08_access_token_claims_and_expiry(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id, role=UserRole.employee)
    resp = _login(client, user.email, password)
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "iat", "sub"]},
    )
    assert payload["sub"] == str(user.id)
    assert payload["company_id"] == str(company_a.company_id)
    assert payload["role"] == UserRole.employee.value
    assert payload["type"] == "access"
    assert payload["exp"] - payload["iat"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_P12_deactivated_user_unexpired_token_rejected_401(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id, is_active=True)

    login_resp = _login(client, user.email, password)
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify protected route works initially
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    # Deactivate user in DB
    user.is_active = False
    db.commit()

    # Call protected route with unexpired token -> 401
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_P13_cross_company_token_rejected_401(client, db, company_a, company_b):
    user, _ = _create_test_user(db, company_a.company_id)

    # Token built with sub=user A id, company_id=company B id, role=A's role
    tampered_token = create_access_token(
        sub=str(user.id),
        company_id=str(company_b.company_id),
        role=user.role.value,
    )
    headers = {"Authorization": f"Bearer {tampered_token}"}

    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_P16_expired_refresh_token_rejected_identical_to_unknown(client, db, company_a):
    # Reference response for unknown refresh token
    client.cookies.set("refresh_token", "unknown_refresh_token_value_not_in_db")
    resp_unknown = client.post("/api/v1/auth/refresh")
    assert resp_unknown.status_code == 401

    # Good login
    user, password = _create_test_user(db, company_a.company_id)
    login_resp = _login(client, user.email, password)
    assert login_resp.status_code == 200
    raw_refresh = login_resp.cookies.get("refresh_token")
    assert raw_refresh

    # Set that refresh token record's expires_at to the past
    token_record = (
        db.query(RefreshToken).filter(RefreshToken.token_hash == hash_token(raw_refresh)).first()
    )
    assert token_record is not None
    token_record.expires_at = utcnow() - timedelta(days=1)
    db.commit()

    client.cookies.set("refresh_token", raw_refresh)
    resp_expired = client.post("/api/v1/auth/refresh")
    assert resp_expired.status_code == resp_unknown.status_code
    assert resp_expired.json()["error"]["message"] == resp_unknown.json()["error"]["message"]
    assert resp_expired.json()["error"]["code"] == resp_unknown.json()["error"]["code"]


def test_P19_refresh_token_hash_stored_not_raw(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id)
    login_resp = _login(client, user.email, password)
    assert login_resp.status_code == 200
    raw_cookie = login_resp.cookies.get("refresh_token")
    assert raw_cookie

    # Ensure raw cookie is not stored anywhere in refresh_tokens table
    for row in db.query(RefreshToken).all():
        assert row.token_hash != raw_cookie
        assert row.device_info != raw_cookie

    # hash_token(cookie value) is stored
    expected_hash = hash_token(raw_cookie)
    matched = db.query(RefreshToken).filter(RefreshToken.token_hash == expected_hash).first()
    assert matched is not None


def test_P20_login_cookie_attributes(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id)
    resp = _login(client, user.email, password)
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie or "samesite=lax" in set_cookie.lower()
    assert "Path=/api/v1/auth" in set_cookie
    max_age_expected = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    assert f"Max-Age={max_age_expected}" in set_cookie


def test_S03_failed_attempts_reset_after_success(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id)

    # (MAX_LOGIN_ATTEMPTS - 1) wrong passwords
    for _ in range(settings.MAX_LOGIN_ATTEMPTS - 1):
        resp = _login(client, user.email, "WrongPass123!")
        assert resp.status_code == 401

    db.refresh(user)
    assert user.failed_attempts == settings.MAX_LOGIN_ATTEMPTS - 1

    # Correct password succeeds
    good_resp = _login(client, user.email, password)
    assert good_resp.status_code == 200

    db.refresh(user)
    assert user.failed_attempts == 0


def test_S05_same_email_multiple_companies_requires_company_code(client, db, company_a, company_b):
    shared_email = f"shared-{uuid.uuid4().hex[:8]}@example.com"
    shared_password = "SharedPassword123!"

    u_a = User(
        company_id=company_a.company_id,
        email=shared_email,
        hashed_password=hash_password(shared_password),
        role=UserRole.employee,
        is_active=True,
    )
    u_b = User(
        company_id=company_b.company_id,
        email=shared_email,
        hashed_password=hash_password(shared_password),
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([u_a, u_b])
    db.commit()

    # Login without company_code -> CompanyRequiredError (409)
    resp = _login(client, shared_email, shared_password)
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "company_required"
    assert "access_token" not in body
    assert len(body["error"]["details"]["companies"]) >= 2

    # Query company A's code
    comp_a = db.query(Company).filter(Company.id == company_a.company_id).first()
    assert comp_a is not None

    # Login WITH company_code succeeds
    resp_with_code = _login(client, shared_email, shared_password, company_code=comp_a.code)
    assert resp_with_code.status_code == 200
    assert "access_token" in resp_with_code.json()


def test_S06_role_change_in_db_reflected_immediately(client, db, company_a):
    user, password = _create_test_user(db, company_a.company_id, role=UserRole.employee)

    login_resp = _login(client, user.email, password)
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Initially employee
    me_resp_1 = client.get("/api/v1/auth/me", headers=headers)
    assert me_resp_1.status_code == 200
    assert me_resp_1.json()["role"] == UserRole.employee.value

    # Change user's role in DB
    user.role = UserRole.hr_admin
    db.commit()

    # With OLD token, GET /auth/me sees NEW role immediately
    me_resp_2 = client.get("/api/v1/auth/me", headers=headers)
    assert me_resp_2.status_code == 200
    assert me_resp_2.json()["role"] == UserRole.hr_admin.value


def test_S07_cookie_secure_in_non_development(client, monkeypatch, db, company_a):
    monkeypatch.setattr("app.modules.identity.router.settings.ENVIRONMENT", "staging")
    user, password = _create_test_user(db, company_a.company_id)
    resp = _login(client, user.email, password)
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "Secure" in set_cookie or "secure" in set_cookie.lower()


@pytest.mark.xfail(strict=True, reason="S08 not met yet")
def test_S08_secret_key_shorter_than_32_chars_raises_in_non_dev():
    with pytest.raises(PydanticValidationError):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="too-short",
            DATABASE_URL="postgresql://user:pass@localhost/db",
            ALEMBIC_DATABASE_URL="postgresql://user:pass@localhost/db",
        )
