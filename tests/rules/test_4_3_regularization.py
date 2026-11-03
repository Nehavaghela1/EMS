"""Module 4, sub-feature 4.3: Attendance regularization. One test per rule line (R1..R10).

Dates and times are computed from utcnow(); nothing that a rule compares with
today is typed in.
"""

import re
import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import Employee
from app.modules.identity.models import (
    Company,
    CompanySettings,
    CompanyStatus,
    User,
    UserRole,
)
from app.modules.platform.models import AuditLog, Notification
from app.modules.time_leave.models import (
    Attendance,
    AttendanceRegularizationRequest,
    AttendanceSource,
    AttendanceStatus,
    Leave,
    LeaveStatus,
    RegularizationStatus,
)
from tests.conftest import TenantContext
from tests.rules.test_4_2_punch import _create_employee, _link_user_to_employee

ATT = "/api/v1/attendance"
MIGRATION_REVISION = "d5e6f7a8b9c0"
PREVIOUS_REVISION = "7fe2862a3b33"
PDF = b"%PDF-1.4 proof"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


@pytest.fixture(autouse=True)
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "regularizations"
    target.mkdir()
    monkeypatch.setattr(
        "app.modules.time_leave.router.get_regularizations_upload_dir", lambda: str(target)
    )
    return target


@pytest.fixture
def limits_on():
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = False


def _day(days_ago: int) -> date:
    return utcnow().date() - timedelta(days=days_ago)


def _at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=UTC)


def _record(
    db: Session,
    ctx: TenantContext,
    employee_id: str,
    days_ago: int = 3,
    status: AttendanceStatus = AttendanceStatus.mispunch,
) -> str:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    day = _day(days_ago)
    row = Attendance(
        company_id=ctx.company_id,
        employee_id=uuid.UUID(employee_id),
        date=day,
        check_in=_at(day, 9),
        status=status,
        source=AttendanceSource.web,
    )
    db.add(row)
    db.commit()
    return str(row.id)


def _body(days_ago: int = 3, **over: Any) -> dict[str, Any]:
    day = _day(days_ago)
    body: dict[str, Any] = {
        "requested_check_in": _at(day, 9).isoformat(),
        "requested_check_out": _at(day, 18).isoformat(),
        "reason": "Forgot to punch out",
    }
    body.update(over)
    return body


def _request(client: TestClient, headers: dict[str, str], att_id: str, **over: Any):
    days_ago = over.pop("days_ago", 3)
    return client.post(f"{ATT}/{att_id}/regularize", headers=headers, json=_body(days_ago, **over))


def _decide(client: TestClient, headers: dict[str, str], reg_id: str, **body: Any):
    payload = {"status": "approved"}
    payload.update(body)
    return client.put(f"{ATT}/regularizations/{reg_id}/approve", headers=headers, json=payload)


def _audit(db: Session, ctx: TenantContext, action: str) -> list[AuditLog]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    return (
        db.query(AuditLog)
        .filter(AuditLog.company_id == ctx.company_id, AuditLog.action == action)
        .all()
    )


def _notes_for(
    db: Session, ctx: TenantContext, user_id: uuid.UUID, kind: str
) -> list[Notification]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.type == kind)
        .all()
    )


@pytest.fixture
def org(client: TestClient, db: Session, company_a: TenantContext) -> dict[str, Any]:
    """senior (manager) <- boss (manager) <- emp; colleague; outsider manager; HR and owner
    with their own employee records."""
    world: dict[str, Any] = {"ctx": company_a}

    def make(key: str, role: UserRole, manager: str | None = None) -> None:
        extra = {"reporting_manager_id": manager} if manager else {}
        emp = _create_employee(client, company_a.hr_headers, **extra)
        headers, user = _link_user_to_employee(db, company_a.company_id, emp["id"], role)
        world[key] = {"id": emp["id"], "h": headers, "user": user}

    make("senior", UserRole.manager)
    make("boss", UserRole.manager, world["senior"]["id"])
    make("emp", UserRole.employee, world["boss"]["id"])
    make("colleague", UserRole.employee)
    make("outsider", UserRole.manager)
    make("hr2", UserRole.hr_admin)
    make("owner", UserRole.owner)
    make("sadmin", UserRole.super_admin)
    return world


# ------------------------------------------------------------------- R1


def test_R1_no_login_gets_401(client: TestClient) -> None:
    assert client.post(f"{ATT}/{uuid.uuid4()}/regularize", json=_body()).status_code == 401
    assert client.get(f"{ATT}/{uuid.uuid4()}/regularization").status_code == 401
    assert client.put(f"{ATT}/regularizations/{uuid.uuid4()}/approve", json={}).status_code == 401


