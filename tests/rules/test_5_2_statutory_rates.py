"""Module 5, sub-feature 5.2: Statutory rates and tax slabs. One test per rule line (R1..R10).

Dates a rule compares with today are computed from utcnow(). Fixed dates below are only the
effective dates of the official rows pinned from the source table (they are compared with other
fixed dates, never with today). Modules that this package creates are imported lazily through
`_need`, so a missing module fails the test by assertion instead of breaking collection.
"""

import importlib
import re
import threading
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.tax_slabs import seed_tax_slabs
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.payroll import payslip_engine
from app.modules.payroll.payslip_engine import (
    ComponentSpec,
    PayslipInput,
    PTSlabSpec,
    StatutoryConfigSpec,
    TaxSlabSpec,
    calculate_payslip,
)
from app.modules.platform.models import AuditLog
from app.modules.platform.service import AuditService
from tests.conftest import REPO_ROOT, TenantContext, _make_user_headers
from tests.rules.test_5_4_payroll_runs import (
    RUNS,
    _extra_user,
    _item_for,
    _make_run,
    _month_back,
    _post_run,
    _staff,
    _structure,
)

RATES = "/api/v1/payroll/statutory-rates"
PT = "/api/v1/payroll/pt-slabs"
TAX = "/api/v1/payroll/tax-slabs"
CONFIG = "/api/v1/payroll/statutory-config"
MIGRATION_REVISION = "5c2a0001a001"  # the first 5.2 migration (rate tables, source columns)
OLD_RATE_COLUMNS = (
    "pf_employee_rate",
    "pf_employer_rate",
    "pf_wage_ceiling",
    "esi_employee_rate",
    "esi_employer_rate",
    "esi_wage_ceiling",
)
OFFICIAL_HOSTS = {
    "epfindia.gov.in",
    "pmvbry.epfindia.gov.in",
    "esic.gov.in",
    "labour.gov.in",
    "pib.gov.in",
    "incometaxindia.gov.in",
    "incometax.gov.in",
    "indiabudget.gov.in",
    "egazette.gov.in",
    "commercialtax.gujarat.gov.in",
    "gujarat.gov.in",
}


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


def _need(module: str) -> Any:
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError:
        pytest.fail(f"the module {module} does not exist yet")


def _attr(module: str, name: str) -> Any:
    found = getattr(_need(module), name, None)
    assert found is not None, f"{module} needs {name}"
    return found


def _seed_all(db: Session) -> None:
    seed_pt_slabs(db)
    seed_tax_slabs(db)
    _attr("app.db.seed.statutory_rates", "seed_statutory_rates")(db)


def _first_of(back: int) -> date:
    year, month = _month_back(back)
    return date(year, month, 1)


def _rate_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "scheme": "esi",
        "employee_rate": "1.000",
        "employer_rate": "4.000",
        "wage_ceiling": "30000.00",
        "effective_from": _first_of(2).isoformat(),
        "source_url": "https://esic.gov.in/contribution",
        "source_title": "ESIC contribution rates",
        "verified_on": utcnow().date().isoformat(),
        "source_note": "test note",
    }
    body.update(over)
    return body


def _pt_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "state": "Gujarat",
        "effective_from": _first_of(2).isoformat(),
        "source_url": "https://commercialtax.gujarat.gov.in/vatwebsite/download/schedule/x.pdf",
        "source_title": "Gujarat professional tax schedule",
        "verified_on": utcnow().date().isoformat(),
        "source_note": "test note",
        "slabs": [{"income_min": "0.00", "income_max": None, "monthly_amount": "300.00"}],
    }
    body.update(over)
    return body


def _tax_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "country": "IN",
        "financial_year": "2031-2032",
        "regime": "new",
        "cess_percent": "4.000",
        "surcharge_rules": None,
        "effective_from": "2031-04-01",
        "source_url": "https://www.incometaxindia.gov.in/w/tax-rates",
        "source_title": "Income tax slabs",
        "verified_on": utcnow().date().isoformat(),
        "source_note": "test note",
        "brackets": [
            {"min_income": "0.00", "max_income": "400000.00", "rate_percent": "0.000"},
            {"min_income": "400000.01", "max_income": None, "rate_percent": "5.000"},
        ],
    }
    body.update(over)
    return body


def _post_rate(client: TestClient, headers: dict[str, str], **over: Any):
    return client.post(RATES, json=_rate_body(**over), headers=headers)


def _list_rates(client: TestClient, headers: dict[str, str], query: str = ""):
    return client.get(f"{RATES}{query}", headers=headers)


def _items(resp) -> list[dict[str, Any]]:
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _message(resp) -> str:
    body = resp.json() if resp.content else {}
    error = body.get("error") if isinstance(body, dict) else None
    return error["message"] if isinstance(error, dict) else resp.text


