"""Tests for Rules 1.1c: Auth audit events and logging.
Strictly tests only; no app code modified. Red where code is missing.
"""

import logging
import uuid

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.modules.identity.models import User, UserRole
from app.modules.platform.models import AuditLog


def _make_test_user(
    db, company_id: uuid.UUID, *, role: UserRole = UserRole.employee, is_active: bool = True
) -> tuple[User, str]:
    pw = "CorrectPassword123!"
    user = User(
        company_id=company_id,
        email=f"auth-audit-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password(pw),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    return user, pw


# ── C01: Successful login writes one LOGIN_SUCCEEDED row ──────────────────────
def test_C01_successful_login_writes_login_succeeded_audit(client, db, company_a):
    user, pw = _make_test_user(db, company_a.company_id)

    resp = client.post("/api/v1/auth/login", json={"email": user.email, "password": pw})
    assert resp.status_code == 200

    logs = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action == "LOGIN_SUCCEEDED",
        )
    ).all()
    assert len(logs) == 1
    log = logs[0]
    assert log.actor_user_id == user.id
    assert log.actor_email.lower() == user.email.lower()
    assert log.company_id == company_a.company_id

    # Check details: no password, hash, or token
    details_str = str(log.details or {})
    assert pw not in details_str
    assert user.hashed_password not in details_str
    assert resp.json()["access_token"] not in details_str
    assert resp.cookies["refresh_token"] not in details_str


# ── C02: Wrong password writes NO audit row but emits one structured warning log
def test_C02_wrong_password_no_audit_row_emits_warning_log(client, db, company_a, caplog):
    user, _ = _make_test_user(db, company_a.company_id)
    wrong_pw = "WrongSecretPass123!"

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": wrong_pw},
        )
    assert resp.status_code == 401

    # NO audit row written for failed password attempt
    logs = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action.in_(["LOGIN_FAILED", "LOGIN_SUCCEEDED"]),
        )
    ).all()
    assert len(logs) == 0

    # Structured warning log emitted with reason code, containing neither password nor email
    warning_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and (
            "login" in r.getMessage().lower()
            or (hasattr(r, "reason") and "credential" in str(r.reason).lower())
        )
    ]
    assert len(warning_records) >= 1

    for rec in warning_records:
        msg = rec.getMessage()
        assert wrong_pw not in msg
        assert user.email not in msg


# ── C03: Attempt reaching lockout limit writes exactly one ACCOUNT_LOCKED row ──
def test_C03_lockout_limit_writes_account_locked_audit(client, db, company_a):
    user, _ = _make_test_user(db, company_a.company_id)

    # Attempts 1 to MAX_LOGIN_ATTEMPTS - 1
    for _ in range(settings.MAX_LOGIN_ATTEMPTS - 1):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "WrongPassword123!"},
        )
        assert resp.status_code == 401

    # Before the locking attempt, no ACCOUNT_LOCKED log
    locked_logs = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action == "ACCOUNT_LOCKED",
        )
    ).all()
    assert len(locked_logs) == 0

    # The attempt that reaches the lockout limit
    resp_lock = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "WrongPassword123!"},
    )
    assert resp_lock.status_code == 401

    # Exactly one ACCOUNT_LOCKED audit row
    locked_logs = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action == "ACCOUNT_LOCKED",
        )
    ).all()
    assert len(locked_logs) == 1
    log = locked_logs[0]
    assert log.actor_user_id == user.id

    # Later attempts write NONE
    resp_subsequent = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "WrongPassword123!"},
    )
    assert resp_subsequent.status_code == 401

    locked_logs_after = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action == "ACCOUNT_LOCKED",
        )
    ).all()
    assert len(locked_logs_after) == 1


# ── C04: Logout writes LOGOUT; logout_all writes LOGOUT_ALL ────────────────────
def test_C04_logout_and_logout_all_audit_rows(client, db, company_a):
    user, pw = _make_test_user(db, company_a.company_id)

    # 1. Login and call /logout
    login_1 = client.post("/api/v1/auth/login", json={"email": user.email, "password": pw})
    assert login_1.status_code == 200
    token_1 = login_1.json()["access_token"]
    refresh_1 = login_1.cookies["refresh_token"]

    resp_lo = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token_1}"},
        cookies={"refresh_token": refresh_1},
    )
    assert resp_lo.status_code == 204

    logout_logs = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action == "LOGOUT",
        )
    ).all()
    assert len(logout_logs) == 1
    assert logout_logs[0].actor_user_id == user.id

    # 2. Login and call /logout-all
    login_2 = client.post("/api/v1/auth/login", json={"email": user.email, "password": pw})
    assert login_2.status_code == 200
    token_2 = login_2.json()["access_token"]

    resp_lo_all = client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {token_2}"},
    )
    assert resp_lo_all.status_code == 204

    logout_all_logs = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action == "LOGOUT_ALL",
        )
    ).all()
    assert len(logout_all_logs) == 1
    assert logout_all_logs[0].actor_user_id == user.id


# ── C05: Login with malformed body gives 422, never 500 ────────────────────────
def test_C05_login_malformed_body_gives_422(client):
    malformed_bodies = [
        {},  # missing fields
        {"email": "valid@example.com"},  # missing password
        {"password": "ValidPassword123!"},  # missing email
        {"email": "", "password": "ValidPassword123!"},  # empty email
        {"email": "valid@example.com", "password": ""},  # empty password
        {"email": 123, "password": "ValidPassword123!"},  # non-text email number
        {"email": ["a"], "password": "ValidPassword123!"},  # non-text email list
        {"email": {}, "password": "ValidPassword123!"},  # non-text email dict
        {"email": "valid@example.com", "password": 123},  # non-text password number
        {"email": "valid@example.com", "password": ["a"]},  # non-text password list
        {"email": "valid@example.com", "password": {}},  # non-text password dict
    ]

    for body in malformed_bodies:
        resp = client.post("/api/v1/auth/login", json=body)
        assert resp.status_code == 422, f"Expected 422 for {body}, got {resp.status_code}"
        assert resp.status_code != 500
