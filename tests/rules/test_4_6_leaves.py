"""Module 4, sub-feature 4.6: Leave requests and approvals. One test per rule line (R1..R10).

Dates are computed from utcnow(). The company leave year is moved so that its boundary is
about six months away, which keeps every "next few weeks" test inside one leave year.
"""

import threading
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import Employee, ResignationStatus
from app.modules.hr.schemas import EmployeeCreateRequest
from app.modules.hr.service import EmployeeService
from app.modules.identity.models import (
    Company,
    CompanySettings,
    CompanyStatus,
    LeaveYearType,
    User,
    UserRole,
)
from app.modules.platform.models import AuditLog, Notification
from app.modules.time_leave.models import (
    Attendance,
    AttendanceSource,
    AttendanceStatus,
    LeaveBalance,
)
from tests.conftest import TenantContext
from tests.rules.test_4_2_punch import _create_employee, _link_user_to_employee  # noqa: F401
from tests.rules.test_4_3_regularization import _purge_company, org  # noqa: F401

LEAVES = "/api/v1/leaves"


@pytest.fixture
def limits_on():
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = False


def _boundary_month(today: date) -> int:
    return (today.month + 5) % 12 + 1


@pytest.fixture
def world(client: TestClient, db: Session, org: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    """The 4.3 organisation plus a leave year whose boundary is about six months away and
    a paid leave type with 10 days."""
    ctx: TenantContext = org["ctx"]
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    row = db.query(CompanySettings).filter(CompanySettings.company_id == ctx.company_id).one()
    row.leave_year_type = LeaveYearType.financial
    row.leave_year_start_month = _boundary_month(utcnow().date())
    db.commit()
    org["lt"] = _leave_type(client, ctx.hr_headers)
    return org


def _leave_type(client: TestClient, headers: dict[str, str], **over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": f"LT {uuid.uuid4().hex[:8]}",
        "code": f"L{uuid.uuid4().hex[:8].upper()}",
        "annual_allowance": "10",
    }
    payload.update(over)
    resp = client.post("/api/v1/leave-types", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _monday(weeks_ahead: int = 1) -> date:
    day = utcnow().date() + timedelta(days=1)
    while day.isoweekday() != 1:
        day += timedelta(days=1)
    return day + timedelta(weeks=weeks_ahead - 1)


def _apply(client: TestClient, headers: dict[str, str], lt_id: str, start: date, end: date, **over):
    body: dict[str, Any] = {
        "leave_type_id": lt_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "reason": "Family trip",
    }
    body.update(over)
    return client.post(LEAVES, headers=headers, json=body)


def _decide(client: TestClient, headers: dict[str, str], leave_id: str, **body: Any):
    payload = {"status": "approved"}
    payload.update(body)
    return client.put(f"{LEAVES}/{leave_id}", headers=headers, json=payload)


def _audit(db: Session, ctx: TenantContext, action: str) -> list[AuditLog]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    return (
        db.query(AuditLog)
        .filter(AuditLog.company_id == ctx.company_id, AuditLog.action == action)
        .all()
    )


def _notes(db: Session, ctx: TenantContext, user_id: uuid.UUID, kind: str) -> list[Notification]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.type == kind)
        .all()
    )


def _balance(db: Session, ctx: TenantContext, employee_id: str, lt_id: str) -> LeaveBalance | None:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.expire_all()
    return (
        db.query(LeaveBalance)
        .filter(
            LeaveBalance.employee_id == uuid.UUID(employee_id),
            LeaveBalance.leave_type_id == uuid.UUID(lt_id),
        )
        .first()
    )


def _attendance_rows(db: Session, ctx: TenantContext, employee_id: str) -> list[Attendance]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.expire_all()
    return (
        db.query(Attendance)
        .filter(Attendance.employee_id == uuid.UUID(employee_id), Attendance.deleted_at.is_(None))
        .order_by(Attendance.date)
        .all()
    )


def _punch(db: Session, ctx: TenantContext, employee_id: str, day: date) -> None:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.add(
        Attendance(
            company_id=ctx.company_id,
            employee_id=uuid.UUID(employee_id),
            date=day,
            check_in=datetime(day.year, day.month, day.day, 9, tzinfo=UTC),
            check_out=datetime(day.year, day.month, day.day, 18, tzinfo=UTC),
            hours_worked=Decimal("9.00"),
            status=AttendanceStatus.present,
            source=AttendanceSource.web,
        )
    )
    db.commit()


# ------------------------------------------------------------------- R1


def test_R1_no_login_gets_401(client: TestClient) -> None:
    assert client.post(LEAVES, json={}).status_code == 401
    assert client.get(LEAVES).status_code == 401
    assert client.get(f"{LEAVES}/{uuid.uuid4()}").status_code == 401
    assert client.put(f"{LEAVES}/{uuid.uuid4()}", json={}).status_code == 401
    assert client.delete(f"{LEAVES}/{uuid.uuid4()}").status_code == 401


def test_R1_employee_applies_for_themselves(client, world) -> None:
    resp = _apply(client, world["emp"]["h"], world["lt"]["id"], _monday(), _monday())
    assert resp.status_code == 201, f"R1: own application must give 201: {resp.text}"
    body = resp.json()
    assert body["status"] == "pending" and body["employee_id"] == world["emp"]["id"]


