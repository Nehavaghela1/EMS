"""Module 5, sub-feature 5.2 (regions): one country and state list, always chosen, never typed.
One test per rule line (C1..C8).

The list lives in app/core/regions.py. The holiday code reads the same data. A company's
country decides which payroll rules apply; a country is payroll-ready only when its statutory
tables hold official rows. There is no silent Gujarat any more.
"""

import importlib
import importlib.util
import uuid
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
from app.core.rate_limit import limiter
from app.db.rls import bind_tenant_to_session
from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.statutory_rates import seed_statutory_rates
from app.db.seed.tax_slabs import seed_tax_slabs
from app.modules.identity.models import Company, UserRole
from tests.conftest import REPO_ROOT, TenantContext
from tests.rules.test_5_2_statutory_rates import _pt_body, _rate_body
from tests.rules.test_5_4_payroll_runs import (
    RUNS,
    _extra_user,
    _fill,
    _month_back,
    _post_run,
    _staff,
    _structure,
)

P = "/api/v1/payroll"
CONFIG = f"{P}/statutory-config"
REGIONS = "/api/v1/regions"
ALLOWED = "AE, AU, CA, GB, IN, SG, US"


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


def _message(resp) -> str:
    body = resp.json() if resp.content else {}
    error = body.get("error") if isinstance(body, dict) else None
    return error["message"] if isinstance(error, dict) else resp.text


def _details(resp) -> dict[str, Any]:
    return (resp.json().get("error") or {}).get("details") or {}


def _set_country(db: Session, ctx: TenantContext, country: str) -> None:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=True)
    company = db.get(Company, ctx.company_id)
    assert company is not None
    company.country = country
    db.commit()


def _regions_module() -> Any:
    assert importlib.util.find_spec("app.core.regions") is not None, (
        "C1: the shared module app/core/regions.py does not exist yet"
    )
    return importlib.import_module("app.core.regions")


# ------------------------------------------------------------------- C1


def test_C1_the_list_lives_in_one_shared_module_and_the_holiday_code_reads_it() -> None:
    regions = _regions_module()
    shared = getattr(regions, "COUNTRY_REGIONS_MAP", None)
    assert shared is not None, "C1: app/core/regions.py needs COUNTRY_REGIONS_MAP"
    constants = importlib.import_module("app.modules.time_leave.constants")
    own = getattr(constants, "COUNTRY_REGIONS_MAP", shared)
    assert own is shared, "C1: time_leave/constants.py must not keep a second copy of the list"
    service = importlib.import_module("app.modules.time_leave.service")
    assert service.HolidayService.supported_regions() is shared, (
        "C1: the holiday code must serve the shared list"
    )


def test_C1_get_regions_lists_each_country_for_any_logged_in_user(
    client: TestClient, company_a: TenantContext
) -> None:
    assert client.get(REGIONS).status_code == 401, "C1: no login gives 401"
    for headers in (company_a.employee_headers, company_a.manager_headers, company_a.hr_headers):
        resp = client.get(REGIONS, headers=headers)
        assert resp.status_code == 200, f"C1: any logged-in user may read it: {resp.text}"
    countries = {c["code"]: c for c in resp.json()}
    assert sorted(countries) == ["AE", "AU", "CA", "GB", "IN", "SG", "US"], sorted(countries)
    for entry in countries.values():
        assert set(entry) == {"code", "name", "payroll_ready", "states"}, set(entry)
    assert countries["IN"]["name"] == "India" and "Gujarat" in countries["IN"]["states"]
    assert len(countries["IN"]["states"]) == 36, "C1: 28 states and 8 union territories"


def test_C1_holidays_regions_keeps_working_from_the_same_data(
    client: TestClient, company_a: TenantContext
) -> None:
    holiday = client.get("/api/v1/holidays/regions", headers=company_a.hr_headers)
    regions = client.get(REGIONS, headers=company_a.hr_headers)
    assert holiday.status_code == 200, holiday.text
    for entry in regions.json():
        old = holiday.json()[entry["code"]]
        assert old["name"] == entry["name"] and old["states"] == entry["states"], (
            f"C1: the two routes disagree on {entry['code']}"
        )