def _fields(resp) -> set[str]:
    body = resp.json() if resp.content else {}
    error = body.get("error") if isinstance(body, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    errors = details.get("errors", []) if isinstance(details, dict) else []
    return {str(e["loc"][-1]) for e in errors if e["loc"]}


def _audit(db: Session, action: str) -> list[AuditLog]:
    return db.query(AuditLog).filter(AuditLog.action == action).all()


def _table_columns(db: Session, table: str) -> dict[str, bool]:
    """column name -> nullable"""
    if table not in inspect(db.get_bind()).get_table_names():
        pytest.fail(f"the table {table} does not exist")
    return {c["name"]: c["nullable"] for c in inspect(db.get_bind()).get_columns(table)}


def _need_rates_table(db: Session) -> None:
    assert "statutory_rates" in inspect(db.get_bind()).get_table_names(), (
        "R1: the platform table statutory_rates does not exist"
    )


@pytest.fixture
def hr(company_a: TenantContext) -> dict[str, str]:
    return company_a.hr_headers


@pytest.fixture
def rworld(client: TestClient, db: Session, company_a: TenantContext) -> dict[str, Any]:
    """Company A with a low-paid employee (gross 15,000 a month, inside the ESI ceiling), TDS
    switched off (the seeded income-tax years end with 2026-27), every rate seeded."""
    seed_pt_slabs(db)
    seed_tax_slabs(db)
    try:  # before the rate seed exists the tests that need it fail by assertion, not here
        importlib.import_module("app.db.seed.statutory_rates").seed_statutory_rates(db)
    except ModuleNotFoundError:
        pass
    ctx = company_a
    switched = client.put(CONFIG, json={"tds_enabled": False}, headers=ctx.hr_headers)
    assert switched.status_code == 200, switched.text
    owner_h, _ = _extra_user(db, ctx.company_id, UserRole.owner)
    structure_id = _structure(client, ctx.hr_headers)
    emp = _staff(client, db, ctx, structure_id, ctc="180000.00", exempt=True)
    return {"ctx": ctx, "hr": ctx.hr_headers, "owner": owner_h, "emp": emp}


def _ded(item: dict[str, Any], code: str) -> str | None:
    for line in item["deductions_json"]:
        if line["code"] == code:
            return line["amount"]
    return None


def _er(item: dict[str, Any], code: str) -> str | None:
    for line in item["employer_contributions_json"]:
        if line["code"] == code:
            return line["amount"]
    return None


def _run_item(client: TestClient, w: dict[str, Any], back: int) -> dict[str, Any]:
    year, month = _month_back(back)
    run = _make_run(client, w["hr"], year, month)
    return _item_for(client, w["hr"], run["id"], w["emp"]["id"])


# ------------------------------------------------------------------- R1


def test_R1_statutory_rates_is_a_platform_table_without_row_level_security(db: Session) -> None:
    _need_rates_table(db)
    columns = _table_columns(db, "statutory_rates")
    expected = {
        "scheme",
        "employee_rate",
        "employer_rate",
        "wage_ceiling",
        "employer_epf_rate",
        "employer_eps_rate",
        "edli_rate",
        "admin_charge_rate",
        "effective_from",
        "effective_to",
        "source_url",
        "source_title",
        "source_note",
        "verified_on",
    }
    assert expected <= set(columns), f"R1: columns missing: {sorted(expected - set(columns))}"
    assert "company_id" not in columns, "R1: a platform table has no company_id"
    rls = db.execute(
        text("SELECT relrowsecurity FROM pg_class WHERE relname = 'statutory_rates'")
    ).scalar_one()
    assert rls is False, "R1: statutory_rates must have no row level security, like pt_slabs"


def test_R1_no_login_gets_401(client: TestClient) -> None:
    codes = [
        client.post(RATES, json=_rate_body()).status_code,
        client.get(RATES).status_code,
    ]
    assert codes == [401, 401], f"R1: no login must give 401 on both rate routes: {codes}"


def test_R1_only_super_admin_adds_a_rate(client, db, hr, company_a, super_admin_headers) -> None:
    for label, headers in (
        ("hr_admin", hr),
        ("owner", _make_user_headers(db, company_a.company_id, UserRole.owner)),
        ("manager", company_a.manager_headers),
        ("employee", company_a.employee_headers),
    ):
        resp = _post_rate(client, headers)
        assert resp.status_code == 403, f"R1: {label} must not add a rate: {resp.text}"
    created = _post_rate(client, super_admin_headers)
    assert created.status_code == 201, f"R1: super_admin adds a rate: {created.text}"
    body = created.json()
    assert body["scheme"] == "esi" and body["effective_to"] is None, body
    assert body["source_url"] == "https://esic.gov.in/contribution", "R1: source must be returned"


def test_R1_hr_level_reads_rates_and_employee_and_manager_get_403(
    client, db, hr, company_a, super_admin_headers
) -> None:
    _seed_all(db)
    owner = _make_user_headers(db, company_a.company_id, UserRole.owner)
    for label, headers in (
        ("hr_admin", hr),
        ("owner", owner),
        ("super_admin", super_admin_headers),
    ):
        resp = _list_rates(client, headers)
        assert resp.status_code == 200, f"R1: {label} must read rates: {resp.text}"
        body = resp.json()
        assert {"items", "page", "limit", "total", "pages", "has_next"} <= set(body), body
    for label, headers in (
        ("manager", company_a.manager_headers),
        ("employee", company_a.employee_headers),
    ):
        assert _list_rates(client, headers).status_code == 403, f"R1: {label} must get 403"


def test_R1_rates_can_be_filtered_by_scheme_and_date_and_are_paged(client, db, hr) -> None:
    _seed_all(db)
    epf = _items(_list_rates(client, hr, "?scheme=epf"))
    assert {r["scheme"] for r in epf} == {"epf"} and len(epf) == 2, f"R1: scheme filter: {epf}"
    before = _items(_list_rates(client, hr, "?scheme=epf&on_date=2026-09-16"))
    after = _items(_list_rates(client, hr, "?scheme=epf&on_date=2026-09-17"))
    assert [r["wage_ceiling"] for r in before] == ["15000.00"], f"R1: on_date 2026-09-16: {before}"
    assert [r["wage_ceiling"] for r in after] == ["25000.00"], f"R1: on_date 2026-09-17: {after}"
    page = _list_rates(client, hr, "?limit=1&page=2").json()
    assert len(page["items"]) == 1 and page["total"] >= 3 and page["has_next"] is not None, page
    for bad in ("?scheme=pf", "?on_date=not-a-date", "?page=0", "?limit=0", "?limit=101"):
        assert _list_rates(client, hr, bad).status_code == 422, f"R1: {bad} must give 422"


def test_R1_the_six_rate_columns_are_removed_from_the_company_config_table(db: Session) -> None:
    columns = _table_columns(db, "statutory_configs")
    still_there = [c for c in OLD_RATE_COLUMNS if c in columns]
    assert still_there == [], f"R1: these rate columns must be removed by migration: {still_there}"
    for kept in ("pf_enabled", "pf_restrict_to_ceiling", "esi_enabled", "pt_state", "pt_enabled"):
        assert kept in columns, f"R1: the switch {kept} must stay"


def test_R1_the_company_config_shows_read_only_effective_rates(client, db, hr) -> None:
    _seed_all(db)
    body = client.get(CONFIG, headers=hr).json()
    for name in OLD_RATE_COLUMNS:
        assert name not in body, f"R1: the config response still carries {name}"
    rates = body.get("effective_rates")
    assert isinstance(rates, list), f"R1: effective_rates missing: {sorted(body)}"
    assert {r["scheme"] for r in rates} == {"epf", "esi"}, f"R1: one row per scheme: {rates}"
    today = utcnow().date().isoformat()
    for row in rates:
        assert row["source_url"].startswith("https://"), f"R1: the source link is shown: {row}"
        assert row["effective_from"] <= today, f"R1: only the rows in force today: {row}"
        assert row["effective_to"] is None or row["effective_to"] >= today, row


@pytest.mark.parametrize("name", OLD_RATE_COLUMNS)
def test_R1_sending_a_rate_or_ceiling_to_the_company_config_gives_422(client, hr, name) -> None:
    resp = client.put(CONFIG, json={name: "10.000"}, headers=hr)
    assert resp.status_code == 422, f"R1: {name} on the company config must give 422: {resp.text}"


def test_R1_a_company_can_still_switch_items_and_choose_state_and_regime(client, hr) -> None:
    body = {
        "pf_enabled": False,
        "esi_enabled": False,
        "pt_state": "Gujarat",
        "default_tax_regime": "old",
    }
    resp = client.put(CONFIG, json=body, headers=hr)
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_tax_regime"] == "old" and resp.json()["pf_enabled"] is False


# ------------------------------------------------------------------- R2


def test_R2_the_official_host_list_is_exactly_the_agreed_one() -> None:
    hosts = _attr("app.core.official_sources", "OFFICIAL_HOSTS")
    assert set(hosts) == OFFICIAL_HOSTS, f"R2: host list differs: {set(hosts) ^ OFFICIAL_HOSTS}"


@pytest.mark.parametrize(
    "url",
    [
        "https://epfindia.gov.in/x",
        "https://pmvbry.epfindia.gov.in/epf-scheme/",
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=1",
        "https://commercialtax.gujarat.gov.in/vatwebsite/download/schedule/a.pdf",
        "https://static.pib.gov.in/WriteReadData/x.pdf",
    ],
)
def test_R2_an_exact_host_or_a_subdomain_of_the_list_is_official(url: str) -> None:
    check = _attr("app.core.official_sources", "is_official_url")
    assert check(url) is True, f"R2: {url} is on the government list"


@pytest.mark.parametrize(
    "url",
    [
        "http://epfindia.gov.in/x",
        "https://taxguru.in/income-tax/x.html",
        "https://evil.com/epfindia.gov.in",
        "https://epfindia.gov.in.evil.com/x",
        "https://notepfindia.gov.in/x",
        "https://user@evil.com/x",
        "https://epfindia.gov.in@evil.com/x",
        "https://epfindia.gov.in:8443/x",
        "ftp://epfindia.gov.in/x",
        "epfindia.gov.in",
        "",
    ],
)
def test_R2_anything_else_is_not_official(url: str) -> None:
    check = _attr("app.core.official_sources", "is_official_url")
    assert check(url) is False, f"R2: {url!r} must not be accepted"


ROUTES = [
    pytest.param("rates", id="rates"),
    pytest.param("pt", id="pt"),
    pytest.param("tax", id="tax"),
]


def _write(client: TestClient, headers: dict[str, str], route: str, **over: Any):
    if route == "rates":
        return client.post(RATES, json=_rate_body(**over), headers=headers)
    if route == "pt":
        return client.put(PT, json=_pt_body(**over), headers=headers)
    return client.post(TAX, json=_tax_body(**over), headers=headers)


@pytest.mark.parametrize("route", ROUTES)
def test_R2_a_valid_write_with_all_source_fields_is_accepted(
    client, super_admin_headers, route
) -> None:
    resp = _write(client, super_admin_headers, route)
    assert resp.status_code in (200, 201), f"R2: {route} with a full source must work: {resp.text}"
    row = resp.json()[0] if isinstance(resp.json(), list) else resp.json()
    for name in ("source_url", "source_title", "verified_on"):
        assert row.get(name), f"R2: {route} response must show {name}: {row}"


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("missing", ["source_url", "source_title", "verified_on"])
def test_R2_a_write_missing_a_source_field_gives_422(
    client, super_admin_headers, route, missing
) -> None:
    body = {"rates": _rate_body, "pt": _pt_body, "tax": _tax_body}[route]()
    del body[missing]
    send = client.post if route in ("rates", "tax") else client.put
    url = {"rates": RATES, "pt": PT, "tax": TAX}[route]
    resp = send(url, json=body, headers=super_admin_headers)
    assert resp.status_code == 422, f"R2: {route} without {missing} must give 422: {resp.text}"
    assert missing in _fields(resp), f"R2: the error must name {missing}: {resp.text}"


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(
    "url",
    [
        "https://taxguru.in/x",
        "http://epfindia.gov.in/x",
        "https://epfindia.gov.in.evil.com/x",
        "https://evil.com/",
        "",
    ],
)
def test_R2_a_write_with_another_host_gives_422(client, super_admin_headers, route, url) -> None:
    resp = _write(client, super_admin_headers, route, source_url=url)
    assert resp.status_code == 422, f"R2: {route} with source {url!r} must give 422: {resp.text}"
    assert "source_url" in _fields(resp), f"R2: the error must name source_url: {resp.text}"


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_R2_the_source_title_must_be_1_to_200_characters(
    client, super_admin_headers, route, title
) -> None:
    resp = _write(client, super_admin_headers, route, source_title=title)
    assert resp.status_code == 422, f"R2: title {title[:5]!r}.. must give 422: {resp.text}"
    assert "source_title" in _fields(resp)


def test_R2_a_200_character_title_is_allowed(client, super_admin_headers) -> None:
    assert _post_rate(client, super_admin_headers, source_title="x" * 200).status_code == 201


@pytest.mark.parametrize("route", ROUTES)
def test_R2_verified_on_cannot_be_in_the_future(client, super_admin_headers, route) -> None:
    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    resp = _write(client, super_admin_headers, route, verified_on=tomorrow)
    assert resp.status_code == 422, f"R2: {route} verified tomorrow must give 422: {resp.text}"
    assert "verified_on" in _fields(resp)


def test_R2_the_source_note_is_optional(client, super_admin_headers) -> None:
    body = _rate_body()
    del body["source_note"]
    resp = client.post(RATES, json=body, headers=super_admin_headers)
    assert resp.status_code == 201, f"R2: the note is optional: {resp.text}"


@pytest.mark.parametrize("table", ["statutory_rates", "pt_slabs", "tax_slabs"])
def test_R2_the_source_columns_exist_and_are_required_in_the_database(
    db: Session, table: str
) -> None:
    columns = _table_columns(db, table)
    for name in ("source_url", "source_title", "verified_on"):
        assert name in columns, f"R2: {table}.{name} is missing"
        assert columns[name] is False, f"R2: {table}.{name} must be NOT NULL"
    assert "source_note" in columns


@pytest.mark.parametrize("route", ["pt", "tax"])
def test_R2_the_pt_and_tax_reads_show_the_source(client, db, hr, route) -> None:
    _seed_all(db)
    resp = (
        client.get(PT, headers=hr)
        if route == "pt"
        else client.get(f"{TAX}?financial_year=2026-2027", headers=hr)
    )
    assert resp.status_code == 200, resp.text
    for row in resp.json():
        assert row["source_url"].startswith("https://") and row["source_title"], row
        assert row["verified_on"] == "2026-11-04", f"R2: verified_on is the seeded date: {row}"


# ------------------------------------------------------------------- R3


def test_R3_a_new_rate_adds_a_row_and_ends_the_open_row_the_day_before(
    client, db, hr, super_admin_headers
) -> None:
    _seed_all(db)
    start = _first_of(2)
    created = _post_rate(client, super_admin_headers, effective_from=start.isoformat())
    assert created.status_code == 201, created.text
    rows = _items(_list_rates(client, hr, "?scheme=esi"))
    assert len(rows) == 2, f"R3: the old row must be kept and a new one added: {rows}"
    old = next(r for r in rows if r["effective_from"] == "2019-07-01")
    new = next(r for r in rows if r["effective_from"] == start.isoformat())
    assert old["effective_to"] == (start - timedelta(days=1)).isoformat(), (
        f"R3: the open row must end the day before: {old}"
    )
    assert new["effective_to"] is None and old["employee_rate"] == "0.750", (new, old)


def test_R3_a_new_row_must_start_after_the_open_rows_start(client, db, super_admin_headers) -> None:
    _seed_all(db)
    for start in ("2019-07-01", "2019-06-30", "2018-01-01"):
        resp = _post_rate(client, super_admin_headers, effective_from=start)
        assert resp.status_code == 409, f"R3: a start of {start} must give 409: {resp.text}"
        assert "2019-07-01" in _message(resp), f"R3: the message names the dates: {_message(resp)}"
    assert len(_items(_list_rates(client, super_admin_headers, "?scheme=esi"))) == 1


def test_R3_rows_of_one_scheme_never_overlap(client, db, super_admin_headers) -> None:
    _seed_all(db)
    start = _first_of(2)
    assert (
        _post_rate(client, super_admin_headers, effective_from=start.isoformat()).status_code == 201
    )
    inside_old = start - timedelta(days=10)
    resp = _post_rate(client, super_admin_headers, effective_from=inside_old.isoformat())
    assert resp.status_code == 409, f"R3: a start inside a closed row must give 409: {resp.text}"
    assert "2019-07-01" in _message(resp) and start.isoformat() in _message(resp), _message(resp)
    same = _post_rate(client, super_admin_headers, effective_from=start.isoformat())
    assert same.status_code == 409, f"R3: the same start twice must give 409: {same.text}"


def test_R3_a_refused_add_changes_nothing(client, db, hr, super_admin_headers) -> None:
    _seed_all(db)
    before = _items(_list_rates(client, hr, "?scheme=esi"))
    _post_rate(client, super_admin_headers, effective_from="2019-07-01")
    assert _items(_list_rates(client, hr, "?scheme=esi")) == before, "R3: a 409 must save nothing"


def _need_exclusion(db: Session) -> None:
    _need_rates_table(db)
    found = db.execute(
        text(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conrelid = 'statutory_rates'::regclass AND contype = 'x'"
        )
    ).scalar_one()
    assert found == 1, f"R3: statutory_rates needs one exclusion constraint, found {found}"


def _raw_rate(db: Session, scheme: str, start: str, end: str | None) -> None:
    db.execute(
        text(
            "INSERT INTO statutory_rates (id, scheme, employee_rate, employer_rate, wage_ceiling, "
            "effective_from, effective_to, source_url, source_title, verified_on) VALUES "
            "(:id, :s, 1, 1, 1000, :f, :t, 'https://esic.gov.in/x', 'raw', '2026-11-04')"
        ),
        {"id": uuid.uuid4(), "s": scheme, "f": start, "t": end},
    )
    db.flush()


def test_R3_the_database_itself_refuses_overlapping_rows(db: Session) -> None:
    _need_exclusion(db)
    _raw_rate(db, "esi", "2040-01-01", "2040-12-31")
    with pytest.raises(IntegrityError):
        _raw_rate(db, "esi", "2040-06-01", None)
    db.rollback()


def test_R3_rows_of_different_schemes_may_share_dates(db: Session) -> None:
    _need_exclusion(db)
    _raw_rate(db, "esi", "2041-01-01", None)
    _raw_rate(db, "epf", "2041-01-01", None)


def _committed_rate_world(engine) -> dict[str, Any]:
    """A committed super admin and one open ESI row, for the simultaneous-add test."""
    cid = uuid.uuid4()
    with Session(engine) as setup:
        setup.add(
            Company(
                id=cid,
                name="Rate Race Co",
                code=f"RAT{uuid.uuid4().hex[:4].upper()}",
                email=f"rat-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
                is_active=True,
            )
        )
        setup.flush()
        bind_tenant_to_session(setup, company_id=cid, is_platform_admin=False)
        user = User(
            id=uuid.uuid4(),
            company_id=cid,
            email=f"sa-{uuid.uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("Test1234pass!"),
            role=UserRole.super_admin,
            is_active=True,
        )
        setup.add(user)
        setup.flush()
        token = create_access_token(sub=str(user.id), company_id=str(cid), role="super_admin")
        setup.commit()
    return {"cid": cid, "h": {"Authorization": f"Bearer {token}"}}


def _purge_rate_world(cid: uuid.UUID) -> None:
    owner = create_engine(settings.TEST_MIGRATION_URL)
    try:
        with owner.begin() as conn:
            conn.execute(text("DELETE FROM statutory_rates WHERE source_title LIKE 'RACE TEST%'"))
            conn.execute(text("DELETE FROM audit_logs WHERE company_id = :c"), {"c": cid})
            conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
            conn.execute(text("DELETE FROM users WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": cid})
    finally:
        owner.dispose()


def test_R3_two_simultaneous_adds_give_one_201_and_one_409(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _attr("app.modules.payroll.repository", "StatutoryRateRepository")
    original = repo.create

    def _slow(self, **kwargs):  # noqa: ANN001, ANN003
        time.sleep(0.5)  # both requests passed the overlap look before either saves
        return original(self, **kwargs)

    monkeypatch.setattr(repo, "create", _slow)
    assert settings.TEST_DATABASE_URL is not None and settings.TEST_MIGRATION_URL is not None
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    world = _committed_rate_world(engine)
    owner = create_engine(settings.TEST_MIGRATION_URL)
    try:
        with owner.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO statutory_rates (id, scheme, employee_rate, employer_rate, "
                    "wage_ceiling, effective_from, effective_to, source_url, source_title, "
                    "verified_on) VALUES (:id, 'esi', 1, 1, 1000, '2040-01-01', NULL, "
                    "'https://esic.gov.in/x', 'RACE TEST base', '2026-11-04')"
                ),
                {"id": uuid.uuid4()},
            )

        def _get_test_db():
            session = Session(engine)
            try:
                yield session
            finally:
                session.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db
        results: list[int] = []
        barrier = threading.Barrier(2)

        def _worker() -> None:
            c = TestClient(fastapi_app)
            barrier.wait()
            body = _rate_body(effective_from="2041-01-01", source_title="RACE TEST new")
            results.append(c.post(RATES, json=body, headers=world["h"]).status_code)

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert 500 not in results, f"R3: a race must never give a 500: {results}"
        assert sorted(results) == [201, 409], f"R3: expected one 201 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        owner.dispose()
        _purge_rate_world(world["cid"])


def test_R3_a_run_uses_the_row_in_force_on_the_first_day_of_its_month(
    client, db, rworld, super_admin_headers
) -> None:
    w = rworld
    older = _run_item(client, w, 3)
    assert _ded(older, "ESI_EE") == "112.50", (
        f"R3: the seeded 0.75% on 15,000: {older['deductions_json']}"
    )
    first_change = _first_of(2)
    mid_month_change = _first_of(1) + timedelta(days=16)
    one = _post_rate(client, super_admin_headers, effective_from=first_change.isoformat())
    assert one.status_code == 201, one.text
    two = _post_rate(
        client,
        super_admin_headers,
        effective_from=mid_month_change.isoformat(),
        employee_rate="2.000",
        employer_rate="5.000",
    )
    assert two.status_code == 201, two.text
    year, month = _month_back(2)
    middle = _item_for(
        client, w["hr"], _make_run(client, w["hr"], year, month)["id"], w["emp"]["id"]
    )
    assert _ded(middle, "ESI_EE") == "150.00", f"R3: the 1st-of-month change applies: {middle}"
    assert _er(middle, "ESI_ER") == "600.00", f"R3: employer share of the new row: {middle}"
    latest = _run_item(client, w, 1)
    assert _ded(latest, "ESI_EE") == "150.00", (
        f"R3: a change on the 17th does not apply to that month: {latest['deductions_json']}"
    )


def test_R3_an_issued_payslip_never_changes_when_a_rate_is_added(
    client, db, rworld, super_admin_headers
) -> None:
    w = rworld
    year, month = _month_back(3)
    run = _make_run(client, w["hr"], year, month)
    before = _item_for(client, w["hr"], run["id"], w["emp"]["id"])
    client.post(f"{RUNS}/{run['id']}/approve", headers=w["owner"])
    assert (
        _post_rate(client, super_admin_headers, effective_from=_first_of(2).isoformat()).status_code
        == 201
    )
    after = _item_for(client, w["hr"], run["id"], w["emp"]["id"])
    assert after == before, "R3: an issued payslip must not change when a rate is added"


def test_R3_pt_slab_sets_are_effective_dated_too(client, db, rworld, super_admin_headers) -> None:
    w = rworld
    assert _ded(_run_item(client, w, 3), "PT") == "200.00", "R3: the seeded Gujarat PT on 15,000"
    resp = client.put(
        PT, json=_pt_body(effective_from=_first_of(2).isoformat()), headers=super_admin_headers
    )
    assert resp.status_code == 200, resp.text
    year, month = _month_back(2)
    item = _item_for(client, w["hr"], _make_run(client, w["hr"], year, month)["id"], w["emp"]["id"])
    assert _ded(item, "PT") == "300.00", f"R3: the new PT set applies from its month: {item}"
    old_rows = client.get(PT, headers=w["hr"]).json()
    ends = {r["effective_to"] for r in old_rows if r["effective_from"] == "2022-04-01"}
    assert ends == {(_first_of(2) - timedelta(days=1)).isoformat()}, (
        f"R3: old set ends the day before: {ends}"
    )


def test_R3_a_pt_set_must_start_after_the_open_sets_start(client, db, super_admin_headers) -> None:
    _seed_all(db)
    for start in ("2022-04-01", "2021-01-01"):
        resp = client.put(PT, json=_pt_body(effective_from=start), headers=super_admin_headers)
        assert resp.status_code == 409, f"R3: PT set starting {start} must give 409: {resp.text}"
        assert "2022-04-01" in _message(resp), _message(resp)


def test_R3_a_second_tax_set_for_the_same_year_and_regime_gives_409(
    client, db, super_admin_headers
) -> None:
    _seed_all(db)
    resp = client.post(
        TAX,
        json=_tax_body(financial_year="2026-2027", effective_from="2026-04-01"),
        headers=super_admin_headers,
    )
    assert resp.status_code == 409, f"R3: the year already has a bracket set: {resp.text}"


@pytest.mark.parametrize(
    "month_year,needle",
    [((2016, 1), "EPF"), ((2019, 1), "ESI")],
)
def test_R3_no_row_in_force_fails_the_run_with_409_and_no_run_row(
    client, db, rworld, month_year, needle
) -> None:
    w = rworld
    resp = _post_run(client, w["hr"], month_year[0], month_year[1])
    assert resp.status_code == 409, f"R3: no {needle} rate in force must give 409: {resp.text}"
    assert needle in _message(resp), f"R3: the message names the scheme: {_message(resp)}"
    assert str(month_year[0]) in _message(resp) or "01" in _message(resp), _message(resp)
    bind_tenant_to_session(db, company_id=w["ctx"].company_id, is_platform_admin=False)
    count = db.execute(text("SELECT count(*) FROM payroll_runs")).scalar_one()
    assert count == 0, "R3: a failed run must leave no run row"


def test_R3_a_switched_off_item_needs_no_rate(client, db, rworld) -> None:
    w = rworld
    switched = client.put(
        CONFIG,
        json={"pf_enabled": False, "esi_enabled": False, "pt_enabled": False},
        headers=w["hr"],
    )
    assert switched.status_code == 200
    resp = _post_run(client, w["hr"], 2016, 1)
    assert resp.status_code == 202, f"R3: with every item off no rate is needed: {resp.text}"


# ------------------------------------------------------------------- R4

LINK = re.compile(r"https?://[^\s,;)\]]+")


def _all_seeded_text(db: Session) -> list[tuple[str, str]]:
    _seed_all(db)
    found: list[tuple[str, str]] = []
    for table in ("statutory_rates", "pt_slabs", "tax_slabs"):
        for url, note in db.execute(
            text(f"SELECT source_url, source_note FROM {table}")
        ).fetchall():
            found.append((table, f"{url} {note or ''}"))
    return found


def test_R4_every_seeded_link_is_on_the_government_list(db: Session) -> None:
    check = _attr("app.core.official_sources", "is_official_url")
    texts = _all_seeded_text(db)
    assert texts, "R4: nothing was seeded"
    for table, blob in texts:
        for link in LINK.findall(blob):
            assert check(link) is True, f"R4: {table} holds a non-official link: {link}"


def test_R4_no_seeded_text_mentions_taxguru_or_a_notification_number(db: Session) -> None:
    for table, blob in _all_seeded_text(db):
        lowered = blob.lower()
        assert "taxguru" not in lowered, f"R4: {table} still quotes TaxGuru"
        assert "ghn-35" not in lowered and "s.o." not in lowered, (
            f"R4: {table}: notification number"
        )


def test_R4_the_placeholder_pre_2022_pt_rows_are_gone(db: Session) -> None:
    _seed_all(db)
    old = db.execute(
        text("SELECT count(*) FROM pt_slabs WHERE effective_from < '2022-04-01'")
    ).scalar_one()
    assert old == 0, f"R4: {old} placeholder PT rows before 2022-04-01 remain"
    unverified = db.execute(
        text("SELECT count(*) FROM pt_slabs WHERE source_note ILIKE '%placeholder%'")
    ).scalar_one()
    assert unverified == 0, "R4: no row may call itself a placeholder"


def _cfg() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


def _previous_revision() -> str:
    try:
        revision = ScriptDirectory.from_config(_cfg()).get_revision(MIGRATION_REVISION)
    except Exception:  # noqa: BLE001 - alembic raises its own error for an unknown revision
        revision = None
    assert revision is not None and isinstance(revision.down_revision, str), (
        f"R4: the migration {MIGRATION_REVISION} does not exist yet"
    )
    return revision.down_revision


def _insert_old_pt(
    conn, state: str, start: str, end: str | None, note: str, income_max: str | None
) -> None:
    conn.execute(
        text(
            "INSERT INTO pt_slabs (id, state, income_min, income_max, monthly_amount, "
            "effective_from, effective_to, source_note) "
            "VALUES (:id, :st, 0, :mx, 0, :f, :t, :n)"
        ),
        {"id": uuid.uuid4(), "st": state, "mx": income_max, "f": start, "t": end, "n": note},
    )


def test_R4_the_migration_deletes_placeholder_rows_backfills_sources_and_round_trips() -> None:
    assert settings.TEST_MIGRATION_URL is not None
    engine = create_engine(settings.TEST_MIGRATION_URL)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        try:
            command.downgrade(cfg, _previous_revision())
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM pt_slabs"))
                conn.execute(text("DELETE FROM tax_slabs"))
                _insert_old_pt(
                    conn, "Gujarat", "2000-01-01", "2022-03-31", "TaxGuru placeholder", "5999.99"
                )
                _insert_old_pt(
                    conn, "Gujarat", "2022-04-01", None, "TaxGuru GHN-35 current", "12000.00"
                )
            command.upgrade(cfg, MIGRATION_REVISION)
            with engine.begin() as conn:
                rows = conn.execute(
                    text("SELECT effective_from::text, source_url, source_note FROM pt_slabs")
                ).fetchall()
                config_cols = {c["name"] for c in inspect(conn).get_columns("statutory_configs")}
            assert [r[0] for r in rows] == ["2022-04-01"], (
                f"R4: placeholder rows must be deleted: {rows}"
            )
            assert rows[0][1] == (
                "https://commercialtax.gujarat.gov.in/vatwebsite/download/schedule/Rate_of_Profession_Tax.pdf"
            ), "R4: the kept Gujarat row gets the official source"
            assert "taxguru" not in (rows[0][2] or "").lower(), "R4: TaxGuru text must be removed"
            assert not set(OLD_RATE_COLUMNS) & config_cols, "R4: rate columns must be dropped"

            command.downgrade(cfg, _previous_revision())
            with engine.begin() as conn:
                config_cols = {c["name"] for c in inspect(conn).get_columns("statutory_configs")}
                tables = inspect(conn).get_table_names()
            assert set(OLD_RATE_COLUMNS) <= config_cols, (
                "R4: downgrade must re-add the rate columns"
            )
            assert "statutory_rates" not in tables, "R4: downgrade must drop the rates table"
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM pt_slabs"))
            command.upgrade(cfg, "head")
            engine.dispose()


def test_R4_the_migration_stops_on_a_row_with_an_unknown_source() -> None:
    assert settings.TEST_MIGRATION_URL is not None
    engine = create_engine(settings.TEST_MIGRATION_URL)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        try:
            command.downgrade(cfg, _previous_revision())
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM pt_slabs"))
                _insert_old_pt(conn, "Kerala", "2023-01-01", None, "added by hand", None)
            with pytest.raises(RuntimeError) as caught:
                command.upgrade(cfg, MIGRATION_REVISION)
            message = str(caught.value)
            assert "Kerala" in message and "source" in message.lower(), f"R4: unclear: {message}"
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM pt_slabs"))
            command.upgrade(cfg, "head")
            engine.dispose()


# ------------------------------------------------------------------- R5

EPF_ROW_1_SOURCE = "https://pmvbry.epfindia.gov.in/epf-scheme/"
EPF_ROW_2_SOURCE = "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2313790&reg=48&lang=2"


def _row(rows: list[dict[str, Any]], start: str) -> dict[str, Any]:
    found = [r for r in rows if r["effective_from"] == start]
    assert len(found) == 1, f"R5: expected one row starting {start}, got {len(found)}"
    return found[0]


def test_R5_the_epf_rows_equal_the_source_table(client, db, hr) -> None:
    _seed_all(db)
    rows = _items(_list_rates(client, hr, "?scheme=epf"))
    assert len(rows) == 2, f"R5: two EPF periods are seeded: {len(rows)}"
    one, two = _row(rows, "2017-04-01"), _row(rows, "2026-09-17")
    for row in (one, two):
        assert (row["employee_rate"], row["employer_rate"]) == ("12.000", "12.000"), row
        assert row["employer_epf_rate"] == "3.670" and row["employer_eps_rate"] == "8.330", row
        assert row["edli_rate"] == "0.500" and row["admin_charge_rate"] == "0.650", row
    assert (one["wage_ceiling"], one["effective_to"]) == ("15000.00", "2026-09-16"), one
    assert (two["wage_ceiling"], two["effective_to"]) == ("25000.00", None), two
    assert one["source_url"] == EPF_ROW_1_SOURCE and two["source_url"] == EPF_ROW_2_SOURCE
    for link in (
        "https://www.epfindia.gov.in/site_docs/PDFs/MiscPDFs/Employer_Information_Booklet.pdf",
        "https://pmvbry.epfindia.gov.in/insurance-scheme-edli/",
        "https://www.epfindia.gov.in/site_docs/PDFs/CBT_Files/220CBT_AGENDA5.pdf",
    ):
        assert link in one["source_note"], f"R5: row 1 note must list {link}"
    for link in (
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2310811&reg=48&lang=2",
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2314111&lang=1&reg=3",
    ):
        assert link in two["source_note"], f"R5: row 2 note must list {link}"
    assert "earlier history is not seeded" in one["source_note"].lower(), one["source_note"]
    assert not re.search(r"\bS\.?O\.?\s*\d", two["source_note"]), "R5: no notification number"
    assert one["verified_on"] == two["verified_on"] == "2026-11-04"


def test_R5_the_esi_row_equals_the_source_table(client, db, hr) -> None:
    _seed_all(db)
    rows = _items(_list_rates(client, hr, "?scheme=esi"))
    assert len(rows) == 1, f"R5: one ESI row: {rows}"
    row = rows[0]
    assert (row["employee_rate"], row["employer_rate"], row["wage_ceiling"]) == (
        "0.750",
        "3.250",
        "21000.00",
    ), row
    assert row["effective_from"] == "2019-07-01" and row["effective_to"] is None, row
    assert row["source_url"] == "https://esic.gov.in/contribution", row
    assert "https://esic.gov.in/coverage" in row["source_note"], row["source_note"]
    assert row["edli_rate"] is None and row["admin_charge_rate"] is None, "R5: EPF-only columns"


def test_R5_gujarat_professional_tax_equals_the_source_table(client, db, hr) -> None:
    _seed_all(db)
    rows = client.get(PT, headers=hr).json()
    assert len(rows) == 2, f"R5: two Gujarat slabs: {rows}"
    by_min = {r["income_min"]: r for r in rows}
    low, high = by_min["0.00"], by_min["12000.01"]
    assert (low["income_max"], low["monthly_amount"]) == ("12000.00", "0.00"), low
    assert (high["income_max"], high["monthly_amount"]) == (None, "200.00"), high
    for row in rows:
        assert row["effective_from"] == "2022-04-01" and row["effective_to"] is None, row
        assert row["source_url"] == (
            "https://commercialtax.gujarat.gov.in/vatwebsite/download/schedule/Rate_of_Profession_Tax.pdf"
        ), row


@pytest.mark.parametrize("gross,expected", [("12000.00", None), ("12000.01", "200.00")])
def test_R5_professional_tax_boundary_at_12000(client, db, hr, gross, expected) -> None:
    _seed_all(db)
    slabs = [
        PTSlabSpec(
            state=r["state"],
            income_min=Decimal(r["income_min"]),
            income_max=Decimal(r["income_max"]) if r["income_max"] else None,
            monthly_amount=Decimal(r["monthly_amount"]),
        )
        for r in client.get(PT, headers=hr).json()
    ]
    out = calculate_payslip(
        _engine_input(
            ctc=Decimal(gross) * 12,
            statutory=StatutoryConfigSpec(
                pf_enabled=False, esi_enabled=False, pt_enabled=True, tds_enabled=False
            ),
            pt_slabs=slabs,
        )
    )
    pt = [d.amount for d in out.deductions if d.code == "PT"]
    assert (str(pt[0]) if pt else None) == expected, f"R5: PT on {gross}: {pt}"


NEW_BRACKETS = [
    ("0.00", "400000.00", "0.000"),
    ("400000.01", "800000.00", "5.000"),
    ("800000.01", "1200000.00", "10.000"),
    ("1200000.01", "1600000.00", "15.000"),
    ("1600000.01", "2000000.00", "20.000"),
    ("2000000.01", "2400000.00", "25.000"),
    ("2400000.01", None, "30.000"),
]
OLD_BRACKETS = [
    ("0.00", "250000.00", "0.000"),
    ("250000.01", "500000.00", "5.000"),
    ("500000.01", "1000000.00", "20.000"),
    ("1000000.01", None, "30.000"),
]
NEW_SURCHARGE = [
    ("5000000.00", "10000000.00", "10.000"),
    ("10000000.00", "20000000.00", "15.000"),
    ("20000000.00", None, "25.000"),
]
OLD_SURCHARGE = [
    ("5000000.00", "10000000.00", "10.000"),
    ("10000000.00", "20000000.00", "15.000"),
    ("20000000.00", "50000000.00", "25.000"),
    ("50000000.00", None, "37.000"),
]


@pytest.mark.parametrize("fy", ["2025-2026", "2026-2027"])
@pytest.mark.parametrize("regime", ["new", "old"])
def test_R5_income_tax_slabs_equal_the_source_table(client, db, hr, fy, regime) -> None:
    _seed_all(db)
    rows = client.get(f"{TAX}?financial_year={fy}&regime={regime}", headers=hr).json()
    brackets = NEW_BRACKETS if regime == "new" else OLD_BRACKETS
    got = [(r["min_income"], r["max_income"], r["rate_percent"]) for r in rows]
    assert got == brackets, f"R5: {fy} {regime} brackets differ: {got}"
    for row in rows:
        assert row["cess_percent"] == "4.000", f"R5: cess must be 4%: {row}"
    rules = rows[0]["surcharge_rules"]
    assert rules["standard_deduction"] == ("75000.00" if regime == "new" else "50000.00"), rules
    rebate = rules["rebate_87a"]
    expected = ("1200000.00", "60000.00") if regime == "new" else ("500000.00", "12500.00")
    assert (rebate["income_limit"], rebate["max_rebate"]) == expected, f"R5: 87A rebate: {rebate}"
    surcharge = [(s["income_min"], s["income_max"], s["rate_percent"]) for s in rules["surcharge"]]
    assert surcharge == (NEW_SURCHARGE if regime == "new" else OLD_SURCHARGE), (
        f"R5: surcharge: {surcharge}"
    )
    if fy == "2025-2026":
        assert (
            rows[0]["source_url"]
            == "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2098406&reg=3&lang=2"
        )
        assert "https://www.incometaxindia.gov.in/w/tax-rates%E2%80%8B" in rows[0]["source_note"]
    else:
        assert rows[0]["source_url"] == "https://www.indiabudget.gov.in/doc/memo.pdf", rows[0][
            "source_url"
        ]
        note = rows[0]["source_note"]
        assert (
            "https://static.pib.gov.in/WriteReadData/specificdocs/documents/2026/feb/doc202621776101.pdf"
            in note
        )
        assert "Finance Act 2026" in note, "R5: the human-check warning must be in the note"
    if regime == "old":
        assert "not re-verified" in rows[0]["source_note"].lower(), (
            "R5: the old-regime standard deduction must be flagged as not re-verified"
        )


def _engine_input(**over: Any) -> PayslipInput:
    """A one-component payslip input: the whole CTC is one BASIC line."""
    ctc = over.pop("ctc", Decimal("480000.00"))
    base: dict[str, Any] = {
        "ctc_annual": ctc,
        "components": [
            ComponentSpec(
                code="BASIC",
                name="Basic",
                type="earning",
                calculation_type="percentage",
                value=Decimal("100"),
                percentage_of="ctc",
            )
        ],
        "statutory": StatutoryConfigSpec(
            pf_enabled=False,
            esi_enabled=False,
            pt_enabled=False,
            tds_enabled=True,
            default_tax_regime="new",
        ),
        "pt_slabs": [],
        "tax_slabs": [],
        "month": 4,
        "year": 2030,
        "financial_year": "2030-2031",
        "working_days": Decimal("30"),
        "present_days": Decimal("30"),
        "paid_leave_days": Decimal("0"),
        "lop_days": Decimal("0"),
    }
    base.update(over)
    try:
        return PayslipInput(**base)
    except TypeError as exc:
        pytest.fail(f"R5: the engine input does not take the rate rows yet: {exc}")


def _flat_slab(rules: dict[str, Any] | None, cess: str = "4.000") -> TaxSlabSpec:
    return TaxSlabSpec(
        country="IN",
        financial_year="2030-2031",
        regime="new",
        min_income=Decimal("0.00"),
        max_income=None,
        rate_percent=Decimal("10.000"),
        cess_percent=Decimal(cess),
        surcharge_rules=rules,
    )


RULES = {
    "standard_deduction": "0.00",
    "rebate_87a": {"income_limit": "500000.00", "max_rebate": "30000.00"},
}


def _tds(out) -> str | None:
    found = [d.amount for d in out.deductions if d.code == "TDS"]
    return str(found[0]) if found else None


def test_R5_the_engine_has_no_rebate_deduction_or_cess_literals() -> None:
    source = Path(payslip_engine.__file__).read_text()
    assert "SECTION_87A" not in source, "R5: the SECTION_87A_* literals must be removed"
    assert not hasattr(payslip_engine, "SECTION_87A_NEW_REGIME_THRESHOLD")
    for literal in (
        'Decimal("75000',
        'Decimal("50000',
        'Decimal("4.000")',
        'Decimal("1200000',
        'Decimal("500000',
    ):
        assert literal not in source, f"R5: the engine still holds the literal {literal}"


def test_R5_the_rebate_limit_and_maximum_come_from_the_slab_row() -> None:
    # 480,000 a year at a flat 10% is 48,000; the row allows a rebate up to 30,000 on incomes
    # up to 500,000: tax 18,000 + 4% cess = 18,720, i.e. 1,560.00 a month.
    out = calculate_payslip(_engine_input(tax_slabs=[_flat_slab(RULES)]))
    assert _tds(out) == "1560.00", f"R5: rebate from the row: TDS {_tds(out)}"


def test_R5_above_the_rebate_limit_of_the_row_no_rebate_applies() -> None:
    rules = {**RULES, "rebate_87a": {"income_limit": "400000.00", "max_rebate": "30000.00"}}
    out = calculate_payslip(_engine_input(tax_slabs=[_flat_slab(rules)]))
    assert _tds(out) == "4160.00", f"R5: 48,000 + 4% cess = 49,920 a year: TDS {_tds(out)}"


def test_R5_the_standard_deduction_comes_from_the_slab_row() -> None:
    rules = {
        **RULES,
        "standard_deduction": "80000.00",
        "rebate_87a": {"income_limit": "0.00", "max_rebate": "0.00"},
    }
    out = calculate_payslip(_engine_input(tax_slabs=[_flat_slab(rules)]))
    assert _tds(out) == "3466.67", f"R5: (480,000-80,000) x 10% x 1.04 / 12: TDS {_tds(out)}"


def test_R5_the_cess_comes_from_the_slab_row() -> None:
    rules = {**RULES, "rebate_87a": {"income_limit": "0.00", "max_rebate": "0.00"}}
    out = calculate_payslip(_engine_input(tax_slabs=[_flat_slab(rules, cess="10.000")]))
    assert _tds(out) == "4400.00", f"R5: 48,000 x 1.10 / 12: TDS {_tds(out)}"


@pytest.mark.parametrize(
    "rules",
    [
        None,
        {"rebate_87a": {"income_limit": "1.00", "max_rebate": "1.00"}},
        {"standard_deduction": "0.00"},
    ],
    ids=["no rules", "no standard deduction", "no rebate"],
)
def test_R5_missing_slab_figures_fail_with_a_clear_error_never_a_literal(rules) -> None:
    with pytest.raises(AppError) as caught:
        calculate_payslip(_engine_input(tax_slabs=[_flat_slab(rules)]))
    assert caught.value.status_code == 409, f"R5: a missing figure must be a 409: {caught.value}"


def test_R5_no_tax_slab_rows_at_all_fail_instead_of_paying_no_tax() -> None:
    with pytest.raises(AppError) as caught:
        calculate_payslip(_engine_input(tax_slabs=[]))
    assert caught.value.status_code == 409, str(caught.value)


def _pf_input(ceiling: str, basic: str = "40000.00") -> PayslipInput:
    rate = _attr("app.modules.payroll.payslip_engine", "PfRateSpec")(
        employee_rate=Decimal("12.000"),
        employer_rate=Decimal("12.000"),
        wage_ceiling=Decimal(ceiling),
    )
    return _engine_input(
        ctc=Decimal(basic) * 12,
        statutory=StatutoryConfigSpec(
            pf_enabled=True, esi_enabled=False, pt_enabled=False, tds_enabled=False
        ),
        pf_rate=rate,
    )


@pytest.mark.parametrize("ceiling,expected", [("15000.00", "1800.00"), ("25000.00", "3000.00")])
def test_R5_pf_is_capped_at_the_ceiling_of_the_rate_row(ceiling, expected) -> None:
    out = calculate_payslip(_pf_input(ceiling))
    epf = [d.amount for d in out.deductions if d.code == "EPF_EE"]
    assert [str(x) for x in epf] == [expected], (
        f"R5: PF on a 40,000 basic with a {ceiling} row: {epf}"
    )


def test_R5_pf_without_a_rate_row_fails_instead_of_using_a_literal() -> None:
    with pytest.raises(AppError) as caught:
        calculate_payslip(
            _engine_input(
                statutory=StatutoryConfigSpec(
                    pf_enabled=True, esi_enabled=False, pt_enabled=False, tds_enabled=False
                )
            )
        )
    assert caught.value.status_code == 409, str(caught.value)


@pytest.mark.parametrize(
    "ceiling,applies", [("20000.00", False), ("21000.00", True), ("25000.00", True)]
)
def test_R5_esi_applies_only_within_the_ceiling_of_the_rate_row(ceiling, applies) -> None:
    rate = _attr("app.modules.payroll.payslip_engine", "EsiRateSpec")(
        employee_rate=Decimal("0.750"),
        employer_rate=Decimal("3.250"),
        wage_ceiling=Decimal(ceiling),
    )
    out = calculate_payslip(
        _engine_input(
            ctc=Decimal("21000.00") * 12,
            statutory=StatutoryConfigSpec(
                pf_enabled=False, esi_enabled=True, pt_enabled=False, tds_enabled=False
            ),
            esi_rate=rate,
        )
    )
    has = any(d.code == "ESI_EE" for d in out.deductions)
    assert has is applies, f"R5: gross 21,000 against a {ceiling} ceiling: ESI applied={has}"


def test_R5_company_config_defaults_no_longer_hold_rate_literals() -> None:
    service = Path(REPO_ROOT / "app/modules/payroll/service.py").read_text()
    assert "_DEFAULT_PF_" not in service and "_DEFAULT_ESI_" not in service, (
        "R5: the _DEFAULT_* rate literals must be removed from the service"
    )


# ------------------------------------------------------------------- R6


@pytest.mark.parametrize("field", ["employee_rate", "employer_rate"])
@pytest.mark.parametrize("value", ["-0.001", "100.001", "101", "abc", "", "1.0001"])
def test_R6_a_bad_rate_gives_422(client, super_admin_headers, field, value) -> None:
    resp = _post_rate(client, super_admin_headers, **{field: value})
    assert resp.status_code == 422, f"R6: {field} {value!r} must give 422: {resp.text}"
    assert field in _fields(resp), f"R6: the error must name {field}: {resp.text}"


@pytest.mark.parametrize("value", ["0", "0.000", "100.000", "12.345"])
def test_R6_rates_from_0_to_100_with_3_decimals_are_accepted(
    client, super_admin_headers, value
) -> None:
    assert _post_rate(client, super_admin_headers, employee_rate=value).status_code == 201


@pytest.mark.parametrize(
    "value", ["0", "0.00", "-1", "100000000.00", "99999999.995", "1000.001", "abc"]
)
def test_R6_a_bad_ceiling_gives_422(client, super_admin_headers, value) -> None:
    resp = _post_rate(client, super_admin_headers, wage_ceiling=value)
    assert resp.status_code == 422, f"R6: ceiling {value!r} must give 422: {resp.text}"
    assert "wage_ceiling" in _fields(resp)


@pytest.mark.parametrize("value", ["0.01", "99999999.99"])
def test_R6_ceilings_above_0_up_to_99999999_99_are_accepted(
    client, super_admin_headers, value
) -> None:
    assert _post_rate(client, super_admin_headers, wage_ceiling=value).status_code == 201


@pytest.mark.parametrize("start", ["1999-12-31", "2101-01-01", "not-a-date", ""])
def test_R6_an_effective_date_outside_2000_to_2100_gives_422(
    client, super_admin_headers, start
) -> None:
    resp = _post_rate(client, super_admin_headers, effective_from=start)
    assert resp.status_code == 422, f"R6: {start!r} must give 422: {resp.text}"
    assert "effective_from" in _fields(resp)


def test_R6_the_date_range_edges_are_allowed(client, db, super_admin_headers) -> None:
    _seed_all(db)
    last = _post_rate(client, super_admin_headers, effective_from="2100-12-31")
    assert last.status_code == 201, f"R6: 2100-12-31 is allowed: {last.text}"
    first = _post_rate(client, super_admin_headers, effective_from="2000-01-01")
    assert first.status_code != 422, f"R6: 2000-01-01 passes the date check: {first.text}"


@pytest.mark.parametrize("scheme", ["pf", "", None, "EPF"])
def test_R6_an_unknown_scheme_gives_422(client, super_admin_headers, scheme) -> None:
    assert _post_rate(client, super_admin_headers, scheme=scheme).status_code == 422


@pytest.mark.parametrize(
    "field",
    [
        "scheme",
        "employee_rate",
        "employer_rate",
        "wage_ceiling",
        "effective_from",
        "source_url",
        "source_title",
        "verified_on",
    ],
)
def test_R6_a_null_or_missing_required_field_gives_422(client, super_admin_headers, field) -> None:
    nulled = _post_rate(client, super_admin_headers, **{field: None})
    assert nulled.status_code == 422, f"R6: {field} null must give 422: {nulled.text}"
    body = _rate_body()
    del body[field]
    missing = client.post(RATES, json=body, headers=super_admin_headers)
    assert missing.status_code == 422 and field in _fields(missing), (
        f"R6: {field} missing: {missing.text}"
    )


@pytest.mark.parametrize(
    "extra", [{"company_id": "x"}, {"id": "x"}, {"effective_to": "2040-01-01"}, {"nonsense": 1}]
)
def test_R6_unknown_fields_give_422(client, super_admin_headers, extra) -> None:
    resp = client.post(RATES, json={**_rate_body(), **extra}, headers=super_admin_headers)
    assert resp.status_code == 422, f"R6: unknown field {list(extra)} must give 422: {resp.text}"


PT_CASES = {
    "empty": [],
    "does not start at zero": [
        {"income_min": "100.00", "income_max": None, "monthly_amount": "1.00"}
    ],
    "gap": [
        {"income_min": "0.00", "income_max": "5000.00", "monthly_amount": "0.00"},
        {"income_min": "6000.00", "income_max": None, "monthly_amount": "1.00"},
    ],
    "overlap": [
        {"income_min": "0.00", "income_max": "5000.00", "monthly_amount": "0.00"},
        {"income_min": "4000.00", "income_max": None, "monthly_amount": "1.00"},
    ],
    "last is not open": [{"income_min": "0.00", "income_max": "5000.00", "monthly_amount": "0.00"}],
    "max below min": [{"income_min": "10.00", "income_max": "5.00", "monthly_amount": "0.00"}],
    "open slab in the middle": [
        {"income_min": "0.00", "income_max": None, "monthly_amount": "0.00"},
        {"income_min": "5000.01", "income_max": None, "monthly_amount": "1.00"},
    ],
    "negative amount": [{"income_min": "0.00", "income_max": None, "monthly_amount": "-1.00"}],
    "amount too large": [
        {"income_min": "0.00", "income_max": None, "monthly_amount": "100000000.00"}
    ],
}


@pytest.mark.parametrize("case", list(PT_CASES))
def test_R6_a_bad_pt_slab_set_gives_422_and_saves_nothing(
    client, db, super_admin_headers, case
) -> None:
    _seed_all(db)
    resp = client.put(
        PT, json=_pt_body(slabs=PT_CASES[case], state="Kerala"), headers=super_admin_headers
    )
    assert resp.status_code == 422, f"R6: PT set ({case}) must give 422: {resp.text}"
    kerala = db.execute(text("SELECT count(*) FROM pt_slabs WHERE state = 'Kerala'")).scalar_one()
    assert kerala == 0, "R6: a refused set must save nothing"


def test_R6_pt_slabs_sent_out_of_order_are_accepted_when_they_fit(
    client, super_admin_headers
) -> None:
    slabs = [
        {"income_min": "5000.01", "income_max": None, "monthly_amount": "1.00"},
        {"income_min": "0.00", "income_max": "5000.00", "monthly_amount": "0.00"},
    ]
    resp = client.put(PT, json=_pt_body(slabs=slabs, state="Kerala"), headers=super_admin_headers)
    assert resp.status_code == 200, f"R6: order does not matter for a contiguous set: {resp.text}"


TAX_CASES = {
    "empty": [],
    "does not start at zero": [
        {"min_income": "100.00", "max_income": None, "rate_percent": "5.000"}
    ],
    "gap": [
        {"min_income": "0.00", "max_income": "400000.00", "rate_percent": "0.000"},
        {"min_income": "500000.00", "max_income": None, "rate_percent": "5.000"},
    ],
    "overlap": [
        {"min_income": "0.00", "max_income": "400000.00", "rate_percent": "0.000"},
        {"min_income": "300000.00", "max_income": None, "rate_percent": "5.000"},
    ],
    "last is not open": [
        {"min_income": "0.00", "max_income": "400000.00", "rate_percent": "0.000"}
    ],
    "max below min": [{"min_income": "10.00", "max_income": "5.00", "rate_percent": "0.000"}],
    "rate above 100": [{"min_income": "0.00", "max_income": None, "rate_percent": "100.001"}],
    "negative rate": [{"min_income": "0.00", "max_income": None, "rate_percent": "-1.000"}],
}


@pytest.mark.parametrize("case", list(TAX_CASES))
def test_R6_a_bad_tax_bracket_set_gives_422_and_saves_nothing(
    client, db, super_admin_headers, case
) -> None:
    resp = client.post(TAX, json=_tax_body(brackets=TAX_CASES[case]), headers=super_admin_headers)
    assert resp.status_code == 422, f"R6: tax set ({case}) must give 422: {resp.text}"
    count = db.execute(
        text("SELECT count(*) FROM tax_slabs WHERE financial_year = '2031-2032'")
    ).scalar_one()
    assert count == 0, "R6: a refused set must save nothing"


@pytest.mark.parametrize("value", ["-0.001", "100.001", "abc"])
def test_R6_a_bad_cess_gives_422(client, super_admin_headers, value) -> None:
    assert (
        client.post(
            TAX, json=_tax_body(cess_percent=value), headers=super_admin_headers
        ).status_code
        == 422
    )


@pytest.mark.parametrize("route", ["pt", "tax"])
@pytest.mark.parametrize("start", ["1999-12-31", "2101-01-01"])
def test_R6_pt_and_tax_dates_must_be_between_2000_and_2100(
    client, super_admin_headers, route, start
) -> None:
    resp = _write(client, super_admin_headers, route, effective_from=start)
    assert resp.status_code == 422, f"R6: {route} {start} must give 422: {resp.text}"


@pytest.mark.parametrize("route", ["pt", "tax"])
def test_R6_pt_and_tax_reject_unknown_fields_and_nulls(client, super_admin_headers, route) -> None:
    assert _write(client, super_admin_headers, route, nonsense=1).status_code == 422, (
        "unknown field"
    )
    required = "state" if route == "pt" else "financial_year"
    assert _write(client, super_admin_headers, route, **{required: None}).status_code == 422, "null"


# ------------------------------------------------------------------- R7


def _snapshot(db: Session) -> dict[str, list[tuple]]:
    out: dict[str, list[tuple]] = {}
    for table in ("statutory_rates", "pt_slabs", "tax_slabs"):
        columns = [
            c for c in _table_columns(db, table) if c not in ("id", "created_at", "updated_at")
        ]
        rows = db.execute(
            text(f"SELECT {', '.join(columns)} FROM {table} ORDER BY 1, 2, 3")
        ).fetchall()
        out[table] = [tuple(map(str, r)) for r in rows]
    return out


def test_R7_running_the_seeds_twice_gives_the_same_rows(db: Session) -> None:
    _seed_all(db)
    first = _snapshot(db)
    _seed_all(db)
    second = _snapshot(db)
    assert first == second, "R7: a second seed run changed the data"
    assert len(first["statutory_rates"]) == 3 and len(first["pt_slabs"]) == 2, {
        k: len(v) for k, v in first.items()
    }
    assert len(first["tax_slabs"]) == 22, (
        f"R7: 2 years x (7 + 4) brackets: {len(first['tax_slabs'])}"
    )


def test_R7_a_seed_restores_a_drifted_row_by_key_and_adds_no_duplicate(db: Session) -> None:
    _seed_all(db)
    db.execute(
        text(
            "UPDATE statutory_rates SET wage_ceiling = 99999 "
            "WHERE scheme = 'epf' AND effective_from = '2026-09-17'"
        )
    )
    db.execute(text("UPDATE pt_slabs SET monthly_amount = 1 WHERE income_min = 12000.01"))
    db.execute(
        text(
            "UPDATE tax_slabs SET rate_percent = 99 "
            "WHERE financial_year = '2026-2027' AND min_income = 0"
        )
    )
    db.flush()
    before_counts = {k: len(v) for k, v in _snapshot(db).items()}
    _seed_all(db)
    snap = _snapshot(db)
    assert {k: len(v) for k, v in snap.items()} == before_counts, "R7: reseeding must not add rows"
    ceilings = db.execute(
        text(
            "SELECT wage_ceiling::text FROM statutory_rates "
            "WHERE scheme = 'epf' AND effective_from = '2026-09-17'"
        )
    ).scalar_one()
    assert ceilings == "25000.00", f"R7: the seed must restore the official ceiling: {ceilings}"
    assert (
        db.execute(
            text("SELECT monthly_amount::text FROM pt_slabs WHERE income_min = 12000.01")
        ).scalar_one()
        == "200.00"
    )


def test_R7_a_rate_row_with_a_bad_host_or_no_source_makes_the_seed_raise(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _need("app.db.seed.statutory_rates")
    rows = list(getattr(module, "RATE_ROWS", None) or [])
    assert rows, "R7: the seed module needs a RATE_ROWS list"
    bad_host = [{**rows[0], "source_url": "https://taxguru.in/x"}]
    monkeypatch.setattr(module, "RATE_ROWS", bad_host)
    with pytest.raises(Exception):  # noqa: B017
        module.seed_statutory_rates(db)
    db.rollback()
    no_source = {k: v for k, v in rows[0].items() if k != "source_url"}
    monkeypatch.setattr(module, "RATE_ROWS", [no_source])
    with pytest.raises(Exception):  # noqa: B017
        module.seed_statutory_rates(db)
    db.rollback()


def test_R7_a_pt_row_with_a_bad_host_makes_the_seed_raise(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.seed import pt_slabs

    rows = list(pt_slabs.GUJARAT_SLABS)
    assert "source_url" in rows[0], "R7: PT seed rows must carry source_url"
    monkeypatch.setattr(
        pt_slabs, "GUJARAT_SLABS", [{**rows[0], "source_url": "https://taxguru.in/x"}]
    )
    with pytest.raises(Exception):  # noqa: B017
        pt_slabs.seed_pt_slabs(db)
    db.rollback()


def test_R7_a_tax_row_with_a_bad_host_makes_the_seed_raise(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.seed import tax_slabs

    rows = tax_slabs._rows()
    assert "source_url" in rows[0], "R7: tax seed rows must carry source_url"
    monkeypatch.setattr(
        tax_slabs, "_rows", lambda: [{**rows[0], "source_url": "https://evil.com/x"}]
    )
    with pytest.raises(Exception):  # noqa: B017
        tax_slabs.seed_tax_slabs(db)
    db.rollback()


def test_R7_the_new_seed_can_be_run_directly_like_the_others() -> None:
    path = REPO_ROOT / "app/db/seed/statutory_rates.py"
    assert path.exists(), "R7: app/db/seed/statutory_rates.py is missing"
    assert 'if __name__ == "__main__"' in path.read_text(), "R7: must be runnable with python -m"


# ------------------------------------------------------------------- R8


def test_R8_adding_a_rate_writes_one_audit_row_with_ids_and_names_only(
    client, db, super_admin_headers
) -> None:
    _seed_all(db)
    created = _post_rate(client, super_admin_headers, source_note="private note text").json()
    rows = _audit(db, "STATUTORY_RATE_ADDED")
    assert len(rows) == 1, f"R8: one add must write one audit row, got {len(rows)}"
    row = rows[0]
    assert row.entity_type == "statutory_rate" and str(row.entity_id) == created["id"], row
    assert row.details["scheme"] == "esi", row.details
    shown = str(row.details)
    for secret in ("private note text", "esic.gov.in", "ESIC contribution rates"):
        assert secret not in shown, f"R8: the audit row holds {secret}"


def test_R8_adding_a_pt_set_writes_one_audit_row(client, db, super_admin_headers) -> None:
    _seed_all(db)
    resp = client.put(PT, json=_pt_body(source_note="private pt note"), headers=super_admin_headers)
    assert resp.status_code == 200, resp.text
    rows = _audit(db, "PT_SLAB_SET_ADDED")
    assert len(rows) == 1, f"R8: one PT set must write one audit row, got {len(rows)}"
    assert rows[0].details["state"] == "Gujarat", rows[0].details
    assert "private pt note" not in str(rows[0].details) and "gov.in" not in str(rows[0].details)


def test_R8_adding_a_tax_set_writes_one_audit_row(client, db, super_admin_headers) -> None:
    resp = client.post(
        TAX, json=_tax_body(source_note="private tax note"), headers=super_admin_headers
    )
    assert resp.status_code == 201, resp.text
    rows = _audit(db, "TAX_SLAB_SET_ADDED")
    assert len(rows) == 1, f"R8: one tax set must write one audit row, got {len(rows)}"
    assert rows[0].details["regime"] == "new" and rows[0].details["financial_year"] == "2031-2032"
    assert "private tax note" not in str(rows[0].details) and "gov.in" not in str(rows[0].details)


def test_R8_refused_writes_write_no_audit_row(client, db, hr, super_admin_headers) -> None:
    _seed_all(db)
    _post_rate(client, hr)
    _post_rate(client, super_admin_headers, source_url="https://evil.com/x")
    _post_rate(client, super_admin_headers, effective_from="2019-07-01")
    client.put(PT, json=_pt_body(slabs=[]), headers=super_admin_headers)
    client.post(TAX, json=_tax_body(brackets=[]), headers=super_admin_headers)
    for action in ("STATUTORY_RATE_ADDED", "PT_SLAB_SET_ADDED", "TAX_SLAB_SET_ADDED"):
        assert _audit(db, action) == [], f"R8: a refused request wrote {action}"


def test_R8_the_rate_and_its_audit_row_are_one_save(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_cls = _attr("app.modules.payroll.service", "StatutoryRateService")
    schemas = _need("app.modules.payroll.schemas")
    request = schemas.StatutoryRateCreateRequest(**_rate_body())
    actor = User(
        id=uuid.uuid4(), company_id=uuid.uuid4(), email="x@example.com", role=UserRole.super_admin
    )

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit failed")

    monkeypatch.setattr(AuditService, "record", _boom)
    _seed_all(db)
    with pytest.raises(RuntimeError):
        service_cls(db).add_rate(request, actor)
    db.rollback()
    left = db.execute(
        text("SELECT count(*) FROM statutory_rates WHERE source_title = 'ESIC contribution rates'")
    ).scalar_one()
    assert left == 0, "R8: the rate was saved although its audit row failed"


def test_R8_adding_a_rate_is_limited_to_30_per_minute(
    client, db, super_admin_headers, limits_on
) -> None:
    _seed_all(db)
    codes = [
        _post_rate(client, super_admin_headers, effective_from="2019-07-01").status_code
        for _ in range(31)
    ]
    assert codes[:30] == [409] * 30 and codes[30] == 429, f"R8: write limit wrong: {codes[-3:]}"


def test_R8_reading_rates_is_limited_to_60_per_minute_per_user(
    client, db, hr, company_a, limits_on
) -> None:
    codes = [_list_rates(client, hr).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429, f"R8: read limit wrong: {codes[-3:]}"
    other = _make_user_headers(db, company_a.company_id, UserRole.owner)
    assert _list_rates(client, other).status_code == 200, "R8: the limit is per user"


# ------------------------------------------------------------------- R9


def _config_without_rates(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    body = client.get(CONFIG, headers=headers).json()
    body.pop("effective_rates", None)
    return body


def test_R9_a_platform_rate_change_leaves_every_company_setting_alone(
    client, db, company_a, company_b, super_admin_headers
) -> None:
    _seed_all(db)
    one = client.put(
        CONFIG,
        json={
            "pf_enabled": False,
            "pt_state": "Gujarat",
            "default_tax_regime": "old",
            "payout_bank_name": "HDFC Bank",
            "payout_account_number": "123456789012",
            "payout_ifsc_code": "HDFC0001234",
            "payout_enabled": True,
        },
        headers=company_a.hr_headers,
    )
    assert one.status_code == 200, one.text
    two = client.put(
        CONFIG,
        json={"esi_enabled": False, "default_tax_regime": "new"},
        headers=company_b.hr_headers,
    )
    assert two.status_code == 200, two.text
    before = (
        _config_without_rates(client, company_a.hr_headers),
        _config_without_rates(client, company_b.hr_headers),
    )
    assert (
        _post_rate(client, super_admin_headers, effective_from=_first_of(2).isoformat()).status_code
        == 201
    )
    assert client.put(PT, json=_pt_body(), headers=super_admin_headers).status_code == 200
    after = (
        _config_without_rates(client, company_a.hr_headers),
        _config_without_rates(client, company_b.hr_headers),
    )
    assert after == before, "R9: a platform rate change altered a company's settings"
    rates_after = client.get(CONFIG, headers=company_a.hr_headers).json()["effective_rates"]
    assert any(r["scheme"] == "esi" and r["employee_rate"] == "1.000" for r in rates_after), (
        "R9: both companies see the new platform rate through effective_rates"
    )


def test_R9_a_platform_rate_change_never_reaches_an_approved_run(
    client, db, rworld, super_admin_headers
) -> None:
    w = rworld
    year, month = _month_back(3)
    run = _make_run(client, w["hr"], year, month)
    assert client.post(f"{RUNS}/{run['id']}/approve", headers=w["owner"]).status_code == 200
    before = client.get(f"{RUNS}/{run['id']}", headers=w["hr"]).json()
    assert (
        _post_rate(client, super_admin_headers, effective_from=_first_of(4).isoformat()).status_code
        == 201
    )
    assert (
        _post_rate(
            client,
            super_admin_headers,
            scheme="epf",
            effective_from="2099-01-01",
            wage_ceiling="50000.00",
        ).status_code
        == 201
    )
    after = client.get(f"{RUNS}/{run['id']}", headers=w["hr"]).json()
    assert after == before, "R9: an approved run changed after a platform rate change"


# ------------------------------------------------------------------- R10


def test_R10_every_rule_from_1_to_9_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_R")]
    for rule in range(1, 10):
        assert any(n.startswith(f"test_R{rule}_") for n in names), f"R10: no test for rule {rule}"
    assert Path(__file__).name == "test_5_2_statutory_rates.py"
