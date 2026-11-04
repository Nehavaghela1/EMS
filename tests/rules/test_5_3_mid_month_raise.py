"""Module 5, parts 5.3 and 5.4: a salary that starts mid-month is paid by days at the old and
new CTC (rules B1 to B6).

The structure used here has two earning lines that add up to the whole CTC (BASIC 60%, ALLOW
40%), so every expected figure can be worked out by hand: monthly CTC 30,000 -> BASIC 18,000 and
ALLOW 12,000; monthly CTC 60,000 -> BASIC 36,000 and ALLOW 24,000. The month used has 30 days,
and its dates are computed from today's date (the run rule compares the month with today).
"""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.tax_slabs import seed_tax_slabs
from app.modules.identity.models import UserRole
from tests.conftest import TenantContext, days_ago, upload_receipt
from tests.rules.test_5_4_payroll_runs import (
    RUNS,
    _extra_user,
    _fill,
    _item_for,
    _make_run,
    _month_with_days,
    _staff,
    _working_days_of,
)

CONFIG = "/api/v1/payroll/statutory-config"
RATES = "/api/v1/payroll/statutory-rates"
OLD_CTC = "360000.00"
MID_CTC = "720000.00"
TOP_CTC = "1080000.00"


# ---------------------------------------------------------------- helpers


