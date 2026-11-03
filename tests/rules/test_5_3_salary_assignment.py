# ruff: noqa: F811
"""Module 5, sub-feature 5.3: Salary assignment and revisions. One test per rule line (R1..R10).

Dates a rule compares with today are computed from utcnow(); dates only compared with each
other (history, overlaps) are offsets from today as well, so nothing here ages.
"""

import threading
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.main import app as fastapi_app
from app.modules.identity.models import UserRole
from app.modules.payroll.models import (
    EmployeeSalary,
    PayrollRun,
    PayrollRunStatus,
    SalaryStructure,
)
from tests.conftest import TenantContext
from tests.rules.test_4_2_punch import _create_employee
from tests.rules.test_5_1_salary_structures import (  # noqa: F401
    E,
    S,
    _assign,
    _c,
    _day,
    _make,
    _msg,
    _std,
    race_company,
)
from tests.rules.test_5_4_payroll_runs import (  # noqa: F401
    PAYSLIPS,
    RUNS,
    _audit,
    _extra_user,
    _fill,
    _make_run,
    _month_back,
    _seed_statutory,
    _set_flags,
    _staff,
    limits_on,
    world,
)

NO_SALARY = "No salary is currently assigned to this employee."


def _quiet(client: TestClient) -> TestClient:
    """A server error comes back as a 500 (not as a raised exception), so a test that expects
    another status fails on its assertion."""
    return TestClient(client.app, raise_server_exceptions=False)


def _hist(client: TestClient, headers: dict[str, str], emp_id: str, query: str = ""):
    return _quiet(client).get(f"{E}/{emp_id}/salary-history{query}", headers=headers)


def _hist_json(client: TestClient, headers: dict[str, str], emp_id: str, query: str = "") -> dict:
    resp = _hist(client, headers, emp_id, query)
    assert resp.status_code == 200, f"history {query!r}: {resp.status_code} {resp.text[:200]}"
    return resp.json()


def _salary(client: TestClient, headers: dict[str, str], emp_id: str):
    return _quiet(client).get(f"{E}/{emp_id}/salary", headers=headers)


def _rows(db: Session, ctx: TenantContext, emp_id: str) -> list[EmployeeSalary]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.expire_all()
    return (
        db.query(EmployeeSalary)
        .filter(EmployeeSalary.employee_id == uuid.UUID(emp_id))
        .order_by(EmployeeSalary.effective_from)
        .all()
    )


def _insert_row(
    db: Session,
    ctx: TenantContext,
    emp_id: str,
    structure_id: str,
    start: date,
    end: date | None,
    created_by: uuid.UUID,
    deleted: bool = False,
) -> EmployeeSalary:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    row = EmployeeSalary(
        company_id=ctx.company_id,
        employee_id=uuid.UUID(emp_id),
        structure_id=uuid.UUID(structure_id),
        ctc=Decimal("120000.00"),
        effective_from=start,
        effective_to=end,
        created_by=created_by,
    )
    if deleted:
        row.deleted_at = utcnow()
    db.add(row)
    db.flush()
    return row


def _today() -> date:
    return utcnow().date()


@pytest.fixture
def bits(client: TestClient, db: Session, company_a: TenantContext) -> dict[str, Any]:
    """A structure and an employee with no salary yet."""
    return {
        "ctx": company_a,
        "h": company_a.hr_headers,
        "sid": _make(client, company_a.hr_headers)["id"],
        "emp": _staff(client, db, company_a, None),
    }


# ------------------------------------------------------------------- R1


def test_R1_no_login_gets_401_and_employee_and_manager_get_403(
    client: TestClient, bits: dict[str, Any], company_a: TenantContext
) -> None:
    url = f"{E}/{bits['emp']['id']}/assign"
    body = {"structure_id": bits["sid"], "ctc": "600000.00", "effective_from": _day(0)}
    assert client.post(url, json=body).status_code == 401, "R1: no login must be 401"
    for who in (company_a.employee_headers, company_a.manager_headers, bits["emp"]["h"]):
        assert client.post(url, json=body, headers=who).status_code == 403, "R1: 403 for non-HR"