def test_R1_manager_applies_for_a_direct_report_only(client, world) -> None:
    lt = world["lt"]["id"]
    ok = _apply(
        client, world["boss"]["h"], lt, _monday(), _monday(), employee_id=world["emp"]["id"]
    )
    assert ok.status_code == 201 and ok.json()["employee_id"] == world["emp"]["id"], ok.text
    stranger = _apply(
        client, world["boss"]["h"], lt, _monday(), _monday(), employee_id=world["colleague"]["id"]
    )
    assert stranger.status_code == 403, (
        f"R1: manager for a non-report must give 403: {stranger.text}"
    )


def test_R1_an_employee_cannot_apply_for_someone_else(client, world) -> None:
    resp = _apply(
        client,
        world["emp"]["h"],
        world["lt"]["id"],
        _monday(),
        _monday(),
        employee_id=world["colleague"]["id"],
    )
    assert resp.status_code == 403, f"R1: employee for someone else must give 403: {resp.text}"


def test_R1_hr_level_applies_for_anyone_in_the_company(client, world) -> None:
    lt = world["lt"]["id"]
    for who, offset in (("hr2", 1), ("owner", 2), ("sadmin", 3)):
        resp = _apply(
            client,
            world[who]["h"],
            lt,
            _monday(offset),
            _monday(offset),
            employee_id=world["colleague"]["id"],
        )
        assert resp.status_code == 201, f"R1: {who} must apply for anyone: {resp.text}"
    resp = _apply(
        client,
        world["ctx"].hr_headers,
        lt,
        _monday(4),
        _monday(4),
        employee_id=world["colleague"]["id"],
    )
    assert resp.status_code == 201


def test_R1_other_company_and_missing_employee_give_the_same_404(
    client, db, world, company_b: TenantContext
) -> None:
    foreign = _create_employee(client, company_b.hr_headers)
    lt = world["lt"]["id"]
    other = _apply(client, world["hr2"]["h"], lt, _monday(), _monday(), employee_id=foreign["id"])
    missing = _apply(
        client, world["hr2"]["h"], lt, _monday(), _monday(), employee_id=str(uuid.uuid4())
    )
    assert other.status_code == 404 == missing.status_code, f"R1: {other.text} / {missing.text}"
    assert other.json()["error"]["message"] == missing.json()["error"]["message"]


def test_R1_unknown_fields_give_422(client, world) -> None:
    resp = _apply(
        client, world["emp"]["h"], world["lt"]["id"], _monday(), _monday(), status="approved"
    )
    assert resp.status_code == 422, f"R1: unknown field must give 422: {resp.text}"
    resp = client.put(
        f"{LEAVES}/{uuid.uuid4()}", headers=world["boss"]["h"], json={"status": "approved", "x": 1}
    )
    assert resp.status_code == 422, "R1: unknown field on a decision must give 422"


# ------------------------------------------------------------------- R2


def test_R2_end_before_start_is_refused(client, world) -> None:
    resp = _apply(
        client, world["emp"]["h"], world["lt"]["id"], _monday() + timedelta(days=2), _monday()
    )
    assert resp.status_code == 400, f"R2: end before start must be refused: {resp.text}"
    assert resp.json()["error"]["code"] == "invalid_leave_request"


def test_R2_a_start_in_the_past_is_refused_for_employees_and_allowed_for_hr_with_an_audit(
    client, db, world
) -> None:
    ctx = world["ctx"]
    day = utcnow().date() - timedelta(days=14)
    while day.isoweekday() > 5:
        day -= timedelta(days=1)
    denied = _apply(client, world["emp"]["h"], world["lt"]["id"], day, day)
    assert denied.status_code == 400, f"R2: employee back-dating must be refused: {denied.text}"
    ok = _apply(
        client, world["hr2"]["h"], world["lt"]["id"], day, day, employee_id=world["emp"]["id"]
    )
    assert ok.status_code == 201, f"R2: HR may back-date: {ok.text}"
    rows = _audit(db, ctx, "LEAVE_APPLIED")
    assert len(rows) == 1 and rows[0].details["back_dated"] is True, "R2: back-dating not audited"


def test_R2_no_start_after_an_approved_last_working_date(client, db: Session, world) -> None:
    ctx = world["ctx"]
    start = _monday()
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    emp = db.get(Employee, uuid.UUID(world["emp"]["id"]))
    emp.resignation_status = ResignationStatus.approved
    emp.last_working_date = start - timedelta(days=1)
    db.commit()
    resp = _apply(client, world["emp"]["h"], world["lt"]["id"], start, start)
    assert resp.status_code == 422, f"R2: start after last working date must give 422: {resp.text}"
    emp.last_working_date = start
    db.commit()
    ok = _apply(client, world["emp"]["h"], world["lt"]["id"], start, start)
    assert ok.status_code == 201, f"R2: starting on the last working day is allowed: {ok.text}"


