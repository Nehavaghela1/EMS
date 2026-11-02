"""Module 4, sub-feature 4.5: Leave types and balances. One test per rule line (R1..R10).

Dates that a rule compares with today come from utcnow().
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.identity.models import CompanySettings, LeaveYearType, UserRole
from app.modules.platform.models import AuditLog
from app.modules.time_leave.models import LeaveBalance
from app.modules.time_leave.repository import LeaveBalanceRepository, LeaveTypeRepository
from app.modules.time_leave.service import InsufficientLeaveBalanceError, LeaveService
from tests.conftest import REPO_ROOT, TenantContext, _make_user_headers
from tests.integration.test_leaves import (
    _create_employee,
    _link_user_to_employee,
    _next_monday_through_friday,
)

LEAVE_TYPES = "/api/v1/leave-types"
MIGRATION_REVISION = "c4d5e6f7a8b9"
PREVIOUS_REVISION = "a1b2c3d4e5f6"


def _code() -> str:
    return f"T{uuid.uuid4().hex[:8].upper()}"


def _payload(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"Type {uuid.uuid4().hex[:8]}",
        "code": _code(),
        "annual_allowance": "10",
    }
    body.update(over)
    return body


def _make(client: TestClient, headers: dict[str, str], **over: Any) -> dict[str, Any]:
    resp = client.post(LEAVE_TYPES, headers=headers, json=_payload(**over))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _owner_headers(db: Session, ctx: TenantContext) -> dict[str, str]:
    headers = _make_user_headers(db, ctx.company_id, UserRole.owner)
    db.commit()
    return headers


def _calendar_year_company(db: Session, ctx: TenantContext) -> None:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    row = db.query(CompanySettings).filter(CompanySettings.company_id == ctx.company_id).one()
    row.leave_year_type = LeaveYearType.calendar
    db.commit()


def _audit(db: Session, ctx: TenantContext, action: str) -> list[AuditLog]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    return (
        db.query(AuditLog)
        .filter(AuditLog.company_id == ctx.company_id, AuditLog.action == action)
        .all()
    )


def _employee(client, db, ctx: TenantContext, role: UserRole = UserRole.employee, **extra):
    emp = _create_employee(
        client, ctx.hr_headers, email=f"e-{uuid.uuid4().hex[:8]}@typeco.com", **extra
    )
    return emp, _link_user_to_employee(db, ctx.company_id, emp["id"], role)


def _seed(client, headers, employee_id: str, year: int | None = None):
    body: dict[str, Any] = {"employee_id": employee_id}
    if year is not None:
        body["year"] = year
    return client.post("/api/v1/leaves/balances/seed", headers=headers, json=body)


def _set_balance(db: Session, ctx: TenantContext, employee_id: str, type_id: str, year: int, **f):
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    row = (
        db.query(LeaveBalance)
        .filter(
            LeaveBalance.employee_id == uuid.UUID(employee_id),
            LeaveBalance.leave_type_id == uuid.UUID(type_id),
            LeaveBalance.year == year,
        )
        .one()
    )
    for key, value in f.items():
        setattr(row, key, Decimal(str(value)))
    db.commit()


def _balances(client, headers, employee_id: str, year: int | None = None):
    url = f"/api/v1/leaves/balance/{employee_id}"
    return client.get(url + (f"?year={year}" if year is not None else ""), headers=headers)


def _apply(client, headers, type_id: str, start, end, employee_id: str | None = None):
    body: dict[str, Any] = {
        "leave_type_id": type_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "reason": "Leave type rule test",
    }
    if employee_id:
        body["employee_id"] = employee_id
    return client.post("/api/v1/leaves", headers=headers, json=body)


# ---------------------------------------------------------------- R1 roles


def test_R1_no_login_gets_401(client: TestClient) -> None:
    assert client.get(LEAVE_TYPES).status_code == 401
    assert client.post(LEAVE_TYPES, json=_payload()).status_code == 401
    assert client.put(f"{LEAVE_TYPES}/{uuid.uuid4()}", json={"name": "x"}).status_code == 401


def test_R1_manager_and_employee_writes_get_403(client: TestClient, company_a: TenantContext):
    lt = _make(client, company_a.hr_headers)
    for who, headers in (
        ("manager", company_a.manager_headers),
        ("employee", company_a.employee_headers),
    ):
        assert client.post(LEAVE_TYPES, headers=headers, json=_payload()).status_code == 403, who
        put = client.put(f"{LEAVE_TYPES}/{lt['id']}", headers=headers, json={"is_active": False})
        assert put.status_code == 403, f"R1: {who} must not edit or deactivate a leave type"


def test_R1_owner_and_hr_admin_create_edit_and_deactivate(
    client: TestClient, db: Session, company_a: TenantContext
):
    for headers in (company_a.hr_headers, _owner_headers(db, company_a)):
        lt = _make(client, headers)
        edit = client.put(
            f"{LEAVE_TYPES}/{lt['id']}", headers=headers, json={"annual_allowance": "12"}
        )
        assert edit.status_code == 200 and Decimal(edit.json()["annual_allowance"]) == Decimal("12")
        off = client.put(f"{LEAVE_TYPES}/{lt['id']}", headers=headers, json={"is_active": False})
        assert off.status_code == 200 and off.json()["is_active"] is False


def test_R1_everyone_lists_only_active_types(client: TestClient, company_a: TenantContext):
    keep = _make(client, company_a.hr_headers)
    gone = _make(client, company_a.hr_headers)
    client.put(
        f"{LEAVE_TYPES}/{gone['id']}", headers=company_a.hr_headers, json={"is_active": False}
    )
    for headers in (company_a.employee_headers, company_a.manager_headers, company_a.hr_headers):
        ids = {lt["id"] for lt in client.get(LEAVE_TYPES, headers=headers).json()}
        assert keep["id"] in ids and gone["id"] not in ids, "R1: list must show active types only"


# --------------------------------------------------------------- R2 input


def test_R2_name_is_trimmed_1_to_100_and_unique_ignoring_case(
    client: TestClient, company_a: TenantContext
):
    trimmed = _make(client, company_a.hr_headers, name="  Sabbatical  ")
    assert trimmed["name"] == "Sabbatical", "R2: name not trimmed"
    assert _make(client, company_a.hr_headers, name="x" * 100)["name"] == "x" * 100
    for bad in ("", "   ", "x" * 101):
        resp = client.post(LEAVE_TYPES, headers=company_a.hr_headers, json=_payload(name=bad))
        assert resp.status_code == 422, f"R2: name of length {len(bad)} must give 422"
    dup = client.post(LEAVE_TYPES, headers=company_a.hr_headers, json=_payload(name="SABBATICAL"))
    assert dup.status_code == 409, f"R2: name unique ignoring case, got {dup.status_code}"


def test_R2_code_is_2_to_10_alphanumeric_uppercased_and_unique(
    client: TestClient, company_a: TenantContext
):
    made = _make(client, company_a.hr_headers, code="pl01")
    assert made["code"] == "PL01", "R2: code must be upper-cased"
    for bad in ("A", "ABCDEFGHIJK", "AB-C", "AB_C", "AB C", ""):
        resp = client.post(LEAVE_TYPES, headers=company_a.hr_headers, json=_payload(code=bad))
        assert resp.status_code == 422, f"R2: code {bad!r} must give 422, got {resp.status_code}"
    assert _make(client, company_a.hr_headers, code="AB")["code"] == "AB"
    assert _make(client, company_a.hr_headers, code="ABCDEFGHIJ")["code"] == "ABCDEFGHIJ"
    dup = client.post(LEAVE_TYPES, headers=company_a.hr_headers, json=_payload(code="Pl01"))
    assert dup.status_code == 409, "R2: code unique ignoring case must give 409"


def test_R2_allowance_0_to_365_in_half_steps(client: TestClient, company_a: TenantContext):
    for bad in ("-1", "365.5", "366", "1.3", "0.25"):
        resp = client.post(
            LEAVE_TYPES, headers=company_a.hr_headers, json=_payload(annual_allowance=bad)
        )
        assert resp.status_code == 422, f"R2: allowance {bad} must give 422, got {resp.status_code}"
    for good in ("0", "0.5", "2.5", "365"):
        _make(client, company_a.hr_headers, annual_allowance=good)


def test_R2_carry_forward_is_0_up_to_the_allowance(client: TestClient, company_a: TenantContext):
    for bad in ("-0.5", "10.5"):
        resp = client.post(
            LEAVE_TYPES,
            headers=company_a.hr_headers,
            json=_payload(annual_allowance="10", carry_forward_limit=bad),
        )
        assert resp.status_code == 422, f"R2: carry-forward {bad} over allowance 10 must give 422"
    _make(client, company_a.hr_headers, annual_allowance="10", carry_forward_limit="10")
    lt = _make(client, company_a.hr_headers, annual_allowance="10", carry_forward_limit="4")
    edit = client.put(
        f"{LEAVE_TYPES}/{lt['id']}", headers=company_a.hr_headers, json={"annual_allowance": "3"}
    )
    assert edit.status_code == 422, "R2: lowering allowance below carry-forward must give 422"


def test_R2_max_consecutive_days_1_to_365_or_empty(client: TestClient, company_a: TenantContext):
    for bad in (0, -1, 366):
        resp = client.post(
            LEAVE_TYPES, headers=company_a.hr_headers, json=_payload(max_consecutive_days=bad)
        )
        assert resp.status_code == 422, f"R2: max_consecutive_days {bad} must give 422"
    assert _make(client, company_a.hr_headers, max_consecutive_days=1)["max_consecutive_days"] == 1
    assert _make(client, company_a.hr_headers, max_consecutive_days=365)
    empty = _make(client, company_a.hr_headers, max_consecutive_days=None)
    assert empty["max_consecutive_days"] is None
    cleared = client.put(
        f"{LEAVE_TYPES}/{empty['id']}",
        headers=company_a.hr_headers,
        json={"max_consecutive_days": None},
    )
    assert cleared.status_code == 200


def test_R2_unknown_fields_and_nulls_on_required_fields_give_422(
    client: TestClient, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers)
    assert (
        client.post(
            LEAVE_TYPES, headers=company_a.hr_headers, json=_payload(color="red")
        ).status_code
        == 422
    )
    for field in ("name", "code", "annual_allowance", "is_paid"):
        resp = client.post(
            LEAVE_TYPES, headers=company_a.hr_headers, json=_payload(**{field: None})
        )
        assert resp.status_code == 422, f"R2: null {field} on create must give 422"
    for field in ("name", "annual_allowance", "carry_forward_limit", "is_paid", "is_active"):
        resp = client.put(
            f"{LEAVE_TYPES}/{lt['id']}", headers=company_a.hr_headers, json={field: None}
        )
        assert resp.status_code == 422, f"R2: null {field} on update must give 422"
    resp = client.put(
        f"{LEAVE_TYPES}/{lt['id']}", headers=company_a.hr_headers, json={"color": "red"}
    )
    assert resp.status_code == 422, "R2: unknown field on update must give 422"


def test_R2_renaming_to_another_types_name_or_code_is_409(
    client: TestClient, company_a: TenantContext
):
    first = _make(client, company_a.hr_headers, name="First One", code="FIRST1")
    second = _make(client, company_a.hr_headers)
    by_name = client.put(
        f"{LEAVE_TYPES}/{second['id']}", headers=company_a.hr_headers, json={"name": "first one"}
    )
    assert by_name.status_code == 409, "R2: rename to an existing name must give 409"
    by_code = client.put(
        f"{LEAVE_TYPES}/{second['id']}", headers=company_a.hr_headers, json={"code": "first1"}
    )
    assert by_code.status_code == 409, "R2: code change to an existing code must give 409"
    same = client.put(
        f"{LEAVE_TYPES}/{first['id']}", headers=company_a.hr_headers, json={"name": "FIRST ONE"}
    )
    assert same.status_code == 200, "R2: a type may keep its own name (case change)"


# ------------------------------------------------- R3 locked fields, policy


def test_R3_code_and_paid_flag_can_change_while_nothing_uses_the_type(
    client: TestClient, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers)
    resp = client.put(
        f"{LEAVE_TYPES}/{lt['id']}",
        headers=company_a.hr_headers,
        json={"code": "NEWCODE", "is_paid": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == "NEWCODE" and resp.json()["is_paid"] is False


def test_R3_code_and_paid_flag_are_locked_once_a_balance_exists(
    client: TestClient, db: Session, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers)
    emp, _ = _employee(client, db, company_a)
    assert _seed(client, company_a.hr_headers, emp["id"], 2031).status_code == 200
    for body in ({"code": "OTHER1"}, {"is_paid": False}):
        resp = client.put(f"{LEAVE_TYPES}/{lt['id']}", headers=company_a.hr_headers, json=body)
        assert resp.status_code == 409, f"R3: {body} after a balance exists must give 409"
    same = client.put(
        f"{LEAVE_TYPES}/{lt['id']}",
        headers=company_a.hr_headers,
        json={"code": lt["code"].lower(), "is_paid": True, "name": "Renamed ok"},
    )
    assert same.status_code == 200, "R3: unchanged code and paid flag must not be blocked"


def test_R3_code_and_paid_flag_are_locked_once_a_leave_exists(
    client: TestClient, db: Session, company_a: TenantContext
):
    _calendar_year_company(db, company_a)
    lt = _make(client, company_a.hr_headers)
    emp, headers = _employee(client, db, company_a)
    start, end = _next_monday_through_friday()
    assert _apply(client, headers, lt["id"], start, start).status_code == 201
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    db.query(LeaveBalance).filter(LeaveBalance.leave_type_id == uuid.UUID(lt["id"])).delete()
    db.commit()  # only the leave remains
    for body in ({"code": "OTHER2"}, {"is_paid": False}):
        resp = client.put(f"{LEAVE_TYPES}/{lt['id']}", headers=company_a.hr_headers, json=body)
        assert resp.status_code == 409, f"R3: {body} after a leave exists must give 409"


def test_R3_allowance_change_affects_only_balances_created_later(
    client: TestClient, db: Session, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers, annual_allowance="10")
    first, _ = _employee(client, db, company_a)
    second, _ = _employee(client, db, company_a)
    assert _seed(client, company_a.hr_headers, first["id"], 2031).status_code == 200
    edit = client.put(
        f"{LEAVE_TYPES}/{lt['id']}", headers=company_a.hr_headers, json={"annual_allowance": "20"}
    )
    assert edit.status_code == 200
    old = _balances(client, company_a.hr_headers, first["id"], 2031).json()
    assert [Decimal(b["allocated"]) for b in old if b["leave_type_id"] == lt["id"]] == [
        Decimal("10")
    ]
    assert _seed(client, company_a.hr_headers, second["id"], 2031).status_code == 200
    new = _balances(client, company_a.hr_headers, second["id"], 2031).json()
    assert [Decimal(b["allocated"]) for b in new if b["leave_type_id"] == lt["id"]] == [
        Decimal("20")
    ]


# ------------------------------------------------------------ R4 deactivate


def test_R4_deactivated_type_cannot_be_applied_for_but_history_stays(
    client: TestClient, db: Session, company_a: TenantContext
):
    _calendar_year_company(db, company_a)
    lt = _make(client, company_a.hr_headers, annual_allowance="10")
    emp, headers = _employee(client, db, company_a)
    start, end = _next_monday_through_friday()
    first = _apply(client, headers, lt["id"], start, start)
    assert first.status_code == 201, first.text
    off = client.put(
        f"{LEAVE_TYPES}/{lt['id']}", headers=company_a.hr_headers, json={"is_active": False}
    )
    assert off.status_code == 200
    again = _apply(client, headers, lt["id"], end, end)
    assert again.status_code == 404, (
        f"R4: inactive type must not be applied for, got {again.status_code}"
    )
    still = client.get(f"/api/v1/leaves/{first.json()['id']}", headers=headers)
    assert still.status_code == 200, "R4: existing leave must stay"
    balances = _balances(client, headers, emp["id"], start.year).json()
    assert lt["id"] in {b["leave_type_id"] for b in balances}, (
        "R4: balance must stay after deactivation"
    )


# --------------------------------------------------------------- R5 balance


def test_R5_available_is_opening_plus_allocated_minus_used_minus_encashed(
    client: TestClient, db: Session, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers, annual_allowance="10")
    emp, _ = _employee(client, db, company_a)
    _seed(client, company_a.hr_headers, emp["id"], 2031)
    _set_balance(
        db, company_a, emp["id"], lt["id"], 2031, opening_balance="2", used="3", encashed="1"
    )
    row = next(
        b
        for b in _balances(client, company_a.hr_headers, emp["id"], 2031).json()
        if b["leave_type_id"] == lt["id"]
    )
    assert Decimal(row["available"]) == Decimal("8"), f"R5: 2 + 10 - 3 - 1 expected 8, got {row}"


def test_R5_paid_leave_beyond_the_balance_is_refused_and_exact_balance_works(
    client: TestClient, db: Session, company_a: TenantContext
):
    _calendar_year_company(db, company_a)
    lt = _make(client, company_a.hr_headers, annual_allowance="4")
    emp, headers = _employee(client, db, company_a)
    start, end = _next_monday_through_friday()  # five working days
    too_much = _apply(client, headers, lt["id"], start, end)
    assert too_much.status_code == 400, too_much.text
    assert too_much.json()["error"]["code"] == "insufficient_leave_balance"
    four = _apply(client, headers, lt["id"], start, start + (end - start) * 3 // 4)  # Mon-Thu
    assert four.status_code == 201, (
        f"R5: a leave equal to the balance must be accepted: {four.text}"
    )
    row = next(
        b
        for b in _balances(client, headers, emp["id"], start.year).json()
        if b["leave_type_id"] == lt["id"]
    )
    assert Decimal(row["available"]) >= 0, "R5: balance must never be negative for a paid type"


def test_R5_unpaid_type_has_no_balance_check(
    client: TestClient, db: Session, company_a: TenantContext
):
    _calendar_year_company(db, company_a)
    lt = _make(client, company_a.hr_headers, annual_allowance="0", is_paid=False)
    _, headers = _employee(client, db, company_a)
    start, end = _next_monday_through_friday()
    resp = _apply(client, headers, lt["id"], start, end)
    assert resp.status_code == 201, f"R5: unpaid leave must not be balance-checked: {resp.text}"


def test_R5_locked_helper_checks_the_balance_under_a_row_lock(
    client: TestClient, db: Session, company_a: TenantContext
):
    paid = _make(client, company_a.hr_headers, annual_allowance="3")
    unpaid = _make(client, company_a.hr_headers, annual_allowance="0", is_paid=False)
    emp, _ = _employee(client, db, company_a)
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    types = LeaveTypeRepository(db)
    paid_type = types.get_by_id(uuid.UUID(paid["id"]), company_a.company_id)
    unpaid_type = types.get_by_id(uuid.UUID(unpaid["id"]), company_a.company_id)
    service = LeaveService(db)
    statements: list[str] = []

    def _capture(conn, cursor, statement, *args):  # noqa: ANN001
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", _capture)
    try:
        service.require_available_balance_locked(
            company_a.company_id, uuid.UUID(emp["id"]), paid_type, 2031, Decimal("3")
        )
        with pytest.raises(InsufficientLeaveBalanceError):
            service.require_available_balance_locked(
                company_a.company_id, uuid.UUID(emp["id"]), paid_type, 2031, Decimal("3.5")
            )
        service.require_available_balance_locked(
            company_a.company_id, uuid.UUID(emp["id"]), unpaid_type, 2031, Decimal("99")
        )
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", _capture)
    assert any("FOR UPDATE" in s.upper() for s in statements), "R5: balance row was not locked"


# ------------------------------------------------- R6 leave year, carry fwd


def test_R6_balance_year_is_validated(client: TestClient, db: Session, company_a: TenantContext):
    emp, _ = _employee(client, db, company_a)
    for bad in ("1999", "2101", "abc"):
        resp = client.get(
            f"/api/v1/leaves/balance/{emp['id']}?year={bad}", headers=company_a.hr_headers
        )
        assert resp.status_code == 422, f"R6: balance year {bad} must give 422"
    for bad in (1999, 2101):
        assert _seed(client, company_a.hr_headers, emp["id"], bad).status_code == 422


def test_R6_default_balance_year_is_the_current_leave_year_of_the_company(
    client: TestClient, db: Session, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers)
    emp, _ = _employee(client, db, company_a)
    today = utcnow().date()
    if today.month < 12:
        start_month, expected = today.month + 1, today.year - 1  # the year began last year
    else:
        start_month, expected = 12, today.year
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    row = db.query(CompanySettings).filter(CompanySettings.company_id == company_a.company_id).one()
    row.leave_year_type = LeaveYearType.financial
    row.leave_year_start_month = start_month
    db.commit()
    seeded = _seed(client, company_a.hr_headers, emp["id"])
    assert seeded.status_code == 200, seeded.text
    assert {b["year"] for b in seeded.json()} == {expected}, (
        "R6: seed default is not the leave year"
    )
    listed = _balances(client, company_a.hr_headers, emp["id"]).json()
    assert lt["id"] in {b["leave_type_id"] for b in listed}, (
        "R6: default year of the route is wrong"
    )
    assert {b["year"] for b in listed} == {expected}


@pytest.mark.parametrize(
    ("carry_limit", "expected_opening"),
    [("0", "0"), ("5", "5"), ("10", "7")],
)
def test_R6_new_year_opening_is_unused_balance_up_to_carry_forward_limit(
    client: TestClient,
    db: Session,
    company_a: TenantContext,
    carry_limit: str,
    expected_opening: str,
):
    lt = _make(client, company_a.hr_headers, annual_allowance="10", carry_forward_limit=carry_limit)
    emp, _ = _employee(client, db, company_a)
    _seed(client, company_a.hr_headers, emp["id"], 2031)
    _set_balance(db, company_a, emp["id"], lt["id"], 2031, used="3")  # 7 unused
    assert _seed(client, company_a.hr_headers, emp["id"], 2032).status_code == 200
    row = next(
        b
        for b in _balances(client, company_a.hr_headers, emp["id"], 2032).json()
        if b["leave_type_id"] == lt["id"]
    )
    assert Decimal(row["opening_balance"]) == Decimal(expected_opening), f"R6: carry wrong: {row}"
    assert Decimal(row["allocated"]) == Decimal("10")


def test_R6_carry_forward_also_applies_when_the_balance_is_created_by_applying(
    client: TestClient, db: Session, company_a: TenantContext
):
    _calendar_year_company(db, company_a)
    lt = _make(client, company_a.hr_headers, annual_allowance="10", carry_forward_limit="4")
    emp, headers = _employee(client, db, company_a)
    start, _ = _next_monday_through_friday()
    previous = start.year - 1
    _seed(client, company_a.hr_headers, emp["id"], previous)
    _set_balance(db, company_a, emp["id"], lt["id"], previous, used="2")  # 8 unused, limit 4
    assert _apply(client, headers, lt["id"], start, start).status_code == 201
    row = next(
        b
        for b in _balances(client, headers, emp["id"], start.year).json()
        if b["leave_type_id"] == lt["id"]
    )
    assert Decimal(row["opening_balance"]) == Decimal("4"), f"R6: lazy balance lost carry: {row}"


def test_R6_overspent_previous_year_carries_nothing(
    client: TestClient, db: Session, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers, annual_allowance="10", carry_forward_limit="5")
    emp, _ = _employee(client, db, company_a)
    _seed(client, company_a.hr_headers, emp["id"], 2031)
    _set_balance(db, company_a, emp["id"], lt["id"], 2031, used="12")
    _seed(client, company_a.hr_headers, emp["id"], 2032)
    row = next(
        b
        for b in _balances(client, company_a.hr_headers, emp["id"], 2032).json()
        if b["leave_type_id"] == lt["id"]
    )
    assert Decimal(row["opening_balance"]) == Decimal("0"), "R6: negative carry must be 0"


# ------------------------------------------------------------- R7 who sees


def test_R7_employee_sees_own_balances_only(
    client: TestClient, db: Session, company_a: TenantContext
):
    _make(client, company_a.hr_headers)
    mine, my_headers = _employee(client, db, company_a)
    other, _ = _employee(client, db, company_a)
    assert _balances(client, my_headers, mine["id"]).status_code == 200
    denied = _balances(client, my_headers, other["id"])
    assert denied.status_code == 403, (
        f"R7: employee must not see a colleague, got {denied.status_code}"
    )


def test_R7_manager_sees_direct_reports_read_only(
    client: TestClient, db: Session, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers)
    boss, boss_headers = _employee(client, db, company_a, UserRole.manager)
    report, _ = _employee(client, db, company_a, reporting_manager_id=boss["id"])
    stranger, _ = _employee(client, db, company_a)
    _seed(client, company_a.hr_headers, report["id"], 2031)
    seen = _balances(client, boss_headers, report["id"], 2031)
    assert seen.status_code == 200, f"R7: manager must see a direct report: {seen.text}"
    assert lt["id"] in {b["leave_type_id"] for b in seen.json()}
    assert _balances(client, boss_headers, boss["id"]).status_code == 200, "R7: manager own balance"
    assert _balances(client, boss_headers, stranger["id"]).status_code == 403, "R7: not a report"
    assert _seed(client, boss_headers, report["id"], 2031).status_code == 403, "R7: read only"


def test_R7_hr_level_sees_anyone_in_the_company(
    client: TestClient, db: Session, company_a: TenantContext
):
    emp, _ = _employee(client, db, company_a)
    assert _balances(client, company_a.hr_headers, emp["id"]).status_code == 200
    assert _balances(client, _owner_headers(db, company_a), emp["id"]).status_code == 200


def test_R7_other_company_and_missing_employee_give_the_same_404(
    client: TestClient,
    db: Session,
    company_a: TenantContext,
    company_b: TenantContext,
    super_admin_headers: dict[str, str],
):
    foreign, foreign_headers = _employee(client, db, company_b)
    mine, my_headers = _employee(client, db, company_a)
    missing = str(uuid.uuid4())
    answers = [
        _balances(client, company_a.hr_headers, foreign["id"]),
        _balances(client, my_headers, foreign["id"]),
        _balances(client, company_a.hr_headers, missing),
        _balances(client, super_admin_headers, mine["id"]),
    ]
    assert [r.status_code for r in answers] == [404, 404, 404, 404], (
        f"R7: other company must be 404 for everyone incl. super admin: "
        f"{[r.status_code for r in answers]}"
    )
    assert len({r.json()["error"]["message"] for r in answers}) == 1, "R7: messages differ"


# ------------------------------------------------------------------ R8 seed


def test_R8_seed_creates_missing_balances_and_is_safe_to_repeat(
    client: TestClient, db: Session, company_a: TenantContext
):
    first_type = _make(client, company_a.hr_headers, annual_allowance="6")
    emp, _ = _employee(client, db, company_a)
    once = _seed(client, company_a.hr_headers, emp["id"], 2031)
    assert once.status_code == 200, once.text
    assert first_type["id"] in {b["leave_type_id"] for b in once.json()}
    second_type = _make(client, company_a.hr_headers, annual_allowance="4")
    _set_balance(db, company_a, emp["id"], first_type["id"], 2031, used="2")
    again = _seed(client, company_a.hr_headers, emp["id"], 2031)
    assert again.status_code == 200
    rows = [b for b in again.json() if b["leave_type_id"] == first_type["id"]]
    assert len(rows) == 1 and Decimal(rows[0]["used"]) == Decimal("2"), "R8: repeat overwrote a row"
    assert second_type["id"] in {b["leave_type_id"] for b in again.json()}, "R8: missing not added"
    ids = [(b["leave_type_id"], b["year"]) for b in again.json()]
    assert len(ids) == len(set(ids)), "R8: duplicate balances after repeat"


def test_R8_seed_insert_is_idempotent_at_the_database(
    client: TestClient, db: Session, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers)
    emp, _ = _employee(client, db, company_a)
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    repo = LeaveBalanceRepository(db)
    kwargs = {
        "company_id": company_a.company_id,
        "employee_id": uuid.UUID(emp["id"]),
        "leave_type_id": uuid.UUID(lt["id"]),
        "year": 2031,
        "opening_balance": Decimal("0"),
        "allocated": Decimal("10"),
    }
    first, created_first = repo.create_if_missing(**kwargs)
    second, created_second = repo.create_if_missing(**kwargs)
    assert created_first is True and created_second is False, "R8: second insert must be a no-op"
    assert first.id == second.id


def test_R8_only_hr_level_seeds_and_other_company_is_404(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    emp, emp_headers = _employee(client, db, company_a)
    foreign, _ = _employee(client, db, company_b)
    assert _seed(client, emp_headers, emp["id"], 2031).status_code == 403
    assert _seed(client, company_a.manager_headers, emp["id"], 2031).status_code == 403
    assert _seed(client, company_a.hr_headers, foreign["id"], 2031).status_code == 404
    assert _seed(client, company_a.hr_headers, str(uuid.uuid4()), 2031).status_code == 404
    assert _seed(client, _owner_headers(db, company_a), emp["id"], 2031).status_code == 200
    bad = client.post(
        "/api/v1/leaves/balances/seed",
        headers=company_a.hr_headers,
        json={"employee_id": emp["id"], "year": 2031, "extra": 1},
    )
    assert bad.status_code == 422, "R8: unknown field must give 422"


def test_R8_seed_is_limited_to_30_per_minute(
    client: TestClient, db: Session, company_a: TenantContext
):
    emp, _ = _employee(client, db, company_a)
    limiter.enabled = True
    limiter.reset()
    try:
        codes = [
            _seed(client, company_a.hr_headers, emp["id"], 2031).status_code for _ in range(31)
        ]
    finally:
        limiter.reset()
        limiter.enabled = False
    assert codes[:30] == [200] * 30 and codes[30] == 429, f"R8: seed limit wrong: {codes}"


# ----------------------------------------------------------------- R9 audit


def test_R9_create_edit_deactivate_and_seed_write_audit_rows_without_free_text(
    client: TestClient, db: Session, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers, name="Very Private Name", code="PRIV1")
    type_id = uuid.UUID(lt["id"])
    created = _audit(db, company_a, "LEAVE_TYPE_CREATED")
    assert len(created) == 1 and created[0].entity_id == type_id, "R9: LEAVE_TYPE_CREATED missing"

    edit = client.put(
        f"{LEAVE_TYPES}/{lt['id']}",
        headers=company_a.hr_headers,
        json={"annual_allowance": "12", "name": "Another Private Name"},
    )
    assert edit.status_code == 200
    updated = _audit(db, company_a, "LEAVE_TYPE_UPDATED")
    assert len(updated) == 1 and updated[0].entity_id == type_id, "R9: LEAVE_TYPE_UPDATED missing"
    assert sorted(updated[0].details["changed_fields"]) == ["annual_allowance", "name"]

    noop = client.put(
        f"{LEAVE_TYPES}/{lt['id']}", headers=company_a.hr_headers, json={"annual_allowance": "12"}
    )
    assert noop.status_code == 200
    assert len(_audit(db, company_a, "LEAVE_TYPE_UPDATED")) == 1, "R9: no-op must not audit"

    off = client.put(
        f"{LEAVE_TYPES}/{lt['id']}", headers=company_a.hr_headers, json={"is_active": False}
    )
    assert off.status_code == 200
    deactivated = _audit(db, company_a, "LEAVE_TYPE_DEACTIVATED")
    assert len(deactivated) == 1 and deactivated[0].entity_id == type_id, "R9: DEACTIVATED missing"

    emp, _ = _employee(client, db, company_a)
    _make(client, company_a.hr_headers)
    assert _seed(client, company_a.hr_headers, emp["id"], 2031).status_code == 200
    seeded = _audit(db, company_a, "LEAVE_BALANCES_SEEDED")
    assert len(seeded) == 1, "R9: LEAVE_BALANCES_SEEDED missing"
    assert seeded[0].details["employee_id"] == emp["id"] and seeded[0].details["year"] == 2031

    everything = " ".join(
        str(r.details)
        for action in (
            "LEAVE_TYPE_CREATED",
            "LEAVE_TYPE_UPDATED",
            "LEAVE_TYPE_DEACTIVATED",
            "LEAVE_BALANCES_SEEDED",
        )
        for r in _audit(db, company_a, action)
    )
    assert "Private" not in everything and "PRIV1" not in everything, "R9: free text in audit"


def test_R9_failed_requests_write_no_audit_row(
    client: TestClient, db: Session, company_a: TenantContext
):
    lt = _make(client, company_a.hr_headers, code="DUPE1")
    before = len(_audit(db, company_a, "LEAVE_TYPE_CREATED"))
    assert (
        client.post(
            LEAVE_TYPES, headers=company_a.hr_headers, json=_payload(code="dupe1")
        ).status_code
        == 409
    )
    assert len(_audit(db, company_a, "LEAVE_TYPE_CREATED")) == before
    assert lt


# ------------------------------------------------------- R10 migration/meta


def test_R10_migration_refuses_duplicates_and_round_trips() -> None:
    assert settings.TEST_MIGRATION_URL is not None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        engine = create_engine(settings.TEST_MIGRATION_URL)
        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        company_id = uuid.uuid4()
        code = f"ML{company_id.hex[:10].upper()}"
        insert = (
            "INSERT INTO leave_types (id, company_id, name, code, annual_allowance,"
            " carry_forward_limit, requires_approval, is_paid, is_encashable, is_active,"
            " deleted_at, created_at, updated_at) VALUES (gen_random_uuid(), :c, :n, :k, 1, 0,"
            " true, true, false, true, {deleted}, NOW(), NOW())"
        )

        def _add(name: str, kind: str, deleted: str = "NULL") -> None:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE leave_types NO FORCE ROW LEVEL SECURITY"))
                conn.execute(
                    text(insert.format(deleted=deleted)), {"c": company_id, "n": name, "k": kind}
                )
                conn.execute(text("ALTER TABLE leave_types FORCE ROW LEVEL SECURITY"))

        def _clean() -> None:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE leave_types NO FORCE ROW LEVEL SECURITY"))
                conn.execute(
                    text("DELETE FROM leave_types WHERE company_id = :c"), {"c": company_id}
                )
                conn.execute(text("ALTER TABLE leave_types FORCE ROW LEVEL SECURITY"))

        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO companies (id, name, code, email, status, country, currency,"
                        " last_employee_seq, created_at, updated_at) VALUES (:i, 'Mig Type Co', :c,"
                        " :e, 'active', 'IN', 'INR', 0, NOW(), NOW())"
                    ),
                    {"i": company_id, "c": code, "e": f"{code.lower()}@test.test"},
                )
            indexes = {i["name"] for i in inspect(engine).get_indexes("leave_types")}
            assert {
                "uq_leave_types_company_lower_name",
                "uq_leave_types_company_lower_code",
            } <= indexes

            command.downgrade(cfg, PREVIOUS_REVISION)
            _add("Annual", "ANN")
            _add("annual", "ANN2")  # same name, other case
            with pytest.raises(RuntimeError) as by_name:
                command.upgrade(cfg, MIGRATION_REVISION)
            assert (
                "duplicate" in str(by_name.value).lower() and "annual" in str(by_name.value).lower()
            )

            _clean()
            _add("Annual", "ann")
            _add("Other", "ANN")  # same code, other case
            with pytest.raises(RuntimeError) as by_code:
                command.upgrade(cfg, MIGRATION_REVISION)
            assert "duplicate" in str(by_code.value).lower() and "ann" in str(by_code.value).lower()

            _clean()
            _add("Annual", "ANN", deleted="NOW()")
            _add("annual", "ann")  # the first one is soft-deleted: allowed
            command.upgrade(cfg, MIGRATION_REVISION)
            indexes = {i["name"] for i in inspect(engine).get_indexes("leave_types")}
            assert "uq_leave_types_company_lower_code" in indexes

            command.downgrade(cfg, PREVIOUS_REVISION)
            names = {c["name"] for c in inspect(engine).get_unique_constraints("leave_types")}
            assert "uq_leave_types_company_id_code" in names, "R10: old constraint not restored"
            command.upgrade(cfg, MIGRATION_REVISION)

            _clean()
            _add("Gone", "XX1", deleted="NOW()")
            _add("Live", "XX1")  # allowed only by the partial index
            with pytest.raises(RuntimeError) as down:
                command.downgrade(cfg, PREVIOUS_REVISION)
            assert (
                "cannot restore" in str(down.value).lower()
                or "duplicate" in str(down.value).lower()
            )
        finally:
            try:
                _clean()
                command.upgrade(cfg, "head")
            finally:
                _clean()
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": company_id})
                engine.dispose()
