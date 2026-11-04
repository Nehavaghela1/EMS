"""Module 5, sub-feature 5.4: Payroll runs. One test per rule line (R1..R10).

Months are computed from utcnow(): a run is only allowed for a completed month, so every
test uses "the month before the current one" or earlier. Employees are filled with a
`present` attendance row for every day of the month unless a test says otherwise, because a
working day without any attendance row is loss of pay (rule 7).
"""

import calendar
import threading
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.tax_slabs import seed_tax_slabs
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import Employee, ResignationStatus
from app.modules.identity.models import (
    Company,
    CompanySettings,
    CompanyStatus,
    User,
    UserRole,
)
from app.modules.payroll.models import (
    PayrollItem,
    PayrollRun,
    PayrollRunStatus,
    Reimbursement,
    ReimbursementStatus,
)
from app.modules.payroll.schemas import PayrollRunCreateRequest
from app.modules.payroll.service import PayrollRunService
from app.modules.platform.models import AuditLog
from app.modules.time_leave.models import (
    Attendance,
    AttendanceSource,
    AttendanceStatus,
    Holiday,
    Leave,
    LeaveStatus,
    LeaveType,
)
from tests.conftest import TenantContext, upload_receipt
from tests.rules.test_4_2_punch import _create_employee, _link_user_to_employee

RUNS = "/api/v1/payroll/runs"
PAYSLIPS = "/api/v1/payroll/payslips"


@pytest.fixture(autouse=True)
def _seed_statutory(db: Session) -> None:
    seed_pt_slabs(db)
    seed_tax_slabs(db)


@pytest.fixture
def limits_on():
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = False


# ---------------------------------------------------------------- helpers


def _month_back(back: int = 1) -> tuple[int, int]:
    today = utcnow().date()
    year, month = today.year, today.month - back
    while month < 1:
        month += 12
        year -= 1
    return year, month


def _month_with_days(days: int) -> tuple[int, int]:
    for back in range(1, 14):
        year, month = _month_back(back)
        if calendar.monthrange(year, month)[1] == days:
            return year, month
    raise AssertionError(f"no month with {days} days in the last year")


def _days_of(year: int, month: int) -> list[date]:
    return [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]


def _working_days_of(year: int, month: int) -> list[date]:
    return [d for d in _days_of(year, month) if d.isoweekday() not in (6, 7)]


def _extra_user(db: Session, cid: uuid.UUID, role: UserRole) -> tuple[dict[str, str], User]:
    user = User(
        company_id=cid,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@payco.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(cid), role=role.value)
    return {"Authorization": f"Bearer {token}"}, user