def test_R2_reason_is_trimmed_and_limited_to_1_to_500(client, world) -> None:
    lt = world["lt"]["id"]
    for bad in ("", "   ", "r" * 501):
        resp = _apply(client, world["emp"]["h"], lt, _monday(), _monday(), reason=bad)
        assert resp.status_code == 422, f"R2: reason of length {len(bad)} must give 422"
    ok = _apply(client, world["emp"]["h"], lt, _monday(), _monday(), reason="  go  ")
    assert ok.status_code == 201
    assert (
        client.get(f"{LEAVES}/{ok.json()['id']}", headers=world["emp"]["h"]).json()["reason"]
        == "go"
    )
    longest = _apply(client, world["emp"]["h"], lt, _monday(2), _monday(2), reason="r" * 500)
    assert longest.status_code == 201


# ------------------------------------------------------------------- R3


def test_R3_days_exclude_weekends_and_mandatory_holidays_only(client, db: Session, world) -> None:
    ctx = world["ctx"]
    monday = _monday()
    for offset, optional in ((2, False), (3, True)):
        resp = client.post(
            "/api/v1/holidays",
            headers=ctx.hr_headers,
            json={
                "name": f"H{offset}",
                "date": (monday + timedelta(days=offset)).isoformat(),
                "is_optional": optional,
            },
        )
        assert resp.status_code == 201, resp.text
    resp = _apply(client, world["emp"]["h"], world["lt"]["id"], monday, monday + timedelta(days=6))
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["total_days"]) == Decimal("4"), (
        f"R3: Mon-Sun with one mandatory and one optional holiday is 4 days: {resp.json()}"
    )


def test_R3_a_range_with_no_working_days_gives_422(client, db, world) -> None:
    ctx = world["ctx"]
    saturday = _monday() + timedelta(days=5)
    resp = _apply(
        client, world["emp"]["h"], world["lt"]["id"], saturday, saturday + timedelta(days=1)
    )
    assert resp.status_code == 422, f"R3: weekend only must give 422: {resp.text}"
    assert "no working days" in resp.json()["error"]["message"].lower()
    holiday_day = _monday(2)
    client.post(
        "/api/v1/holidays",
        headers=ctx.hr_headers,
        json={"name": "Only day", "date": holiday_day.isoformat()},
    )
    resp = _apply(client, world["emp"]["h"], world["lt"]["id"], holiday_day, holiday_day)
    assert resp.status_code == 422, f"R3: a single holiday must give 422: {resp.text}"


def test_R3_half_day_is_one_date_only_and_counts_half(client, world) -> None:
    lt = world["lt"]["id"]
    monday = _monday()
    one = _apply(client, world["emp"]["h"], lt, monday, monday, is_half_day=True)
    assert one.status_code == 201 and Decimal(one.json()["total_days"]) == Decimal("0.5"), one.text
    many = _apply(
        client, world["emp"]["h"], lt, _monday(2), _monday(2) + timedelta(days=1), is_half_day=True
    )
    assert many.status_code == 422, f"R3: half day over two dates must give 422: {many.text}"
    saturday = _monday(3) + timedelta(days=5)
    weekend = _apply(client, world["emp"]["h"], lt, saturday, saturday, is_half_day=True)
    assert weekend.status_code == 422, f"R3: half day on a weekend must give 422: {weekend.text}"


def test_R3_a_leave_cannot_cross_the_leave_year(client, world) -> None:
    today = utcnow().date()
    month = _boundary_month(today)
    boundary = date(today.year if month > today.month else today.year + 1, month, 1)
    resp = _apply(
        client,
        world["hr2"]["h"],
        world["lt"]["id"],
        boundary - timedelta(days=4),
        boundary + timedelta(days=4),
        employee_id=world["emp"]["id"],
    )
    assert resp.status_code == 422, f"R3: crossing the leave year must give 422: {resp.text}"
    assert "leave year" in resp.json()["error"]["message"].lower()


def test_R3_max_consecutive_days_counts_working_days(client, world) -> None:
    lt = _leave_type(client, world["ctx"].hr_headers, max_consecutive_days=3)["id"]
    friday = _monday() + timedelta(days=4)
    ok = _apply(client, world["emp"]["h"], lt, friday, friday + timedelta(days=3))
    assert ok.status_code == 201, f"R3: Fri-Mon is two working days: {ok.text}"
    monday = _monday(2)
    over = _apply(client, world["emp"]["h"], lt, monday, monday + timedelta(days=4))
    assert over.status_code == 400, f"R3: five working days exceed 3: {over.text}"
    assert over.json()["error"]["details"]["max_consecutive_days"] == 3


# ------------------------------------------------------------------- R4


def test_R4_pending_leaves_count_against_the_balance_at_apply(client, db, world) -> None:
    lt = _leave_type(client, world["ctx"].hr_headers, annual_allowance="5")["id"]
    first = _apply(client, world["emp"]["h"], lt, _monday(), _monday() + timedelta(days=2))
    assert first.status_code == 201, first.text
    second = _apply(client, world["emp"]["h"], lt, _monday(2), _monday(2) + timedelta(days=2))
    assert second.status_code == 409, f"R4: 3 pending + 3 asked of 5 must give 409: {second.text}"
    details = second.json()["error"]["details"]
    assert Decimal(details["available"]) == Decimal("2") and Decimal(details["requested"]) == 3, (
        f"R4: available must already exclude pending days: {details}"
    )
    cancelled = client.delete(f"{LEAVES}/{first.json()['id']}", headers=world["emp"]["h"])
    assert cancelled.status_code == 200
    again = _apply(client, world["emp"]["h"], lt, _monday(2), _monday(2) + timedelta(days=2))
    assert again.status_code == 201, f"R4: a cancelled leave frees its days: {again.text}"