def test_R1_employee_requests_for_own_record_up_to_30_days_old(client, db, org) -> None:
    ctx = org["ctx"]
    own = _record(db, ctx, org["emp"]["id"], days_ago=3)
    resp = _request(client, org["emp"]["h"], own)
    assert resp.status_code == 201, (
        f"R1: own record must give 201, got {resp.status_code} {resp.text}"
    )
    assert resp.json()["status"] == "pending" and resp.json()["employee_id"] == org["emp"]["id"]

    edge = _record(db, ctx, org["colleague"]["id"], days_ago=30)
    ok = _request(client, org["colleague"]["h"], edge, days_ago=30)
    assert ok.status_code == 201, f"R1: a 30 day old record is allowed, got {ok.text}"

    old = _record(db, ctx, org["boss"]["id"], days_ago=31)
    too_old = _request(client, org["boss"]["h"], old, days_ago=31)
    assert too_old.status_code == 422, f"R1: older than 30 days must give 422, got {too_old.text}"
    assert "30" in too_old.json()["error"]["message"]


def test_R1_someone_elses_record_gets_403_for_every_role(client, db, org) -> None:
    ctx = org["ctx"]
    theirs = _record(db, ctx, org["emp"]["id"], days_ago=4)
    for who in ("colleague", "boss", "outsider", "hr2", "owner"):
        resp = _request(client, org[who]["h"], theirs, days_ago=4)
        assert resp.status_code == 403, f"R1: {who} must not request for someone else: {resp.text}"
    assert _request(client, ctx.hr_headers, theirs, days_ago=4).status_code == 403


def test_R1_other_company_and_missing_record_give_the_same_404(
    client, db, org, company_b: TenantContext
) -> None:
    ctx = org["ctx"]
    foreign_emp = _create_employee(client, company_b.hr_headers)
    foreign = _record(db, company_b, foreign_emp["id"])
    other = _request(client, org["emp"]["h"], foreign)
    missing = _request(client, org["emp"]["h"], str(uuid.uuid4()))
    assert other.status_code == 404 == missing.status_code, f"R1: {other.text} / {missing.text}"
    assert other.json()["error"]["message"] == missing.json()["error"]["message"]
    assert ctx is not None


# ------------------------------------------------------------------- R2