def test_C1_regions_are_limited_to_60_per_minute(
    client: TestClient, company_a: TenantContext, limits_on: None
) -> None:
    codes = [client.get(REGIONS, headers=company_a.hr_headers).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429, f"C1: limit wrong: {codes[-3:]}"


# ------------------------------------------------------------------- C2


def test_C2_only_india_is_payroll_ready_and_the_flag_comes_from_the_constant(
    client: TestClient, company_a: TenantContext
) -> None:
    regions = _regions_module()
    ready = getattr(regions, "PAYROLL_READY_COUNTRIES", None)
    assert ready == {"IN"}, f"C2: PAYROLL_READY_COUNTRIES must be {{'IN'}}, got {ready}"
    flags = {
        c["code"]: c["payroll_ready"]
        for c in client.get(REGIONS, headers=company_a.hr_headers).json()
    }
    assert flags == {
        "IN": True,
        "US": False,
        "GB": False,
        "AE": False,
        "SG": False,
        "CA": False,
        "AU": False,
    }, flags


# ------------------------------------------------------------------- C3


def _register(client: TestClient, country: Any) -> Any:
    return client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Region Co",
            "company_email": f"reg-{uuid.uuid4().hex[:8]}@example.com",
            "password": "ValidPassword123!",
            "country": country,
        },
    )


@pytest.mark.parametrize("country", ["ZZ", "India", "XX", "", "I1", "USA"])
def test_C3_registration_refuses_an_unknown_country_and_lists_the_allowed_codes(
    client: TestClient, country: str
) -> None:
    resp = _register(client, country)
    assert resp.status_code == 422, f"C3: {country!r} must give 422, got {resp.status_code}"
    assert ALLOWED in resp.text, f"C3: the allowed codes must be listed: {resp.text}"


def test_C3_registration_accepts_a_listed_country_in_any_case_and_stores_upper_case(
    client: TestClient,
) -> None:
    resp = _register(client, "gb")
    assert resp.status_code == 201, resp.text
    assert resp.json().get("country", "GB") == "GB"


def test_C3_the_platform_admin_edit_and_workspace_creation_use_the_same_list(
    client: TestClient,
    company_a: TenantContext,
    super_admin_headers: dict[str, str],
) -> None:
    edit = client.put(
        f"/api/v1/companies/{company_a.company_id}",
        json={"country": "ZZ"},
        headers=super_admin_headers,
    )
    assert edit.status_code == 422 and ALLOWED in edit.text, f"C3: admin edit: {edit.text}"
    workspace = client.post(
        "/api/v1/companies/workspaces",
        json={
            "company_name": "WS Region Co",
            "company_email": f"ws-{uuid.uuid4().hex[:8]}@example.com",
            "country": "ZZ",
        },
        headers=company_a.hr_headers,
    )
    assert workspace.status_code == 422 and ALLOWED in workspace.text, (
        f"C3: workspace creation: {workspace.text}"
    )
    ok = client.put(
        f"/api/v1/companies/{company_a.company_id}",
        json={"country": "us"},
        headers=super_admin_headers,
    )
    assert ok.status_code == 200, f"C3: a listed country is accepted: {ok.text}"


# ------------------------------------------------------------------- C4