def test_R1_owner_and_hr_admin_can_assign(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    owner_h, _ = _extra_user(db, bits["ctx"].company_id, UserRole.owner)
    other = _staff(client, db, bits["ctx"], None)
    assert _assign(client, bits["h"], bits["emp"]["id"], bits["sid"]).status_code == 201
    assert _assign(client, owner_h, other["id"], bits["sid"]).status_code == 201


def test_R1_another_companys_employee_or_structure_gives_404(
    client: TestClient,
    db: Session,
    bits: dict[str, Any],
    company_b: TenantContext,
) -> None:
    theirs_emp = _staff(client, db, company_b, None)
    theirs_structure = _make(client, company_b.hr_headers)["id"]
    cross_emp = _assign(client, bits["h"], theirs_emp["id"], bits["sid"])
    missing_emp = _assign(client, bits["h"], str(uuid.uuid4()), bits["sid"])
    assert (cross_emp.status_code, _msg(cross_emp)) == (404, "Employee not found.")
    assert (missing_emp.status_code, _msg(missing_emp)) == (404, _msg(cross_emp)), (
        "R1: missing and other-company employee must look the same"
    )
    cross_structure = _assign(client, bits["h"], bits["emp"]["id"], theirs_structure)
    assert (cross_structure.status_code, _msg(cross_structure)) == (
        404,
        "Salary structure not found.",
    ), "R1: another company's structure is 404"
    assert _rows(db, bits["ctx"], bits["emp"]["id"]) == [], "R1: nothing may be saved"
    assert _rows(db, company_b, theirs_emp["id"]) == [], "R1: nothing may reach the other company"


def test_R1_the_employee_must_be_active(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    _set_flags(db, bits["ctx"], bits["emp"]["id"], is_active=False)
    resp = _assign(client, bits["h"], bits["emp"]["id"], bits["sid"])
    assert (resp.status_code, _msg(resp)) == (404, "Employee not found."), (
        "R1: an inactive employee cannot be given a salary"
    )
    assert _rows(db, bits["ctx"], bits["emp"]["id"]) == []


# ------------------------------------------------------------------- R2


@pytest.mark.parametrize(
    "fields",
    [
        {"ctc": "0"},
        {"ctc": "-100.00"},
        {"ctc": "100000000.00"},
        {"ctc": "600000.123"},
        {"ctc": "abc"},
        {"ctc": None},
        {"effective_from": "1999-12-31"},
        {"effective_from": "2101-01-01"},
        {"effective_from": "not-a-date"},
        {"effective_from": None},
        {"structure_id": None},
        {"structure_id": "nope"},
        {"company_id": str(uuid.uuid4())},
        {"revision_reason": ""},
        {"revision_reason": "   "},
        {"revision_reason": "r" * 256},
    ],
)
def test_R2_bad_input_gives_422_and_saves_nothing(
    client: TestClient, db: Session, bits: dict[str, Any], fields: dict[str, Any]
) -> None:
    body: dict[str, Any] = {
        "structure_id": bits["sid"],
        "ctc": "600000.00",
        "effective_from": _day(0),
    }
    body.update(fields)
    resp = _quiet(client).post(f"{E}/{bits['emp']['id']}/assign", json=body, headers=bits["h"])
    assert resp.status_code == 422, f"R2: {fields} must be 422, got {resp.status_code}"
    assert _rows(db, bits["ctx"], bits["emp"]["id"]) == [], "R2: a refused request saves nothing"


def test_R2_the_edges_are_accepted(client: TestClient, db: Session, bits: dict[str, Any]) -> None:
    ctx, h = bits["ctx"], bits["h"]
    top = _staff(client, db, ctx, None)
    assert _assign(client, h, top["id"], bits["sid"], ctc="99999999.99").status_code == 201, (
        "R2: the largest CTC"
    )
    low = _staff(client, db, ctx, None)
    assert _assign(client, h, low["id"], bits["sid"], ctc="1.00").status_code == 201
    early = _staff(client, db, ctx, None)
    assert (
        _assign(client, h, early["id"], bits["sid"], effective_from="2000-01-01").status_code == 201
    )
    late = _staff(client, db, ctx, None)
    assert (
        _assign(client, h, late["id"], bits["sid"], effective_from="2100-12-31").status_code == 201
    )


def test_R2_a_reason_is_required_only_when_the_employee_already_has_a_salary_and_is_trimmed(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    ctx, h, emp = bits["ctx"], bits["h"], bits["emp"]["id"]
    first = _assign(client, h, emp, bits["sid"], effective_from=_day(-100))
    assert first.status_code == 201, "R2: the first assignment needs no reason"
    assert first.json()["revision_reason"] is None
    for reason in ({}, {"revision_reason": None}):
        resp = _assign(client, h, emp, bits["sid"], effective_from=_day(-50), **reason)
        assert resp.status_code == 422, f"R2: a revision without a reason must be 422: {reason}"
        assert "reason" in _msg(resp), f"R2: message must name the reason: {_msg(resp)}"
    assert len(_rows(db, ctx, emp)) == 1, "R2: the refused revision saved nothing"
    ok = _assign(
        client, h, emp, bits["sid"], effective_from=_day(-50), revision_reason="  Promotion  "
    )
    assert ok.status_code == 201 and ok.json()["revision_reason"] == "Promotion", (
        "R2: the reason is trimmed"
    )
    edge = _assign(client, h, emp, bits["sid"], effective_from=_day(-10), revision_reason="r" * 255)
    assert edge.status_code == 201, "R2: a 255-character reason is allowed"


# ------------------------------------------------------------------- R3


def test_R3_a_start_on_or_before_the_open_ended_row_gives_409_naming_the_date(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    h, emp = bits["h"], bits["emp"]["id"]
    start = _day(-30)
    assert _assign(client, h, emp, bits["sid"], effective_from=start).status_code == 201
    for earlier in (start, _day(-31), _day(-200)):
        resp = _assign(client, h, emp, bits["sid"], effective_from=earlier, revision_reason="x")
        assert resp.status_code == 409, f"R3: {earlier} must overlap, got {resp.status_code}"
        assert start in _msg(resp), f"R3: the message must name {start}: {_msg(resp)}"
    assert len(_rows(db, bits["ctx"], emp)) == 1


def test_R3_a_start_inside_a_closed_period_gives_409_naming_the_dates(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    h, emp = bits["h"], bits["emp"]["id"]
    assert _assign(client, h, emp, bits["sid"], effective_from=_day(-100)).status_code == 201
    assert _assign(
        client, h, emp, bits["sid"], effective_from=_day(-40), revision_reason="up"
    ).status_code == 201  # fmt: skip
    resp = _assign(client, h, emp, bits["sid"], effective_from=_day(-70), revision_reason="x")
    assert resp.status_code == 409, f"R3: inside the closed period: {resp.status_code}"
    assert _day(-100) in _msg(resp) and _day(-41) in _msg(resp), f"R3: dates missing: {_msg(resp)}"


def test_R3_a_start_before_a_future_dated_closed_row_gives_409_naming_the_dates(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    ctx, emp = bits["ctx"], bits["emp"]["id"]
    _, user = _extra_user(db, ctx.company_id, UserRole.hr_admin)
    start, end = _today() + timedelta(days=30), _today() + timedelta(days=60)
    _insert_row(db, ctx, emp, bits["sid"], start, end, user.id)
    db.commit()
    resp = _assign(
        client, bits["h"], emp, bits["sid"], effective_from=_day(10), revision_reason="x"
    )
    assert resp.status_code == 409, f"R3: a start before a future closed row: {resp.status_code}"
    assert start.isoformat() in _msg(resp) and end.isoformat() in _msg(resp), (
        f"R3: the message must name the dates: {_msg(resp)}"
    )
    assert len(_rows(db, ctx, emp)) == 1, "R3: nothing may be saved"


def test_R3_a_new_salary_after_the_open_ended_row_closes_it_the_day_before(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    h, emp = bits["h"], bits["emp"]["id"]
    assert _assign(client, h, emp, bits["sid"], effective_from=_day(-100)).status_code == 201
    assert _assign(
        client, h, emp, bits["sid"], ctc="900000.00", effective_from=_day(-20), revision_reason="up"
    ).status_code == 201  # fmt: skip
    old, new = _rows(db, bits["ctx"], emp)
    assert old.effective_to == _today() - timedelta(days=21), (
        "R3: the old row closes the day before"
    )
    assert new.effective_to is None and new.ctc == Decimal("900000.00")


def test_R3_two_simultaneous_assignments_give_one_201_and_one_409_never_a_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.payroll.repository import EmployeeSalaryRepository

    original = EmployeeSalaryRepository.get_overlapping

    def _slow(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        found = original(self, *args, **kwargs)
        time.sleep(0.5)  # both requests looked for overlaps before either saved
        return found

    monkeypatch.setattr(EmployeeSalaryRepository, "get_overlapping", _slow)
    with race_company() as (_cid, headers, _engine):
        setup = TestClient(fastapi_app)
        sid = _make(setup, headers)["id"]
        emp = _create_employee(setup, headers)["id"]
        barrier = threading.Barrier(2)
        results: list[int] = []
        bodies: list[str] = []

        def _worker() -> None:
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                resp = _assign(c, headers, emp, sid, effective_from=_day(-5), revision_reason="r")
                results.append(resp.status_code)
                bodies.append(resp.text)
            except Exception:
                results.append(999)

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert 500 not in results and 999 not in results, f"R3: race gave an error: {results}"
        assert sorted(results) == [201, 409], f"R3: expected one 201 and one 409, got {results}"
        loser = bodies[results.index(409)]
        assert "Existing salary starts on" in loser, f"R3: the loser sees the winner's row: {loser}"
        history = _hist_json(setup, headers, emp)
        assert history["total"] == 1, "R3: exactly one salary row may exist"


def test_R3_the_database_itself_refuses_overlapping_rows(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    ctx, emp, sid = bits["ctx"], bits["emp"]["id"], bits["sid"]
    _, user = _extra_user(db, ctx.company_id, UserRole.hr_admin)
    base = _today()
    _insert_row(db, ctx, emp, sid, base - timedelta(days=100), base - timedelta(days=50), user.id)
    db.commit()
    for start, end in (
        (base - timedelta(days=60), base - timedelta(days=40)),  # overlaps the end
        (base - timedelta(days=100), base - timedelta(days=100)),  # the first day only
        (base - timedelta(days=120), None),  # open-ended, swallows it
    ):
        with pytest.raises(IntegrityError) as caught:
            with db.begin_nested():
                _insert_row(db, ctx, emp, sid, start, end, user.id)
        assert "ex_employee_salaries_no_overlap" in str(caught.value), (
            f"R3: the exclusion constraint must refuse {start}..{end}: {caught.value}"
        )
    # touching is fine, a soft-deleted row is ignored, another employee is unaffected
    _insert_row(db, ctx, emp, sid, base - timedelta(days=49), base - timedelta(days=10), user.id)
    _insert_row(db, ctx, emp, sid, base - timedelta(days=90), None, user.id, deleted=True)
    other = _staff(client, db, ctx, None)
    _insert_row(db, ctx, other["id"], sid, base - timedelta(days=100), None, user.id)
    db.commit()


# ------------------------------------------------------------------- R4


def test_R4_history_is_append_only_and_no_route_edits_or_deletes_a_row(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    h, emp, ctx = bits["h"], bits["emp"]["id"], bits["ctx"]
    assert (
        _assign(client, h, emp, bits["sid"], ctc="500000.00", effective_from=_day(-90)).status_code
        == 201
    )
    before = _rows(db, ctx, emp)[0]
    snapshot = (
        before.id,
        before.ctc,
        before.structure_id,
        before.effective_from,
        before.created_by,
    )
    assert _assign(
        client, h, emp, bits["sid"], ctc="700000.00", effective_from=_day(-30), revision_reason="up"
    ).status_code == 201  # fmt: skip
    rows = _rows(db, ctx, emp)
    assert len(rows) == 2 and rows[0].deleted_at is None, "R4: both rows stay"
    kept = rows[0]
    assert (
        kept.id,
        kept.ctc,
        kept.structure_id,
        kept.effective_from,
        kept.created_by,
    ) == snapshot, "R4: only effective_to of the old row may change"
    assert kept.effective_to == _today() - timedelta(days=31)
    for method in ("put", "patch", "delete"):
        resp = getattr(client, method)(f"{E}/{emp}/assign", headers=h)
        assert resp.status_code == 405, (
            f"R4: {method} on assign must be 405, got {resp.status_code}"
        )
        resp = getattr(client, method)(f"{E}/{emp}/salary", headers=h)
        assert resp.status_code == 405, (
            f"R4: {method} on salary must be 405, got {resp.status_code}"
        )


def _approved_run(client: TestClient, db: Session, w: dict[str, Any]) -> dict:
    for who in ("emp", "manager"):
        _fill(db, w["ctx"], w[who]["id"], w["year"], w["month"])
    run = _make_run(client, w["hr1"], w["year"], w["month"])
    assert client.post(f"{RUNS}/{run['id']}/approve", headers=w["hr2"]).status_code == 200
    return run


def test_R4_a_start_inside_or_before_an_approved_run_month_gives_409_naming_the_month(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    _approved_run(client, db, world)
    year, month, emp = world["year"], world["month"], world["emp"]["id"]
    label = f"{month:02d}/{year}"
    for start in (
        date(year, month, 15),
        date(year, month, 1),
        date(year, month, 1) - timedelta(days=40),
    ):
        resp = _assign(
            client, world["hr1"], emp, world["structure_id"], effective_from=start.isoformat(),
            revision_reason="late",
        )  # fmt: skip
        assert resp.status_code == 409, f"R4: {start} must be refused, got {resp.status_code}"
        assert label in _msg(resp), f"R4: the message must name {label}: {_msg(resp)}"
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    ok = _assign(
        client, world["hr1"], emp, world["structure_id"], effective_from=nxt.isoformat(),
        revision_reason="next month",
    )  # fmt: skip
    assert ok.status_code == 201, f"R4: the month after the run is allowed: {ok.text}"


def test_R4_a_paid_run_blocks_too_but_a_pending_run_does_not(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    for who in ("emp", "manager"):
        _fill(db, world["ctx"], world[who]["id"], world["year"], world["month"])
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    year, month, emp = world["year"], world["month"], world["emp"]["id"]
    inside = date(year, month, 10).isoformat()

    def _set(status: PayrollRunStatus) -> None:
        bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
        row = db.get(PayrollRun, uuid.UUID(run["id"]))
        assert row is not None
        row.status = status
        db.commit()

    _set(PayrollRunStatus.paid)
    paid = _assign(
        client, world["hr1"], emp, world["structure_id"], effective_from=inside, revision_reason="x"
    )
    assert paid.status_code == 409 and f"{month:02d}/{year}" in _msg(paid), "R4: a paid run blocks"
    _set(PayrollRunStatus.pending_approval)
    pending = _assign(
        client, world["hr1"], emp, world["structure_id"], effective_from=inside, revision_reason="x"
    )
    assert pending.status_code == 201, f"R4: a run not yet approved does not block: {pending.text}"


def test_R4_a_run_that_does_not_include_the_employee_does_not_block(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    _approved_run(client, db, world)
    year, month = world["year"], world["month"]
    late = _staff(client, db, world["ctx"], None)
    resp = _assign(
        client, world["hr1"], late["id"], world["structure_id"],
        effective_from=date(year, month, 10).isoformat(),
    )  # fmt: skip
    assert resp.status_code == 201, f"R4: an employee outside the run is not blocked: {resp.text}"


# ------------------------------------------------------------------- R5


def _with_salary(client: TestClient, db: Session, ctx: TenantContext, sid: str) -> dict[str, Any]:
    emp = _staff(client, db, ctx, None)
    resp = _assign(
        client, ctx.hr_headers, emp["id"], sid, ctc="480000.00", effective_from=_day(-30)
    )
    assert resp.status_code == 201, resp.text
    return emp


def test_R5_an_employee_sees_only_their_own_current_salary(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    ctx = bits["ctx"]
    mine = _with_salary(client, db, ctx, bits["sid"])
    theirs = _with_salary(client, db, ctx, bits["sid"])
    own = _salary(client, mine["h"], mine["id"])
    assert own.status_code == 200 and own.json()["ctc"] == "480000.00", (
        f"R5: own salary: {own.text}"
    )
    other = _salary(client, mine["h"], theirs["id"])
    assert other.status_code == 403, (
        f"R5: another employee's salary must be 403, got {other.status_code}"
    )
    assert "480000" not in other.text, "R5: a refused read must not leak the pay"


def test_R5_owner_and_hr_admin_see_anyones_and_a_manager_never_does(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    ctx = bits["ctx"]
    report = _with_salary(client, db, ctx, bits["sid"])
    boss = _staff(client, db, ctx, bits["sid"], UserRole.manager)
    _set_flags(db, ctx, report["id"], reporting_manager_id=uuid.UUID(boss["id"]))
    owner_h, _ = _extra_user(db, ctx.company_id, UserRole.owner)
    assert _salary(client, bits["h"], report["id"]).status_code == 200, "R5: HR sees anyone"
    assert _salary(client, owner_h, report["id"]).status_code == 200, "R5: owner sees anyone"
    direct = _salary(client, boss["h"], report["id"])
    assert direct.status_code == 403, (
        f"R5: a manager must not read a direct report: {direct.status_code}"
    )
    assert _salary(client, boss["h"], boss["id"]).status_code == 200, (
        "R5: a manager reads their own"
    )
    assert _salary(client, ctx.manager_headers, report["id"]).status_code == 403


def test_R5_another_company_and_a_missing_employee_give_the_same_404(
    client: TestClient, db: Session, bits: dict[str, Any], company_b: TenantContext
) -> None:
    theirs = _staff(client, db, company_b, _make(client, company_b.hr_headers)["id"])
    cross = _salary(client, bits["h"], theirs["id"])
    missing = _salary(client, bits["h"], str(uuid.uuid4()))
    assert (cross.status_code, _msg(cross)) == (404, "Employee not found.")
    assert (missing.status_code, _msg(missing)) == (404, _msg(cross)), "R5: same 404"
    emp = _with_salary(client, db, bits["ctx"], bits["sid"])
    as_employee = _salary(client, emp["h"], theirs["id"])
    assert as_employee.status_code == 404, "R5: an employee asking for another company is a 404"


def test_R5_no_salary_gives_one_fixed_404_message_also_for_a_future_only_salary(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    emp = bits["emp"]
    for headers in (bits["h"], emp["h"]):
        resp = _salary(client, headers, emp["id"])
        assert (resp.status_code, _msg(resp)) == (404, NO_SALARY), "R5: no salary message"
    assert (
        _assign(client, bits["h"], emp["id"], bits["sid"], effective_from=_day(30)).status_code
        == 201
    )
    later = _salary(client, emp["h"], emp["id"])
    assert (later.status_code, _msg(later)) == (404, NO_SALARY), (
        "R5: a future salary is not current"
    )


def test_R5_a_deleted_structure_never_causes_a_500(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    ctx = bits["ctx"]
    emp = _with_salary(client, db, ctx, bits["sid"])
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    structure = db.get(SalaryStructure, uuid.UUID(bits["sid"]))
    assert structure is not None
    structure.deleted_at = utcnow()
    db.commit()
    current = _salary(client, bits["h"], emp["id"])
    assert current.status_code == 200, (
        f"R5: current salary with a deleted structure: {current.text}"
    )
    assert current.json()["structure_name"] == structure.name
    history = _hist(client, bits["h"], emp["id"])
    assert (
        history.status_code == 200
        and history.json()["items"][0]["structure_name"] == structure.name
    )


# ------------------------------------------------------------------- R6


def _three_rows(client: TestClient, bits: dict[str, Any]) -> list[str]:
    h, emp = bits["h"], bits["emp"]["id"]
    starts = [_day(-300), _day(-200), _day(-100)]
    first = _assign(client, h, emp, bits["sid"], ctc="100000.00", effective_from=starts[0])
    assert first.status_code == 201, first.text
    for ctc, start in (("200000.00", starts[1]), ("300000.00", starts[2])):
        resp = _assign(
            client, h, emp, bits["sid"], ctc=ctc, effective_from=start, revision_reason=f"to {ctc}"
        )
        assert resp.status_code == 201, resp.text
    return starts


def test_R6_history_is_paged_newest_first_with_every_field(
    client: TestClient, bits: dict[str, Any]
) -> None:
    starts = _three_rows(client, bits)
    emp = bits["emp"]["id"]
    page1 = _hist_json(client, bits["h"], emp, "?limit=2&page=1")
    page2 = _hist_json(client, bits["h"], emp, "?limit=2&page=2")
    assert [i["effective_from"] for i in page1["items"]] == [starts[2], starts[1]], (
        "R6: newest first"
    )
    assert [i["effective_from"] for i in page2["items"]] == [starts[0]]
    assert (page1["total"], page1["pages"], page1["has_next"]) == (3, 2, True)
    row = page1["items"][0]
    assert row["ctc"] == "300000.00" and row["effective_to"] is None
    assert row["revision_reason"] == "to 300000.00" and row["structure_name"]
    assert page1["items"][1]["effective_to"] == (_today() - timedelta(days=101)).isoformat()
    assert {"structure_id", "structure_name", "ctc", "effective_from", "effective_to",
            "revision_reason"} <= set(row), f"R6: fields: {sorted(row)}"  # fmt: skip


def test_R6_filters_are_validated_and_applied(client: TestClient, bits: dict[str, Any]) -> None:
    starts = _three_rows(client, bits)
    emp, h = bits["emp"]["id"], bits["h"]
    after = _hist_json(client, h, emp, f"?from_date={starts[1]}")
    assert [i["effective_from"] for i in after["items"]] == [starts[2], starts[1]], "R6: from_date"
    before = _hist_json(client, h, emp, f"?to_date={starts[1]}")
    assert [i["effective_from"] for i in before["items"]] == [starts[1], starts[0]], "R6: to_date"
    for bad in (
        "?from_date=nope", "?to_date=2024-13-01", f"?from_date={starts[2]}&to_date={starts[0]}",
        "?limit=0", "?limit=101", "?page=0", "?from_date=1999-01-01", "?to_date=2101-01-01",
    ):  # fmt: skip
        assert _hist(client, h, emp, bad).status_code == 422, f"R6: {bad} must be 422"
    assert client.get(f"{E}/not-a-uuid/salary-history", headers=h).status_code == 422, "R6: bad id"


def test_R6_history_has_the_same_visibility_as_the_current_salary(
    client: TestClient, db: Session, bits: dict[str, Any], company_b: TenantContext
) -> None:
    ctx = bits["ctx"]
    mine = _with_salary(client, db, ctx, bits["sid"])
    theirs = _with_salary(client, db, ctx, bits["sid"])
    boss = _staff(client, db, ctx, None, UserRole.manager)
    _set_flags(db, ctx, mine["id"], reporting_manager_id=uuid.UUID(boss["id"]))
    owner_h, _ = _extra_user(db, ctx.company_id, UserRole.owner)
    assert client.get(f"{E}/{mine['id']}/salary-history").status_code == 401, "R6: no login"
    assert _hist(client, mine["h"], mine["id"]).status_code == 200, "R6: own"
    assert _hist(client, bits["h"], mine["id"]).status_code == 200, "R6: HR"
    assert _hist(client, owner_h, mine["id"]).status_code == 200, "R6: owner"
    assert _hist(client, mine["h"], theirs["id"]).status_code == 403, "R6: another employee"
    assert _hist(client, boss["h"], mine["id"]).status_code == 403, (
        "R6: a manager, even for a report"
    )
    other_company = _staff(client, db, company_b, None)
    cross = _hist(client, bits["h"], other_company["id"])
    missing = _hist(client, bits["h"], str(uuid.uuid4()))
    assert (cross.status_code, _msg(cross)) == (404, "Employee not found.")
    assert (missing.status_code, _msg(missing)) == (404, _msg(cross)), "R6: same 404"


def test_R6_an_employee_with_no_salary_has_an_empty_history(
    client: TestClient, bits: dict[str, Any]
) -> None:
    resp = _hist(client, bits["h"], bits["emp"]["id"])
    assert resp.status_code == 200 and resp.json()["items"] == [] and resp.json()["total"] == 0


# ------------------------------------------------------------------- R7


def test_R7_assigning_writes_one_audit_row_without_the_ctc(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    emp, start = bits["emp"]["id"], _day(-10)
    assert (
        _assign(
            client, bits["h"], emp, bits["sid"], ctc="777777.00", effective_from=start
        ).status_code
        == 201
    )
    rows = _audit(db, bits["ctx"], "EMPLOYEE_SALARY_ASSIGNED")
    assert len(rows) == 1, "R7: one audit row per assignment"
    assert rows[0].details == {
        "employee_id": emp, "structure_id": bits["sid"], "effective_from": start,
    }, f"R7: details: {rows[0].details}"  # fmt: skip
    assert "777777" not in str(rows[0].details), "R7: no CTC in the audit"
    refused = _assign(
        client, bits["h"], emp, bits["sid"], effective_from=start, revision_reason="x"
    )
    assert refused.status_code == 409
    assert len(_audit(db, bits["ctx"], "EMPLOYEE_SALARY_ASSIGNED")) == 1, "R7: refused = no row"


def test_R7_hr_and_owner_reading_someone_elses_salary_or_history_write_one_audit_row_each(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    ctx = bits["ctx"]
    emp = _with_salary(client, db, ctx, bits["sid"])
    owner_h, _ = _extra_user(db, ctx.company_id, UserRole.owner)
    assert _salary(client, bits["h"], emp["id"]).status_code == 200
    rows = _audit(db, ctx, "SALARY_VIEWED_BY_HR")
    assert len(rows) == 1, "R7: one audit row for an HR read"
    assert rows[0].entity_id == uuid.UUID(emp["id"]) and rows[0].details == {
        "employee_id": emp["id"]
    }
    assert _hist(client, bits["h"], emp["id"]).status_code == 200
    assert len(_audit(db, ctx, "SALARY_VIEWED_BY_HR")) == 2, "R7: one more for the history read"
    assert _salary(client, owner_h, emp["id"]).status_code == 200
    assert len(_audit(db, ctx, "SALARY_VIEWED_BY_HR")) == 3, "R7: the owner is audited too"


def test_R7_reading_your_own_or_a_refused_read_writes_no_audit_row(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    ctx = bits["ctx"]
    mine = _with_salary(client, db, ctx, bits["sid"])
    theirs = _with_salary(client, db, ctx, bits["sid"])
    assert _salary(client, mine["h"], mine["id"]).status_code == 200
    assert _hist(client, mine["h"], mine["id"]).status_code == 200
    assert _salary(client, mine["h"], theirs["id"]).status_code == 403
    assert _hist(client, mine["h"], theirs["id"]).status_code == 403
    assert _salary(client, bits["h"], str(uuid.uuid4())).status_code == 404
    assert _audit(db, ctx, "SALARY_VIEWED_BY_HR") == [], "R7: own and refused reads leave no row"


# ------------------------------------------------------------------- R8


def test_R8_assign_is_limited_to_30_per_minute(
    client: TestClient, bits: dict[str, Any], limits_on
) -> None:
    body = {"structure_id": str(uuid.uuid4()), "ctc": "600000.00", "effective_from": _day(0)}
    url = f"{E}/{uuid.uuid4()}/assign"
    codes = [client.post(url, json=body, headers=bits["h"]).status_code for _ in range(31)]
    assert codes[:30] == [404] * 30 and codes[30] == 429, f"R8: assign limit wrong: {codes[-3:]}"


def test_R8_the_salary_and_history_reads_are_limited_to_60_per_minute(
    client: TestClient, bits: dict[str, Any], limits_on
) -> None:
    missing = uuid.uuid4()
    one = [client.get(f"{E}/{missing}/salary", headers=bits["h"]).status_code for _ in range(61)]
    assert one[:60] == [404] * 60 and one[60] == 429, f"R8: salary limit wrong: {one[-3:]}"
    limiter.reset()
    many = [
        client.get(f"{E}/{missing}/salary-history", headers=bits["h"]).status_code
        for _ in range(61)
    ]
    assert many[:60] == [404] * 60 and many[60] == 429, f"R8: history limit wrong: {many[-3:]}"


# ------------------------------------------------------------------- R9


def test_R9_a_failure_between_closing_and_creating_leaves_the_old_row_open_and_no_new_row(
    client: TestClient, db: Session, bits: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.payroll.repository import EmployeeSalaryRepository

    h, emp, ctx = bits["h"], bits["emp"]["id"], bits["ctx"]
    assert _assign(client, h, emp, bits["sid"], effective_from=_day(-100)).status_code == 201

    def _boom(self, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("insert failed after the old row was closed")

    monkeypatch.setattr(EmployeeSalaryRepository, "create", _boom)
    with pytest.raises(RuntimeError):
        _assign(client, h, emp, bits["sid"], effective_from=_day(-10), revision_reason="x")
    rows = _rows(db, ctx, emp)
    assert len(rows) == 1 and rows[0].effective_to is None, (
        "R9: the old row must stay open and no new row may exist"
    )


def test_R9_exactly_one_row_is_in_force_on_any_date(
    client: TestClient, db: Session, bits: dict[str, Any]
) -> None:
    from app.modules.payroll.repository import EmployeeSalaryRepository

    h, emp, ctx = bits["h"], bits["emp"]["id"], bits["ctx"]
    assert _assign(client, h, emp, bits["sid"], effective_from=_day(-100)).status_code == 201
    assert (
        _assign(
            client,
            h,
            emp,
            bits["sid"],
            ctc="700000.00",
            effective_from=_day(-40),
            revision_reason="a",
        ).status_code
        == 201
    )
    assert (
        _assign(
            client,
            h,
            emp,
            bits["sid"],
            ctc="800000.00",
            effective_from=_day(20),
            revision_reason="b",
        ).status_code
        == 201
    )
    repo = EmployeeSalaryRepository(db)
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    rows = _rows(db, ctx, emp)
    for offset, expected in (
        (-101, None),
        (-100, 0),
        (-41, 0),
        (-40, 1),
        (19, 1),
        (20, 2),
        (400, 2),
    ):
        day = _today() + timedelta(days=offset)
        found = repo.get_in_force(uuid.UUID(emp), ctx.company_id, day)
        covering = [
            r for r in rows
            if r.effective_from <= day and (r.effective_to is None or r.effective_to >= day)
        ]  # fmt: skip
        if expected is None:
            assert found is None and covering == [], f"R9: nothing is in force on {day}"
        else:
            assert len(covering) == 1 and found is not None and found.id == rows[expected].id, (
                f"R9: exactly one row must be in force on {day}"
            )
    assert _salary(client, h, emp).json()["ctc"] == "700000.00", "R9: the route agrees for today"


def test_R9_the_salary_route_and_payroll_use_the_same_lookup(
    client: TestClient, db: Session, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.payroll.repository import EmployeeSalaryRepository

    calls: list[str] = []
    real = EmployeeSalaryRepository.get_in_force

    def _spy(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append("lookup")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(EmployeeSalaryRepository, "get_in_force", _spy)
    assert _salary(client, world["hr1"], world["emp"]["id"]).status_code == 200
    assert calls == ["lookup"], "R9: the salary route must use get_in_force"
    calls.clear()
    for who in ("emp", "manager"):
        _fill(db, world["ctx"], world[who]["id"], world["year"], world["month"])
    _make_run(client, world["hr1"], world["year"], world["month"])
    assert len(calls) >= 2, "R9: payroll must use get_in_force for each employee"


# ------------------------------------------------------------------ R10


def test_R10_every_rule_from_1_to_9_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_R")]
    for rule in range(1, 10):
        assert any(n.startswith(f"test_R{rule}_") for n in names), f"R10: no test for rule {rule}"


def test_R10_the_models_and_the_migrations_agree_on_the_salary_tables() -> None:
    """What `alembic check` does in CI, for the two tables this package changed."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from app.core.config import settings
    from app.db.base import Base

    engine = create_engine(settings.TEST_MIGRATION_URL)
    try:
        with engine.connect() as conn:
            diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()
    mine = [d for d in diffs if "salary_structures" in str(d) or "employee_salaries" in str(d)]
    assert mine == [], f"R10: models and migrations differ: {mine}"