def test_R2_at_least_one_time_is_required(client, db, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    resp = _request(client, org["emp"]["h"], rec, requested_check_in=None, requested_check_out=None)
    assert resp.status_code == 422, f"R2: no time given must give 422, got {resp.text}"


def test_R2_a_single_time_is_enough(client, db, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    resp = _request(client, org["emp"]["h"], rec, requested_check_in=None)
    assert resp.status_code == 201, f"R2: only check-out is a valid request: {resp.text}"


def test_R2_check_out_must_be_after_check_in(client, db, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    day = _day(3)
    resp = _request(
        client,
        org["emp"]["h"],
        rec,
        requested_check_in=_at(day, 18).isoformat(),
        requested_check_out=_at(day, 9).isoformat(),
    )
    assert resp.status_code == 422, f"R2: check-out before check-in must give 422: {resp.text}"


def test_R2_times_in_the_future_are_refused(client, db, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"], days_ago=0)
    soon = (utcnow() + timedelta(hours=1)).isoformat()
    resp = _request(
        client, org["emp"]["h"], rec, days_ago=0, requested_check_in=None, requested_check_out=soon
    )
    assert resp.status_code == 422, f"R2: future check-out must give 422: {resp.text}"


def test_R2_times_must_fall_on_the_record_date_or_the_next_morning(client, db, org) -> None:
    ctx = org["ctx"]
    day = _day(5)
    wrong_in = _request(
        client,
        org["emp"]["h"],
        _record(db, ctx, org["emp"]["id"], days_ago=5),
        days_ago=5,
        requested_check_in=_at(day - timedelta(days=1), 9).isoformat(),
    )
    assert wrong_in.status_code == 422, (
        f"R2: check-in on another date must give 422: {wrong_in.text}"
    )

    night = _record(db, ctx, org["colleague"]["id"], days_ago=5)
    ok = _request(
        client,
        org["colleague"]["h"],
        night,
        days_ago=5,
        requested_check_in=_at(day, 22).isoformat(),
        requested_check_out=_at(day + timedelta(days=1), 6).isoformat(),
    )
    assert ok.status_code == 201, f"R2: night shift ending next morning is allowed: {ok.text}"

    late = _record(db, ctx, org["boss"]["id"], days_ago=5)
    too_late = _request(
        client,
        org["boss"]["h"],
        late,
        days_ago=5,
        requested_check_in=_at(day, 22).isoformat(),
        requested_check_out=_at(day + timedelta(days=2), 6).isoformat(),
    )
    assert too_late.status_code == 422, (
        f"R2: check-out two days later must give 422: {too_late.text}"
    )


def test_R2_reason_is_trimmed_and_limited_to_1_to_500(client, db, org) -> None:
    ctx = org["ctx"]
    for bad in ("", "    ", "x" * 501):
        rec = _record(db, ctx, org["emp"]["id"], days_ago=6)
        resp = _request(client, org["emp"]["h"], rec, days_ago=6, reason=bad)
        assert resp.status_code == 422, f"R2: reason of length {len(bad)} must give 422"
        _clear(db, ctx, rec)
    rec = _record(db, ctx, org["emp"]["id"], days_ago=6)
    ok = _request(client, org["emp"]["h"], rec, days_ago=6, reason="  trimmed  ")
    assert ok.status_code == 201 and ok.json()["reason"] == "trimmed", "R2: reason not trimmed"
    rec2 = _record(db, ctx, org["colleague"]["id"], days_ago=6)
    longest = _request(client, org["colleague"]["h"], rec2, days_ago=6, reason="y" * 500)
    assert longest.status_code == 201, "R2: 500 characters must be accepted"


def _clear(db: Session, ctx: TenantContext, att_id: str) -> None:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.query(AttendanceRegularizationRequest).filter(
        AttendanceRegularizationRequest.attendance_id == uuid.UUID(att_id)
    ).delete()
    db.query(Attendance).filter(Attendance.id == uuid.UUID(att_id)).delete()
    db.commit()


def test_R2_unknown_fields_and_bad_dates_give_422(client, db, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    extra = _request(client, org["emp"]["h"], rec, color="red")
    assert extra.status_code == 422, "R2: unknown field must give 422"
    link = _request(client, org["emp"]["h"], rec, attachment_url="/etc/passwd")
    assert link.status_code == 422, "R2: the client cannot set an attachment link"
    bad = _request(client, org["emp"]["h"], rec, requested_check_in="not-a-date")
    assert bad.status_code == 422, "R2: malformed JSON date must give 422"
    form = client.post(
        f"{ATT}/{rec}/regularize",
        headers=org["emp"]["h"],
        data={"check_in": "31-31-2026 99:99", "reason": "bad date in a form"},
    )
    assert form.status_code == 422, f"R2: malformed form date must give 422, got {form.text}"
    unknown_form = client.post(
        f"{ATT}/{rec}/regularize",
        headers=org["emp"]["h"],
        data={"check_out": _at(_day(3), 18).isoformat(), "reason": "x", "color": "red"},
    )
    assert unknown_form.status_code == 422, "R2: unknown form field must give 422"


# ------------------------------------------------------------------- R3


def test_R3_second_pending_request_for_a_record_gets_409(client, db, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    first = _request(client, org["emp"]["h"], rec)
    assert first.status_code == 201
    second = _request(client, org["emp"]["h"], rec)
    assert second.status_code == 409, f"R3: second pending request must give 409: {second.text}"
    again = _decide(
        client, org["boss"]["h"], first.json()["id"], status="rejected", rejection_reason="no"
    )
    assert again.status_code == 200
    third = _request(client, org["emp"]["h"], rec)
    assert third.status_code == 201, f"R3: after a decision a new request is allowed: {third.text}"


def test_R3_database_refuses_a_second_pending_row(db: Session, client, org) -> None:
    ctx = org["ctx"]
    rec = _record(db, ctx, org["emp"]["id"])
    assert _request(client, org["emp"]["h"], rec).status_code == 201
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.add(
        AttendanceRegularizationRequest(
            company_id=ctx.company_id,
            attendance_id=uuid.UUID(rec),
            employee_id=uuid.UUID(org["emp"]["id"]),
            reason="direct insert",
            status=RegularizationStatus.pending,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_R3_two_simultaneous_requests_give_one_201_and_one_409() -> None:
    assert settings.TEST_DATABASE_URL is not None and settings.TEST_MIGRATION_URL is not None
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    cid = uuid.uuid4()
    day = _day(3)
    try:
        with Session(engine) as setup:
            setup.add(
                Company(
                    id=cid,
                    name="Reg Race Co",
                    code=f"RRC{uuid.uuid4().hex[:4].upper()}",
                    email=f"rrc-{uuid.uuid4().hex[:6]}@example.com",
                    status=CompanyStatus.active,
                    is_active=True,
                )
            )
            setup.flush()
            bind_tenant_to_session(setup, company_id=cid, is_platform_admin=False)
            emp = Employee(
                id=uuid.uuid4(),
                company_id=cid,
                employee_code=f"EMP{uuid.uuid4().hex[:4].upper()}",
                first_name="Reg",
                last_name="Racer",
                email=f"reg-{uuid.uuid4().hex[:6]}@example.com",
                hire_date=day,
                is_active=True,
            )
            user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"user-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.employee,
                is_active=True,
            )
            setup.add_all([emp, user])
            setup.flush()
            emp.user_id = user.id
            att = Attendance(
                company_id=cid,
                employee_id=emp.id,
                date=day,
                check_in=_at(day, 9),
                status=AttendanceStatus.mispunch,
                source=AttendanceSource.web,
            )
            setup.add(att)
            setup.commit()
            att_id, token = (
                str(att.id),
                create_access_token(sub=str(user.id), company_id=str(cid), role="employee"),
            )
        headers = {"Authorization": f"Bearer {token}"}

        def _get_test_db():
            session = Session(engine)
            try:
                yield session
            finally:
                session.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db
        barrier = threading.Barrier(2)
        results: list[int] = []

        def _worker() -> None:
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                results.append(
                    c.post(f"{ATT}/{att_id}/regularize", headers=headers, json=_body(3)).status_code
                )
            except Exception:
                results.append(999)

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert 500 not in results and 999 not in results, f"R3: race gave an error: {results}"
        assert sorted(results) == [201, 409], f"R3: expected one 201 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        _purge_company(cid)


def _purge_company(cid: uuid.UUID) -> None:
    owner = create_engine(settings.TEST_MIGRATION_URL)
    try:
        with owner.begin() as conn:
            conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
            for table in (
                "audit_logs",
                "notifications",
                "attendance_regularizations",
                "leaves",
                "leave_balances",
                "leave_types",
                "attendance",
                "employees",
                "users",
                "company_settings",
            ):
                conn.execute(text(f"DELETE FROM {table} WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": cid})
    finally:
        owner.dispose()


# ------------------------------------------------------------------- R4


def test_R4_reporting_chain_hr_admin_and_owner_can_decide(client, db, org) -> None:
    ctx = org["ctx"]
    for who, days_ago in (("boss", 3), ("senior", 4), ("hr2", 5), ("owner", 6)):
        rec = _record(db, ctx, org["emp"]["id"], days_ago=days_ago)
        reg = _request(client, org["emp"]["h"], rec, days_ago=days_ago).json()["id"]
        resp = _decide(client, org[who]["h"], reg)
        assert resp.status_code == 200, f"R4: {who} must be able to decide: {resp.text}"
        assert resp.json()["status"] == "approved"


def test_R4_outsiders_get_403_with_the_same_message(client, db, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    manager = _decide(client, org["outsider"]["h"], reg)
    employee = _decide(client, org["colleague"]["h"], reg)
    assert manager.status_code == 403 == employee.status_code, f"{manager.text} / {employee.text}"
    assert manager.json()["error"]["message"] == employee.json()["error"]["message"], (
        "R4: a manager outside the chain and an employee must get the same message"
    )


def test_R4_other_company_cannot_decide(client, db, org, company_b: TenantContext) -> None:
    ctx = org["ctx"]
    rec = _record(db, ctx, org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    foreign = _decide(client, company_b.hr_headers, reg)
    missing = _decide(client, company_b.hr_headers, str(uuid.uuid4()))
    assert foreign.status_code == 404 == missing.status_code, f"R4: {foreign.text}"
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]


def test_R4_nobody_approves_their_own_request_except_an_owner(client, db, org) -> None:
    ctx = org["ctx"]
    for who, days_ago in (("emp", 3), ("boss", 4), ("hr2", 5), ("sadmin", 6)):
        rec = _record(db, ctx, org[who]["id"], days_ago=days_ago)
        made = _request(client, org[who]["h"], rec, days_ago=days_ago)
        assert made.status_code == 201 and made.json()["status"] == "pending", (
            f"R4: {who}'s own request must stay pending, got {made.text}"
        )
        own = _decide(client, org[who]["h"], made.json()["id"])
        assert own.status_code == 403, f"R4: {who} must not approve their own request: {own.text}"
        if who != "emp":  # a plain employee is refused by role before any self check
            assert "your own" in own.json()["error"]["message"].lower()


def test_R4_an_owners_own_request_is_approved_at_once_and_audited(client, db, org) -> None:
    ctx = org["ctx"]
    rec = _record(db, ctx, org["owner"]["id"])
    made = _request(client, org["owner"]["h"], rec)
    assert made.status_code == 201, made.text
    assert made.json()["status"] == "approved", "R4: an owner's own request is approved at once"
    assert len(_audit(db, ctx, "REGULARIZATION_REQUESTED")) == 1
    approved = _audit(db, ctx, "REGULARIZATION_APPROVED")
    assert len(approved) == 1 and approved[0].details["auto_approved"] is True


# ------------------------------------------------------------------- R5


def test_R5_reject_needs_a_reason_of_1_to_500_characters(client, db, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    for bad in (None, "", "   ", "z" * 501):
        resp = _decide(client, org["boss"]["h"], reg, status="rejected", rejection_reason=bad)
        assert resp.status_code == 422, f"R5: reject reason {bad!r} must give 422, got {resp.text}"
    ok = _decide(client, org["boss"]["h"], reg, status="rejected", rejection_reason="  no proof  ")
    assert ok.status_code == 200 and ok.json()["rejection_reason"] == "no proof"


def test_R5_only_approved_or_rejected_and_no_unknown_fields(client, db, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    assert _decide(client, org["boss"]["h"], reg, status="maybe").status_code == 422
    assert _decide(client, org["boss"]["h"], reg, color="red").status_code == 422


def test_R5_a_second_decision_gives_409(client, db, org) -> None:
    ctx = org["ctx"]
    rec = _record(db, ctx, org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    assert _decide(client, org["boss"]["h"], reg).status_code == 200
    again = _decide(client, org["boss"]["h"], reg)
    assert again.status_code == 409, f"R5: a second decision must give 409: {again.text}"
    flip = _decide(client, org["boss"]["h"], reg, status="rejected", rejection_reason="late")
    assert flip.status_code == 409, "R5: approved then rejected must give 409"


def test_R5_a_decision_is_one_transaction_with_one_commit(client, db: Session, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    commits: list[int] = []

    def _count(_session: Session) -> None:
        commits.append(1)

    event.listen(db, "after_commit", _count)
    try:
        assert _decide(client, org["boss"]["h"], reg).status_code == 200
    finally:
        event.remove(db, "after_commit", _count)
    assert len(commits) == 1, f"R5: a decision must commit once, committed {len(commits)} times"


# ------------------------------------------------------------------- R6


def test_R6_approval_writes_times_hours_status_and_source(client, db, org) -> None:
    ctx = org["ctx"]
    rec = _record(db, ctx, org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    assert _decide(client, org["boss"]["h"], reg).status_code == 200
    row = client.get(f"{ATT}/{rec}", headers=ctx.hr_headers).json()
    assert Decimal(row["hours_worked"]) == Decimal("9.00"), f"R6: hours wrong: {row}"
    assert row["status"] == "present" and row["source"] == "regularized", f"R6: {row}"
    assert row["check_out"] is not None


def test_R6_hours_are_decimal_rounded_half_up(client, db, org) -> None:
    day = _day(3)
    rec = _record(db, org["ctx"], org["emp"]["id"])
    reg = _request(
        client,
        org["emp"]["h"],
        rec,
        requested_check_out=_at(day, 11, 0, 18).isoformat(),  # 2h 18s = 2.005 hours
    ).json()["id"]
    assert _decide(client, org["boss"]["h"], reg).status_code == 200
    row = client.get(f"{ATT}/{rec}", headers=org["ctx"].hr_headers).json()
    assert Decimal(row["hours_worked"]) == Decimal("2.01"), f"R6: half up expected 2.01, {row}"
    assert row["status"] == "half_day"


def test_R6_status_follows_the_company_threshold_and_under_one_hour_is_absent(
    client, db: Session, org
) -> None:
    ctx = org["ctx"]
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    row = db.query(CompanySettings).filter(CompanySettings.company_id == ctx.company_id).one()
    row.half_day_hours_threshold = Decimal("10")
    db.commit()
    day = _day(3)
    rec = _record(db, ctx, org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    assert _decide(client, org["boss"]["h"], reg).status_code == 200
    assert client.get(f"{ATT}/{rec}", headers=ctx.hr_headers).json()["status"] == "half_day", (
        "R6: 9 hours is under a 10 hour threshold"
    )
    short = _record(db, ctx, org["colleague"]["id"], days_ago=4)
    reg2 = _request(
        client,
        org["colleague"]["h"],
        short,
        days_ago=4,
        requested_check_out=_at(_day(4), 9, 30).isoformat(),
    ).json()["id"]
    assert _decide(client, org["hr2"]["h"], reg2).status_code == 200
    assert client.get(f"{ATT}/{short}", headers=ctx.hr_headers).json()["status"] == "absent"
    assert day is not None


def test_R6_the_approver_can_adjust_the_times(client, db, org) -> None:
    day = _day(3)
    rec = _record(db, org["ctx"], org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    resp = _decide(client, org["boss"]["h"], reg, adjusted_check_out=_at(day, 15).isoformat())
    assert resp.status_code == 200, resp.text
    row = client.get(f"{ATT}/{rec}", headers=org["ctx"].hr_headers).json()
    assert Decimal(row["hours_worked"]) == Decimal("6.00"), f"R6: adjusted time ignored: {row}"


def test_R6_a_day_with_approved_leave_is_never_touched(client, db: Session, org) -> None:
    ctx = org["ctx"]
    rec = _record(db, ctx, org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    _approved_leave_on(client, db, ctx, org["emp"]["id"], _day(3))
    resp = _decide(client, org["boss"]["h"], reg)
    assert resp.status_code == 409, f"R6: a day on approved leave must give 409, got {resp.text}"
    row = client.get(f"{ATT}/{rec}", headers=ctx.hr_headers).json()
    assert row["check_out"] is None, "R6: the record must stay untouched"
    still = client.get(f"{ATT}/{rec}/regularization", headers=ctx.hr_headers).json()
    assert still["status"] == "pending"


def test_R6_a_request_for_a_day_on_approved_leave_is_refused(client, db: Session, org) -> None:
    ctx = org["ctx"]
    rec = _record(db, ctx, org["emp"]["id"])
    _approved_leave_on(client, db, ctx, org["emp"]["id"], _day(3))
    resp = _request(client, org["emp"]["h"], rec)
    assert resp.status_code == 409, f"R6: requests on a leave day must give 409: {resp.text}"


def _approved_leave_on(
    client, db: Session, ctx: TenantContext, employee_id: str, day: date
) -> None:
    lt = client.post(
        "/api/v1/leave-types",
        headers=ctx.hr_headers,
        json={"name": f"LT {uuid.uuid4().hex[:6]}", "code": f"L{uuid.uuid4().hex[:8].upper()}"},
    ).json()
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.add(
        Leave(
            company_id=ctx.company_id,
            employee_id=uuid.UUID(employee_id),
            leave_type_id=uuid.UUID(lt["id"]),
            start_date=day,
            end_date=day,
            total_days=Decimal("1"),
            reason="seeded",
            status=LeaveStatus.approved,
        )
    )
    db.commit()


# ------------------------------------------------------------------- R7


def test_R7_reading_a_request_is_limited_to_requester_approvers_and_hr(client, db, org) -> None:
    ctx = org["ctx"]
    rec = _record(db, ctx, org["emp"]["id"])
    made = _request(client, org["emp"]["h"], rec).json()
    url = f"{ATT}/{rec}/regularization"
    for who in ("emp", "boss", "senior", "hr2", "owner"):
        resp = client.get(url, headers=org[who]["h"])
        assert resp.status_code == 200 and resp.json()["id"] == made["id"], (
            f"R7: {who}: {resp.text}"
        )
    assert client.get(url, headers=ctx.hr_headers).status_code == 200
    for who in ("colleague", "outsider"):
        resp = client.get(url, headers=org[who]["h"])
        assert resp.status_code == 403, f"R7: {who} must get 403, got {resp.status_code}"


def test_R7_other_company_and_missing_record_give_the_same_404(
    client, db, org, company_b: TenantContext
) -> None:
    foreign_emp = _create_employee(client, company_b.hr_headers)
    foreign = _record(db, company_b, foreign_emp["id"])
    other = client.get(f"{ATT}/{foreign}/regularization", headers=org["ctx"].hr_headers)
    missing = client.get(f"{ATT}/{uuid.uuid4()}/regularization", headers=org["ctx"].hr_headers)
    assert other.status_code == 404 == missing.status_code
    assert other.json()["error"]["message"] == missing.json()["error"]["message"]


def test_R7_a_record_without_a_request_reads_as_null_for_the_allowed_and_403_for_others(
    client, db, org
) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    url = f"{ATT}/{rec}/regularization"
    assert client.get(url, headers=org["emp"]["h"]).json() is None
    assert client.get(url, headers=org["colleague"]["h"]).status_code == 403


def test_R7_attachment_download_follows_the_same_access_rule(client, db, org, company_b) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    made = client.post(
        f"{ATT}/{rec}/regularize",
        headers=org["emp"]["h"],
        data={"requested_check_out": _at(_day(3), 18).isoformat(), "reason": "with proof"},
        files={"attachment": ("proof.pdf", PDF, "application/pdf")},
    )
    assert made.status_code == 201, made.text
    url = made.json()["attachment_url"]
    for who in ("emp", "boss", "hr2"):
        assert client.get(url, headers=org[who]["h"]).status_code == 200, f"R7: {who}"
    for who in ("colleague", "outsider"):
        assert client.get(url, headers=org[who]["h"]).status_code == 403, f"R7: {who}"
    assert client.get(url, headers=company_b.hr_headers).status_code == 404
    assert client.get(url).status_code == 401


# ------------------------------------------------------------------- R8


def _with_file(client, org, db, name: str, content: bytes, mime: str, days_ago: int = 3):
    rec = _record(db, org["ctx"], org["emp"]["id"], days_ago=days_ago)
    return client.post(
        f"{ATT}/{rec}/regularize",
        headers=org["emp"]["h"],
        data={
            "requested_check_out": _at(_day(days_ago), 18).isoformat(),
            "reason": "attachment test",
        },
        files={"attachment": (name, content, mime)},
    )


def test_R8_pdf_png_jpg_jpeg_are_accepted_and_stored_under_a_server_name(
    client, db, org, upload_dir: Path
) -> None:
    jpeg = b"\xff\xd8\xff" + b"0" * 20
    for days_ago, (name, content, mime) in enumerate(
        (
            ("../../Evil Name.pdf", PDF, "application/pdf"),
            ("a.png", PNG, "image/png"),
            ("b.jpg", jpeg, "image/jpeg"),
            ("c.jpeg", jpeg, "image/jpeg"),
        ),
        start=2,
    ):
        rec = _record(db, org["ctx"], org["emp"]["id"], days_ago=days_ago)
        resp = client.post(
            f"{ATT}/{rec}/regularize",
            headers=org["emp"]["h"],
            data={
                "requested_check_out": _at(_day(days_ago), 18).isoformat(),
                "reason": "attachment test",
            },
            files={"attachment": (name, content, mime)},
        )
        assert resp.status_code == 201, f"R8: {name} must be accepted: {resp.text}"
        stored = resp.json()["attachment_url"].rsplit("/", 1)[-1]
        assert re.fullmatch(r"[0-9a-f-]{36}\.(pdf|png|jpg|jpeg)", stored), (
            f"R8: stored name must be server made, got {stored}"
        )
        assert (upload_dir / stored).read_bytes() == content


def test_R8_other_types_and_mismatching_content_are_refused(client, db, org, upload_dir) -> None:
    docx = b"PK\x03\x04" + b"0" * 30
    cases = (
        ("run.exe", b"MZ" + b"0" * 20, "application/octet-stream"),
        ("notes.txt", b"hello", "text/plain"),
        (
            "letter.docx",
            docx,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("fake.pdf", b"not a pdf", "application/pdf"),
        ("fake.png", PDF, "image/png"),
        ("noext", PDF, "application/pdf"),
        ("empty.pdf", b"", "application/pdf"),
    )
    for days_ago, (name, content, mime) in enumerate(cases, start=2):
        resp = _with_file(client, org, db, name, content, mime, days_ago)
        assert resp.status_code in (415, 422), f"R8: {name} must be refused, got {resp.status_code}"
    assert list(upload_dir.iterdir()) == [], "R8: a refused file must not be stored"


def test_R8_a_file_over_the_size_cap_gives_413(
    client, db, org, monkeypatch: pytest.MonkeyPatch, upload_dir
) -> None:
    monkeypatch.setattr("app.modules.time_leave.router.MAX_FILE_UPLOAD_BYTES", 1024, raising=False)
    resp = _with_file(client, org, db, "big.pdf", PDF + b"0" * 2048, "application/pdf")
    assert resp.status_code == 413, f"R8: oversize file must give 413, got {resp.status_code}"
    assert list(upload_dir.iterdir()) == []


def test_R8_the_size_cap_is_the_shared_upload_cap() -> None:
    from app.core.upload_validation import MAX_FILE_UPLOAD_BYTES as shared
    from app.modules.time_leave import router

    used = getattr(router, "MAX_FILE_UPLOAD_BYTES", None)
    assert used == shared, "R8: attachments must use the 3.3 size cap"


# ------------------------------------------------------------------- R9


def test_R9_request_and_decisions_write_one_audit_row_without_free_text(client, db, org) -> None:
    ctx = org["ctx"]
    rec = _record(db, ctx, org["emp"]["id"])
    made = client.post(
        f"{ATT}/{rec}/regularize",
        headers=org["emp"]["h"],
        data={
            "requested_check_out": _at(_day(3), 18).isoformat(),
            "reason": "Very private reason text",
        },
        files={"attachment": ("secret-file-name.pdf", PDF, "application/pdf")},
    )
    reg_id = uuid.UUID(made.json()["id"])
    requested = _audit(db, ctx, "REGULARIZATION_REQUESTED")
    assert len(requested) == 1 and requested[0].entity_id == reg_id, "R9: REQUESTED row missing"
    assert requested[0].details["attendance_id"] == rec

    assert _decide(client, org["boss"]["h"], str(reg_id)).status_code == 200
    approved = _audit(db, ctx, "REGULARIZATION_APPROVED")
    assert len(approved) == 1 and approved[0].entity_id == reg_id, "R9: APPROVED row missing"

    rec2 = _record(db, ctx, org["colleague"]["id"], days_ago=4)
    reg2 = _request(client, org["colleague"]["h"], rec2, days_ago=4).json()["id"]
    _decide(client, org["hr2"]["h"], reg2, status="rejected", rejection_reason="Private rejection")
    rejected = _audit(db, ctx, "REGULARIZATION_REJECTED")
    assert len(rejected) == 1 and rejected[0].entity_id == uuid.UUID(reg2), "R9: REJECTED missing"

    blob = " ".join(str(r.details) for r in (*requested, *approved, *rejected))
    for secret in ("Very private", "secret-file-name", "Private rejection", ".pdf"):
        assert secret not in blob, f"R9: {secret!r} leaked into an audit row"


def test_R9_failed_requests_write_no_audit_row(client, db, org) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    assert _request(client, org["emp"]["h"], rec).status_code == 201
    assert _request(client, org["emp"]["h"], rec).status_code == 409
    assert len(_audit(db, org["ctx"], "REGULARIZATION_REQUESTED")) == 1


def test_R9_the_manager_and_requester_are_notified_and_the_employee_on_decision(
    client, db, org
) -> None:
    ctx = org["ctx"]
    rec = _record(db, ctx, org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    assert len(_notes_for(db, ctx, org["boss"]["user"].id, "regularization_requested")) == 1, (
        "R9: the manager must be notified of the request"
    )
    assert len(_notes_for(db, ctx, org["emp"]["user"].id, "regularization_submitted")) == 1, (
        "R9: the requester must be notified of the submission"
    )
    assert _decide(client, org["boss"]["h"], reg).status_code == 200
    assert len(_notes_for(db, ctx, org["emp"]["user"].id, "regularization_approved")) == 1
    rec2 = _record(db, ctx, org["emp"]["id"], days_ago=4)
    reg2 = _request(client, org["emp"]["h"], rec2, days_ago=4).json()["id"]
    _decide(client, org["boss"]["h"], reg2, status="rejected", rejection_reason="no")
    assert len(_notes_for(db, ctx, org["emp"]["user"].id, "regularization_rejected")) == 1


def test_R9_requests_are_limited_to_10_per_minute(client, db, org, limits_on) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    codes = [_request(client, org["emp"]["h"], rec).status_code for _ in range(11)]
    assert 429 not in codes[:10] and codes[10] == 429, f"R9: request limit wrong: {codes}"


def test_R9_decisions_are_limited_to_10_per_minute(client, db, org, limits_on) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    reg = _request(client, org["emp"]["h"], rec).json()["id"]
    codes = [_decide(client, org["boss"]["h"], reg).status_code for _ in range(11)]
    assert 429 not in codes[:10] and codes[10] == 429, f"R9: decision limit wrong: {codes}"


def test_R9_reads_are_limited_to_60_per_minute(client, db, org, limits_on) -> None:
    rec = _record(db, org["ctx"], org["emp"]["id"])
    url = f"{ATT}/{rec}/regularization"
    codes = [client.get(url, headers=org["emp"]["h"]).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429, f"R9: read limit wrong: {codes[-3:]}"


def test_R9_attachment_downloads_are_limited_to_60_per_minute(client, db, org, limits_on) -> None:
    resp = _with_file(client, org, db, "p.pdf", PDF, "application/pdf")
    url = resp.json()["attachment_url"]
    limiter.reset()
    codes = [client.get(url, headers=org["emp"]["h"]).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429, f"R9: download limit wrong: {codes[-3:]}"


# ------------------------------------------------------------ R3 migration


def test_R3_migration_index_round_trip_and_loud_failure_on_duplicates() -> None:
    assert settings.TEST_MIGRATION_URL is not None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        engine = create_engine(settings.TEST_MIGRATION_URL)
        cfg = Config(str(_repo_root() / "alembic.ini"))
        cid = uuid.uuid4()
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        assert len(heads) == 1, f"R3: there must be a single head: {heads}"
        chain = {rev.revision for rev in script.walk_revisions()}
        assert MIGRATION_REVISION in chain, "R3: the migration is not part of the history"
        command.downgrade(cfg, PREVIOUS_REVISION)
        command.upgrade(cfg, MIGRATION_REVISION)
        try:
            names = {i["name"] for i in inspect(engine).get_indexes("attendance_regularizations")}
            assert "uq_attendance_regularizations_pending" in names, "R3: pending index missing"

            command.downgrade(cfg, PREVIOUS_REVISION)
            names = {i["name"] for i in inspect(engine).get_indexes("attendance_regularizations")}
            assert "uq_attendance_regularizations_pending" not in names, "R3: downgrade kept index"

            day = _day(3)
            with Session(engine) as sess:
                sess.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
                sess.add(
                    Company(
                        id=cid,
                        name="Reg Migration Co",
                        code=f"RMC{uuid.uuid4().hex[:4].upper()}",
                        email=f"rmc-{uuid.uuid4().hex[:6]}@example.com",
                        status=CompanyStatus.active,
                        is_active=True,
                    )
                )
                sess.flush()
                emp = Employee(
                    id=uuid.uuid4(),
                    company_id=cid,
                    employee_code=f"EMP{uuid.uuid4().hex[:4].upper()}",
                    first_name="Mig",
                    last_name="Rate",
                    email=f"mig-{uuid.uuid4().hex[:6]}@example.com",
                    hire_date=day,
                    is_active=True,
                )
                sess.add(emp)
                sess.flush()
                att = Attendance(
                    company_id=cid,
                    employee_id=emp.id,
                    date=day,
                    status=AttendanceStatus.mispunch,
                    source=AttendanceSource.web,
                )
                sess.add(att)
                sess.flush()
                for _ in range(2):
                    sess.add(
                        AttendanceRegularizationRequest(
                            company_id=cid,
                            attendance_id=att.id,
                            employee_id=emp.id,
                            reason="dup",
                            status=RegularizationStatus.pending,
                        )
                    )
                sess.commit()
            with pytest.raises(RuntimeError) as exc:
                command.upgrade(cfg, MIGRATION_REVISION)
            message = str(exc.value).lower()
            assert "duplicate" in message and "pending" in message, f"R3: unclear message {message}"
        finally:
            _purge_company(cid)
            command.upgrade(cfg, "head")
            engine.dispose()


def _repo_root() -> Path:
    from tests.conftest import REPO_ROOT

    return Path(REPO_ROOT)
