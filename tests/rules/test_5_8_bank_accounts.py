"""Module 5, sub-feature 5.8: employee bank accounts and the payment file. One test per rule
line (R1..R10).

An employee keeps their own bank details; owner and HR admin keep anyone's. The account number
is encrypted (AES-256-GCM, bound to the company and the column) and shown masked. A payroll
run snapshots its payment lines when it is approved; the CSV payment file is built from that
snapshot, so a later change of bank details never alters an approved run's file.
"""

import csv
import io
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.encryption import DecryptionFailedError, decrypt_field
from app.core.rate_limit import limiter
from app.db.rls import bind_tenant_to_session
from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.statutory_rates import seed_statutory_rates
from app.db.seed.tax_slabs import seed_tax_slabs
from app.modules.identity.models import Company, User, UserRole
from app.modules.platform.models import AuditLog, Notification
from tests.conftest import TenantContext, _make_user_headers
from tests.rules.test_5_4_payroll_runs import (
    RUNS,
    _extra_user,
    _fill,
    _item_for,
    _make_run,
    _month_back,
    _staff,
    _structure,
)

ME = "/api/v1/payroll/bank-account/me"
CONFIG = "/api/v1/payroll/statutory-config"
EMPLOYEES = "/api/v1/employees"
ACCOUNT = "123456789012"
LAST4 = "9012"
MASKED = "********9012"
COLUMN = "bank_account_number"
BANK = {
    "account_holder": "Asha Rao",
    "bank_name": "HDFC Bank",
    "account_number": ACCOUNT,
    "ifsc_code": "HDFC0001234",
}
PAYMENT_COLUMNS = [
    "payment_reference",
    "employee_code",
    "account_holder",
    "bank_name",
    "account_number",
    "ifsc",
    "amount",
    "currency",
    "payment_date",
    "narration",
]


@pytest.fixture(autouse=True)
def _seed_rates(db: Session) -> None:
    seed_pt_slabs(db)
    seed_tax_slabs(db)
    seed_statutory_rates(db)


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


def _for(emp_id: str) -> str:
    return f"/api/v1/payroll/employees/{emp_id}/bank-account"


def _file_url(run_id: str, query: str = "?format=csv") -> str:
    return f"{RUNS}/{run_id}/payment-file{query}"


def _body(**over: Any) -> dict[str, Any]:
    return {**BANK, **over}


def _message(resp) -> str:
    body = resp.json() if resp.content else {}
    error = body.get("error") if isinstance(body, dict) else None
    return error["message"] if isinstance(error, dict) else resp.text


def _expect_tables(db: Session) -> None:
    names = set(inspect(db.get_bind()).get_table_names())
    assert {"employee_bank_accounts", "payroll_run_payments"} <= names, (
        f"R3/R6: the tables employee_bank_accounts and payroll_run_payments are missing: {names}"
    )


def _rows(db: Session, cid: uuid.UUID, employee_id: str) -> list[Any]:
    _expect_tables(db)
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)
    db.expire_all()
    return list(
        db.execute(
            text(
                "SELECT * FROM employee_bank_accounts WHERE employee_id = :e "
                "ORDER BY created_at, is_active"
            ),
            {"e": uuid.UUID(employee_id)},
        )
        .mappings()
        .all()
    )


def _active(db: Session, cid: uuid.UUID, employee_id: str) -> Any:
    found = [r for r in _rows(db, cid, employee_id) if r["is_active"]]
    assert len(found) == 1, f"R2: exactly one active account expected, got {len(found)}"
    return found[0]


def _audit(db: Session, cid: uuid.UUID, action: str) -> list[AuditLog]:
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)
    return db.query(AuditLog).filter(AuditLog.company_id == cid, AuditLog.action == action).all()


@pytest.fixture
def world(client: TestClient, db: Session, company_a: TenantContext) -> dict[str, Any]:
    year, month = _month_back()
    assert (
        client.put(CONFIG, json={"pt_state": "Gujarat"}, headers=company_a.hr_headers).status_code
        == 200
    )
    hr2_h, hr2_user = _extra_user(db, company_a.company_id, UserRole.hr_admin)
    owner_h, owner_user = _extra_user(db, company_a.company_id, UserRole.owner)
    structure_id = _structure(client, company_a.hr_headers)
    emp = _staff(client, db, company_a, structure_id)
    emp2 = _staff(client, db, company_a, structure_id)
    manager = _staff(client, db, company_a, structure_id, UserRole.manager)
    return {
        "ctx": company_a,
        "year": year,
        "month": month,
        "hr1": company_a.hr_headers,
        "hr2": hr2_h,
        "owner": owner_h,
        "owner_user": owner_user,
        "emp": emp,
        "emp2": emp2,
        "manager": manager,
    }


