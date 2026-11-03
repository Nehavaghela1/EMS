# ruff: noqa: F811
"""Module 5, sub-feature 5.5: Payslips. One test per rule line (R1..R10).

Runs are made for completed months only (see 5.4). The employees in `world` are not
attendance-exempt unless a test sets the flag, so tests that need clean numbers fill the month.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.db.rls import bind_tenant_to_session
from app.modules.payroll.models import (
    EmployeeSalary,
    PayrollRun,
    PayrollRunStatus,
    SalaryComponent,
    StatutoryConfig,
)
from app.modules.payroll.schemas import PayrollItemResponse
from app.modules.platform.models import AuditLog
from tests.conftest import TenantContext
from tests.rules.test_5_4_payroll_runs import (  # noqa: F401
    PAYSLIPS,
    RUNS,
    _claim,
    _fill,
    _filled_world,
    _make_run,
    _month_back,
    _month_with_days,
    _seed_statutory,
    _set_flags,
    _staff,
    limits_on,
    world,
)


def _released(client: TestClient, w: dict[str, Any], year: int, month: int) -> dict:
    """Make a run for the month and approve it with the second HR admin."""
    run = _make_run(client, w["hr1"], year, month)
    resp = client.post(f"{RUNS}/{run['id']}/approve", headers=w["hr2"])
    assert resp.status_code == 200, resp.text
    return run


def _set_status(db: Session, w: dict[str, Any], run_id: str, status: PayrollRunStatus) -> None:
    bind_tenant_to_session(db, company_id=w["ctx"].company_id, is_platform_admin=False)
    row = db.get(PayrollRun, uuid.UUID(run_id))
    assert row is not None
    row.status = status
    db.commit()


def _me(client: TestClient, headers: dict[str, str], query: str = "") -> dict:
    resp = client.get(f"{PAYSLIPS}/me{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, dict) and "items" in body, f"payslips must come as a page: {body}"
    return body


def _of(client: TestClient, headers: dict[str, str], emp_id: str, query: str = ""):
    return client.get(f"{PAYSLIPS}/{emp_id}{query}", headers=headers)


def _audit(db: Session, w: dict[str, Any], action: str) -> list[AuditLog]:
    bind_tenant_to_session(db, company_id=w["ctx"].company_id, is_platform_admin=False)
    return (
        db.query(AuditLog)
        .filter(AuditLog.company_id == w["ctx"].company_id, AuditLog.action == action)
        .all()
    )


# ------------------------------------------------------------------- R1


def test_R1_no_login_gets_401(client: TestClient) -> None:
    codes = [
        client.get(f"{PAYSLIPS}/me").status_code,
        client.get(f"{PAYSLIPS}/{uuid.uuid4()}").status_code,
    ]
    assert codes == [401, 401], f"R1: no login must give 401, got {codes}"


def test_R1_an_employee_sees_only_their_own_payslips(client, db, world) -> None:
    _filled_world(db, world)
    _released(client, world, world["year"], world["month"])
    mine = _me(client, world["emp"]["h"])
    assert [i["employee_id"] for i in mine["items"]] == [world["emp"]["id"]], (
        f"R1: an employee sees exactly their own payslip: {mine}"
    )
    theirs = _me(client, world["manager"]["h"])
    assert [i["employee_id"] for i in theirs["items"]] == [world["manager"]["id"]], (
        "R1: a manager sees only their own payslip through /me"
    )


def test_R1_hr_admin_and_owner_see_anyones_payslips_in_their_company(client, db, world) -> None:
    _filled_world(db, world)
    _released(client, world, world["year"], world["month"])
    for who in ("hr1", "hr2", "owner"):
        for target in ("emp", "manager"):
            resp = _of(client, world[who], world[target]["id"])
            assert resp.status_code == 200, f"R1: {who} must read {target}: {resp.text}"
            ids = {i["employee_id"] for i in resp.json()["items"]}
            assert ids == {world[target]["id"]}, f"R1: only {target}'s items: {ids}"


def test_R1_manager_and_other_employees_get_403_on_someone_elses_payslips(
    client, db, world
) -> None:
    _filled_world(db, world)
    _released(client, world, world["year"], world["month"])
    other = _staff(client, db, world["ctx"], world["structure_id"])
    for who, target in (
        ("manager", "emp"),
        ("emp", "manager"),
        ("emp", "emp"),
        ("manager", "manager"),
    ):
        resp = _of(client, world[who]["h"], world[target]["id"])
        assert resp.status_code == 403, f"R1: {who} reading {target} must give 403: {resp.text}"
    assert _of(client, other["h"], world["emp"]["id"]).status_code == 403


def test_R1_another_company_and_a_missing_employee_give_the_same_404(
    client, db, world, company_b: TenantContext
) -> None:
    _filled_world(db, world)
    _released(client, world, world["year"], world["month"])
    foreign = _of(client, company_b.hr_headers, world["emp"]["id"])
    missing = _of(client, world["hr1"], str(uuid.uuid4()))
    assert foreign.status_code == 404, f"R1: another company must give 404: {foreign.text}"
    assert missing.status_code == 404, f"R1: a missing employee must give 404: {missing.text}"
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]


# ------------------------------------------------------------------- R2


def test_R2_a_payslip_shows_for_the_employee_only_after_the_run_is_approved(
    client, db, world
) -> None:
    _filled_world(db, world)
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    assert _me(client, world["emp"]["h"])["items"] == [], "R2: a pending-approval run is hidden"
    assert _me(client, world["emp"]["h"])["total"] == 0
    hr_view = _of(client, world["hr1"], world["emp"]["id"]).json()
    assert len(hr_view["items"]) == 1, "R2: HR still sees the pending payslip"
    client.post(f"{RUNS}/{run['id']}/approve", headers=world["hr2"])
    assert len(_me(client, world["emp"]["h"])["items"]) == 1, "R2: visible once approved"


@pytest.mark.parametrize(
    "state",
    [PayrollRunStatus.draft, PayrollRunStatus.processing, PayrollRunStatus.failed],
)
def test_R2_draft_processing_and_failed_runs_are_hidden_from_the_employee(
    client, db, world, state
) -> None:
    _filled_world(db, world)
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    _set_status(db, world, run["id"], state)
    assert _me(client, world["emp"]["h"])["items"] == [], f"R2: a {state.value} run is hidden"
    assert len(_of(client, world["hr1"], world["emp"]["id"]).json()["items"]) == 1


def test_R2_a_paid_run_is_visible_to_the_employee(client, db, world) -> None:
    _filled_world(db, world)
    run = _released(client, world, world["year"], world["month"])
    _set_status(db, world, run["id"], PayrollRunStatus.paid)
    assert len(_me(client, world["emp"]["h"])["items"]) == 1, "R2: a paid run is visible"


# ------------------------------------------------------------------- R3

CASES = [
    # (annual CTC, day of the month the employee joined, reimbursement)
    ("600000.12", 16, "123.45"),
    ("333333.33", 8, None),
    ("100001.00", 1, "0.01"),
    ("987654.32", 21, "2500.00"),
    ("456789.01", 11, "999.99"),
]


@pytest.mark.parametrize(("ctc", "join_day", "reimbursement"), CASES)
def test_R3_the_breakdown_adds_up_to_the_paisa(
    client, db, world, ctc: str, join_day: int, reimbursement: str | None
) -> None:
    ctx = world["ctx"]
    y, m = _month_with_days(30)
    person = _staff(
        client, db, ctx, world["structure_id"], ctc=ctc, hire=date(y, m, join_day).isoformat()
    )
    _fill(db, ctx, person["id"], y, m)
    for who in ("emp", "manager"):
        _fill(db, ctx, world[who]["id"], y, m)
    if reimbursement:
        _claim(client, {"emp": person, "hr1": world["hr1"]}, reimbursement)
    _released(client, world, y, m)
    item = _me(client, person["h"])["items"][0]
    earnings = sum(Decimal(e["amount"]) for e in item["earnings_json"])
    deductions = sum(Decimal(d["amount"]) for d in item["deductions_json"])
    gross, net = Decimal(item["gross_salary"]), Decimal(item["net_salary"])
    reimb = Decimal(item["reimbursement_amount"])
    assert earnings == gross, f"R3: earnings {earnings} must total gross {gross} for ctc {ctc}"
    assert Decimal(item["total_deductions"]) == deductions, "R3: deduction lines add up"
    assert gross - deductions + reimb == net, f"R3: net must be gross - deductions + reimb: {item}"
    assert reimb == Decimal(reimbursement or "0"), "R3: the reimbursement is in the payslip"
    for amount in [gross, net, reimb, *(Decimal(e["amount"]) for e in item["earnings_json"])]:
        assert amount == amount.quantize(Decimal("0.01")), f"R3: {amount} must have two decimals"
    assert any(e["code"] == "SPECIAL" for e in item["earnings_json"]), "R3: balance line present"
    assert Decimal(item["lop_days"]) == Decimal(join_day - 1), "R3: the case includes a LOP part"


# ------------------------------------------------------------------- R4


def test_R4_an_issued_payslip_does_not_change_when_structure_salary_or_rates_change(
    client, db, world
) -> None:
    _filled_world(db, world)
    ctx = world["ctx"]
    _released(client, world, world["year"], world["month"])
    before = _me(client, world["emp"]["h"])["items"][0]
    before_hr = _of(client, world["hr1"], world["emp"]["id"]).json()["items"][0]

    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    for salary in db.query(EmployeeSalary).filter(EmployeeSalary.company_id == ctx.company_id):
        salary.ctc = Decimal("1800000.00")
    for comp in db.query(SalaryComponent).filter(SalaryComponent.company_id == ctx.company_id):
        if comp.value is not None:
            comp.value = Decimal("10.00")
    for cfg in db.query(StatutoryConfig).filter(StatutoryConfig.company_id == ctx.company_id):
        cfg.pf_employee_rate = Decimal("20.00")
        cfg.pf_enabled = False
    db.commit()
    client.put(
        "/api/v1/payroll/statutory-config",
        json={"pf_employee_rate": "15.00"},
        headers=world["hr1"],
    )
    after = _me(client, world["emp"]["h"])["items"][0]
    after_hr = _of(client, world["hr1"], world["emp"]["id"]).json()["items"][0]
    assert after == before, "R4: an issued payslip must return the same numbers after changes"
    assert after_hr == before_hr
    assert Decimal(after["gross_salary"]) == Decimal(before["gross_salary"])


# ------------------------------------------------------------------- R5


def test_R5_a_payslip_has_exactly_the_documented_fields_and_nobody_elses_data(
    client, db, world
) -> None:
    _filled_world(db, world)
    _released(client, world, world["year"], world["month"])
    item = _me(client, world["emp"]["h"])["items"][0]
    assert set(item) == set(PayrollItemResponse.model_fields), (
        f"R5: unexpected fields: {set(item) ^ set(PayrollItemResponse.model_fields)}"
    )
    text = client.get(f"{PAYSLIPS}/me", headers=world["emp"]["h"]).text.lower()
    assert world["manager"]["id"] not in text, "R5: another employee's id must not appear"
    for word in ("account_number", "bank", "ifsc", "pan", "aadhaar", "password", "token"):
        assert word not in text, f"R5: {word!r} must never be in a payslip response"
    hr_text = _of(client, world["hr1"], world["emp"]["id"]).text
    assert world["manager"]["id"] not in hr_text, "R5: HR's view of one person has only theirs"


# ------------------------------------------------------------------- R6


def test_R6_invalid_ids_and_filters_give_422(client, db, world) -> None:
    hr = world["hr1"]
    assert client.get(f"{PAYSLIPS}/not-a-uuid", headers=hr).status_code == 422, "R6: bad id"
    emp = world["emp"]["id"]
    for query in (
        "?page=0",
        "?page=-1",
        "?limit=0",
        "?limit=abc",
        "?year=1999",
        "?month=13",
        "?month=0",
    ):
        mine = client.get(f"{PAYSLIPS}/me{query}", headers=world["emp"]["h"])
        theirs = _of(client, hr, emp, query)
        assert mine.status_code == 422, f"R6: /me{query} must give 422, got {mine.status_code}"
        assert theirs.status_code == 422, f"R6: /{{id}}{query} must give 422: {theirs.status_code}"


def test_R6_the_list_is_newest_first_paged_and_can_be_filtered(client, db, world) -> None:
    ctx = world["ctx"]
    _set_flags(db, ctx, world["emp"]["id"], is_attendance_exempt=True)
    _set_flags(db, ctx, world["manager"]["id"], is_attendance_exempt=True)
    months = [_month_back(3), _month_back(1), _month_back(2)]  # created out of order on purpose
    ids = {}
    for y, m in months:
        ids[(y, m)] = _released(client, world, y, m)["id"]
    newest_first = [ids[_month_back(1)], ids[_month_back(2)], ids[_month_back(3)]]

    page1 = _me(client, world["emp"]["h"], "?page=1&limit=2")
    assert [i["payroll_run_id"] for i in page1["items"]] == newest_first[:2], (
        f"R6: newest month first: {[i['payroll_run_id'] for i in page1['items']]}"
    )
    assert page1["total"] == 3 and page1["pages"] == 2 and page1["has_next"] is True
    page2 = _me(client, world["emp"]["h"], "?page=2&limit=2")
    assert [i["payroll_run_id"] for i in page2["items"]] == newest_first[2:], "R6: second page"
    assert page2["has_next"] is False
    hr_page = _of(client, world["hr1"], world["emp"]["id"], "?limit=1").json()
    assert hr_page["items"][0]["payroll_run_id"] == newest_first[0] and hr_page["total"] == 3

    y, m = _month_back(2)
    only = _me(client, world["emp"]["h"], f"?year={y}&month={m}")
    assert [i["payroll_run_id"] for i in only["items"]] == [newest_first[1]], "R6: month filter"


# ------------------------------------------------------------------- R7


def test_R7_an_employee_without_a_profile_gets_an_empty_page(
    client, company_a: TenantContext
) -> None:
    resp = client.get(f"{PAYSLIPS}/me", headers=company_a.employee_headers)
    assert resp.status_code == 200, f"R7: no profile must not be an error: {resp.text}"
    body = resp.json()
    assert isinstance(body, dict), f"R7: the answer is a page, got {body}"
    assert body["items"] == [] and body["total"] == 0 and body["has_next"] is False


# ------------------------------------------------------------------- R8


def test_R8_hr_reading_someone_elses_payslips_writes_exactly_one_audit_row(
    client, db, world
) -> None:
    _filled_world(db, world)
    _released(client, world, world["year"], world["month"])
    assert _of(client, world["hr1"], world["emp"]["id"]).status_code == 200
    rows = _audit(db, world, "PAYSLIP_VIEWED_BY_HR")
    assert len(rows) == 1, f"R8: one read, one audit row, got {len(rows)}"
    row = rows[0]
    assert row.entity_id == uuid.UUID(world["emp"]["id"]), "R8: the row names the employee"
    assert set(row.details or {}) == {"employee_id", "run_count"}, f"R8: details: {row.details}"
    assert row.details["employee_id"] == world["emp"]["id"] and row.details["run_count"] == 1
    item = _me(client, world["emp"]["h"])["items"][0]
    blob = str(row.details)
    for amount in (item["gross_salary"], item["net_salary"], item["total_deductions"]):
        assert amount not in blob, "R8: no amount may be in the audit row"
    assert _of(client, world["owner"], world["emp"]["id"]).status_code == 200
    assert len(_audit(db, world, "PAYSLIP_VIEWED_BY_HR")) == 2, "R8: the owner's read is logged too"


def test_R8_an_employee_reading_their_own_or_a_refused_read_writes_no_audit_row(
    client, db, world
) -> None:
    _filled_world(db, world)
    _released(client, world, world["year"], world["month"])
    _me(client, world["emp"]["h"])
    _me(client, world["manager"]["h"])
    assert _of(client, world["manager"]["h"], world["emp"]["id"]).status_code == 403
    assert _of(client, world["hr1"], str(uuid.uuid4())).status_code == 404
    assert _audit(db, world, "PAYSLIP_VIEWED_BY_HR") == [], "R8: only HR reads of others are logged"


# ------------------------------------------------------------------- R9


def test_R9_both_payslip_routes_are_limited_to_60_per_minute(client, db, world, limits_on) -> None:
    mine = [client.get(f"{PAYSLIPS}/me", headers=world["emp"]["h"]).status_code for _ in range(61)]
    assert mine[:60] == [200] * 60 and mine[60] == 429, "R9: /me limit wrong"
    limiter.reset()
    emp = world["emp"]["id"]
    theirs = [_of(client, world["hr1"], emp).status_code for _ in range(61)]
    assert theirs[:60] == [200] * 60 and theirs[60] == 429, "R9: /{employee_id} limit wrong"


# ------------------------------------------------------------------- R10


def test_R10_every_rule_from_1_to_9_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_R")]
    for rule in range(1, 10):
        assert any(n.startswith(f"test_R{rule}_") for n in names), f"R10: no test for rule {rule}"