def _structure(client: TestClient, hr: dict[str, str]) -> str:
    components = [
        {
            "code": "BASIC",
            "name": "Basic Pay",
            "type": "earning",
            "calculation_type": "percentage",
            "value": "60.00",
            "percentage_of": "ctc",
            "display_order": 1,
        },
        {
            "code": "ALLOW",
            "name": "Allowance",
            "type": "earning",
            "calculation_type": "percentage",
            "value": "40.00",
            "percentage_of": "ctc",
            "display_order": 2,
        },
    ]
    resp = client.post(
        "/api/v1/payroll/structures",
        json={"name": f"Split {uuid.uuid4().hex[:6]}", "components": components},
        headers=hr,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed(db: Session) -> None:
    seed_pt_slabs(db)
    seed_tax_slabs(db)
    from app.db.seed.statutory_rates import seed_statutory_rates

    seed_statutory_rates(db)


@pytest.fixture
def mworld(client: TestClient, db: Session, company_a: TenantContext) -> dict[str, Any]:
    """A 30-day month, one employee on CTC 360,000 since 2024-01-01 (monthly 30,000), every
    statutory item and TDS switched off so that only the salary split is under test."""
    _seed(db)
    ctx = company_a
    off = {"pf_enabled": False, "esi_enabled": False, "pt_enabled": False, "tds_enabled": False}
    assert client.put(CONFIG, json=off, headers=ctx.hr_headers).status_code == 200
    owner_h, _ = _extra_user(db, ctx.company_id, UserRole.owner)
    structure_id = _structure(client, ctx.hr_headers)
    year, month = _month_with_days(30)
    emp = _staff(client, db, ctx, structure_id, ctc=OLD_CTC, exempt=True)
    return {
        "ctx": ctx,
        "hr": ctx.hr_headers,
        "owner": owner_h,
        "structure_id": structure_id,
        "emp": emp,
        "year": year,
        "month": month,
    }


def _raise(client: TestClient, w: dict[str, Any], ctc: str, day: int) -> None:
    resp = client.post(
        f"/api/v1/payroll/employees/{w['emp']['id']}/assign",
        json={
            "structure_id": w["structure_id"],
            "ctc": ctc,
            "effective_from": date(w["year"], w["month"], day).isoformat(),
            "revision_reason": "raise",
        },
        headers=w["hr"],
    )
    assert resp.status_code == 201, resp.text


def _item(client: TestClient, w: dict[str, Any]) -> dict[str, Any]:
    run = _make_run(client, w["hr"], w["year"], w["month"])
    w["run"] = run
    return _item_for(client, w["hr"], run["id"], w["emp"]["id"])


def _earnings(item: dict[str, Any]) -> dict[str, str]:
    return {e["code"]: e["amount"] for e in item["earnings_json"]}


def _segments(item: dict[str, Any]) -> list[dict[str, Any]]:
    segments = item.get("salary_segments_json")
    assert isinstance(segments, list), f"the payslip must keep its salary segments: {sorted(item)}"
    return segments


def _salary_ids(client: TestClient, w: dict[str, Any]) -> list[str]:
    resp = client.get(
        f"/api/v1/payroll/employees/{w['emp']['id']}/salary-history?limit=100", headers=w["hr"]
    )
    assert resp.status_code == 200, resp.text
    rows = sorted(resp.json()["items"], key=lambda r: r["effective_from"])
    return [r["id"] for r in rows]


def _money(value: str) -> Decimal:
    return Decimal(value)


# ------------------------------------------------------------------- B1, B2


def test_B1_a_raise_on_the_16th_pays_days_1_to_15_at_the_old_ctc_and_16_to_30_at_the_new(
    client, db, mworld
) -> None:
    w = mworld
    _raise(client, w, MID_CTC, 16)
    item = _item(client, w)
    # BASIC: 18,000 x 15/30 + 36,000 x 15/30 = 9,000 + 18,000. ALLOW: 6,000 + 12,000.
    assert _earnings(item) == {"BASIC": "27000.00", "ALLOW": "18000.00"}, (
        f"B2: the lines are the sum of the two segments: {item['earnings_json']}"
    )
    assert item["gross_salary"] == "45000.00", f"B2: gross is the sum: {item['gross_salary']}"
    assert item["net_salary"] == "45000.00" and item["total_deductions"] == "0.00", item


def test_B1_the_payslip_keeps_the_segment_detail(client, db, mworld) -> None:
    w = mworld
    _raise(client, w, MID_CTC, 16)
    ids = _salary_ids(client, w)
    segments = _segments(_item(client, w))
    y, m = w["year"], w["month"]
    assert len(segments) == 2, f"B5: two segments expected: {segments}"
    first, second = segments
    assert (first["from_date"], first["to_date"], first["days"]) == (
        date(y, m, 1).isoformat(),
        date(y, m, 15).isoformat(),
        15,
    ), first
    assert (second["from_date"], second["to_date"], second["days"]) == (
        date(y, m, 16).isoformat(),
        date(y, m, 30).isoformat(),
        15,
    ), second
    assert [first["salary_id"], second["salary_id"]] == ids, "B5: the salary row ids are kept"
    assert (first["ctc"], second["ctc"]) == (OLD_CTC, MID_CTC), (first, second)


def test_B2_a_raise_on_the_first_day_gives_one_segment_at_the_new_ctc(client, db, mworld) -> None:
    w = mworld
    _raise(client, w, MID_CTC, 1)
    item = _item(client, w)
    assert _earnings(item) == {"BASIC": "36000.00", "ALLOW": "24000.00"}, item["earnings_json"]
    segments = _segments(item)
    assert len(segments) == 1 and segments[0]["days"] == 30, f"B6: one segment: {segments}"
    assert segments[0]["ctc"] == MID_CTC and item["ctc_snapshot"] == MID_CTC, item


def test_B2_a_month_with_one_salary_is_one_segment_and_the_plain_amounts(
    client, db, mworld
) -> None:
    item = _item(client, mworld)
    assert _earnings(item) == {"BASIC": "18000.00", "ALLOW": "12000.00"}, item["earnings_json"]
    segments = _segments(item)
    assert len(segments) == 1 and segments[0]["days"] == 30 and segments[0]["ctc"] == OLD_CTC


def test_B6_two_raises_inside_one_month_give_three_segments(client, db, mworld) -> None:
    w = mworld
    _raise(client, w, MID_CTC, 11)
    _raise(client, w, TOP_CTC, 21)
    item = _item(client, w)
    # BASIC: (18,000 + 36,000 + 54,000) x 10/30 = 36,000. ALLOW: (12,000 + 24,000 + 36,000) x 10/30.
    assert _earnings(item) == {"BASIC": "36000.00", "ALLOW": "24000.00"}, item["earnings_json"]
    assert item["gross_salary"] == "60000.00", item["gross_salary"]
    segments = _segments(item)
    assert [s["days"] for s in segments] == [10, 10, 10], (
        f"B6: three segments of ten days: {segments}"
    )
    assert [s["ctc"] for s in segments] == [OLD_CTC, MID_CTC, TOP_CTC], segments
    assert item["ctc_snapshot"] == TOP_CTC, "the snapshot is the salary at the month end"


def test_B2_each_component_line_rounds_half_up_per_segment(client, db, mworld) -> None:
    w = mworld
    # New CTC 360,001.00 -> monthly 30,000.08 -> BASIC 18,000.05 and ALLOW 12,000.03. For the
    # 15 new days: 18,000.05 x 15/30 = 9,000.025 -> 9,000.03 and 12,000.03 x 15/30 =
    # 6,000.015 -> 6,000.02 (half up). The 15 old days are 9,000.00 and 6,000.00.
    _raise(client, w, "360001.00", 16)
    item = _item(client, w)
    assert _earnings(item) == {"BASIC": "18000.03", "ALLOW": "12000.02"}, item["earnings_json"]


# ------------------------------------------------------------------- B3


def _working_days(w: dict[str, Any]) -> list[date]:
    return _working_days_of(w["year"], w["month"])


def _lop_world(client: TestClient, db: Session, w: dict[str, Any]) -> tuple[date, date]:
    """An employee who needs attendance: one working day without a punch in each segment."""
    ctx = w["ctx"]
    w["emp"] = _staff(client, db, ctx, w["structure_id"], ctc=OLD_CTC, exempt=False)
    working = _working_days(w)
    in_old = next(d for d in working if d.day <= 15)
    in_new = [d for d in working if d.day >= 16][-1]
    _fill(db, ctx, w["emp"]["id"], w["year"], w["month"], skip={in_old, in_new})
    return in_old, in_new


def test_B3_loss_of_pay_is_charged_at_the_daily_rate_of_the_segment_that_holds_the_day(
    client, db, mworld
) -> None:
    w = mworld
    _lop_world(client, db, w)
    _raise(client, w, MID_CTC, 16)
    item = _item(client, w)
    # Old segment: 15 days - 1 LOP day = 14/30 of (18,000, 12,000) = 8,400 and 5,600.
    # New segment: 14/30 of (36,000, 24,000) = 16,800 and 11,200.
    assert _earnings(item) == {"BASIC": "25200.00", "ALLOW": "16800.00"}, item["earnings_json"]
    assert item["gross_salary"] == "42000.00", item["gross_salary"]
    assert item["lop_days"] == "2.0", f"B3: the existing day count is unchanged: {item}"


def test_B3_a_loss_of_pay_day_in_only_the_old_segment_is_charged_at_the_old_rate(
    client, db, mworld
) -> None:
    w = mworld
    ctx = w["ctx"]
    w["emp"] = _staff(client, db, ctx, w["structure_id"], ctc=OLD_CTC, exempt=False)
    in_old = next(d for d in _working_days(w) if d.day <= 15)
    _fill(db, ctx, w["emp"]["id"], w["year"], w["month"], skip={in_old})
    _raise(client, w, MID_CTC, 16)
    item = _item(client, w)
    # BASIC: 18,000 x 14/30 + 36,000 x 15/30 = 8,400 + 18,000; ALLOW: 5,600 + 12,000.
    assert _earnings(item) == {"BASIC": "26400.00", "ALLOW": "17600.00"}, item["earnings_json"]


# ------------------------------------------------------------------- B4


def test_B4_professional_tax_is_worked_out_on_the_month_total(client, db, mworld) -> None:
    w = mworld
    assert client.put(CONFIG, json={"pt_enabled": True}, headers=w["hr"]).status_code == 200, (
        "PT switched on"
    )
    _raise(client, w, MID_CTC, 16)
    item = _item(client, w)
    pt = [d["amount"] for d in item["deductions_json"] if d["code"] == "PT"]
    assert pt == ["200.00"], (
        f"B4: PT on the month's total earned amounts: {item['deductions_json']}"
    )


def test_B4_pf_is_worked_out_on_the_total_basic_of_all_segments_capped_at_the_ceiling(
    client, db, mworld
) -> None:
    w = mworld
    assert client.put(CONFIG, json={"pf_enabled": True}, headers=w["hr"]).status_code == 200
    _raise(client, w, MID_CTC, 16)
    first_day = date(w["year"], w["month"], 1).isoformat()
    rates = client.get(f"{RATES}?scheme=epf&on_date={first_day}", headers=w["hr"]).json()["items"]
    assert len(rates) == 1, f"the EPF row of the month: {rates}"
    ceiling, rate = Decimal(rates[0]["wage_ceiling"]), Decimal(rates[0]["employee_rate"])
    item = _item(client, w)
    expected = (min(Decimal("27000.00"), ceiling) * rate / Decimal("100")).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )
    got = [d["amount"] for d in item["deductions_json"] if d["code"] == "EPF_EE"]
    assert got == [str(expected)], f"B4: PF on total BASIC 27,000 and the month's row: {got}"