def _save(client: TestClient, w: dict[str, Any], who: str, **over: Any) -> None:
    resp = client.put(_for(w[who]["id"]), json=_body(**over), headers=w["hr1"])
    assert resp.status_code == 200, resp.text


def _code(client: TestClient, w: dict[str, Any], who: str) -> str:
    resp = client.get(f"{EMPLOYEES}/{w[who]['id']}", headers=w["hr1"])
    assert resp.status_code == 200, resp.text
    return resp.json()["employee_code"]


def _pending_run(
    client: TestClient, db: Session, w: dict[str, Any], banks: tuple[str, ...] = ("emp", "emp2")
) -> dict[str, Any]:
    """Everyone present all month, bank details for `banks`, and a run waiting for approval."""
    for who in ("emp", "emp2", "manager"):
        _fill(db, w["ctx"], w[who]["id"], w["year"], w["month"])
    for number, who in enumerate(banks):
        _save(client, w, who, account_number=f"{ACCOUNT[:-1]}{number}")
    return _make_run(client, w["hr1"], w["year"], w["month"])


def _approve(client: TestClient, w: dict[str, Any], run_id: str) -> dict[str, Any]:
    resp = client.post(f"{RUNS}/{run_id}/approve", headers=w["owner"])
    assert resp.status_code == 200, resp.text
    return resp.json()


def _approved(
    client: TestClient, db: Session, w: dict[str, Any], banks: tuple[str, ...] = ("emp", "emp2")
) -> dict[str, Any]:
    run = _pending_run(client, db, w, banks)
    return _approve(client, w, run["id"])


def _csv(resp) -> list[dict[str, str]]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.text)))


# ------------------------------------------------------------------- R1


def test_R1_no_login_gets_401_on_every_bank_route(client: TestClient) -> None:
    some = uuid.uuid4()
    codes = [
        client.get(ME).status_code,
        client.put(ME, json=BANK).status_code,
        client.get(_for(str(some))).status_code,
        client.put(_for(str(some)), json=BANK).status_code,
        client.get(_file_url(str(some))).status_code,
    ]
    assert codes == [401] * 5, f"R1: no login must give 401 on every route, got {codes}"