def test_R4_unpaid_types_skip_the_balance_check(client, world) -> None:
    lt = _leave_type(client, world["ctx"].hr_headers, annual_allowance="0", is_paid=False)["id"]
    resp = _apply(client, world["emp"]["h"], lt, _monday(), _monday() + timedelta(days=4))
    assert resp.status_code == 201, f"R4: unpaid leave is never balance-checked: {resp.text}"


def test_R4_the_balance_is_re_checked_under_a_lock_at_approval(client, db: Session, world) -> None:
    ctx = world["ctx"]
    lt = _leave_type(client, ctx.hr_headers, annual_allowance="4")["id"]
    a = _apply(client, world["emp"]["h"], lt, _monday(), _monday() + timedelta(days=1)).json()
    b = _apply(client, world["emp"]["h"], lt, _monday(2), _monday(2) + timedelta(days=1)).json()
    balance = _balance(db, ctx, world["emp"]["id"], lt)
    assert balance is not None
    balance.used = Decimal("2")  # only two days are really left
    db.commit()

    statements: list[str] = []

    def _capture(conn, cursor, statement, *args):  # noqa: ANN001
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", _capture)
    try:
        first = _decide(client, world["boss"]["h"], a["id"])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", _capture)
    assert first.status_code == 200, first.text
    assert any("FOR UPDATE" in s.upper() and "leave_balances" in s for s in statements), (
        "R4: the balance row must be locked at approval"
    )
    second = _decide(client, world["boss"]["h"], b["id"])
    assert second.status_code == 409, f"R4: the second approval must give 409: {second.text}"
    assert (
        client.get(f"{LEAVES}/{b['id']}", headers=world["emp"]["h"]).json()["status"] == "pending"
    )
    assert _balance(db, ctx, world["emp"]["id"], lt).used == Decimal("4"), "R4: balance overspent"


# ------------------------------------------------------------------- R5


def test_R5_overlap_with_pending_or_approved_gives_409_naming_the_leaves(client, world) -> None:
    lt = world["lt"]["id"]
    monday = _monday()
    first = _apply(client, world["emp"]["h"], lt, monday, monday + timedelta(days=2)).json()
    clash = _apply(
        client, world["emp"]["h"], lt, monday + timedelta(days=2), monday + timedelta(days=3)
    )
    assert clash.status_code == 409, f"R5: overlap must give 409: {clash.text}"
    conflicts = clash.json()["error"]["details"]["conflicts"]
    assert conflicts[0]["id"] == first["id"]
    assert conflicts[0]["start_date"] == monday.isoformat()
    assert _decide(client, world["boss"]["h"], first["id"]).status_code == 200
    again = _apply(client, world["emp"]["h"], lt, monday, monday)
    assert again.status_code == 409, "R5: an approved leave also blocks"
    adjacent = _apply(
        client, world["emp"]["h"], lt, monday + timedelta(days=3), monday + timedelta(days=3)
    )
    assert adjacent.status_code == 201, f"R5: the next day is free: {adjacent.text}"


def test_R5_rejected_and_cancelled_leaves_do_not_block(client, world) -> None:
    lt = world["lt"]["id"]
    monday = _monday()
    rejected = _apply(client, world["emp"]["h"], lt, monday, monday).json()
    assert (
        _decide(
            client, world["boss"]["h"], rejected["id"], status="rejected", rejection_reason="busy"
        ).status_code
        == 200
    )
    cancelled = _apply(client, world["emp"]["h"], lt, monday, monday).json()
    assert (
        client.delete(f"{LEAVES}/{cancelled['id']}", headers=world["emp"]["h"]).status_code == 200
    )
    assert _apply(client, world["emp"]["h"], lt, monday, monday).status_code == 201


def test_R5_two_simultaneous_applications_give_one_201_and_one_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.time_leave.repository import LeaveRepository

    original = LeaveRepository.get_overlapping

    def _slow_overlap(self, **kwargs):  # noqa: ANN001, ANN003
        found = original(self, **kwargs)
        time.sleep(0.5)  # widen the race: both requests have looked before either one saves
        return found

    monkeypatch.setattr(LeaveRepository, "get_overlapping", _slow_overlap)
    assert settings.TEST_DATABASE_URL is not None
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    cid = uuid.uuid4()
    today = utcnow().date()
    try:
        with Session(engine) as setup:
            setup.add(
                Company(
                    id=cid,
                    name="Leave Race Co",
                    code=f"LRC{uuid.uuid4().hex[:4].upper()}",
                    email=f"lrc-{uuid.uuid4().hex[:6]}@example.com",
                    status=CompanyStatus.active,
                    is_active=True,
                )
            )
            setup.flush()
            bind_tenant_to_session(setup, company_id=cid, is_platform_admin=False)
            setup.add(
                CompanySettings(
                    company_id=cid,
                    leave_year_type=LeaveYearType.financial,
                    leave_year_start_month=_boundary_month(today),
                )
            )
            user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"user-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.employee,
                is_active=True,
            )
            setup.add(user)
            setup.flush()
            owner_user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"own-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.owner,
                is_active=True,
            )
            setup.add(owner_user)
            setup.flush()
            emp, _ = EmployeeService(setup).create_employee(
                cid,
                EmployeeCreateRequest(
                    first_name="Leave",
                    last_name="Racer",
                    email=f"racer-{uuid.uuid4().hex[:6]}@example.com",
                    employment_type="full_time",
                    hire_date=today - timedelta(days=400),
                ),
                actor=owner_user,
            )
            emp.user_id = user.id
            setup.commit()
            token = create_access_token(sub=str(user.id), company_id=str(cid), role="employee")
            owner_token = create_access_token(
                sub=str(owner_user.id), company_id=str(cid), role="owner"
            )
        assert owner_token
        _seed_leave_type(engine, cid)
        headers = {"Authorization": f"Bearer {token}"}
        lt_id = _first_leave_type(engine, cid)

        def _get_test_db():
            session = Session(engine)
            try:
                yield session
            finally:
                session.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db
        barrier = threading.Barrier(2)
        results: list[int] = []
        start = _monday()

        def _worker() -> None:
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                results.append(
                    _apply(c, headers, lt_id, start, start + timedelta(days=1)).status_code
                )
            except Exception:
                results.append(999)

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert 500 not in results and 999 not in results, f"R5: race gave an error: {results}"
        assert sorted(results) == [201, 409], f"R5: expected one 201 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        _purge_company(cid)