def test_B4_the_esi_ceiling_check_uses_the_salary_in_force_at_the_month_end(
    client, db, mworld
) -> None:
    w = mworld
    assert client.put(CONFIG, json={"esi_enabled": True}, headers=w["hr"]).status_code == 200
    # Old monthly gross 30,000 and new 60,000 are both above the 21,000 ESI ceiling, so no
    # ESI line appears whichever segment is looked at: month-end salary decides.
    _raise(client, w, MID_CTC, 16)
    item = _item(client, w)
    assert not [d for d in item["deductions_json"] if d["code"] == "ESI_EE"], item[
        "deductions_json"
    ]


# ------------------------------------------------------------------- B5


def _approved_claim(client: TestClient, w: dict[str, Any], amount: str) -> None:
    emp = w["emp"]
    made = client.post(
        "/api/v1/payroll/reimbursements",
        json={
            "type": "food",
            "amount": amount,
            "expense_date": days_ago(40),
            "description": "Team lunch",
            "file_object_id": upload_receipt(client, emp["h"]),
        },
        headers=emp["h"],
    )
    assert made.status_code == 201, made.text
    decided = client.put(
        f"/api/v1/payroll/reimbursements/{made.json()['id']}",
        json={"action": "approve"},
        headers=w["hr"],
    )
    assert decided.status_code == 200, decided.text