def test_R1_an_employee_saves_and_changes_their_own_details(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    first = client.put(ME, json=BANK, headers=world["emp"]["h"])
    assert first.status_code == 200, f"R1: an employee saves their own details: {first.text}"
    second = client.put(ME, json=_body(bank_name="State Bank of India"), headers=world["emp"]["h"])
    assert second.status_code == 200, f"R1: and changes them: {second.text}"
    shown = client.get(ME, headers=world["emp"]["h"])
    assert shown.status_code == 200 and shown.json()["bank_name"] == "State Bank of India", (
        f"R1: the change must be what is shown: {shown.text}"
    )
    by_id = client.put(_for(world["emp"]["id"]), json=BANK, headers=world["emp"]["h"])
    assert by_id.status_code == 200, (
        f"R1: the employee may use the by-id route for self: {by_id.text}"
    )


@pytest.mark.parametrize("who", ["hr1", "hr2", "owner"])
def test_R1_hr_admin_and_owner_save_and_read_anyones_details(
    client: TestClient, world: dict[str, Any], who: str
) -> None:
    put = client.put(_for(world["emp"]["id"]), json=BANK, headers=world[who])
    assert put.status_code == 200, f"R1: {who} saves for an employee: {put.text}"
    get = client.get(_for(world["emp"]["id"]), headers=world[who])
    assert get.status_code == 200, f"R1: {who} reads an employee's details: {get.text}"


@pytest.mark.parametrize("who", ["manager", "emp2"])
def test_R1_a_manager_and_another_employee_get_403_on_someone_elses(
    client: TestClient, world: dict[str, Any], who: str
) -> None:
    _save(client, world, "emp")
    headers = world[who]["h"]
    codes = [
        client.get(_for(world["emp"]["id"]), headers=headers).status_code,
        client.put(_for(world["emp"]["id"]), json=BANK, headers=headers).status_code,
        client.get(_for(world["emp"]["id"]) + "?reveal=true", headers=headers).status_code,
    ]
    assert codes == [403] * 3, f"R1: {who} must get 403 on another employee's details: {codes}"


def test_R1_a_super_admin_gets_403_on_every_bank_and_payment_file_route(
    client: TestClient, world: dict[str, Any], super_admin_headers: dict[str, str]
) -> None:
    some = world["emp"]["id"]
    codes = {
        "GET me": client.get(ME, headers=super_admin_headers).status_code,
        "PUT me": client.put(ME, json=BANK, headers=super_admin_headers).status_code,
        "GET by id": client.get(_for(some), headers=super_admin_headers).status_code,
        "PUT by id": client.put(_for(some), json=BANK, headers=super_admin_headers).status_code,
        "reveal": client.get(_for(some) + "?reveal=true", headers=super_admin_headers).status_code,
        "payment file": client.get(
            _file_url(str(uuid.uuid4())), headers=super_admin_headers
        ).status_code,
    }
    assert set(codes.values()) == {403}, f"R1: a super admin must get 403 everywhere: {codes}"


def test_R1_another_companys_employee_and_run_give_404(
    client: TestClient, db: Session, world: dict[str, Any], company_b: TenantContext
) -> None:
    other = client.put(_for(world["emp"]["id"]), json=BANK, headers=company_b.hr_headers)
    missing = client.put(_for(str(uuid.uuid4())), json=BANK, headers=world["hr1"])
    assert other.status_code == 404 and missing.status_code == 404, (
        f"R1: another company's employee must be a 404: {other.status_code}, {missing.status_code}"
    )
    assert _message(other) == _message(missing), "R1: missing and foreign must read the same"
    run = _approved(client, db, world)
    foreign = client.get(_file_url(run["id"]), headers=_owner_of(db, company_b))
    assert foreign.status_code == 404, f"R1: another company's run must be a 404: {foreign.text}"


def _owner_of(db: Session, ctx: TenantContext) -> dict[str, str]:
    return _make_user_headers(db, ctx.company_id, UserRole.owner)


def test_R1_the_employee_must_be_active(client: TestClient, world: dict[str, Any]) -> None:
    gone = client.delete(f"{EMPLOYEES}/{world['emp2']['id']}", headers=world["hr1"])
    assert gone.status_code in (200, 204), gone.text
    resp = client.put(_for(world["emp2"]["id"]), json=BANK, headers=world["hr1"])
    assert resp.status_code == 409, f"R1: an inactive employee gets 409, got {resp.status_code}"


def test_R1_a_user_without_an_employee_profile_gets_404_on_me(
    client: TestClient, world: dict[str, Any]
) -> None:
    resp = client.get(ME, headers=world["hr1"])
    assert resp.status_code == 404, f"R1: no employee profile must give 404, got {resp.status_code}"


# ------------------------------------------------------------------- R2


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_holder", ""),
        ("account_holder", "x" * 101),
        ("bank_name", ""),
        ("bank_name", "y" * 101),
        ("account_number", "12345678"),
        ("account_number", "1" * 19),
        ("account_number", "12345678a"),
        ("ifsc_code", "HDFC1001234"),
        ("ifsc_code", "HDFC000123"),
        ("ifsc_code", "HDFC00012345"),
        ("account_holder", None),
        ("bank_name", None),
        ("account_number", None),
        ("ifsc_code", None),
    ],
)
def test_R2_bad_input_gives_422_and_never_echoes_the_number(
    client: TestClient, world: dict[str, Any], field: str, value: Any
) -> None:
    resp = client.put(ME, json=_body(**{field: value}), headers=world["emp"]["h"])
    assert resp.status_code == 422, f"R2: {field}={value!r} must give 422, got {resp.status_code}"
    assert ACCOUNT not in resp.text, "R2: the 422 must not echo the account number"


def test_R2_an_unknown_field_gives_422(client: TestClient, world: dict[str, Any]) -> None:
    resp = client.put(ME, json=_body(is_active=False), headers=world["emp"]["h"])
    assert resp.status_code == 422, f"R2: unknown field must give 422, got {resp.status_code}"


