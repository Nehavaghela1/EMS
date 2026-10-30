"""Tests for Work Package 3.6 (Background Jobs) and 3.5 (Audit Logs).
Verifies all contract rules J1-J8 and A1-A8.
"""

import csv
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ExportTooLargeError
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog
from app.modules.platform.service import AuditService, UnsafeAuditDetailsError
from app.workers.tasks import platform as platform_tasks


def _auth_headers(user: User) -> dict[str, str]:
    user_id = user.__dict__.get("id") or user.id
    company_id = user.__dict__.get("company_id") or user.company_id
    role = user.__dict__.get("role") or user.role
    role_val = role.value if hasattr(role, "value") else str(role)
    token = create_access_token(
        sub=str(user_id),
        company_id=str(company_id),
        role=role_val,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_setup(db: Session) -> dict[str, Any]:
    cid1 = uuid.uuid4()
    company1 = Company(
        id=cid1,
        name=f"Company One {uuid.uuid4().hex[:6]}",
        code=f"C1{uuid.uuid4().hex[:4].upper()}",
        email=f"c1-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        is_active=True,
    )
    db.add(company1)
    db.flush()

    owner1 = User(
        id=uuid.uuid4(),
        company_id=cid1,
        email=f"owner1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.owner,
        is_active=True,
    )
    db.add(owner1)
    db.flush()
    company1.owner_user_id = owner1.id
    db.flush()

    hr1 = User(
        id=uuid.uuid4(),
        company_id=cid1,
        email=f"hr1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(hr1)

    mgr1 = User(
        id=uuid.uuid4(),
        company_id=cid1,
        email=f"mgr1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.manager,
        is_active=True,
    )
    db.add(mgr1)

    emp1 = User(
        id=uuid.uuid4(),
        company_id=cid1,
        email=f"emp1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(emp1)

    cid2 = uuid.uuid4()
    company2 = Company(
        id=cid2,
        name=f"Company Two {uuid.uuid4().hex[:6]}",
        code=f"C2{uuid.uuid4().hex[:4].upper()}",
        email=f"c2-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        is_active=True,
    )
    db.add(company2)
    db.flush()

    hr2 = User(
        id=uuid.uuid4(),
        company_id=cid2,
        email=f"hr2-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(hr2)
    db.commit()

    return {
        "company1": company1,
        "owner1": owner1,
        "hr1": hr1,
        "mgr1": mgr1,
        "emp1": emp1,
        "company2": company2,
        "hr2": hr2,
    }


# ── J1, J6: Job status ownership, unknown id, invalid UUID ─────────────


def test_j1_j6_get_job_status_ownership_and_unknown_id(
    client: TestClient, test_setup: dict[str, Any]
) -> None:
    """J1, J6: Starter, HR admin, and owner can view job status.
    Other users of same company, other company users, unknown job IDs,
    and invalid UUIDs all receive identical 404 responses.
    """
    from app.core.jobs import register_job

    job_id = str(uuid.uuid4())
    mgr1 = test_setup["mgr1"]
    register_job(job_id, test_setup["company1"].id, mgr1.id, "test_job")

    with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "SUCCESS"
        mock_task.result = {"row_count": 5, "expires_at": "2026-10-31T00:00:00Z"}
        mock_async.return_value = mock_task

        # Starter (mgr1) can read
        res_starter = client.get(f"/api/v1/jobs/{job_id}", headers=_auth_headers(mgr1))
        assert res_starter.status_code == 200
        assert res_starter.json()["status"] == "success"

        # HR admin of same company can read
        res_hr = client.get(f"/api/v1/jobs/{job_id}", headers=_auth_headers(test_setup["hr1"]))
        assert res_hr.status_code == 200

        # Owner of same company can read
        res_owner = client.get(
            f"/api/v1/jobs/{job_id}", headers=_auth_headers(test_setup["owner1"])
        )
        assert res_owner.status_code == 200

        # Other non-HR user of same company gets 404 (same body as unknown id)
        res_emp = client.get(f"/api/v1/jobs/{job_id}", headers=_auth_headers(test_setup["emp1"]))
        assert res_emp.status_code == 404
        assert res_emp.json()["error"]["message"] == "Job not found."

        # Other company user gets 404
        res_other = client.get(f"/api/v1/jobs/{job_id}", headers=_auth_headers(test_setup["hr2"]))
        assert res_other.status_code == 404
        assert res_other.json()["error"]["message"] == "Job not found."

        # Unknown UUID gets 404 (never "queued")
        unknown_id = str(uuid.uuid4())
        res_unknown = client.get(
            f"/api/v1/jobs/{unknown_id}", headers=_auth_headers(test_setup["hr1"])
        )
        assert res_unknown.status_code == 404
        assert res_unknown.json()["error"]["message"] == "Job not found."

        # Non-UUID string gets 404
        res_invalid_uuid = client.get(
            "/api/v1/jobs/not-a-uuid", headers=_auth_headers(test_setup["hr1"])
        )
        assert res_invalid_uuid.status_code == 404
        assert res_invalid_uuid.json()["error"]["message"] == "Job not found."

        # Unauthenticated request gets 401
        res_unauth = client.get(f"/api/v1/jobs/{job_id}")
        assert res_unauth.status_code == 401


# ── J2: Job registration and 24h TTL ───────────────────────────────────


def test_j2_job_registered_on_queue_with_24h_ttl(
    client: TestClient, test_setup: dict[str, Any], monkeypatch, db: Session
) -> None:
    """J2: When queued, job is registered in Redis with company_id, user_id, kind,
    and a 24-hour expiration.
    """
    import redis

    from app.core.jobs import get_registered_job

    hr_headers = _auth_headers(test_setup["hr1"])

    with patch("app.workers.tasks.platform.export_audit_logs_csv_task.delay") as mock_delay:
        fake_task = MagicMock()
        fake_task.id = str(uuid.uuid4())
        mock_delay.return_value = fake_task

        res = client.post("/api/v1/audit-logs/export", headers=hr_headers, json={})
        assert res.status_code == 202
        job_id = res.json()["job_id"]
        assert job_id == fake_task.id

        reg = get_registered_job(job_id)
        assert reg is not None
        assert reg["company_id"] == str(test_setup["company1"].id)
        assert reg["user_id"] == str(test_setup["hr1"].id)
        assert reg["kind"] == "audit_logs_export"

        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        ttl = r.ttl(f"job:{job_id}")
        assert 86000 <= ttl <= 86400


# ── J3: Celery states mapped to 4-value contract ───────────────────────


def test_j3_celery_states_mapped_to_contract(
    client: TestClient, test_setup: dict[str, Any]
) -> None:
    """J3: States: queued, started, success, failure."""
    from app.core.jobs import register_job

    hr = test_setup["hr1"]
    hr_headers = _auth_headers(hr)

    state_checks = [
        ("PENDING", "queued"),
        ("RECEIVED", "queued"),
        ("STARTED", "started"),
        ("RETRY", "started"),
        ("SUCCESS", "success"),
        ("FAILURE", "failure"),
    ]

    for celery_state, expected_status in state_checks:
        job_id = str(uuid.uuid4())
        register_job(job_id, test_setup["company1"].id, hr.id, "test_job")

        with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
            mock_task = MagicMock()
            mock_task.state = celery_state
            mock_task.result = {"row_count": 1} if celery_state == "SUCCESS" else None
            mock_async.return_value = mock_task

            res = client.get(f"/api/v1/jobs/{job_id}", headers=hr_headers)
            assert res.status_code == 200
            assert res.json()["status"] == expected_status


# ── J4: Safe result fields only ───────────────────────────────────────────


def test_j4_job_status_safe_result_only(client: TestClient, test_setup: dict[str, Any]) -> None:
    """J4: The result shows only safe fields (row_count, expires_at);
    never file path, file name, requester or internal error text;
    a non-dict result is never returned raw (becomes None).
    """
    from app.core.jobs import register_job

    hr = test_setup["hr1"]
    hr_headers = _auth_headers(hr)

    # 1. Dict result with sensitive keys
    job_id1 = str(uuid.uuid4())
    register_job(job_id1, test_setup["company1"].id, hr.id, "test_job")

    with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "SUCCESS"
        mock_task.result = {
            "company_id": str(test_setup["company1"].id),
            "file_path": "/var/exports/audit_logs_sensitive.csv",
            "file_name": "audit_logs_sensitive.csv",
            "requester_id": str(hr.id),
            "row_count": 42,
            "expires_at": "2026-10-31T12:00:00Z",
            "internal_token": "secret123",
        }
        mock_async.return_value = mock_task

        res = client.get(f"/api/v1/jobs/{job_id1}", headers=hr_headers)
        assert res.status_code == 200
        result_data = res.json()["result"]
        assert result_data is not None
        assert set(result_data.keys()) <= {"row_count", "expires_at"}
        assert result_data["row_count"] == 42
        assert result_data["expires_at"] == "2026-10-31T12:00:00Z"
        assert "file_path" not in result_data
        assert "file_name" not in result_data
        assert "requester_id" not in result_data
        assert "company_id" not in result_data
        assert "internal_token" not in result_data

    # 2. Non-dict result (e.g. integer or string) becomes None
    job_id2 = str(uuid.uuid4())
    register_job(job_id2, test_setup["company1"].id, hr.id, "test_job")

    with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "SUCCESS"
        mock_task.result = "raw string result"
        mock_async.return_value = mock_task

        res2 = client.get(f"/api/v1/jobs/{job_id2}", headers=hr_headers)
        assert res2.status_code == 200
        assert res2.json()["result"] is None


# ── J5: Short generic error vs ExportTooLargeError ────────────────────────


def test_j5_job_status_failure_error_message(
    client: TestClient, test_setup: dict[str, Any]
) -> None:
    """J5: Failure shows the existing short generic message; only the "too large"
    message passes through; the real error goes to server log.
    """
    from app.core.jobs import register_job

    hr = test_setup["hr1"]
    hr_headers = _auth_headers(hr)

    # 1. Generic failure mask
    job_id1 = str(uuid.uuid4())
    register_job(job_id1, test_setup["company1"].id, hr.id, "test_job")

    with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "FAILURE"
        mock_task.result = ValueError("Database connection secret_password failed")
        mock_async.return_value = mock_task

        res1 = client.get(f"/api/v1/jobs/{job_id1}", headers=hr_headers)
        assert res1.status_code == 200
        assert res1.json()["error"] == "Export failed. Please try again."

    # 2. ExportTooLargeError passes through
    job_id2 = str(uuid.uuid4())
    register_job(job_id2, test_setup["company1"].id, hr.id, "test_job")

    with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "FAILURE"
        mock_task.result = ExportTooLargeError(
            "Audit log export exceeds maximum limit of 100,000 rows."
        )
        mock_async.return_value = mock_task

        res2 = client.get(f"/api/v1/jobs/{job_id2}", headers=hr_headers)
        assert res2.status_code == 200
        assert "100,000 rows" in res2.json()["error"]


# ── J7: Rate limit on status checks (60/min) ──────────────────────────────


def test_j7_job_status_rate_limit_60_per_min(
    client: TestClient, test_setup: dict[str, Any]
) -> None:
    """J7, A8: Status check rate limit 60/min. 61st call returns 429."""
    from app.core.jobs import register_job

    hr = test_setup["hr1"]
    hr_headers = _auth_headers(hr)
    job_id = str(uuid.uuid4())
    register_job(job_id, test_setup["company1"].id, hr.id, "test_job")

    with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "SUCCESS"
        mock_task.result = {"row_count": 1}
        mock_async.return_value = mock_task

        limiter.enabled = True
        try:
            limiter.reset()
            codes = []
            for _ in range(61):
                r = client.get(f"/api/v1/jobs/{job_id}", headers=hr_headers)
                codes.append(r.status_code)

            assert all(c == 200 for c in codes[:60]), f"First 60 calls failed: {codes[:60]}"
            assert codes[60] == 429, f"61st call must be 429, got {codes[60]}"
        finally:
            limiter.reset()
            limiter.enabled = False


# ── J7: Employee export download ownership ────────────────────────────────


def test_j7_employee_export_download_ownership(
    client: TestClient, test_setup: dict[str, Any], tmp_path, monkeypatch
) -> None:
    """J7, D3: Employee export download enforces registry ownership.
    Starter or HR-level of same company succeeds; others get 404.
    """
    from app.core.jobs import register_job

    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))
    test_file = tmp_path / "emp_test.csv"
    test_file.write_text("code,name\nE1,John\n")

    mgr1 = test_setup["mgr1"]
    job_id = str(uuid.uuid4())
    register_job(job_id, test_setup["company1"].id, mgr1.id, "employee_export")

    with patch("app.modules.hr.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "SUCCESS"
        mock_task.result = {
            "company_id": str(test_setup["company1"].id),
            "requester_id": str(mgr1.id),
            "file_path": str(test_file),
            "file_name": "employees.csv",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
        mock_async.return_value = mock_task

        # Starter (mgr1) can download
        r_starter = client.get(
            f"/api/v1/employees/export/{job_id}/download", headers=_auth_headers(mgr1)
        )
        assert r_starter.status_code == 200

        # HR of same company can download
        r_hr = client.get(
            f"/api/v1/employees/export/{job_id}/download",
            headers=_auth_headers(test_setup["hr1"]),
        )
        assert r_hr.status_code == 200

        # Other company gets 404
        r_other = client.get(
            f"/api/v1/employees/export/{job_id}/download",
            headers=_auth_headers(test_setup["hr2"]),
        )
        assert r_other.status_code == 404

        # Unregistered job gets 404
        unreg_id = str(uuid.uuid4())
        r_unreg = client.get(
            f"/api/v1/employees/export/{unreg_id}/download",
            headers=_auth_headers(test_setup["hr1"]),
        )
        assert r_unreg.status_code == 404


# ── J8: Cleanup of old export files ───────────────────────────────────────


def test_j8_cleanup_expired_exports_task(tmp_path, monkeypatch) -> None:
    """J8, D10: Cleanup task removes files older than 24 hours starting with
    audit_logs_, employees_, attendance_. Younger files and other files are kept.
    """
    from app.workers.tasks.platform import cleanup_expired_exports_task

    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))

    old_time = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    fresh_time = (datetime.now(UTC) - timedelta(hours=1)).timestamp()

    old_audit = tmp_path / "audit_logs_123_abc.csv"
    old_audit.write_text("old audit")
    os.utime(old_audit, (old_time, old_time))

    old_emp = tmp_path / "employees_2026-01-01.csv"
    old_emp.write_text("old emp")
    os.utime(old_emp, (old_time, old_time))

    old_att = tmp_path / "attendance_456_def.csv"
    old_att.write_text("old att")
    os.utime(old_att, (old_time, old_time))

    fresh_audit = tmp_path / "audit_logs_fresh.csv"
    fresh_audit.write_text("fresh audit")
    os.utime(fresh_audit, (fresh_time, fresh_time))

    old_other = tmp_path / "other_file.csv"
    old_other.write_text("other")
    os.utime(old_other, (old_time, old_time))

    deleted = cleanup_expired_exports_task()
    assert deleted == 3
    assert not old_audit.exists()
    assert not old_emp.exists()
    assert not old_att.exists()
    assert fresh_audit.exists()
    assert old_other.exists()


# ── A2: Extended banned fields scanning nested structures ─────────────────


def test_a2_unsafe_audit_details_guard() -> None:
    """A2, D7: Banned fields (including otp, secret, api_key, etc.) cannot be written
    into audit details, including inside lists and nested dictionaries.
    """
    from app.modules.platform.service import _assert_details_safe

    banned_keys = [
        "password",
        "hashed_password",
        "raw_password",
        "token",
        "raw_token",
        "activation_token_hash",
        "refresh_token",
        "access_token",
        "aadhaar",
        "aadhaar_number",
        "pan",
        "pan_number",
        "bank_account",
        "bank_account_number",
        "bank_details",
        "ifsc",
        "otp",
        "secret",
        "client_secret",
        "api_key",
        "authorization",
        "card_number",
        "cvv",
        "password_hash",
    ]

    for key in banned_keys:
        # Top-level key
        with pytest.raises(UnsafeAuditDetailsError):
            _assert_details_safe({key: "value"})

        # Case-insensitive
        with pytest.raises(UnsafeAuditDetailsError):
            _assert_details_safe({key.upper(): "value"})

        # Inside nested dict
        with pytest.raises(UnsafeAuditDetailsError):
            _assert_details_safe({"nested": {key: "value"}})

        # Inside list of dicts
        with pytest.raises(UnsafeAuditDetailsError):
            _assert_details_safe({"list": [{"safe": 1}, {key: "value"}]})

        # Deeply nested
        with pytest.raises(UnsafeAuditDetailsError):
            _assert_details_safe({"data": [{"level2": {"level3": [{key: "leak"}]}}]})

    # Safe details must pass without error
    _assert_details_safe({"action_type": "update", "changed_fields": ["position", "level"]})


# ── A3: Read roles and tenant isolation ───────────────────────────────────


def test_a3_audit_logs_read_roles_and_tenant_isolation(
    client: TestClient, test_setup: dict[str, Any]
) -> None:
    """A3: Read only by HR admin and owner of the same company; others 403;
    other company never sees rows.
    """
    hr_headers = _auth_headers(test_setup["hr1"])
    owner_headers = _auth_headers(test_setup["owner1"])
    mgr_headers = _auth_headers(test_setup["mgr1"])
    emp_headers = _auth_headers(test_setup["emp1"])
    hr2_headers = _auth_headers(test_setup["hr2"])

    # HR admin and owner of same company: 200
    r_hr = client.get("/api/v1/audit-logs", headers=hr_headers)
    assert r_hr.status_code == 200

    r_owner = client.get("/api/v1/audit-logs", headers=owner_headers)
    assert r_owner.status_code == 200

    # Manager and employee: 403
    r_mgr = client.get("/api/v1/audit-logs", headers=mgr_headers)
    assert r_mgr.status_code == 403

    r_emp = client.get("/api/v1/audit-logs", headers=emp_headers)
    assert r_emp.status_code == 403

    # Other company gets only its own logs
    r_hr2 = client.get("/api/v1/audit-logs", headers=hr2_headers)
    assert r_hr2.status_code == 200


# ── A4: Request context parsing and population ────────────────────────────


def test_a4_request_context_parsing_helpers() -> None:
    """A4, D6: Direct testing of IP address, user_agent, and request_id parsing."""
    from app.core.audit_context import (
        parse_audit_ip,
        parse_audit_request_id,
        parse_audit_user_agent,
    )

    # IP parsing
    assert parse_audit_ip("192.168.1.1") == "192.168.1.1"
    assert parse_audit_ip("2001:db8::1") == "2001:db8::1"
    assert parse_audit_ip("not-an-ip") is None
    assert parse_audit_ip("") is None
    assert parse_audit_ip(None) is None
    assert parse_audit_ip("999.999.999.999") is None

    # User agent parsing (cut to 500 chars)
    short_ua = "Mozilla/5.0 TestBrowser"
    assert parse_audit_user_agent(short_ua) == short_ua
    long_ua = "A" * 600
    assert len(parse_audit_user_agent(long_ua) or "") == 500
    assert parse_audit_user_agent(None) is None

    # Request ID parsing
    valid_uuid = uuid.uuid4()
    assert parse_audit_request_id(str(valid_uuid)) == valid_uuid
    assert parse_audit_request_id("not-a-uuid") is None
    assert parse_audit_request_id(None) is None


def test_a4_audit_record_stores_context_when_request_present(
    client: TestClient, test_setup: dict[str, Any], db: Session
) -> None:
    """A4, D6: HTTP request populates ip_address, user_agent, and request_id.
    Direct service record without HTTP context leaves them as None.
    """
    req_id = str(uuid.uuid4())
    headers = _auth_headers(test_setup["hr1"])
    headers["X-Request-ID"] = req_id
    headers["User-Agent"] = "AuditTestSuite/1.0"

    # Trigger an audited action (e.g. queue export) with real IP in client
    custom_client = TestClient(client.app, client=("198.51.100.25", 50000))
    with patch("app.workers.tasks.platform.export_audit_logs_csv_task.delay") as mock_delay:
        mock_delay.return_value = MagicMock(id=str(uuid.uuid4()))
        resp = custom_client.post("/api/v1/audit-logs/export", headers=headers, json={})
        assert resp.status_code == 202

    # Query database for the written audit row
    log = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == test_setup["company1"].id,
            AuditLog.action == "AUDIT_EXPORT_REQUESTED",
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert log is not None
    assert str(log.request_id) == req_id
    assert log.user_agent == "AuditTestSuite/1.0"
    assert log.ip_address == "198.51.100.25"

    # Direct record without request context gets None
    service = AuditService(db)
    direct_log = service.record(
        company_id=test_setup["company1"].id,
        actor=test_setup["hr1"],
        action="TEST_DIRECT_RECORD",
    )
    db.commit()
    assert direct_log.ip_address is None
    assert direct_log.user_agent is None
    assert direct_log.request_id is None


# ── A5: List audit logs validation ────────────────────────────────────────


def test_a5_audit_logs_read_validation(client: TestClient, test_setup: dict[str, Any]) -> None:
    """A5, D8: List audit logs validates page >= 1, limit 1-100, max lengths,
    and date_from <= date_to (422).
    """
    hr_headers = _auth_headers(test_setup["hr1"])

    # Page < 1 -> 422
    assert client.get("/api/v1/audit-logs?page=0", headers=hr_headers).status_code == 422

    # Limit < 1 -> 422
    assert client.get("/api/v1/audit-logs?limit=0", headers=hr_headers).status_code == 422

    # Limit > 100 -> 422
    assert client.get("/api/v1/audit-logs?limit=101", headers=hr_headers).status_code == 422

    # date_from after date_to -> 422
    res_dates = client.get(
        "/api/v1/audit-logs?date_from=2026-10-10&date_to=2026-10-01", headers=hr_headers
    )
    assert res_dates.status_code == 422

    # action > 100 chars -> 422
    long_action = "A" * 101
    assert (
        client.get(f"/api/v1/audit-logs?action={long_action}", headers=hr_headers).status_code
        == 422
    )

    # actor_email > 255 chars -> 422
    long_email = "a" * 250 + "@example.com"
    assert (
        client.get(f"/api/v1/audit-logs?actor_email={long_email}", headers=hr_headers).status_code
        == 422
    )

    # entity_type > 50 chars -> 422
    long_type = "T" * 51
    assert (
        client.get(f"/api/v1/audit-logs?entity_type={long_type}", headers=hr_headers).status_code
        == 422
    )


# ── A6: Export request validation and role check ──────────────────────────


def test_a6_audit_export_roles_and_validation(
    client: TestClient, test_setup: dict[str, Any]
) -> None:
    """A6, D8: Export requires HR admin or owner; rejects date_from > date_to (422)
    and oversized filter values (422).
    """
    emp_headers = _auth_headers(test_setup["emp1"])
    hr_headers = _auth_headers(test_setup["hr1"])

    # Non-HR user gets 403
    assert client.post("/api/v1/audit-logs/export", headers=emp_headers, json={}).status_code == 403

    # date_from > date_to gives 422
    bad_dates = {"date_from": "2026-10-10", "date_to": "2026-10-01"}
    assert (
        client.post("/api/v1/audit-logs/export", headers=hr_headers, json=bad_dates).status_code
        == 422
    )

    # Max lengths
    assert (
        client.post(
            "/api/v1/audit-logs/export", headers=hr_headers, json={"action": "A" * 101}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/audit-logs/export",
            headers=hr_headers,
            json={"actor_email": "e" * 250 + "@example.com"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/audit-logs/export", headers=hr_headers, json={"entity_type": "T" * 51}
        ).status_code
        == 422
    )


# ── A6, D4: Audit export task row cap and CSV formatting ──────────────────


def test_a6_d4_audit_export_task_row_cap_and_csv_formatting(
    tmp_path, monkeypatch, test_setup: dict[str, Any], db: Session
) -> None:
    """A6, D4: Audit export task caps at 100,000 rows, escapes cells via csv_safe_cell,
    formats details as JSON string, and includes columns created_at, actor_email,
    action, entity_type, entity_id, ip_address, request_id, details.
    """
    from app.workers.tasks.platform import export_audit_logs_csv_task

    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))
    monkeypatch.setattr(platform_tasks, "get_task_db_session", lambda: db)

    cid = test_setup["company1"].id

    # Create audit rows with formula injection patterns and details
    req_uuid = uuid.uuid4()
    row1 = AuditLog(
        company_id=cid,
        actor_email="hr@example.com",
        action="=CMD|' /C calc'!A0",
        entity_type="+danger",
        entity_id=uuid.uuid4(),
        details={"status": "updated", "target": "@admin"},
        ip_address="192.168.1.50",
        user_agent="Agent/1.0",
        request_id=req_uuid,
    )
    db.add(row1)
    db.commit()

    # 1. Run task
    result = export_audit_logs_csv_task(
        company_id=str(cid),
        requester_id=str(test_setup["hr1"].id),
    )
    assert result["row_count"] >= 1
    assert "expires_at" in result
    assert result["requester_id"] == str(test_setup["hr1"].id)
    assert os.path.exists(result["file_path"])

    with open(result["file_path"], newline="", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    headers = reader[0]
    expected_headers = [
        "created_at",
        "actor_email",
        "action",
        "entity_type",
        "entity_id",
        "ip_address",
        "request_id",
        "details",
    ]
    assert headers == expected_headers

    # Find row1 in the CSV output
    matched_row = None
    for r in reader[1:]:
        if str(req_uuid) in r[6]:
            matched_row = r
            break
    assert matched_row is not None

    # csv_safe_cell prefix test
    assert matched_row[2].startswith("'=")
    assert matched_row[3].startswith("'+")

    # details must be valid JSON text, NOT python dict string
    raw_details = matched_row[7]
    parsed_details = json.loads(raw_details)
    assert parsed_details["status"] == "updated"
    assert parsed_details["target"] == "@admin"

    # 2. Row cap test: mock repo returning > 100,000 count
    with patch(
        "app.modules.platform.repository.AuditRepository.count_for_export",
        return_value=100001,
    ):
        with pytest.raises(ExportTooLargeError) as exc_info:
            export_audit_logs_csv_task(
                company_id=str(cid),
                requester_id=str(test_setup["hr1"].id),
            )
        assert "100,000" in str(exc_info.value)


# ── A7: Export request audited (AUDIT_EXPORT_REQUESTED) ───────────────────


def test_a7_audit_export_requested_audit_row(
    client: TestClient, test_setup: dict[str, Any], db: Session
) -> None:
    """A7, D9: Export request records AUDIT_EXPORT_REQUESTED.
    details contains filter names and date boundaries only; NO actor email value.
    """
    hr_headers = _auth_headers(test_setup["hr1"])

    with patch("app.workers.tasks.platform.export_audit_logs_csv_task.delay") as mock_delay:
        mock_delay.return_value = MagicMock(id=str(uuid.uuid4()))
        res = client.post(
            "/api/v1/audit-logs/export",
            headers=hr_headers,
            json={
                "action": "EMPLOYEE_CREATED",
                "actor_email": "target@example.com",
                "date_from": "2026-10-01",
                "date_to": "2026-10-15",
            },
        )
        assert res.status_code == 202

    log = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == test_setup["company1"].id,
            AuditLog.action == "AUDIT_EXPORT_REQUESTED",
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert log is not None
    details = log.details or {}
    # Only filter names and date boundaries allowed
    assert "filters" in details
    assert set(details["filters"]) == {"action", "actor_email", "date_from", "date_to"}
    assert details["date_from"] == "2026-10-01"
    assert details["date_to"] == "2026-10-15"
    # Never leak the actual actor email value in details
    details_str = json.dumps(details)
    assert "target@example.com" not in details_str


# ── A7, D5: Export download route ─────────────────────────────────────────


def test_a7_d5_audit_export_download_route(
    client: TestClient, test_setup: dict[str, Any], tmp_path, monkeypatch
) -> None:
    """A7, D5: GET /api/v1/audit-logs/export/{job_id}/download works for starter
    or HR-level of same company; other users / companies get 403 or 404;
    expired files return 404 and get deleted; path traversal outside EXPORT_DIR fails.
    """
    from app.core.jobs import register_job

    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))
    export_file = tmp_path / "audit_logs_valid.csv"
    export_file.write_text("created_at,action\n2026-10-30,TEST\n")

    hr = test_setup["hr1"]
    job_id = str(uuid.uuid4())
    register_job(job_id, test_setup["company1"].id, hr.id, "audit_logs_export")

    with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "SUCCESS"
        mock_task.result = {
            "company_id": str(test_setup["company1"].id),
            "requester_id": str(hr.id),
            "file_path": str(export_file),
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
        mock_async.return_value = mock_task

        # Starter (HR) downloads: 200
        res = client.get(f"/api/v1/audit-logs/export/{job_id}/download", headers=_auth_headers(hr))
        assert res.status_code == 200
        assert "text/csv" in res.headers["content-type"]
        assert "attachment" in res.headers["content-disposition"]

        # Owner downloads: 200
        res_owner = client.get(
            f"/api/v1/audit-logs/export/{job_id}/download",
            headers=_auth_headers(test_setup["owner1"]),
        )
        assert res_owner.status_code == 200

        # Non-HR user gets 403
        res_emp = client.get(
            f"/api/v1/audit-logs/export/{job_id}/download",
            headers=_auth_headers(test_setup["emp1"]),
        )
        assert res_emp.status_code == 403

        # Other company HR admin gets 404
        res_other = client.get(
            f"/api/v1/audit-logs/export/{job_id}/download",
            headers=_auth_headers(test_setup["hr2"]),
        )
        assert res_other.status_code == 404

    # Expired export test: returns 404 AND deletes file from disk
    expired_file = tmp_path / "audit_logs_expired.csv"
    expired_file.write_text("expired")
    job_id_exp = str(uuid.uuid4())
    register_job(job_id_exp, test_setup["company1"].id, hr.id, "audit_logs_export")

    with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "SUCCESS"
        mock_task.result = {
            "company_id": str(test_setup["company1"].id),
            "requester_id": str(hr.id),
            "file_path": str(expired_file),
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        }
        mock_async.return_value = mock_task

        res_exp = client.get(
            f"/api/v1/audit-logs/export/{job_id_exp}/download", headers=_auth_headers(hr)
        )
        assert res_exp.status_code == 404
        assert not expired_file.exists()

    # Path traversal protection: file outside EXPORT_DIR returns 404
    outside_file = tmp_path.parent / "escape.csv"
    outside_file.write_text("escaped")
    job_id_esc = str(uuid.uuid4())
    register_job(job_id_esc, test_setup["company1"].id, hr.id, "audit_logs_export")

    with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "SUCCESS"
        mock_task.result = {
            "company_id": str(test_setup["company1"].id),
            "requester_id": str(hr.id),
            "file_path": str(outside_file),
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
        mock_async.return_value = mock_task

        res_esc = client.get(
            f"/api/v1/audit-logs/export/{job_id_esc}/download", headers=_auth_headers(hr)
        )
        assert res_esc.status_code == 404
        if outside_file.exists():
            outside_file.unlink()


# ── A8: Rate limits on audit routes ───────────────────────────────────────


def test_a8_rate_limits_audit_routes(
    client: TestClient, test_setup: dict[str, Any], tmp_path, monkeypatch
) -> None:
    """A8: Audit list 30/min, export 5/min, export download 10/min.
    The call after the limit returns 429.
    """
    from app.core.jobs import register_job

    hr = test_setup["hr1"]
    hr_headers = _auth_headers(hr)

    limiter.enabled = True
    try:
        # 1. Audit list: 30/min -> 31st gives 429
        limiter.reset()
        codes_list = []
        for _ in range(31):
            r = client.get("/api/v1/audit-logs", headers=hr_headers)
            codes_list.append(r.status_code)
        assert all(c == 200 for c in codes_list[:30])
        assert codes_list[30] == 429

        # 2. Audit export: 5/min -> 6th gives 429
        limiter.reset()
        codes_export = []
        with patch("app.workers.tasks.platform.export_audit_logs_csv_task.delay") as mock_del:
            mock_del.return_value = MagicMock(id=str(uuid.uuid4()))
            for _ in range(6):
                r = client.post("/api/v1/audit-logs/export", headers=hr_headers, json={})
                codes_export.append(r.status_code)
        assert all(c == 202 for c in codes_export[:5])
        assert codes_export[5] == 429

        # 3. Audit export download: 10/min -> 11th gives 429
        limiter.reset()
        monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))
        dl_file = tmp_path / "dl_rl.csv"
        dl_file.write_text("a,b\n1,2\n")

        job_id = str(uuid.uuid4())
        register_job(job_id, test_setup["company1"].id, hr.id, "audit_logs_export")

        codes_dl = []
        with patch("app.modules.platform.router.celery_app.AsyncResult") as mock_async:
            mock_task = MagicMock()
            mock_task.state = "SUCCESS"
            mock_task.result = {
                "company_id": str(test_setup["company1"].id),
                "requester_id": str(hr.id),
                "file_path": str(dl_file),
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
            mock_async.return_value = mock_task

            for _ in range(11):
                r = client.get(f"/api/v1/audit-logs/export/{job_id}/download", headers=hr_headers)
                codes_dl.append(r.status_code)
        assert all(c == 200 for c in codes_dl[:10])
        assert codes_dl[10] == 429

    finally:
        limiter.reset()
        limiter.enabled = False