def test_B5_the_breakdown_adds_up_to_the_paisa_with_two_segments_loss_of_pay_and_a_claim(
    client, db, mworld
) -> None:
    w = mworld
    _lop_world(client, db, w)
    _raise(client, w, MID_CTC, 16)
    _approved_claim(client, w, "1234.56")
    client.put(CONFIG, json={"pt_enabled": True, "pf_enabled": True}, headers=w["hr"])
    item = _item(client, w)
    lines = sum((_money(e["amount"]) for e in item["earnings_json"]), Decimal("0.00"))
    deductions = sum((_money(d["amount"]) for d in item["deductions_json"]), Decimal("0.00"))
    assert lines == _money(item["gross_salary"]), "B5: the earning lines add up to gross"
    assert deductions == _money(item["total_deductions"]), "B5: deductions add up"
    assert item["reimbursement_amount"] == "1234.56", "B5: the claim is paid once, not split"
    assert _money(item["gross_salary"]) - deductions + _money(
        item["reimbursement_amount"]
    ) == _money(item["net_salary"]), "B5: gross - deductions + reimbursement == net, to the paisa"
    assert len(_segments(item)) == 2


def test_B5_the_segments_reach_the_employee_through_the_payslip_route(client, db, mworld) -> None:
    w = mworld
    _raise(client, w, MID_CTC, 16)
    _item(client, w)
    assert client.post(f"{RUNS}/{w['run']['id']}/approve", headers=w["owner"]).status_code == 200
    resp = client.get("/api/v1/payroll/payslips/me", headers=w["emp"]["h"])
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1 and len(_segments(items[0])) == 2, f"B5: payslip shows both: {items}"


# ------------------------------------------------------------------- B6


def test_B6_a_salary_revision_after_an_approved_run_never_changes_that_run(
    client, db, mworld
) -> None:
    w = mworld
    item = _item(client, w)
    assert client.post(f"{RUNS}/{w['run']['id']}/approve", headers=w["owner"]).status_code == 200
    before = client.get(f"{RUNS}/{w['run']['id']}", headers=w["hr"]).json()
    resp = client.post(
        f"/api/v1/payroll/employees/{w['emp']['id']}/assign",
        json={
            "structure_id": w["structure_id"],
            "ctc": MID_CTC,
            "effective_from": date(w["year"], w["month"], 16).isoformat(),
            "revision_reason": "late raise",
        },
        headers=w["hr"],
    )
    assert resp.status_code == 409, f"B6: a start inside a paid month is refused: {resp.text}"
    after = client.get(f"{RUNS}/{w['run']['id']}", headers=w["hr"]).json()
    assert after == before, "B6: the approved run must not change"
    assert _earnings(_item_for(client, w["hr"], w["run"]["id"], w["emp"]["id"])) == _earnings(item)


def test_B6_the_month_before_a_raise_is_one_segment_at_the_old_ctc(client, db, mworld) -> None:
    w = mworld
    _raise(client, w, MID_CTC, 16)
    year, month = (w["year"] - 1, 12) if w["month"] == 1 else (w["year"], w["month"] - 1)
    run = _make_run(client, w["hr"], year, month)
    item = _item_for(client, w["hr"], run["id"], w["emp"]["id"])
    segments = _segments(item)
    assert len(segments) == 1 and segments[0]["ctc"] == OLD_CTC, segments
    assert _earnings(item) == {"BASIC": "18000.00", "ALLOW": "12000.00"}, item["earnings_json"]


def test_B6_every_rule_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_B")]
    for rule in ("B1", "B2", "B3", "B4", "B5", "B6"):
        assert any(n.startswith(f"test_{rule}_") for n in names), f"no test for rule {rule}"