def _seed_leave_type(engine, cid: uuid.UUID) -> None:
    from app.modules.time_leave.models import LeaveType

    with Session(engine) as sess:
        bind_tenant_to_session(sess, company_id=cid, is_platform_admin=False)
        sess.add(
            LeaveType(
                company_id=cid,
                name="Race leave",
                code="RACE1",
                annual_allowance=Decimal("10"),
                carry_forward_limit=Decimal("0"),
            )
        )
        sess.commit()


def _first_leave_type(engine, cid: uuid.UUID) -> str:
    from app.modules.time_leave.models import LeaveType

    with Session(engine) as sess:
        bind_tenant_to_session(sess, company_id=cid, is_platform_admin=False)
        return str(sess.query(LeaveType).filter(LeaveType.company_id == cid).one().id)


# ------------------------------------------------------------------- R6


def test_R6_chain_hr_admin_and_owner_can_decide(client, world) -> None:
    lt = world["lt"]["id"]
    for offset, who in enumerate(("boss", "senior", "hr2", "owner"), start=1):
        leave = _apply(client, world["emp"]["h"], lt, _monday(offset), _monday(offset)).json()
        resp = _decide(client, world[who]["h"], leave["id"])
        assert resp.status_code == 200, f"R6: {who} must be able to decide: {resp.text}"
        assert resp.json()["status"] == "approved"


def test_R6_outsiders_get_403_with_the_same_message(client, world) -> None:
    leave = _apply(client, world["emp"]["h"], world["lt"]["id"], _monday(), _monday()).json()
    manager = _decide(client, world["outsider"]["h"], leave["id"])
    employee = _decide(client, world["colleague"]["h"], leave["id"])
    assert manager.status_code == 403 == employee.status_code, f"{manager.text} / {employee.text}"
    assert manager.json()["error"]["message"] == employee.json()["error"]["message"], (
        "R6: manager outside the chain and an employee must get the same message"
    )


def test_R6_other_company_gets_the_same_404_as_a_missing_leave(
    client, world, company_b: TenantContext
) -> None:
    leave = _apply(client, world["emp"]["h"], world["lt"]["id"], _monday(), _monday()).json()
    foreign = _decide(client, company_b.hr_headers, leave["id"])
    missing = _decide(client, company_b.hr_headers, str(uuid.uuid4()))
    assert foreign.status_code == 404 == missing.status_code
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]


def test_R6_nobody_approves_their_own_leave_except_an_owner(client, world) -> None:
    lt = world["lt"]["id"]
    for offset, who in enumerate(("emp", "boss", "hr2", "sadmin"), start=1):
        leave = _apply(client, world[who]["h"], lt, _monday(offset), _monday(offset))
        assert leave.status_code == 201 and leave.json()["status"] == "pending", (
            f"R6: {who}'s own leave must wait for a decision: {leave.text}"
        )
        own = _decide(client, world[who]["h"], leave.json()["id"])
        assert own.status_code == 403, f"R6: {who} must not approve their own leave: {own.text}"
    owner_leave = _apply(client, world["owner"]["h"], lt, _monday(), _monday())
    assert owner_leave.status_code == 201 and owner_leave.json()["status"] == "approved", (
        f"R6: an owner's own leave is approved at once: {owner_leave.text}"
    )


# ------------------------------------------------------------------- R7


def test_R7_a_second_decision_gives_409_and_reject_needs_a_reason(client, world) -> None:
    lt = world["lt"]["id"]
    leave = _apply(client, world["emp"]["h"], lt, _monday(), _monday()).json()
    for bad in (None, "", "   ", "z" * 501):
        resp = _decide(
            client, world["boss"]["h"], leave["id"], status="rejected", rejection_reason=bad
        )
        assert resp.status_code == 422, f"R7: reject reason {bad!r} must give 422: {resp.text}"
    assert _decide(client, world["boss"]["h"], leave["id"]).status_code == 200
    assert _decide(client, world["boss"]["h"], leave["id"]).status_code == 409, (
        "R7: a second approval must give 409"
    )
    assert (
        _decide(
            client, world["boss"]["h"], leave["id"], status="rejected", rejection_reason="late"
        ).status_code
        == 409
    ), "R7: approved then rejected must give 409"
    other = _apply(client, world["emp"]["h"], lt, _monday(2), _monday(2)).json()
    rejected = _decide(
        client, world["boss"]["h"], other["id"], status="rejected", rejection_reason="  busy  "
    )
    assert rejected.status_code == 200 and rejected.json()["rejection_reason"] == "busy"
    assert _decide(client, world["boss"]["h"], other["id"]).status_code == 409