def test_R2_the_ifsc_is_upper_cased_and_edges_are_accepted(
    client: TestClient, world: dict[str, Any]
) -> None:
    resp = client.put(
        ME,
        json=_body(ifsc_code="hdfc0abc123", account_number="123456789", account_holder="A"),
        headers=world["emp"]["h"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ifsc_code"] == "HDFC0ABC123", f"R2: IFSC must be upper-cased: {resp.text}"
    long = client.put(
        ME,
        json=_body(account_number="9" * 18, account_holder="h" * 100, bank_name="b" * 100),
        headers=world["emp"]["h"],
    )
    assert long.status_code == 200, f"R2: the longest valid values must pass: {long.text}"


def test_R2_a_change_adds_a_row_and_deactivates_the_old_one_keeping_history(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    cid = world["ctx"].company_id
    emp = world["emp"]["id"]
    _save(client, world, "emp")
    _save(client, world, "emp", bank_name="Axis Bank")
    _save(client, world, "emp", bank_name="ICICI Bank")
    rows = _rows(db, cid, emp)
    assert len(rows) == 3, f"R2: old rows are kept as history: {len(rows)}"
    assert [r["is_active"] for r in rows].count(True) == 1, "R2: exactly one active row"
    assert _active(db, cid, emp)["bank_name"] == "ICICI Bank", "R2: the newest row is active"


def test_R2_a_company_whose_country_is_not_payroll_ready_gets_409(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=True)
    company = db.get(Company, world["ctx"].company_id)
    assert company is not None
    company.country = "US"
    db.commit()
    resp = client.put(ME, json=BANK, headers=world["emp"]["h"])
    assert resp.status_code == 409, f"R2: a US company must get 409, got {resp.status_code}"
    assert "not available yet" in _message(resp), f"R2: unclear message: {_message(resp)}"


# ------------------------------------------------------------------- R3


def test_R3_the_number_is_encrypted_bound_to_company_and_column_with_last4_beside_it(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    _save(client, world, "emp")
    cid = world["ctx"].company_id
    row = _active(db, cid, world["emp"]["id"])
    blob = bytes(row["account_number_enc"])
    assert ACCOUNT.encode() not in blob, "R3: the blob must not hold the plain number"
    assert row["account_last4"] == LAST4, f"R3: last four stored beside it: {row['account_last4']}"
    assert decrypt_field(blob, company_id=cid, column=COLUMN) == ACCOUNT, (
        "R3: decrypts to the number with the company and the column name"
    )
    with pytest.raises(DecryptionFailedError):
        decrypt_field(blob, company_id=cid, column="payout_account_number")
    with pytest.raises(DecryptionFailedError):
        decrypt_field(blob, company_id=uuid.uuid4(), column=COLUMN)
    for name, value in row.items():
        if name != "account_number_enc":
            assert ACCOUNT not in str(value), f"R3: the plain number is stored in column {name}"


def test_R3_a_tampered_value_fails_with_the_controlled_error_and_not_the_number(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    _save(client, world, "emp")
    cid = world["ctx"].company_id
    row = _active(db, cid, world["emp"]["id"])
    damaged = bytearray(bytes(row["account_number_enc"]))
    damaged[-1] ^= 0x01
    db.execute(
        text("UPDATE employee_bank_accounts SET account_number_enc = :b WHERE id = :i"),
        {"b": bytes(damaged), "i": row["id"]},
    )
    db.commit()
    resp = client.get(_for(world["emp"]["id"]) + "?reveal=true", headers=world["hr1"])
    assert resp.status_code == 500, f"R3: a damaged value must fail, got {resp.status_code}"
    assert resp.json()["error"]["code"] == "decryption_failed", f"R3: wrong error: {resp.text}"
    assert ACCOUNT not in resp.text, "R3: the error must not hold the number"
    assert client.get(_for(world["emp"]["id"]), headers=world["hr1"]).status_code == 200, (
        "R3: the masked view needs no decryption"
    )


# ------------------------------------------------------------------- R4


def test_R4_every_response_audit_row_and_log_line_shows_only_the_mask(
    client: TestClient, db: Session, world: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    emp = world["emp"]
    seen = [
        client.put(ME, json=BANK, headers=emp["h"]),
        client.get(ME, headers=emp["h"]),
        client.get(_for(emp["id"]), headers=world["hr1"]),
        client.put(_for(emp["id"]), json=_body(bank_name="Axis Bank"), headers=world["hr1"]),
        client.put(ME, json=_body(account_number="12345"), headers=emp["h"]),
    ]
    for resp in seen[:4]:
        assert resp.status_code == 200, resp.text
        assert resp.json()["account_number"] == MASKED, f"R4: must be masked: {resp.text}"
        assert ACCOUNT not in resp.text, "R4: the plain number is in a response"
    assert ACCOUNT not in seen[4].text, "R4: an error echoed the number"
    for action in ("BANK_ACCOUNT_SAVED", "BANK_ACCOUNT_REVEALED"):
        for row in _audit(db, world["ctx"].company_id, action):
            assert ACCOUNT not in str(row.details), f"R4: the number is in an audit row ({action})"
    assert ACCOUNT not in caplog.text, "R4: the number is in a log line"


def test_R4_an_employee_cannot_reveal_even_their_own_number(
    client: TestClient, world: dict[str, Any]
) -> None:
    _save(client, world, "emp")
    resp = client.get(ME + "?reveal=true", headers=world["emp"]["h"])
    assert resp.status_code == 403, f"R4: reveal is for owner and HR admin, got {resp.status_code}"
    assert ACCOUNT not in resp.text


@pytest.mark.parametrize("who", ["hr1", "owner"])
def test_R4_reveal_returns_the_number_with_no_store_and_one_audit_row_each_time(
    client: TestClient, db: Session, world: dict[str, Any], who: str
) -> None:
    _save(client, world, "emp")
    cid = world["ctx"].company_id
    before = len(_audit(db, cid, "BANK_ACCOUNT_REVEALED"))
    first = client.get(_for(world["emp"]["id"]) + "?reveal=true", headers=world[who])
    second = client.get(_for(world["emp"]["id"]) + "?reveal=true", headers=world[who])
    for resp in (first, second):
        assert resp.status_code == 200, resp.text
        assert resp.json()["account_number"] == ACCOUNT, f"R4: reveal shows the number: {resp.text}"
        assert resp.headers.get("cache-control") == "private, no-store", (
            f"R4: reveal must not be cached: {resp.headers.get('cache-control')}"
        )
    rows = _audit(db, cid, "BANK_ACCOUNT_REVEALED")
    assert len(rows) - before == 2, f"R4: one audit row per reveal, got {len(rows) - before}"
    assert all(ACCOUNT not in str(r.details) for r in rows), "R4: the audit row holds the number"


def test_R4_a_plain_get_never_reveals_and_writes_no_audit_row(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    _save(client, world, "emp")
    client.get(_for(world["emp"]["id"]), headers=world["hr1"])
    assert _audit(db, world["ctx"].company_id, "BANK_ACCOUNT_REVEALED") == [], (
        "R4: a masked read is not a reveal"
    )


def test_R4_reveal_is_limited_to_5_per_minute(
    client: TestClient, world: dict[str, Any], limits_on: None
) -> None:
    _save(client, world, "emp")
    codes = [
        client.get(_for(world["emp"]["id"]) + "?reveal=true", headers=world["hr1"]).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [200] * 5 and codes[5] == 429, f"R4: reveal limit wrong: {codes}"


def test_R4_sending_the_mask_back_never_overwrites_and_an_unchanged_save_writes_no_audit_row(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    _save(client, world, "emp")
    cid = world["ctx"].company_id
    emp = world["emp"]["id"]
    changed = client.put(
        _for(emp), json=_body(account_number=MASKED, bank_name="Axis Bank"), headers=world["hr1"]
    )
    assert changed.status_code == 200, changed.text
    blob = bytes(_active(db, cid, emp)["account_number_enc"])
    assert decrypt_field(blob, company_id=cid, column=COLUMN) == ACCOUNT, (
        "R4: the stored number must survive a save that sent the mask"
    )
    audits = len(_audit(db, cid, "BANK_ACCOUNT_SAVED"))
    rows = len(_rows(db, cid, emp))
    same = client.put(
        _for(emp), json=_body(account_number=MASKED, bank_name="Axis Bank"), headers=world["hr1"]
    )
    assert same.status_code == 200, same.text
    assert len(_audit(db, cid, "BANK_ACCOUNT_SAVED")) == audits, "R4: unchanged save: no audit row"
    assert len(_rows(db, cid, emp)) == rows, "R4: unchanged save: no new row"
    wrong = client.put(_for(emp), json=_body(account_number="********0000"), headers=world["hr1"])
    assert wrong.status_code == 422, (
        f"R4: a mask that does not match gives 422: {wrong.status_code}"
    )


# ------------------------------------------------------------------- R5


def test_R5_only_owner_and_hr_admin_export_and_only_an_approved_run(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    run = _pending_run(client, db, world)
    pending = client.get(_file_url(run["id"]), headers=world["hr1"])
    assert pending.status_code == 409, (
        f"R5: a run waiting for approval gives 409: {pending.status_code}"
    )
    _approve(client, world, run["id"])
    for who in ("emp", "manager"):
        resp = client.get(_file_url(run["id"]), headers=world[who]["h"])
        assert resp.status_code == 403, f"R5: {who} must get 403, got {resp.status_code}"
    for who in ("hr1", "hr2", "owner"):
        resp = client.get(_file_url(run["id"]), headers=world[who])
        assert resp.status_code == 200, f"R5: {who} exports: {resp.status_code} {resp.text[:200]}"


def test_R5_the_csv_has_the_columns_in_order_and_the_amounts_add_up_to_the_net_total(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    run = _approved(client, db, world, banks=("emp", "emp2", "manager"))
    resp = client.get(_file_url(run["id"]), headers=world["hr1"])
    assert resp.status_code == 200, resp.text
    header = next(csv.reader(io.StringIO(resp.text)))
    assert header == PAYMENT_COLUMNS, f"R5: header/column order wrong: {header}"
    rows = _csv(resp)
    assert len(rows) == 3, f"R5: one line per payable employee: {len(rows)}"
    total = sum(float(r["amount"]) * 100 for r in rows)
    assert round(total) == round(float(run["total_net"]) * 100), (
        f"R5: amounts {total / 100} must add up to the run's net total {run['total_net']}"
    )
    mine = next(r for r in rows if r["employee_code"] == _code(client, world, "emp"))
    item = _item_for(client, world["hr1"], run["id"], world["emp"]["id"])
    expected_reference = f"PAY-{world['year']}{world['month']:02d}-{mine['employee_code']}"
    assert mine["payment_reference"] == expected_reference, f"R5: reference: {mine}"
    assert mine["amount"] == f"{float(item['net_salary']):.2f}", f"R5: amount is net pay: {mine}"
    assert len(mine["amount"].split(".")[1]) == 2, "R5: two decimals"
    assert mine["currency"] == "INR", f"R5: the company currency: {mine}"
    approved_on = run["approved_at"][:10]
    assert mine["payment_date"] == approved_on, f"R5: the date the run was approved: {mine}"
    assert mine["account_holder"] == BANK["account_holder"] and mine["ifsc"] == BANK["ifsc_code"]
    assert mine["narration"], "R5: a narration is expected"
    for r in rows:
        assert len(r["account_number"]) == 12 and r["account_number"].isdigit(), (
            "R5: the file carries the full number for the bank"
        )


def test_R5_response_headers(client: TestClient, db: Session, world: dict[str, Any]) -> None:
    run = _approved(client, db, world)
    resp = client.get(_file_url(run["id"]), headers=world["hr1"])
    assert resp.headers["content-type"].startswith("text/csv"), resp.headers["content-type"]
    assert resp.headers["content-disposition"].startswith("attachment"), "R5: attachment"
    assert resp.headers["cache-control"] == "private, no-store", "R5: no-store"


def test_R5_export_is_limited_to_5_per_minute(
    client: TestClient, db: Session, world: dict[str, Any], limits_on: None
) -> None:
    run = _approved(client, db, world)
    codes = [client.get(_file_url(run["id"]), headers=world["hr1"]).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429, f"R5: export limit wrong: {codes}"


# ------------------------------------------------------------------- R6


def test_R6_a_later_change_never_alters_an_approved_runs_file_and_two_exports_are_identical(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    run = _approved(client, db, world)
    first = client.get(_file_url(run["id"]), headers=world["hr1"])
    _save(client, world, "emp", account_number="999999999999", bank_name="Other Bank")
    second = client.get(_file_url(run["id"]), headers=world["owner"])
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert first.content == second.content, "R6: the file must not change after approval"
    assert "999999999999" not in second.text, "R6: the new number must not be in the old file"


def test_R6_approval_does_not_fail_when_a_bank_detail_is_missing(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    run = _pending_run(client, db, world, banks=())
    approved = client.post(f"{RUNS}/{run['id']}/approve", headers=world["owner"])
    assert approved.status_code == 200, f"R6: approval must never fail on a bank: {approved.text}"


def test_R6_the_snapshot_is_written_in_the_same_save_as_the_approval(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    run = _approved(client, db, world)
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    count = db.execute(
        text("SELECT count(*) FROM payroll_run_payments WHERE payroll_run_id = :r"),
        {"r": uuid.UUID(run["id"])},
    ).scalar_one()
    assert count == 3, f"R6: one snapshot line per employee in the run (payable or not): {count}"


def test_R6_a_run_approved_before_the_snapshot_existed_gives_409_and_is_not_guessed(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    run = _approved(client, db, world)
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    db.execute(
        text("DELETE FROM payroll_run_payments WHERE payroll_run_id = :r"),
        {"r": uuid.UUID(run["id"])},
    )
    db.commit()
    resp = client.get(_file_url(run["id"]), headers=world["hr1"])
    assert resp.status_code == 409, f"R6: no snapshot must give 409, got {resp.status_code}"
    assert "no saved payment details" in _message(resp), f"R6: unclear: {_message(resp)}"


def test_R6_the_snapshot_holds_the_number_encrypted_not_plain(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    run = _approved(client, db, world)
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    rows = (
        db.execute(
            text("SELECT * FROM payroll_run_payments WHERE payroll_run_id = :r"),
            {"r": uuid.UUID(run["id"])},
        )
        .mappings()
        .all()
    )
    paid = [r for r in rows if r["excluded_reason"] is None]
    assert len(paid) == 2, f"R6: two payable lines expected: {len(paid)}"
    for r in paid:
        assert r["account_last4"] and ACCOUNT[:-1] not in "".join(str(v) for v in r.values()), (
            "R6: the snapshot must not hold a plain number"
        )


# ------------------------------------------------------------------- R7


def test_R7_no_bank_details_or_no_positive_net_pay_leaves_the_employee_out_with_a_reason(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    run = _pending_run(client, db, world, banks=("emp", "manager"))
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    db.execute(
        text("UPDATE payroll_items SET net_salary = 0 WHERE employee_id = :e"),
        {"e": uuid.UUID(world["manager"]["id"])},
    )
    db.commit()
    _approve(client, world, run["id"])
    resp = client.get(_file_url(run["id"]), headers=world["hr1"])
    rows = _csv(resp)
    assert [r["employee_code"] for r in rows] == [_code(client, world, "emp")], (
        f"R7: only the payable employee is in the file: {rows}"
    )
    assert resp.headers.get("x-excluded-count") == "2", (
        f"R7: X-Excluded-Count must say 2: {resp.headers.get('x-excluded-count')}"
    )
    detail = client.get(f"{RUNS}/{run['id']}", headers=world["hr1"]).json()
    left_out = {e["employee_id"]: e["reason"] for e in detail["payment_exclusions"]}
    assert left_out == {
        world["emp2"]["id"]: "no_bank_details",
        world["manager"]["id"]: "net_pay_not_positive",
    }, f"R7: the run detail must list who was left out and why: {left_out}"
    for entry in detail["payment_exclusions"]:
        assert set(entry) == {"employee_id", "reason"}, f"R7: no numbers in the list: {entry}"


def test_R7_nobody_payable_gives_409(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    run = _approved(client, db, world, banks=())
    resp = client.get(_file_url(run["id"]), headers=world["hr1"])
    assert resp.status_code == 409, f"R7: nobody payable gives 409, got {resp.status_code}"


# ------------------------------------------------------------------- R8


def test_R8_an_unknown_format_gives_422_listing_the_known_ones(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    run = _approved(client, db, world)
    resp = client.get(_file_url(run["id"], "?format=xlsx"), headers=world["hr1"])
    assert resp.status_code == 422, f"R8: unknown format gives 422, got {resp.status_code}"
    assert "csv" in resp.text, f"R8: the known formats must be listed: {resp.text}"
    default = client.get(_file_url(run["id"], ""), headers=world["hr1"])
    assert default.status_code in (200, 422), "R8: format is either defaulted or required"


@pytest.mark.parametrize("lead", ["=", "+", "-", "@"])
def test_R8_a_formula_in_a_text_field_is_escaped(
    client: TestClient, db: Session, world: dict[str, Any], lead: str
) -> None:
    holder = f'{lead}HYPERLINK("http://example.test","x")'
    for who in ("emp", "emp2", "manager"):
        _fill(db, world["ctx"], world[who]["id"], world["year"], world["month"])
    _save(client, world, "emp", account_holder=holder, bank_name=f"{lead}Bank")
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    _approve(client, world, run["id"])
    rows = _csv(client.get(_file_url(run["id"]), headers=world["hr1"]))
    assert rows[0]["account_holder"] == "'" + holder, f"R8: formula not escaped: {rows[0]}"
    assert rows[0]["bank_name"] == "'" + f"{lead}Bank", f"R8: bank name not escaped: {rows[0]}"


def test_R8_commas_quotes_and_line_breaks_survive_a_round_trip(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    holder = 'Rao, "Asha"\nKumar'
    for who in ("emp", "emp2", "manager"):
        _fill(db, world["ctx"], world[who]["id"], world["year"], world["month"])
    _save(client, world, "emp", account_holder=holder)
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    _approve(client, world, run["id"])
    rows = _csv(client.get(_file_url(run["id"]), headers=world["hr1"]))
    assert rows[0]["account_holder"] == holder, f"R8: quoting broke the field: {rows[0]}"


def test_R8_the_file_is_built_through_a_registry_with_only_csv_registered() -> None:
    import importlib

    try:
        module = importlib.import_module("app.modules.payroll.payment_files")
    except ModuleNotFoundError:
        pytest.fail("R8: the module app.modules.payroll.payment_files does not exist yet")
    registry = getattr(module, "PAYMENT_FILE_FORMATS", None)
    assert registry is not None, "R8: PAYMENT_FILE_FORMATS (the registry) is missing"
    assert sorted(registry) == ["csv"], f"R8: version 1 registers only csv: {sorted(registry)}"
    csv_format = registry["csv"]
    assert csv_format.content_type.startswith("text/csv"), csv_format.content_type
    for attribute in ("name", "filename", "build"):
        assert hasattr(csv_format, attribute), f"R8: a format needs {attribute}"
    first_cell = csv_format.build(
        [_neutral_row(module, account_holder="\t=cmd"), _neutral_row(module, account_holder="\rx")]
    )
    text_out = first_cell.decode() if isinstance(first_cell, bytes) else first_cell
    assert "'\t=cmd" in text_out and "'\rx" in text_out.replace('"', ""), (
        f"R8: tab and carriage return must be escaped too: {text_out!r}"
    )


def _neutral_row(module: Any, **over: Any) -> Any:
    row_type = getattr(module, "PaymentLine", None)
    assert row_type is not None, "R8: PaymentLine (the neutral payment row) is missing"
    base = {
        "payment_reference": "PAY-202601-E1",
        "employee_code": "E1",
        "account_holder": "A",
        "bank_name": "B",
        "account_number": "123456789",
        "ifsc": "HDFC0001234",
        "amount": "10.00",
        "currency": "INR",
        "payment_date": "2026-01-31",
        "narration": "Salary",
    }
    base.update(over)
    return row_type(**base)


# ------------------------------------------------------------------- R9


def test_R9_save_and_export_each_write_one_audit_row_with_no_numbers(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    cid = world["ctx"].company_id
    _save(client, world, "emp")
    saved = _audit(db, cid, "BANK_ACCOUNT_SAVED")
    assert len(saved) == 1, f"R9: one audit row per save, got {len(saved)}"
    assert saved[0].entity_id is not None and ACCOUNT not in str(saved[0].details)
    run = _approved(client, db, world)
    assert client.get(_file_url(run["id"]), headers=world["hr1"]).status_code == 200
    exported = _audit(db, cid, "PAYMENT_FILE_EXPORTED")
    assert len(exported) == 1, f"R9: one audit row per export, got {len(exported)}"
    details = exported[0].details
    assert details["format"] == "csv" and "row_count" in details, f"R9: details: {details}"
    assert "amount" not in str(details).lower() or "amount" not in details, "R9: no amounts"
    assert ACCOUNT not in str(details)


def test_R9_a_save_notifies_the_other_side_after_the_commit_without_the_number(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    cid = world["ctx"].company_id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)
    before = db.query(Notification).filter(Notification.type == "bank_details_changed").count()
    assert client.put(_for(world["emp"]["id"]), json=BANK, headers=world["hr1"]).status_code == 200
    mine = (
        db.query(Notification)
        .filter(
            Notification.user_id == world["emp"]["user"].id,
            Notification.type == "bank_details_changed",
        )
        .all()
    )
    assert len(mine) == 1, f"R9: the employee is told when HR changes their details: {len(mine)}"
    assert ACCOUNT not in (mine[0].message + mine[0].title), "R9: no number in the message"
    assert (
        client.put(ME, json=_body(bank_name="Axis Bank"), headers=world["emp"]["h"]).status_code
        == 200
    )
    hr_notes = (
        db.query(Notification)
        .filter(
            Notification.user_id == world["owner_user"].id,
            Notification.type == "bank_details_changed",
        )
        .count()
    )
    assert hr_notes == 1, f"R9: HR-level users are told when the employee changes: {hr_notes}"
    again = client.put(ME, json=_body(bank_name="Axis Bank"), headers=world["emp"]["h"])
    assert again.status_code == 200
    total = db.query(Notification).filter(Notification.type == "bank_details_changed").count()
    hr_level = (
        db.query(User)
        .filter(
            User.company_id == cid,
            User.role.in_([UserRole.owner, UserRole.hr_admin]),
            User.is_active.is_(True),
        )
        .count()
    )
    # One notice to the employee for HR's change, one to each HR-level user for the employee's.
    assert total - before == 1 + hr_level, (
        f"R9: an unchanged save notifies nobody: {total - before} (expected {1 + hr_level})"
    )


def test_R9_the_update_and_its_audit_row_are_one_save(
    client: TestClient, db: Session, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = world["ctx"].company_id
    emp = world["emp"]["id"]
    _save(client, world, "emp")
    import app.modules.platform.service as platform_service

    def _boom(self, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("audit failed")

    monkeypatch.setattr(platform_service.AuditService, "record", _boom)
    try:
        status_code = client.put(
            _for(emp), json=_body(bank_name="Axis Bank"), headers=world["hr1"]
        ).status_code
    except RuntimeError:
        status_code = 500
    assert status_code == 500, f"R9: a failing audit must fail the save, got {status_code}"
    db.rollback()
    rows = _rows(db, cid, emp)
    assert len(rows) == 1 and rows[0]["bank_name"] == "HDFC Bank" and rows[0]["is_active"], (
        f"R9: the failed save must change nothing: {rows}"
    )


def test_R9_writes_are_limited_to_30_per_minute(
    client: TestClient, world: dict[str, Any], limits_on: None
) -> None:
    codes = [client.put(ME, json=BANK, headers=world["emp"]["h"]).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429, f"R9: write limit wrong: {codes[-3:]}"


def test_R9_reads_are_limited_to_60_per_minute(
    client: TestClient, world: dict[str, Any], limits_on: None
) -> None:
    _save(client, world, "emp")
    codes = [
        client.get(_for(world["emp"]["id"]), headers=world["hr1"]).status_code for _ in range(61)
    ]
    assert codes[:60] == [200] * 60 and codes[60] == 429, f"R9: read limit wrong: {codes[-3:]}"


# ------------------------------------------------------------------- isolation (new tables)


def test_isolation_one_companys_bank_rows_and_payment_lines_are_invisible_to_another(
    client: TestClient, db: Session, world: dict[str, Any], company_b: TenantContext
) -> None:
    run = _approved(client, db, world)
    _expect_tables(db)
    bind_tenant_to_session(db, company_id=company_b.company_id, is_platform_admin=False)
    for table in ("employee_bank_accounts", "payroll_run_payments"):
        seen = db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert seen == 0, f"isolation: company B sees {seen} rows of {table}"
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    assert db.execute(text("SELECT count(*) FROM employee_bank_accounts")).scalar_one() == 2
    assert run["id"]


# ------------------------------------------------------------------- R10


def test_R10_every_rule_from_1_to_9_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_R")]
    for rule in range(1, 10):
        assert any(n.startswith(f"test_R{rule}_") for n in names), f"R10: no test for rule {rule}"
    assert Path(__file__).name == "test_5_8_bank_accounts.py"