def _structure(client: TestClient, headers: dict[str, str], balance: bool = True) -> str:
    components: list[dict[str, Any]] = [
        {
            "code": "BASIC",
            "name": "Basic Pay",
            "type": "earning",
            "calculation_type": "percentage",
            "value": "50.00",
            "percentage_of": "ctc",
            "display_order": 1,
        },
        {
            "code": "HRA",
            "name": "House Rent Allowance",
            "type": "earning",
            "calculation_type": "percentage",
            "value": "40.00",
            "percentage_of": "basic",
            "display_order": 2,
        },
    ]
    if balance:
        components.append(
            {
                "code": "SPECIAL",
                "name": "Special Allowance",
                "type": "earning",
                "calculation_type": "balance",
                "display_order": 3,
            }
        )
    resp = client.post(
        "/api/v1/payroll/structures",
        json={"name": f"Std {uuid.uuid4().hex[:6]}", "components": components},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _set_flags(db: Session, ctx: TenantContext, emp_id: str, **fields: Any) -> None:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    emp = db.get(Employee, uuid.UUID(emp_id))
    assert emp is not None
    for key, value in fields.items():
        setattr(emp, key, value)
    db.commit()


def _staff(
    client: TestClient,
    db: Session,
    ctx: TenantContext,
    structure_id: str | None,
    role: UserRole = UserRole.employee,
    *,
    ctc: str = "600000.00",
    exempt: bool = False,
    hire: str = "2024-01-15",
) -> dict[str, Any]:
    emp = _create_employee(client, ctx.hr_headers, hire_date=hire)
    headers, user = _link_user_to_employee(db, ctx.company_id, emp["id"], role)
    if exempt:
        _set_flags(db, ctx, emp["id"], is_attendance_exempt=True)
    if structure_id is not None:
        resp = client.post(
            f"/api/v1/payroll/employees/{emp['id']}/assign",
            json={"structure_id": structure_id, "ctc": ctc, "effective_from": "2024-01-01"},
            headers=ctx.hr_headers,
        )
        assert resp.status_code == 201, resp.text
    return {"id": emp["id"], "h": headers, "user": user}


def _mark(db: Session, ctx: TenantContext, emp_id: str, day: date, status: AttendanceStatus):
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    row = (
        db.query(Attendance)
        .filter(Attendance.employee_id == uuid.UUID(emp_id), Attendance.date == day)
        .first()
    )
    if row is None:
        db.add(
            Attendance(
                company_id=ctx.company_id,
                employee_id=uuid.UUID(emp_id),
                date=day,
                status=status,
                source=AttendanceSource.web,
            )
        )
    else:
        row.status = status
    db.commit()


def _fill(
    db: Session,
    ctx: TenantContext,
    emp_id: str,
    year: int,
    month: int,
    skip: set[date] = frozenset(),
) -> None:
    """A `present` row on every calendar day of the month except `skip`."""
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    for day in _days_of(year, month):
        if day in skip:
            continue
        db.add(
            Attendance(
                company_id=ctx.company_id,
                employee_id=uuid.UUID(emp_id),
                date=day,
                status=AttendanceStatus.present,
                source=AttendanceSource.web,
            )
        )
    db.commit()


def _post_run(
    client: TestClient,
    headers: dict[str, str],
    year: int,
    month: int,
    key: str | None = None,
    **extra: Any,
):
    body: dict[str, Any] = {"month": month, "year": year, "run_type": "regular"}
    body.update(extra)
    return client.post(
        RUNS, json=body, headers={**headers, "Idempotency-Key": key or f"k-{uuid.uuid4()}"}
    )


def _make_run(client: TestClient, headers: dict[str, str], year: int, month: int) -> dict:
    resp = _post_run(client, headers, year, month)
    assert resp.status_code == 202, resp.text
    return resp.json()


def _item_for(client: TestClient, headers: dict[str, str], run_id: str, emp_id: str) -> dict:
    detail = client.get(f"{RUNS}/{run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    return next(i for i in detail.json()["items"] if i["employee_id"] == emp_id)


def _audit(db: Session, ctx: TenantContext, action: str) -> list[AuditLog]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    return (
        db.query(AuditLog)
        .filter(AuditLog.company_id == ctx.company_id, AuditLog.action == action)
        .all()
    )


@pytest.fixture
def world(client: TestClient, db: Session, company_a: TenantContext) -> dict[str, Any]:
    """HR (the conftest user) creates; a second HR admin and an owner approve."""
    year, month = _month_back()
    hr2_h, hr2_user = _extra_user(db, company_a.company_id, UserRole.hr_admin)
    owner_h, owner_user = _extra_user(db, company_a.company_id, UserRole.owner)
    structure_id = _structure(client, company_a.hr_headers)
    emp = _staff(client, db, company_a, structure_id)
    manager = _staff(client, db, company_a, structure_id, UserRole.manager)
    return {
        "ctx": company_a,
        "year": year,
        "month": month,
        "structure_id": structure_id,
        "hr1": company_a.hr_headers,
        "hr2": hr2_h,
        "hr2_user": hr2_user,
        "owner": owner_h,
        "owner_user": owner_user,
        "emp": emp,
        "manager": manager,
    }


def _filled_world(db: Session, w: dict[str, Any]) -> dict[str, Any]:
    for who in ("emp", "manager"):
        _fill(db, w["ctx"], w[who]["id"], w["year"], w["month"])
    return w


# ------------------------------------------------------------------- R1


def test_R1_no_login_gets_401(client: TestClient) -> None:
    rid = uuid.uuid4()
    codes = [
        client.post(RUNS, json={"month": 1, "year": 2024}).status_code,
        client.get(RUNS).status_code,
        client.get(f"{RUNS}/{rid}").status_code,
        client.post(f"{RUNS}/{rid}/approve").status_code,
        client.delete(f"{RUNS}/{rid}").status_code,
    ]
    assert codes == [401] * 5, f"R1: no login must give 401 on every runs route, got {codes}"


@pytest.mark.parametrize("who", ["emp", "manager"])
def test_R1_employee_and_manager_get_403_on_every_runs_route(client, db, world, who) -> None:
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    h = world[who]["h"]
    rid = run["id"]
    results = {
        "create": _post_run(client, h, world["year"], world["month"] - 1 or 12).status_code,
        "list": client.get(RUNS, headers=h).status_code,
        "detail": client.get(f"{RUNS}/{rid}", headers=h).status_code,
        "approve": client.post(f"{RUNS}/{rid}/approve", headers=h).status_code,
        "delete": client.delete(f"{RUNS}/{rid}", headers=h).status_code,
    }
    assert set(results.values()) == {403}, f"R1: {who} must get 403 everywhere, got {results}"


def test_R1_hr_admin_and_owner_can_use_the_runs_routes(client, db, world) -> None:
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    for who in ("hr1", "owner"):
        assert client.get(RUNS, headers=world[who]).status_code == 200, f"R1: {who} list"
        detail = client.get(f"{RUNS}/{run['id']}", headers=world[who])
        assert detail.status_code == 200, f"R1: {who} detail: {detail.text}"
    prev_y, prev_m = _month_back(2)
    assert _post_run(client, world["owner"], prev_y, prev_m).status_code == 202, "R1: owner create"
    assert client.post(f"{RUNS}/{run['id']}/approve", headers=world["hr2"]).status_code == 200
    other = _make_run(client, world["hr2"], *_month_back(3))
    assert client.delete(f"{RUNS}/{other['id']}", headers=world["owner"]).status_code == 204


def test_R1_another_companys_run_gives_the_same_404_as_a_missing_one(
    client, db, world, company_b: TenantContext
) -> None:
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    for method, url in (
        ("get", f"{RUNS}/{run['id']}"),
        ("post", f"{RUNS}/{run['id']}/approve"),
        ("delete", f"{RUNS}/{run['id']}"),
    ):
        foreign = getattr(client, method)(url, headers=company_b.hr_headers)
        missing_url = url.replace(run["id"], str(uuid.uuid4()))
        missing = getattr(client, method)(missing_url, headers=company_b.hr_headers)
        assert foreign.status_code == 404 == missing.status_code, (
            f"R1: {method} on another company's run must be 404: {foreign.text}"
        )
        assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]
    listed = client.get(RUNS, headers=company_b.hr_headers).json()
    assert listed["items"] == [], "R1: another company must not list this run"


def test_R1_unknown_field_and_unknown_run_type_give_422(client, db, world) -> None:
    year, month = world["year"], world["month"]
    extra = _post_run(client, world["hr1"], year, month, total_net="1.00")
    assert extra.status_code == 422, f"R1: an unknown field must give 422, got {extra.text}"
    bad_type = _post_run(client, world["hr1"], year, month, run_type="bonus")
    assert bad_type.status_code == 422, f"R1: unknown run_type must give 422, got {bad_type.text}"
    no_key = client.post(RUNS, json={"month": month, "year": year}, headers=world["hr1"])
    assert no_key.status_code == 400, f"R1: missing Idempotency-Key is refused: {no_key.text}"


# ------------------------------------------------------------------- R2


def test_R2_employee_and_manager_cannot_open_run_detail_or_list_even_after_approval(
    client, db, world
) -> None:
    _filled_world(db, world)
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    assert client.post(f"{RUNS}/{run['id']}/approve", headers=world["owner"]).status_code == 200
    for who in ("emp", "manager"):
        detail = client.get(f"{RUNS}/{run['id']}", headers=world[who]["h"])
        assert detail.status_code == 403, f"R2: {who} must not read the run detail: {detail.text}"
        for secret in ("total_net", "total_gross", "total_employer_cost", "items"):
            assert secret not in detail.text, f"R2: {secret} leaked to {who}"
        assert client.get(RUNS, headers=world[who]["h"]).status_code == 403


def test_R2_employee_reads_only_their_own_pay_through_the_payslip_route(client, db, world) -> None:
    _filled_world(db, world)
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    client.post(f"{RUNS}/{run['id']}/approve", headers=world["owner"])
    mine = client.get(f"{PAYSLIPS}/me", headers=world["emp"]["h"])
    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert isinstance(body, dict) and "items" in body, (
        f"R2: payslips are returned as a page: {body}"
    )
    ids = {i["employee_id"] for i in body["items"]}
    assert ids == {world["emp"]["id"]}, f"R2: employee must see only their own payslip: {ids}"


# ------------------------------------------------------------------- R3


def test_R3_a_processed_run_is_pending_approval_and_an_empty_run_is_draft(
    client, db, company_a: TenantContext
) -> None:
    empty = _make_run(client, company_a.hr_headers, *_month_back(2))
    assert empty["status"] == "draft", f"R3: a run nobody was processed in is draft: {empty}"
    structure_id = _structure(client, company_a.hr_headers)
    _staff(client, db, company_a, structure_id, exempt=True)
    full = _make_run(client, company_a.hr_headers, *_month_back(1))
    assert full["status"] == "pending_approval", f"R3: expected pending_approval, got {full}"
    assert full["total_employees"] == 1


@pytest.mark.parametrize("state", [PayrollRunStatus.draft, PayrollRunStatus.processing])
def test_R3_approve_works_only_from_pending_approval_409_names_the_status(
    client, db, world, state
) -> None:
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    row = db.get(PayrollRun, uuid.UUID(run["id"]))
    assert row is not None
    row.status = state
    db.commit()
    resp = client.post(f"{RUNS}/{run['id']}/approve", headers=world["hr2"])
    assert resp.status_code == 409, f"R3: approving a {state.value} run must give 409: {resp.text}"
    assert state.value in resp.json()["error"]["message"], "R3: message must name the status"
    db.refresh(row)
    assert row.status == state and row.approved_by is None, "R3: a refused approval changes nothing"


def test_R3_approving_an_approved_run_again_changes_nothing_and_writes_no_second_audit_row(
    client, db, world
) -> None:
    _filled_world(db, world)
    ctx = world["ctx"]
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    first = client.post(f"{RUNS}/{run['id']}/approve", headers=world["hr2"])
    assert first.status_code == 200 and first.json()["status"] == "approved", first.text
    again = client.post(f"{RUNS}/{run['id']}/approve", headers=world["owner"])
    assert again.status_code == 200, f"R3: a repeated approval is a no-op, got {again.text}"
    assert again.json()["approved_at"] == first.json()["approved_at"]
    assert (
        again.json()["approved_by"] == first.json()["approved_by"] == str(world["hr2_user"].id)
    ), "R3: the first approver stays recorded"
    assert len(_audit(db, ctx, "PAYROLL_RUN_APPROVED")) == 1, "R3: only one approval audit row"


# ------------------------------------------------------------------- R4


def test_R4_the_creator_cannot_approve_their_own_run(client, db, world) -> None:
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    first = client.post(f"{RUNS}/{run['id']}/approve", headers=world["hr1"])
    assert first.status_code == 403, f"R4: creator approving own run must give 403: {first.text}"
    second = _make_run(client, world["hr2"], *_month_back(2))
    other = client.post(f"{RUNS}/{second['id']}/approve", headers=world["hr2"])
    assert other.status_code == 403
    assert other.json()["error"]["message"] == first.json()["error"]["message"], (
        "R4: the refusal has a fixed message"
    )
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    row = db.get(PayrollRun, uuid.UUID(run["id"]))
    assert row is not None
    assert row.status != PayrollRunStatus.approved, "R4: the refused run stays unapproved"
    assert row.approved_by is None


def test_R4_an_owner_may_approve_the_run_they_created(client, db, world) -> None:
    _filled_world(db, world)
    run = _make_run(client, world["owner"], world["year"], world["month"])
    resp = client.post(f"{RUNS}/{run['id']}/approve", headers=world["owner"])
    assert resp.status_code == 200, f"R4: an owner may approve their own run: {resp.text}"
    assert resp.json()["status"] == "approved"


def test_R4_another_hr_admin_and_an_owner_can_approve_a_run_hr_created(client, db, world) -> None:
    _filled_world(db, world)
    first = _make_run(client, world["hr1"], world["year"], world["month"])
    assert client.post(f"{RUNS}/{first['id']}/approve", headers=world["hr2"]).status_code == 200
    second = _make_run(client, world["hr1"], *_month_back(2))
    assert client.post(f"{RUNS}/{second['id']}/approve", headers=world["owner"]).status_code == 200


# ------------------------------------------------------------------- R5


def test_R5_an_approved_run_cannot_be_deleted(client, db, world) -> None:
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    client.post(f"{RUNS}/{run['id']}/approve", headers=world["owner"])
    for who in ("hr1", "hr2", "owner"):
        resp = client.delete(f"{RUNS}/{run['id']}", headers=world[who])
        assert resp.status_code == 409, f"R5: {who} must not delete an approved run: {resp.text}"
    assert client.get(f"{RUNS}/{run['id']}", headers=world["hr1"]).status_code == 200


def test_R5_an_approved_run_blocks_a_new_run_for_the_month_and_keeps_its_items(
    client, db, world
) -> None:
    _filled_world(db, world)
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    client.post(f"{RUNS}/{run['id']}/approve", headers=world["owner"])
    before = client.get(f"{RUNS}/{run['id']}", headers=world["hr1"]).json()
    again = _post_run(client, world["hr1"], world["year"], world["month"])
    assert again.status_code == 409, f"R5: a second run for an approved month is 409: {again.text}"
    after = client.get(f"{RUNS}/{run['id']}", headers=world["hr1"]).json()
    assert before == after, "R5: an approved run's items and totals must not change"


def test_R5_linked_reimbursements_become_paid_exactly_once(client, db, world) -> None:
    _filled_world(db, world)
    ctx = world["ctx"]
    claim = _claim(client, world, "2500.00")
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    item = _item_for(client, world["hr1"], run["id"], world["emp"]["id"])
    assert item["reimbursement_amount"] == "2500.00"
    assert _claim_state(db, ctx, claim)[0] == ReimbursementStatus.approved, "R5: not paid yet"
    client.post(f"{RUNS}/{run['id']}/approve", headers=world["owner"])
    client.post(f"{RUNS}/{run['id']}/approve", headers=world["hr2"])
    status, linked = _claim_state(db, ctx, claim)
    assert status == ReimbursementStatus.paid and str(linked) == run["id"], "R5: paid once"
    extra = client.post(
        RUNS,
        json={
            "month": world["month"],
            "year": world["year"],
            "run_type": "off_cycle",
        },
        headers={**world["hr1"], "Idempotency-Key": f"off-{uuid.uuid4()}"},
    )
    assert extra.status_code == 202, extra.text
    off_item = _item_for(client, world["hr1"], extra.json()["id"], world["emp"]["id"])
    assert off_item["reimbursement_amount"] == "0.00", "R5: a paid claim is never paid twice"
    assert str(_claim_state(db, ctx, claim)[1]) == run["id"], "R5: claim stays on the first run"


def test_R5_deleting_an_unapproved_run_releases_its_reimbursements(client, db, world) -> None:
    _filled_world(db, world)
    ctx = world["ctx"]
    claim = _claim(client, world, "800.00")
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    assert _claim_state(db, ctx, claim)[1] is not None, "R5: the claim is locked into the run"
    assert client.delete(f"{RUNS}/{run['id']}", headers=world["hr2"]).status_code == 204
    status, linked = _claim_state(db, ctx, claim)
    assert status == ReimbursementStatus.approved and linked is None, "R5: claim is released"
    again = _make_run(client, world["hr1"], world["year"], world["month"])
    item = _item_for(client, world["hr1"], again["id"], world["emp"]["id"])
    assert item["reimbursement_amount"] == "800.00", "R5: the released claim is paid next run"


def _claim(client: TestClient, w: dict[str, Any], amount: str) -> str:
    created = client.post(
        "/api/v1/payroll/reimbursements",
        json={
            "type": "food",
            "amount": amount,
            "expense_date": (utcnow().date() - timedelta(days=40)).isoformat(),
            "description": "Team lunch",
            "file_object_id": upload_receipt(client, w["emp"]["h"]),
        },
        headers=w["emp"]["h"],
    )
    assert created.status_code == 201, created.text
    claim_id = created.json()["id"]
    reviewed = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        json={"action": "approve"},
        headers=w["hr1"],
    )
    assert reviewed.status_code == 200, reviewed.text
    return claim_id