def test_R7_approval_adds_used_and_writes_on_leave_for_working_days_only(client, db, world) -> None:
    ctx = world["ctx"]
    monday = _monday()
    lt = world["lt"]["id"]
    leave = _apply(client, world["emp"]["h"], lt, monday, monday + timedelta(days=6)).json()
    assert Decimal(leave["total_days"]) == Decimal("5")
    assert _decide(client, world["boss"]["h"], leave["id"]).status_code == 200
    assert _balance(db, ctx, world["emp"]["id"], lt).used == Decimal("5"), "R7: used not added"
    rows = _attendance_rows(db, ctx, world["emp"]["id"])
    assert [r.date for r in rows] == [monday + timedelta(days=i) for i in range(5)], (
        "R7: on_leave rows must exist for the five working days only"
    )
    assert all(r.status == AttendanceStatus.on_leave for r in rows)


def test_R7_a_real_punch_in_the_range_blocks_the_approval_with_409(client, db, world) -> None:
    ctx = world["ctx"]
    monday = _monday()
    lt = world["lt"]["id"]
    punched = monday + timedelta(days=1)
    leave = _apply(client, world["emp"]["h"], lt, monday, monday + timedelta(days=2)).json()
    _punch(db, ctx, world["emp"]["id"], punched)
    resp = _decide(client, world["boss"]["h"], leave["id"])
    assert resp.status_code == 409, f"R7: a real punch must block approval: {resp.text}"
    assert punched.isoformat() in resp.json()["error"]["details"]["dates"], "R7: dates not named"
    assert client.get(f"{LEAVES}/{leave['id']}", headers=world["emp"]["h"]).json()["status"] == (
        "pending"
    )
    bal = _balance(db, ctx, world["emp"]["id"], lt)
    assert bal is None or bal.used == Decimal("0"), "R7: nothing may be deducted"
    rows = _attendance_rows(db, ctx, world["emp"]["id"])
    assert len(rows) == 1 and rows[0].status == AttendanceStatus.present, "R7: punch overwritten"


def test_R7_a_decision_is_one_transaction_with_one_commit(client, db: Session, world) -> None:
    leave = _apply(client, world["emp"]["h"], world["lt"]["id"], _monday(), _monday()).json()
    commits: list[int] = []

    def _count(_session: Session) -> None:
        commits.append(1)

    event.listen(db, "after_commit", _count)
    try:
        assert _decide(client, world["boss"]["h"], leave["id"]).status_code == 200
    finally:
        event.remove(db, "after_commit", _count)
    assert len(commits) == 1, f"R7: a decision must commit once, committed {len(commits)} times"


# ------------------------------------------------------------------- R8


def test_R8_an_employee_cancels_their_own_pending_leave_only(client, world) -> None:
    lt = world["lt"]["id"]
    mine = _apply(client, world["emp"]["h"], lt, _monday(), _monday()).json()
    other = client.delete(f"{LEAVES}/{mine['id']}", headers=world["colleague"]["h"])
    assert other.status_code == 403, f"R8: someone else's pending leave must give 403: {other.text}"
    boss = client.delete(f"{LEAVES}/{mine['id']}", headers=world["outsider"]["h"])
    assert boss.status_code == 403
    done = client.delete(f"{LEAVES}/{mine['id']}", headers=world["emp"]["h"])
    assert done.status_code == 200 and done.json()["status"] == "cancelled"
    again = client.delete(f"{LEAVES}/{mine['id']}", headers=world["emp"]["h"])
    assert again.status_code == 409, f"R8: cancelling twice must give 409: {again.text}"


def test_R8_only_hr_level_cancels_an_approved_leave_and_it_restores_everything(
    client, db: Session, world
) -> None:
    ctx = world["ctx"]
    lt = world["lt"]["id"]
    monday = _monday()
    leave = _apply(client, world["emp"]["h"], lt, monday, monday + timedelta(days=6)).json()
    assert _decide(client, world["boss"]["h"], leave["id"]).status_code == 200
    saturday = monday + timedelta(days=5)
    _punch(db, ctx, world["emp"]["id"], saturday)  # a real record that must survive

    denied = client.delete(f"{LEAVES}/{leave['id']}", headers=world["emp"]["h"])
    assert denied.status_code == 403, (
        f"R8: employee cancelling approved must give 403: {denied.text}"
    )
    assert client.delete(f"{LEAVES}/{leave['id']}", headers=world["boss"]["h"]).status_code == 403
    done = client.delete(f"{LEAVES}/{leave['id']}", headers=world["hr2"]["h"])
    assert done.status_code == 200 and done.json()["status"] == "cancelled", done.text
    assert _balance(db, ctx, world["emp"]["id"], lt).used == Decimal("0"), "R8: used not restored"
    rows = _attendance_rows(db, ctx, world["emp"]["id"])
    assert [r.date for r in rows] == [saturday], "R8: only the system on_leave rows may go"