def test_C4_pt_state_is_matched_to_the_canonical_spelling(
    client: TestClient, company_a: TenantContext
) -> None:
    resp = client.put(CONFIG, json={"pt_state": "  guJARat "}, headers=company_a.hr_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["pt_state"] == "Gujarat", f"C4: canonical spelling: {resp.text}"


def test_C4_an_unknown_state_or_a_state_of_another_country_gives_422_on_pt_state(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    bad = client.put(CONFIG, json={"pt_state": "Atlantis"}, headers=company_a.hr_headers)
    assert bad.status_code == 422 and _details(bad).get("field") == "pt_state", bad.text
    _set_country(db, company_a, "US")
    other = client.put(CONFIG, json={"pt_state": "Gujarat"}, headers=company_a.hr_headers)
    assert other.status_code == 422 and _details(other).get("field") == "pt_state", (
        f"C4: Gujarat is not a US state: {other.text}"
    )
    fine = client.put(CONFIG, json={"pt_state": "texas"}, headers=company_a.hr_headers)
    assert fine.status_code == 200 and fine.json()["pt_state"] == "Texas", fine.text


def test_C4_pt_enabled_with_no_state_gives_422_but_untouched_settings_still_save(
    client: TestClient, company_a: TenantContext
) -> None:
    other = client.put(CONFIG, json={"pf_enabled": False}, headers=company_a.hr_headers)
    assert other.status_code == 200, f"C4: other settings must still save: {other.text}"
    enable = client.put(CONFIG, json={"pt_enabled": True}, headers=company_a.hr_headers)
    assert enable.status_code == 422 and _details(enable).get("field") == "pt_state", enable.text
    both = client.put(
        CONFIG, json={"pt_enabled": True, "pt_state": "Gujarat"}, headers=company_a.hr_headers
    )
    assert both.status_code == 200, both.text
    cleared = client.put(CONFIG, json={"pt_state": None}, headers=company_a.hr_headers)
    assert cleared.status_code == 422, f"C4: PT on and the state removed gives 422: {cleared.text}"
    off = client.put(
        CONFIG, json={"pt_enabled": False, "pt_state": None}, headers=company_a.hr_headers
    )
    assert off.status_code == 200, f"C4: PT off needs no state: {off.text}"


def test_C4_the_pt_slab_write_route_checks_state_and_country_the_same_way(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    lower = client.put(f"{P}/pt-slabs", json=_pt_body(state="gujarat"), headers=super_admin_headers)
    assert lower.status_code == 200, lower.text
    assert lower.json()[0]["state"] == "Gujarat", f"C4: canonical spelling stored: {lower.text}"
    unknown = client.put(
        f"{P}/pt-slabs", json=_pt_body(state="Atlantis"), headers=super_admin_headers
    )
    assert unknown.status_code == 422 and _details(unknown).get("field") == "state", unknown.text
    bad_country = client.put(
        f"{P}/pt-slabs", json=_pt_body(country="ZZ"), headers=super_admin_headers
    )
    assert bad_country.status_code == 422 and _details(bad_country).get("field") == "country"
    wrong_pair = client.put(
        f"{P}/pt-slabs", json=_pt_body(country="US", state="Gujarat"), headers=super_admin_headers
    )
    assert wrong_pair.status_code == 422, f"C4: Gujarat is not in the US: {wrong_pair.text}"


def test_C4_the_configs_country_is_the_companys_country(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    assert client.get(CONFIG, headers=company_a.hr_headers).json()["country"] == "IN"
    _set_country(db, company_a, "GB")
    assert client.get(CONFIG, headers=company_a.hr_headers).json()["country"] == "GB", (
        "C4: the company's country is the single source for which payroll rules apply"
    )


# ------------------------------------------------------------------- C5


def _payroll_company(client: TestClient, db: Session, ctx: TenantContext) -> tuple[int, int]:
    year, month = _month_back()
    structure_id = _structure(client, ctx.hr_headers)
    emp = _staff(client, db, ctx, structure_id)
    _fill(db, ctx, emp["id"], year, month)
    return year, month


def test_C5_pt_on_with_no_state_stops_the_run_with_409_and_creates_no_run(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    year, month = _payroll_company(client, db, company_a)
    resp = _post_run(client, company_a.hr_headers, year, month)
    assert resp.status_code == 409, f"C5: no state must give 409, got {resp.status_code}"
    assert "professional-tax state" in _message(resp), f"C5: unclear message: {_message(resp)}"
    runs = client.get(RUNS, headers=company_a.hr_headers).json()
    assert runs["total"] == 0, "C5: a refused run must leave no run row"


def test_C5_a_state_with_no_slab_rows_in_force_keeps_the_existing_409(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    year, month = _payroll_company(client, db, company_a)
    assert (
        client.put(CONFIG, json={"pt_state": "Karnataka"}, headers=company_a.hr_headers).status_code
        == 200
    )
    resp = _post_run(client, company_a.hr_headers, year, month)
    assert resp.status_code == 409, resp.text
    assert "No professional-tax slabs for Karnataka are in force on" in _message(resp), (
        f"C5: the existing message must stay: {_message(resp)}"
    )
    assert (
        client.put(CONFIG, json={"pt_state": "Gujarat"}, headers=company_a.hr_headers).status_code
        == 200
    )
    ok = _post_run(client, company_a.hr_headers, year, month)
    assert ok.status_code == 202, f"C5: a state with slabs works: {ok.text}"


def test_C5_pt_off_needs_no_state(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    year, month = _payroll_company(client, db, company_a)
    assert (
        client.put(CONFIG, json={"pt_enabled": False}, headers=company_a.hr_headers).status_code
        == 200
    )
    assert _post_run(client, company_a.hr_headers, year, month).status_code == 202


def test_C5_the_engine_default_and_the_slab_list_have_no_hidden_gujarat(
    client: TestClient, company_a: TenantContext
) -> None:
    from app.modules.payroll.payslip_engine import StatutoryConfigSpec

    assert StatutoryConfigSpec().pt_state is None, "C5: the engine must not default to Gujarat"
    empty = client.get(f"{P}/pt-slabs", headers=company_a.hr_headers)
    assert empty.status_code == 200 and empty.json() == [], (
        f"C5: no state means no slabs listed, not Gujarat's: {empty.text}"
    )
    assert (
        client.put(CONFIG, json={"pt_state": "Gujarat"}, headers=company_a.hr_headers).status_code
        == 200
    )
    listed = client.get(f"{P}/pt-slabs", headers=company_a.hr_headers).json()
    assert listed and {s["state"] for s in listed} == {"Gujarat"}, listed


# ------------------------------------------------------------------- C6


def test_C6_both_tables_have_a_country_column_that_is_not_null_and_defaults_to_india(
    db: Session,
) -> None:
    for table in ("statutory_rates", "pt_slabs"):
        columns = {c["name"]: c for c in inspect(db.get_bind()).get_columns(table)}
        assert "country" in columns, f"C6: {table}.country is missing"
        assert columns["country"]["nullable"] is False, f"C6: {table}.country must be NOT NULL"
        assert "IN" in str(columns["country"]["default"]), f"C6: {table}.country default IN"


def _need_country_columns(db: Session) -> None:
    for table in ("statutory_rates", "pt_slabs"):
        names = {c["name"] for c in inspect(db.get_bind()).get_columns(table)}
        assert "country" in names, f"C6: {table}.country is missing"


def test_C6_seeded_rows_are_india(db: Session) -> None:
    _need_country_columns(db)
    for table in ("statutory_rates", "pt_slabs"):
        countries = {r[0] for r in db.execute(text(f"SELECT DISTINCT country FROM {table}"))}  # noqa: S608
        assert countries == {"IN"}, f"C6: seeded {table} rows must be IN: {countries}"


def test_C6_the_overlap_constraints_include_the_country(db: Session) -> None:
    _need_country_columns(db)

    def _epf(country: str, start: str, end: str | None) -> None:
        db.execute(
            text(
                "INSERT INTO statutory_rates (id, country, scheme, employee_rate, employer_rate, "
                "wage_ceiling, effective_from, effective_to, source_url, source_title, "
                "verified_on) VALUES (:i, :c, 'epf', 1, 1, 1, :f, :t, 'https://x.gov.in', 't', "
                "current_date)"
            ),
            {"i": uuid.uuid4(), "c": country, "f": start, "t": end},
        )

    _epf("GB", "2090-01-01", None)
    _epf("US", "2090-01-01", None)  # another country, same dates: allowed
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            _epf("GB", "2090-06-01", None)  # same country, overlapping: refused
    db.rollback()


def test_C6_the_write_routes_take_a_country_and_lookups_stay_per_country(
    client: TestClient, db: Session, super_admin_headers: dict[str, str], company_a: TenantContext
) -> None:
    gb = client.post(
        f"{P}/statutory-rates",
        json=_rate_body(country="GB", scheme="epf", effective_from="2030-01-01"),
        headers=super_admin_headers,
    )
    assert gb.status_code == 201 and gb.json()["country"] == "GB", f"C6: {gb.text}"
    unknown = client.post(
        f"{P}/statutory-rates",
        json=_rate_body(country="ZZ"),
        headers=super_admin_headers,
    )
    assert unknown.status_code == 422, f"C6: unknown country gives 422: {unknown.status_code}"
    default = client.post(
        f"{P}/statutory-rates",
        json=_rate_body(effective_from="2030-02-01"),
        headers=super_admin_headers,
    )
    assert default.status_code == 201 and default.json()["country"] == "IN", default.text
    india = client.get(f"{P}/statutory-rates?country=IN&scheme=epf", headers=super_admin_headers)
    assert all(r["country"] == "IN" for r in india.json()["items"]), "C6: list filters by country"
    both = client.get(f"{P}/statutory-rates?scheme=epf", headers=super_admin_headers)
    assert {"GB", "IN"} <= {r["country"] for r in both.json()["items"]}


def _cfg() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


def _regions_revision() -> Any:
    script = ScriptDirectory.from_config(_cfg())
    for revision in script.walk_revisions():
        if "country on statutory_rates and pt_slabs" in (revision.doc or ""):
            return revision
    pytest.fail("C6: the migration 'country on statutory_rates and pt_slabs' does not exist yet")


def _owner_engine():
    assert settings.TEST_MIGRATION_URL is not None
    return create_engine(settings.TEST_MIGRATION_URL)


def _old_pt(conn: Any, state: str) -> None:
    conn.execute(
        text(
            "INSERT INTO pt_slabs (id, state, income_min, income_max, monthly_amount, "
            "effective_from, effective_to, source_url, source_title, verified_on) "
            "VALUES (:i, :s, 0, NULL, 0, '2022-04-01', NULL, 'https://x.gov.in', 't', "
            "current_date)"
        ),
        {"i": uuid.uuid4(), "s": state},
    )


def _old_company_config(conn: Any, cid: uuid.UUID, pt_state: str | None) -> None:
    conn.execute(
        text(
            "INSERT INTO companies (id, name, code, email, status, country, currency, "
            "last_employee_seq, created_at, updated_at) VALUES (:c, 'Region Mig Co', :code, "
            ":email, 'active', 'IN', 'INR', 0, now(), now())"
        ),
        {"c": cid, "code": f"RMC{cid.hex[:5].upper()}", "email": f"rmc-{cid.hex[:6]}@example.test"},
    )
    conn.execute(
        text(
            "INSERT INTO statutory_configs (id, company_id, country, pf_enabled, "
            "pf_restrict_to_ceiling, esi_enabled, pt_enabled, pt_state, lwf_enabled, "
            "tds_enabled, default_tax_regime, payout_enabled) VALUES (:i, :c, 'IN', true, true, "
            "true, true, :s, false, true, 'new', false)"
        ),
        {"i": uuid.uuid4(), "c": cid, "s": pt_state},
    )


def _purge(engine: Any, cid: uuid.UUID) -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
        conn.execute(text("DELETE FROM statutory_configs WHERE company_id = :c"), {"c": cid})
        conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": cid})
        conn.execute(text("DELETE FROM pt_slabs"))


def test_C6_the_migration_backfills_india_normalizes_states_and_round_trips() -> None:
    revision = _regions_revision()
    cid = uuid.uuid4()
    engine = _owner_engine()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        try:
            command.downgrade(cfg, revision.down_revision)
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
                conn.execute(text("DELETE FROM pt_slabs"))
                _old_pt(conn, "gujarat")
                _old_company_config(conn, cid, "KARNATAKA")
            command.upgrade(cfg, revision.revision)
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
                slab = conn.execute(text("SELECT state, country FROM pt_slabs")).one()
                state = conn.execute(
                    text("SELECT pt_state FROM statutory_configs WHERE company_id = :c"),
                    {"c": cid},
                ).scalar_one()
                rate_countries = {
                    r[0] for r in conn.execute(text("SELECT DISTINCT country FROM statutory_rates"))
                }
            assert tuple(slab) == ("Gujarat", "IN"), f"C6: normalized and backfilled: {slab}"
            assert state == "Karnataka", f"C6: pt_state normalized: {state}"
            assert rate_countries <= {"IN"}, f"C6: statutory_rates backfilled IN: {rate_countries}"
            command.downgrade(cfg, revision.down_revision)
            for table in ("pt_slabs", "statutory_rates"):
                names = {c["name"] for c in inspect(engine).get_columns(table)}
                assert "country" not in names, f"C6: downgrade must remove {table}.country"
        finally:
            _purge(engine, cid)
            command.upgrade(cfg, "head")
            engine.dispose()


def test_C6_the_migration_stops_and_lists_values_that_match_no_state() -> None:
    revision = _regions_revision()
    cid = uuid.uuid4()
    engine = _owner_engine()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        try:
            command.downgrade(cfg, revision.down_revision)
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
                conn.execute(text("DELETE FROM pt_slabs"))
                _old_pt(conn, "Atlantis")
                _old_pt(conn, "Atlantis")
                _old_company_config(conn, cid, "Narnia")
            with pytest.raises(RuntimeError) as caught:
                command.upgrade(cfg, revision.revision)
            message = str(caught.value)
            assert "Atlantis" in message and "Narnia" in message, f"C6: unclear: {message}"
            assert message.count("Atlantis") == 1, f"C6: distinct values only: {message}"
            names = {c["name"] for c in inspect(engine).get_columns("pt_slabs")}
            assert "country" not in names, "C6: a failed migration must change nothing"
        finally:
            _purge(engine, cid)
            command.upgrade(cfg, "head")
            engine.dispose()


def test_C6_seeds_set_the_country(db: Session) -> None:
    from app.db.seed import pt_slabs, statutory_rates

    for module in (pt_slabs, statutory_rates):
        assert "country" in open(module.__file__).read(), f"C6: {module.__name__} must set country"


# ------------------------------------------------------------------- C7


def test_C7_a_run_for_a_country_that_is_not_payroll_ready_gives_409_and_no_run(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    year, month = _payroll_company(client, db, company_a)
    assert (
        client.put(CONFIG, json={"pt_state": "Gujarat"}, headers=company_a.hr_headers).status_code
        == 200
    )
    _set_country(db, company_a, "US")
    resp = _post_run(client, company_a.hr_headers, year, month)
    assert resp.status_code == 409, f"C7: a US company must get 409, got {resp.status_code}"
    assert _message(resp) == "Payroll rules for United States are not available yet", (
        f"C7: message: {_message(resp)}"
    )
    assert client.get(RUNS, headers=company_a.hr_headers).json()["total"] == 0
    _set_country(db, company_a, "IN")
    owner, _ = _extra_user(db, company_a.company_id, UserRole.owner)
    assert owner and _post_run(client, company_a.hr_headers, year, month).status_code == 202, (
        "C7: an Indian company is unaffected"
    )


# ------------------------------------------------------------------- C8


def test_C8_every_rule_from_1_to_7_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_C")]
    for rule in range(1, 8):
        assert any(n.startswith(f"test_C{rule}_") for n in names), f"C8: no test for rule {rule}"