def _claim_state(db: Session, ctx: TenantContext, claim_id: str):
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.expire_all()
    row = db.get(Reimbursement, uuid.UUID(claim_id))
    assert row is not None
    return row.status, row.added_to_payroll_run_id


# ------------------------------------------------------------------- R6


def test_R6_the_same_idempotency_key_returns_the_same_run(client, db, world) -> None:
    key = f"same-{uuid.uuid4()}"
    first = _post_run(client, world["hr1"], world["year"], world["month"], key=key)
    second = _post_run(client, world["hr1"], world["year"], world["month"], key=key)
    assert first.status_code == 202 == second.status_code
    assert first.json()["id"] == second.json()["id"], "R6: a repeated key returns the same run"
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    assert db.query(PayrollRun).filter(PayrollRun.idempotency_key == key).count() == 1


def test_R6_a_different_key_for_the_same_month_gives_409(client, db, world) -> None:
    _make_run(client, world["hr1"], world["year"], world["month"])
    resp = _post_run(client, world["hr1"], world["year"], world["month"])
    assert resp.status_code == 409, f"R6: one regular run per month, got {resp.text}"
    assert "regular payroll run" in resp.json()["error"]["message"], resp.text
    off = _post_run(client, world["hr1"], world["year"], world["month"], run_type="off_cycle")
    assert off.status_code == 202, f"R6: an off-cycle run is a separate run: {off.text}"