def test_R8_rejected_and_cancelled_leaves_cannot_be_cancelled(client, world) -> None:
    lt = world["lt"]["id"]
    leave = _apply(client, world["emp"]["h"], lt, _monday(), _monday()).json()
    _decide(client, world["boss"]["h"], leave["id"], status="rejected", rejection_reason="no")
    for headers in (world["emp"]["h"], world["hr2"]["h"]):
        resp = client.delete(f"{LEAVES}/{leave['id']}", headers=headers)
        assert resp.status_code == 409, f"R8: a rejected leave cannot be cancelled: {resp.text}"


# ------------------------------------------------------------------- R9


def test_R9_a_type_without_approval_is_approved_at_once_with_the_same_effects(
    client, db, world
) -> None:
    ctx = world["ctx"]
    lt = _leave_type(client, ctx.hr_headers, requires_approval=False)["id"]
    monday = _monday()
    resp = _apply(client, world["emp"]["h"], lt, monday, monday + timedelta(days=1))
    assert resp.status_code == 201 and resp.json()["status"] == "approved", resp.text
    assert _balance(db, ctx, world["emp"]["id"], lt).used == Decimal("2"), "R9: used not added"
    assert len(_attendance_rows(db, ctx, world["emp"]["id"])) == 2, "R9: attendance not written"
    approved = _audit(db, ctx, "LEAVE_APPROVED")
    assert len(approved) == 1 and approved[0].details["auto_approved"] is True, "R9: not audited"
    assert len(_audit(db, ctx, "LEAVE_APPLIED")) == 1


def test_R9_auto_approval_still_refuses_a_real_punch(client, db, world) -> None:
    ctx = world["ctx"]
    lt = _leave_type(client, ctx.hr_headers, requires_approval=False)["id"]
    monday = _monday()
    _punch(db, ctx, world["emp"]["id"], monday)
    resp = _apply(client, world["emp"]["h"], lt, monday, monday)
    assert resp.status_code == 409, f"R9: auto-approval must respect a real punch: {resp.text}"
    assert client.get(LEAVES, headers=world["emp"]["h"]).json()["total"] == 0, "R9: leave kept"


def test_R9_only_an_owners_own_leave_is_auto_approved_otherwise(client, world) -> None:
    lt = world["lt"]["id"]
    own = _apply(client, world["owner"]["h"], lt, _monday(), _monday())
    assert own.json()["status"] == "approved", "R9: owner's own leave is approved at once"
    for offset, who in enumerate(("hr2", "sadmin"), start=2):
        resp = _apply(client, world[who]["h"], lt, _monday(offset), _monday(offset))
        assert resp.json()["status"] == "pending", f"R9: {who}'s own leave must stay pending"
    for_other = _apply(
        client, world["owner"]["h"], lt, _monday(4), _monday(4), employee_id=world["emp"]["id"]
    )
    assert for_other.json()["status"] == "pending", "R9: an owner applying for others is pending"


# ------------------------------------------------------------------- R10


def test_R10_apply_decide_and_cancel_write_one_audit_row_without_free_text(
    client, db, world
) -> None:
    ctx = world["ctx"]
    lt = world["lt"]["id"]
    monday = _monday()
    a = _apply(
        client, world["emp"]["h"], lt, monday, monday + timedelta(days=1), reason="Very private"
    )
    applied = _audit(db, ctx, "LEAVE_APPLIED")
    assert len(applied) == 1 and applied[0].entity_id == uuid.UUID(a.json()["id"]), "R10: APPLIED"
    assert applied[0].details["days"] in ("2", "2.0") and applied[0].details["start_date"]

    assert _decide(client, world["boss"]["h"], a.json()["id"]).status_code == 200
    assert len(_audit(db, ctx, "LEAVE_APPROVED")) == 1, "R10: APPROVED missing"

    b = _apply(
        client, world["emp"]["h"], lt, _monday(2), _monday(2), reason="Another secret"
    ).json()
    _decide(client, world["boss"]["h"], b["id"], status="rejected", rejection_reason="Secret no")
    assert len(_audit(db, ctx, "LEAVE_REJECTED")) == 1, "R10: REJECTED missing"

    c = _apply(client, world["emp"]["h"], lt, _monday(3), _monday(3)).json()
    client.delete(f"{LEAVES}/{c['id']}", headers=world["emp"]["h"])
    cancelled = _audit(db, ctx, "LEAVE_CANCELLED")
    assert len(cancelled) == 1 and cancelled[0].entity_id == uuid.UUID(c["id"]), "R10: CANCELLED"

    blob = " ".join(
        str(r.details)
        for action in ("LEAVE_APPLIED", "LEAVE_APPROVED", "LEAVE_REJECTED", "LEAVE_CANCELLED")
        for r in _audit(db, ctx, action)
    )
    for secret in ("Very private", "Another secret", "Secret no"):
        assert secret not in blob, f"R10: {secret!r} leaked into an audit row"