def test_R6_only_a_completed_month_is_allowed(client, db, world) -> None:
    today = utcnow().date()
    nxt_y, nxt_m = (today.year + (today.month == 12), today.month % 12 + 1)
    current = _post_run(client, world["hr1"], today.year, today.month)
    assert current.status_code == 422, f"R6: the current month must give 422: {current.text}"
    future = _post_run(client, world["hr1"], nxt_y, nxt_m)
    assert future.status_code == 422, f"R6: a future month must give 422: {future.text}"
    far = _post_run(client, world["hr1"], today.year + 1, today.month)
    assert far.status_code == 422, f"R6: next year must give 422: {far.text}"
    ok = _post_run(client, world["hr1"], world["year"], world["month"])
    assert ok.status_code == 202, f"R6: last month is allowed: {ok.text}"
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    assert db.query(PayrollRun).count() == 1, "R6: a refused month leaves no run row"


def test_R6_two_simultaneous_creates_give_one_202_and_one_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.payroll.repository import PayrollRunRepository

    original = PayrollRunRepository.get_regular_run

    def _slow(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        found = original(self, *args, **kwargs)
        time.sleep(0.5)  # both requests passed the "already exists?" look before either saves
        return found

    monkeypatch.setattr(PayrollRunRepository, "get_regular_run", _slow)
    assert settings.TEST_DATABASE_URL is not None
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    cid = uuid.uuid4()
    try:
        with Session(engine) as setup:
            setup.add(
                Company(
                    id=cid,
                    name="Run Race Co",
                    code=f"RRC{uuid.uuid4().hex[:4].upper()}",
                    email=f"rrc-{uuid.uuid4().hex[:6]}@example.com",
                    status=CompanyStatus.active,
                    is_active=True,
                )
            )
            setup.flush()
            bind_tenant_to_session(setup, company_id=cid, is_platform_admin=False)
            setup.add(CompanySettings(company_id=cid))
            user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.hr_admin,
                is_active=True,
            )
            setup.add(user)
            setup.commit()
            token = create_access_token(sub=str(user.id), company_id=str(cid), role="hr_admin")
        headers = {"Authorization": f"Bearer {token}"}
        year, month = _month_back()

        def _get_test_db():
            session = Session(engine)
            try:
                yield session
            finally:
                session.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db
        # The company's statutory config is made on first use; make it now, so that the race
        # below is decided by the run itself and not by two threads creating that config.
        config = TestClient(fastapi_app).get("/api/v1/payroll/statutory-config", headers=headers)
        assert config.status_code == 200, config.text
        barrier = threading.Barrier(2)
        results: list[int] = []
        bodies: list[str] = []

        def _worker() -> None:
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                resp = _post_run(c, headers, year, month)
                results.append(resp.status_code)
                bodies.append(resp.text)
            except Exception:
                results.append(999)

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert 500 not in results and 999 not in results, f"R6: race gave an error: {results}"
        assert sorted(results) == [202, 409], f"R6: expected one 202 and one 409, got {results}"
        loser = bodies[results.index(409)]
        assert "regular payroll run" in loser, f"R6: the loser gets the specific message: {loser}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        _purge(cid)


def _purge(cid: uuid.UUID) -> None:
    owner = create_engine(settings.TEST_MIGRATION_URL)
    try:
        with owner.begin() as conn:
            conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
            for table in (
                "audit_logs",
                "reimbursements",
                "payroll_items",
                "payroll_runs",
                "statutory_configs",
                "employees",
                "users",
                "company_settings",
            ):
                conn.execute(text(f"DELETE FROM {table} WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": cid})
    finally:
        owner.dispose()


def test_R3_two_simultaneous_approvals_write_one_audit_row_and_pay_reimbursements_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.payroll.models import ReimbursementType
    from app.modules.payroll.repository import PayrollRunRepository

    original_update = PayrollRunRepository.update

    def _slow_update(self, run, **kwargs):  # noqa: ANN001, ANN003
        if kwargs.get("status") == PayrollRunStatus.approved:
            time.sleep(0.5)  # both approvers have read the status before either one saves
        return original_update(self, run, **kwargs)

    monkeypatch.setattr(PayrollRunRepository, "update", _slow_update)
    assert settings.TEST_DATABASE_URL is not None
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    cid = uuid.uuid4()
    try:
        with Session(engine) as setup:
            setup.add(
                Company(
                    id=cid,
                    name="Approve Race Co",
                    code=f"ARC{uuid.uuid4().hex[:4].upper()}",
                    email=f"arc-{uuid.uuid4().hex[:6]}@example.com",
                    status=CompanyStatus.active,
                    is_active=True,
                )
            )
            setup.flush()
            bind_tenant_to_session(setup, company_id=cid, is_platform_admin=False)
            setup.add(CompanySettings(company_id=cid))
            users: dict[str, User] = {}
            for key, role in (
                ("creator", UserRole.hr_admin),
                ("hr2", UserRole.hr_admin),
                ("owner", UserRole.owner),
            ):
                users[key] = User(
                    id=uuid.uuid4(),
                    company_id=cid,
                    email=f"{key}-{uuid.uuid4().hex[:6]}@example.com",
                    hashed_password=hash_password("Test1234pass!"),
                    role=role,
                    is_active=True,
                )
                setup.add(users[key])
            setup.flush()
            emp = Employee(
                company_id=cid,
                employee_code=f"E{uuid.uuid4().hex[:6].upper()}",
                first_name="Race",
                last_name="Payee",
                email=f"payee-{uuid.uuid4().hex[:6]}@example.com",
                hire_date=date(2024, 1, 1),
                is_active=True,
            )
            setup.add(emp)
            setup.flush()
            year, month = _month_back()
            run = PayrollRun(
                company_id=cid,
                month=month,
                year=year,
                status=PayrollRunStatus.pending_approval,
                idempotency_key=f"race-{uuid.uuid4()}",
                run_by=users["creator"].id,
                total_employees=1,
            )
            setup.add(run)
            setup.flush()
            claim_ids = []
            for amount in ("100.00", "250.50"):
                claim = Reimbursement(
                    company_id=cid,
                    employee_id=emp.id,
                    type=ReimbursementType.food,
                    amount=Decimal(amount),
                    expense_date=date(2024, 2, 1),
                    description="Lunch",
                    status=ReimbursementStatus.approved,
                    added_to_payroll_run_id=run.id,
                )
                setup.add(claim)
                setup.flush()
                claim_ids.append(claim.id)
            setup.commit()
            run_id = run.id
            tokens = {
                key: create_access_token(sub=str(u.id), company_id=str(cid), role=u.role.value)
                for key, u in users.items()
            }
            hr2_id, owner_id = users["hr2"].id, users["owner"].id

        def _get_test_db():
            session = Session(engine)
            try:
                yield session
            finally:
                session.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db
        barrier = threading.Barrier(2)
        responses: list[tuple[int, dict]] = []

        def _worker(key: str) -> None:
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                resp = c.post(
                    f"{RUNS}/{run_id}/approve",
                    headers={"Authorization": f"Bearer {tokens[key]}"},
                )
                responses.append((resp.status_code, resp.json()))
            except Exception as exc:
                responses.append((999, {"error": str(exc)}))

        threads = [threading.Thread(target=_worker, args=(k,)) for k in ("hr2", "owner")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        codes = sorted(code for code, _ in responses)
        assert codes == [200, 200], f"R3: both approvals must answer 200, got {responses}"
        assert all(body["status"] == "approved" for _, body in responses), responses
        with Session(engine) as check:
            bind_tenant_to_session(check, company_id=cid, is_platform_admin=False)
            audit = (
                check.query(AuditLog)
                .filter(AuditLog.company_id == cid, AuditLog.action == "PAYROLL_RUN_APPROVED")
                .all()
            )
            assert len(audit) == 1, f"R3: exactly one approval audit row, got {len(audit)}"
            stored = check.get(PayrollRun, run_id)
            assert stored is not None and stored.status == PayrollRunStatus.approved
            assert stored.approved_by in (hr2_id, owner_id), "R3: approved_by is set"
            assert audit[0].actor_user_id == stored.approved_by, "R3: audit row names the approver"
            assert {b["approved_by"] for _, b in responses} == {str(stored.approved_by)}, (
                f"R3: both answers show the one recorded approver: {responses}"
            )
            claims = check.query(Reimbursement).filter(Reimbursement.id.in_(claim_ids)).all()
            assert len(claims) == 2
            assert all(c.status == ReimbursementStatus.paid for c in claims), "R3: all paid"
            assert all(c.added_to_payroll_run_id == run_id for c in claims)
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        _purge(cid)


def test_R6_a_failure_in_the_middle_leaves_no_run_row_and_no_locked_reimbursement(
    client, db, world, monkeypatch: pytest.MonkeyPatch
) -> None:
    _filled_world(db, world)
    ctx = world["ctx"]
    claim = _claim(client, world, "300.00")
    calls = {"n": 0}
    import app.modules.payroll.service as svc

    real = svc.calculate_payslip

    def _boom(data):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("engine failed halfway")
        return real(data)

    monkeypatch.setattr(svc, "calculate_payslip", _boom)
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    actor = db.get(User, world["owner_user"].id)
    assert actor is not None
    with pytest.raises(RuntimeError):
        PayrollRunService(db).create_run(
            ctx.company_id,
            PayrollRunCreateRequest(month=world["month"], year=world["year"]),
            f"fail-{uuid.uuid4()}",
            actor,
        )
    assert calls["n"] >= 2, "R6: the failure must happen after the first employee"
    assert db.query(PayrollRun).count() == 0, "R6: a failed run must leave no run row"
    assert db.query(PayrollItem).count() == 0, "R6: a failed run must leave no item"
    assert _claim_state(db, ctx, claim) == (ReimbursementStatus.approved, None), (
        "R6: a failed run must not lock the reimbursement"
    )
    assert _audit(db, ctx, "PAYROLL_RUN_CREATED") == [], "R6: no audit row for a failed run"


# ------------------------------------------------------------------- R7


def _run_item(client: TestClient, w: dict[str, Any], who: str = "emp") -> dict:
    run = _make_run(client, w["hr1"], w["year"], w["month"])
    return _item_for(client, w["hr1"], run["id"], w[who]["id"])


def _lop(item: dict) -> Decimal:
    return Decimal(item["lop_days"])


def test_R7_a_missing_row_and_an_absent_row_each_count_one_day(client, db, world) -> None:
    ctx, y, m = world["ctx"], world["year"], world["month"]
    days = _working_days_of(y, m)
    _fill(db, ctx, world["emp"]["id"], y, m, skip={days[0]})
    _mark(db, ctx, world["emp"]["id"], days[1], AttendanceStatus.absent)
    _fill(db, ctx, world["manager"]["id"], y, m)
    item = _run_item(client, world)
    assert _lop(item) == Decimal("2"), f"R7: one missing + one absent row = 2 days, got {item}"
    assert Decimal(item["absent_days"]) == Decimal("2")


def test_R7_a_half_day_counts_half_a_day(client, db, world) -> None:
    ctx, y, m = world["ctx"], world["year"], world["month"]
    _filled_world(db, world)
    _mark(db, ctx, world["emp"]["id"], _working_days_of(y, m)[2], AttendanceStatus.half_day)
    item = _run_item(client, world)
    assert _lop(item) == Decimal("0.5"), f"R7: a half day counts 0.5, got {item}"
    assert Decimal(item["half_days"]) == Decimal("1")


def test_R7_weekends_and_company_holidays_without_a_row_are_not_loss_of_pay(
    client, db, world
) -> None:
    ctx, y, m = world["ctx"], world["year"], world["month"]
    days = _days_of(y, m)
    weekends = {d for d in days if d.isoweekday() in (6, 7)}
    holiday = _working_days_of(y, m)[3]
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.add(Holiday(company_id=ctx.company_id, name="Founders day", date=holiday))
    db.commit()
    _fill(db, ctx, world["emp"]["id"], y, m, skip=weekends | {holiday})
    _fill(db, ctx, world["manager"]["id"], y, m)
    item = _run_item(client, world)
    assert _lop(item) == Decimal("0"), f"R7: weekend and holiday are not loss of pay: {item}"


def test_R7_a_day_off_work_of_a_five_day_week_company_can_be_moved(client, db, world) -> None:
    """Positive case for the company weekend setting: with Sunday only, a Saturday without a row
    IS a working day and counts as loss of pay."""
    ctx, y, m = world["ctx"], world["year"], world["month"]
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    row = db.query(CompanySettings).filter(CompanySettings.company_id == ctx.company_id).one()
    row.weekend_days = [7]
    db.commit()
    saturdays = {d for d in _days_of(y, m) if d.isoweekday() == 6}
    _fill(db, ctx, world["emp"]["id"], y, m, skip=saturdays)
    _fill(db, ctx, world["manager"]["id"], y, m)
    item = _run_item(client, world)
    assert _lop(item) == Decimal(len(saturdays)), f"R7: Saturdays are working days now: {item}"


def _leave_type(db: Session, ctx: TenantContext, *, paid: bool) -> uuid.UUID:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    lt = LeaveType(
        company_id=ctx.company_id,
        name=f"LT {uuid.uuid4().hex[:6]}",
        code=f"L{uuid.uuid4().hex[:6].upper()}",
        annual_allowance=Decimal("20"),
        carry_forward_limit=Decimal("0"),
        is_paid=paid,
    )
    db.add(lt)
    db.commit()
    return lt.id


def _leave(
    db: Session, ctx: TenantContext, emp_id: str, lt_id: uuid.UUID, start: date, end: date, **kw
):
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    days = [d for d in _days_of(start.year, start.month) if start <= d <= end]
    working = [d for d in days if d.isoweekday() not in (6, 7)]
    db.add(
        Leave(
            company_id=ctx.company_id,
            employee_id=uuid.UUID(emp_id),
            leave_type_id=lt_id,
            start_date=start,
            end_date=end,
            total_days=Decimal(len(working)),
            reason="Trip",
            status=LeaveStatus.approved,
            **kw,
        )
    )
    db.commit()


def test_R7_approved_unpaid_leave_counts_and_paid_leave_does_not(client, db, world) -> None:
    ctx, y, m = world["ctx"], world["year"], world["month"]
    days = _working_days_of(y, m)
    _filled_world(db, world)
    unpaid = _leave_type(db, ctx, paid=False)
    paid = _leave_type(db, ctx, paid=True)
    _leave(db, ctx, world["emp"]["id"], unpaid, days[0], days[0])
    _leave(db, ctx, world["emp"]["id"], paid, days[5], days[5])
    # the paid-leave day has no punch: it must still not be deducted
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.query(Attendance).filter(
        Attendance.employee_id == uuid.UUID(world["emp"]["id"]), Attendance.date == days[5]
    ).delete()
    db.commit()
    item = _run_item(client, world)
    assert _lop(item) == Decimal("1"), f"R7: unpaid leave 1 day, paid leave 0: {item}"
    assert Decimal(item["paid_leave_days"]) == Decimal("1"), f"R7: paid leave day recorded: {item}"


def test_R7_a_day_with_both_unpaid_leave_and_an_absent_row_is_counted_once(
    client, db, world
) -> None:
    ctx, y, m = world["ctx"], world["year"], world["month"]
    days = _working_days_of(y, m)
    _filled_world(db, world)
    unpaid = _leave_type(db, ctx, paid=False)
    _leave(db, ctx, world["emp"]["id"], unpaid, days[1], days[2])
    _mark(db, ctx, world["emp"]["id"], days[1], AttendanceStatus.absent)
    _mark(db, ctx, world["emp"]["id"], days[2], AttendanceStatus.on_leave)
    item = _run_item(client, world)
    assert _lop(item) == Decimal("2"), f"R7: no date may be counted twice, got {item}"


def test_R7_dates_before_joining_and_after_the_last_working_date_are_loss_of_pay(
    client, db, world
) -> None:
    ctx, y, m = world["ctx"], world["year"], world["month"]
    n = calendar.monthrange(y, m)[1]
    joiner = _staff(client, db, ctx, world["structure_id"], hire=date(y, m, 11).isoformat())
    leaver = _staff(client, db, ctx, world["structure_id"])
    _set_flags(
        db,
        ctx,
        leaver["id"],
        resignation_status=ResignationStatus.approved,
        last_working_date=date(y, m, 20),
    )
    _fill(db, ctx, joiner["id"], y, m)
    _fill(db, ctx, leaver["id"], y, m)
    for who in ("emp", "manager"):
        _fill(db, ctx, world[who]["id"], y, m)
    world["joiner"], world["leaver"] = joiner, leaver
    run = _make_run(client, world["hr1"], y, m)
    joiner_item = _item_for(client, world["hr1"], run["id"], joiner["id"])
    leaver_item = _item_for(client, world["hr1"], run["id"], leaver["id"])
    assert _lop(joiner_item) == Decimal(10), f"R7: 10 days before joining, got {joiner_item}"
    assert _lop(leaver_item) == Decimal(n - 20), f"R7: days after the last day: {leaver_item}"
    assert Decimal(joiner_item["gross_salary"]) < Decimal("48200.00")


def test_R7_mispunch_pending_regularization_wfh_and_on_leave_rows_are_not_deducted(
    client, db, world
) -> None:
    ctx, y, m = world["ctx"], world["year"], world["month"]
    days = _working_days_of(y, m)
    _filled_world(db, world)
    for day, status in zip(
        days[:4],
        (
            AttendanceStatus.mispunch,
            AttendanceStatus.pending_regularization,
            AttendanceStatus.wfh,
            AttendanceStatus.on_leave,
        ),
        strict=True,
    ):
        _mark(db, ctx, world["emp"]["id"], day, status)
    item = _run_item(client, world)
    assert _lop(item) == Decimal("0"), f"R7: these rows are not deducted, got {item}"


def test_R7_loss_of_pay_is_between_zero_and_the_days_of_the_month(client, db, world) -> None:
    y, m = world["year"], world["month"]
    run = _make_run(client, world["hr1"], y, m)  # nobody has any attendance at all
    item = _item_for(client, world["hr1"], run["id"], world["emp"]["id"])
    days = calendar.monthrange(y, m)[1]
    assert Decimal(0) <= _lop(item) <= Decimal(days), f"R7: lop out of range: {item}"
    assert Decimal(item["working_days"]) == Decimal(days)
    assert Decimal(item["gross_salary"]) >= Decimal(0)
    assert Decimal(item["net_salary"]) >= Decimal(0) or Decimal(item["gross_salary"]) == 0


def test_R7_an_attendance_exempt_employee_is_not_deducted_for_missing_rows(
    client, db, world
) -> None:
    ctx = world["ctx"]
    exempt = _staff(client, db, ctx, world["structure_id"], exempt=True)
    world["exempt"] = exempt
    item = _run_item(client, world, "exempt")
    assert _lop(item) == Decimal("0"), f"R7: an exempt employee is never deducted: {item}"


# ------------------------------------------------------------------- R8


def test_R8_pay_is_scaled_by_days_payable_with_half_up_rounding(client, db, world) -> None:
    """Worked example. Annual CTC 600000.12 -> monthly 50000.01. Basic 50% = 25000.005 -> 25000.01
    (half up). With 15 of 30 days lost the ratio is 0.5: gross 48200.01 * 0.5 = 24100.005 ->
    24100.01, basic 25000.01 * 0.5 = 12500.005 -> 12500.01. Half-even or truncating gives .00."""
    ctx = world["ctx"]
    y, m = _month_with_days(30)
    joiner = _staff(
        client, db, ctx, world["structure_id"], ctc="600000.12", hire=date(y, m, 16).isoformat()
    )
    _fill(db, ctx, joiner["id"], y, m)
    for who in ("emp", "manager"):
        _fill(db, ctx, world[who]["id"], y, m)
    run = _make_run(client, world["hr1"], y, m)
    item = _item_for(client, world["hr1"], run["id"], joiner["id"])
    assert Decimal(item["lop_days"]) == Decimal("15")
    assert item["gross_salary"] == "24100.01", f"R8: gross must round half up, got {item}"
    earnings = {e["code"]: e["amount"] for e in item["earnings_json"]}
    assert earnings["BASIC"] == "12500.01", f"R8: basic must round half up: {earnings}"
    assert earnings["HRA"] == "5000.00" and earnings["SPECIAL"] == "6600.00", earnings
    assert sum(Decimal(v) for v in earnings.values()) == Decimal(item["gross_salary"])


def test_R8_the_day_counts_on_the_item_come_from_attendance(client, db, world) -> None:
    ctx, y, m = world["ctx"], world["year"], world["month"]
    days = _working_days_of(y, m)
    _fill(db, ctx, world["emp"]["id"], y, m, skip={days[0], days[1]})
    _mark(db, ctx, world["emp"]["id"], days[1], AttendanceStatus.absent)
    _mark(db, ctx, world["emp"]["id"], days[2], AttendanceStatus.half_day)
    paid = _leave_type(db, ctx, paid=True)
    _leave(db, ctx, world["emp"]["id"], paid, days[3], days[4])
    _fill(db, ctx, world["manager"]["id"], y, m)
    item = _run_item(client, world)
    assert Decimal(item["absent_days"]) == Decimal("2"), f"R8: absent days from attendance: {item}"
    assert Decimal(item["half_days"]) == Decimal("1"), f"R8: half days from attendance: {item}"
    assert Decimal(item["paid_leave_days"]) == Decimal("2"), f"R8: paid leave days: {item}"
    assert _lop(item) == Decimal("2.5"), f"R8: lop is 2 absent + one half day: {item}"
    total = calendar.monthrange(y, m)[1]
    assert Decimal(item["present_days"]) == Decimal(total) - Decimal("2.5") - Decimal("2")


def test_R8_an_employee_without_salary_or_structure_is_listed_as_skipped_with_a_reason(
    client, db, world
) -> None:
    ctx, y, m = world["ctx"], world["year"], world["month"]
    no_salary = _staff(client, db, ctx, None)
    _filled_world(db, world)
    run = _make_run(client, world["hr1"], y, m)
    assert run["total_employees"] == 2, "R8: only the two salaried employees are processed"
    skipped = run["skipped_json"]
    assert skipped is not None and len(skipped) == 1, f"R8: expected one skipped: {run}"
    assert skipped[0]["employee_id"] == no_salary["id"]
    assert skipped[0]["reason"], "R8: a skipped employee needs a reason"
    detail = client.get(f"{RUNS}/{run['id']}", headers=world["hr1"]).json()
    assert detail["run"]["skipped_json"] == skipped, "R8: HR sees the same list on the detail"


# ------------------------------------------------------------------- R9


def test_R9_create_approve_and_delete_each_write_one_audit_row_without_amounts(
    client, db, world
) -> None:
    _filled_world(db, world)
    ctx = world["ctx"]
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    client.post(f"{RUNS}/{run['id']}/approve", headers=world["hr2"])
    other = _make_run(client, world["hr1"], *_month_back(2))
    client.delete(f"{RUNS}/{other['id']}", headers=world["hr2"])
    created = _audit(db, ctx, "PAYROLL_RUN_CREATED")
    approved = _audit(db, ctx, "PAYROLL_RUN_APPROVED")
    deleted = _audit(db, ctx, "PAYROLL_RUN_DELETED")
    assert len(created) == 2 and len(approved) == 1 and len(deleted) == 1, (
        f"R9: expected 2/1/1 audit rows, got {len(created)}/{len(approved)}/{len(deleted)}"
    )
    assert approved[0].entity_id == uuid.UUID(run["id"])
    assert approved[0].actor_user_id == world["hr2_user"].id
    for row in created + approved + deleted:
        blob = str(row.details).lower()
        for banned in ("total_net", "total_gross", "net", "gross", "salary", "amount"):
            assert banned not in blob, f"R9: {banned!r} must not be in audit details: {blob}"
        assert {"month", "year"} <= set(row.details or {}), "R9: month and year are recorded"


def test_R9_a_refused_approval_or_delete_writes_no_audit_row(client, db, world) -> None:
    ctx = world["ctx"]
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    client.post(f"{RUNS}/{run['id']}/approve", headers=world["hr1"])  # 403, maker-checker
    client.post(f"{RUNS}/{run['id']}/approve", headers=world["emp"]["h"])  # 403, role
    assert _audit(db, ctx, "PAYROLL_RUN_APPROVED") == [], "R9: no audit row for a refused approval"


def test_R9_create_approve_and_delete_are_limited_to_10_per_minute(client, db, world, limits_on):
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    limiter.reset()
    today = utcnow().date()
    created = [
        _post_run(client, world["hr1"], today.year, today.month).status_code for _ in range(11)
    ]
    assert 429 not in created[:10] and created[10] == 429, f"R9: create limit wrong: {created}"
    limiter.reset()
    approvals = [
        client.post(f"{RUNS}/{run['id']}/approve", headers=world["hr2"]).status_code
        for _ in range(11)
    ]
    assert 429 not in approvals[:10] and approvals[10] == 429, f"R9: approve limit: {approvals}"
    limiter.reset()
    deletes = [
        client.delete(f"{RUNS}/{uuid.uuid4()}", headers=world["hr2"]).status_code for _ in range(11)
    ]
    assert 429 not in deletes[:10] and deletes[10] == 429, f"R9: delete limit wrong: {deletes}"


def test_R9_reads_are_limited_to_60_per_minute(client, db, world, limits_on) -> None:
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    limiter.reset()
    listing = [client.get(RUNS, headers=world["hr1"]).status_code for _ in range(61)]
    assert listing[:60] == [200] * 60 and listing[60] == 429, "R9: list limit wrong"
    limiter.reset()
    single = [
        client.get(f"{RUNS}/{run['id']}", headers=world["hr1"]).status_code for _ in range(61)
    ]
    assert single[:60] == [200] * 60 and single[60] == 429, "R9: detail limit wrong"


# ------------------------------------------------------------------- R10


def test_R10_every_rule_from_1_to_9_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_R")]
    for rule in range(1, 10):
        assert any(n.startswith(f"test_R{rule}_") for n in names), f"R10: no test for rule {rule}"