def test_R10_failed_applications_write_no_audit_row(client, db, world) -> None:
    lt = world["lt"]["id"]
    assert _apply(client, world["emp"]["h"], lt, _monday(), _monday()).status_code == 201
    assert _apply(client, world["emp"]["h"], lt, _monday(), _monday()).status_code == 409
    assert len(_audit(db, world["ctx"], "LEAVE_APPLIED")) == 1


def test_R10_the_manager_is_notified_on_apply_and_the_employee_on_decision(
    client, db, world
) -> None:
    ctx = world["ctx"]
    lt = world["lt"]["id"]
    a = _apply(client, world["emp"]["h"], lt, _monday(), _monday()).json()
    assert len(_notes(db, ctx, world["boss"]["user"].id, "leave_requested")) == 1, "R10: manager"
    _decide(client, world["boss"]["h"], a["id"])
    assert len(_notes(db, ctx, world["emp"]["user"].id, "leave_approved")) == 1, "R10: approval"
    b = _apply(client, world["emp"]["h"], lt, _monday(2), _monday(2)).json()
    _decide(client, world["boss"]["h"], b["id"], status="rejected", rejection_reason="no")
    assert len(_notes(db, ctx, world["emp"]["user"].id, "leave_rejected")) == 1, "R10: rejection"


def test_R10_lists_and_gets_follow_the_visibility_of_rule_1(client, world, company_b) -> None:
    lt = world["lt"]["id"]
    mine = _apply(client, world["emp"]["h"], lt, _monday(), _monday()).json()
    theirs = _apply(client, world["colleague"]["h"], lt, _monday(), _monday()).json()

    def ids(headers: dict[str, str]) -> set[str]:
        resp = client.get(LEAVES, headers=headers)
        assert resp.status_code == 200, resp.text
        return {i["id"] for i in resp.json()["items"]}

    assert ids(world["emp"]["h"]) == {mine["id"]}, "R10: employee sees only their own"
    assert ids(world["boss"]["h"]) == {mine["id"]}, "R10: manager sees direct reports"
    assert ids(world["senior"]["h"]) == set(), "R10: only direct reports, not the whole chain"
    assert ids(world["hr2"]["h"]) == {mine["id"], theirs["id"]}, "R10: HR sees all"
    assert client.get(f"{LEAVES}/{mine['id']}", headers=world["boss"]["h"]).status_code == 200
    assert client.get(f"{LEAVES}/{mine['id']}", headers=world["colleague"]["h"]).status_code == 403
    assert client.get(f"{LEAVES}/{mine['id']}", headers=world["outsider"]["h"]).status_code == 403
    foreign = client.get(f"{LEAVES}/{mine['id']}", headers=company_b.hr_headers)
    missing = client.get(f"{LEAVES}/{uuid.uuid4()}", headers=company_b.hr_headers)
    assert foreign.status_code == 404 == missing.status_code
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]
    cross = client.get(f"{LEAVES}?employee_id={world['emp']['id']}", headers=company_b.hr_headers)
    assert cross.json()["items"] == [], "R10: another company must see nothing"


def test_R10_a_super_admin_does_not_see_another_companys_leaves(
    client, world, super_admin_headers
) -> None:
    mine = _apply(client, world["emp"]["h"], world["lt"]["id"], _monday(), _monday()).json()
    resp = client.get(f"{LEAVES}?employee_id={world['emp']['id']}", headers=super_admin_headers)
    assert resp.status_code == 200 and resp.json()["items"] == [], "R10: no cross-company bypass"
    assert client.get(f"{LEAVES}/{mine['id']}", headers=super_admin_headers).status_code == 404


def test_R10_apply_decide_and_cancel_are_limited_to_10_per_minute(client, world, limits_on) -> None:
    lt = world["lt"]["id"]
    codes = [
        _apply(client, world["emp"]["h"], lt, _monday(i + 1), _monday(i + 1)).status_code
        for i in range(11)
    ]
    assert 429 not in codes[:10] and codes[10] == 429, f"R10: apply limit wrong: {codes}"
    limiter.reset()
    leave = client.get(LEAVES, headers=world["emp"]["h"]).json()["items"][0]["id"]
    limiter.reset()
    decisions = [_decide(client, world["boss"]["h"], leave).status_code for _ in range(11)]
    assert 429 not in decisions[:10] and decisions[10] == 429, f"R10: decide limit: {decisions}"
    limiter.reset()
    cancels = [
        client.delete(f"{LEAVES}/{leave}", headers=world["hr2"]["h"]).status_code for _ in range(11)
    ]
    assert 429 not in cancels[:10] and cancels[10] == 429, f"R10: cancel limit wrong: {cancels}"


def test_R10_reads_are_limited_to_60_per_minute(client, world, limits_on) -> None:
    leave = _apply(client, world["emp"]["h"], world["lt"]["id"], _monday(), _monday()).json()
    limiter.reset()
    listing = [client.get(LEAVES, headers=world["emp"]["h"]).status_code for _ in range(61)]
    assert listing[:60] == [200] * 60 and listing[60] == 429, "R10: list limit wrong"
    limiter.reset()
    single = [
        client.get(f"{LEAVES}/{leave['id']}", headers=world["emp"]["h"]).status_code
        for _ in range(61)
    ]
    assert single[:60] == [200] * 60 and single[60] == 429, "R10: get limit wrong"
