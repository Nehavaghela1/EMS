# ruff: noqa: F811
"""Module 5, sub-feature 5.1: Salary structures. One test per rule line (R1..R10).

Dates that a rule compares with today are computed from utcnow(). Companies use the shared
`company_a` / `company_b` fixtures (unique codes); the race test builds its own company.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
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
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.identity.models import Company, CompanySettings, CompanyStatus, User, UserRole
from app.modules.payroll.models import PayrollRun, PayrollRunStatus, SalaryStructure
from app.modules.platform.models import AuditLog
from app.modules.platform.service import AuditService
from tests.conftest import TenantContext
from tests.rules.test_5_4_payroll_runs import (  # noqa: F401
    PAYSLIPS,
    RUNS,
    _audit,
    _extra_user,
    _fill,
    _make_run,
    _month_back,
    _seed_statutory,
    _staff,
    limits_on,
    world,
)

S = "/api/v1/payroll/structures"
E = "/api/v1/payroll/employees"


# ---------------------------------------------------------------- helpers


def _c(
    code: str,
    calc: str = "fixed",
    value: str | None = "1000.00",
    of: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": code,
        "name": f"{code} pay",
        "type": "earning",
        "calculation_type": calc,
        "display_order": 0,
    }
    if calc in ("fixed", "percentage") and value is not None:
        body["value"] = value
    if calc == "percentage":
        body["percentage_of"] = of or "ctc"
    body.update(extra)
    return body


def _std() -> list[dict[str, Any]]:
    return [
        _c("BASIC", "percentage", "50.00", "ctc", display_order=1),
        _c("HRA", "percentage", "40.00", "basic", display_order=2),
        _c("SPECIAL", "balance", display_order=3),
    ]


def _name() -> str:
    return f"Band {uuid.uuid4().hex[:8]}"


def _post(client: TestClient, headers: dict[str, str], **fields: Any):
    """A server error comes back as a 500 here (not as a raised exception), so that a test
    that expects a 422 fails on its assertion."""
    body: dict[str, Any] = {"name": _name(), "components": _std()}
    body.update(fields)
    quiet = TestClient(client.app, raise_server_exceptions=False)
    return quiet.post(S, json=body, headers=headers)


def _make(client: TestClient, headers: dict[str, str], **fields: Any) -> dict:
    resp = _post(client, headers, **fields)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _msg(resp) -> str:
    return resp.json()["error"]["message"]


def _assign(
    client: TestClient,
    headers: dict[str, str],
    emp_id: str,
    structure_id: str,
    ctc: str = "600000.00",
    effective_from: str = "2024-01-01",
    **extra: Any,
):
    body: dict[str, Any] = {
        "structure_id": structure_id,
        "ctc": ctc,
        "effective_from": effective_from,
    }
    body.update(extra)
    return client.post(f"{E}/{emp_id}/assign", json=body, headers=headers)


def _day(offset: int) -> str:
    return (utcnow().date() + timedelta(days=offset)).isoformat()


def _set_run_status(db: Session, ctx: TenantContext, run_id: str, status: PayrollRunStatus):
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    row = db.get(PayrollRun, uuid.UUID(run_id))
    assert row is not None
    row.status = status
    db.commit()


# ------------------------------------------------------------------- R1


def test_R1_no_login_gets_401_on_every_structure_route(client: TestClient) -> None:
    sid = uuid.uuid4()
    calls = [
        client.post(S, json={"name": "x"}),
        client.get(S),
        client.get(f"{S}/{sid}"),
        client.put(f"{S}/{sid}", json={"name": "x"}),
        client.delete(f"{S}/{sid}"),
    ]
    assert [c.status_code for c in calls] == [401] * 5, "R1: every structure route needs a login"


@pytest.mark.parametrize("who", ["employee_headers", "manager_headers"])
def test_R1_employee_and_manager_get_403_on_every_structure_route(
    client: TestClient, company_a: TenantContext, who: str
) -> None:
    headers = getattr(company_a, who)
    existing = _make(client, company_a.hr_headers)["id"]
    calls = [
        client.post(S, json={"name": _name(), "components": _std()}, headers=headers),
        client.get(S, headers=headers),
        client.get(f"{S}/{existing}", headers=headers),
        client.put(f"{S}/{existing}", json={"name": _name()}, headers=headers),
        client.delete(f"{S}/{existing}", headers=headers),
    ]
    assert [c.status_code for c in calls] == [403] * 5, f"R1: {who} must get 403 on every route"
    assert client.get(f"{S}/{existing}", headers=company_a.hr_headers).status_code == 200, (
        "R1: a refused delete must leave the structure"
    )


def test_R1_owner_and_hr_admin_can_use_every_structure_route(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    owner_h, _ = _extra_user(db, company_a.company_id, UserRole.owner)
    for headers in (company_a.hr_headers, owner_h):
        sid = _make(client, headers)["id"]
        assert client.get(S, headers=headers).status_code == 200
        assert client.get(f"{S}/{sid}", headers=headers).status_code == 200
        assert client.put(f"{S}/{sid}", json={"level": "L2"}, headers=headers).status_code == 200
        assert client.delete(f"{S}/{sid}", headers=headers).status_code == 204


def test_R1_another_companys_structure_gives_the_same_404_as_a_missing_one(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
) -> None:
    theirs = _make(client, company_b.hr_headers)["id"]
    missing = str(uuid.uuid4())
    for method in ("get", "put", "delete"):
        kwargs: dict[str, Any] = {"headers": company_a.hr_headers}
        if method == "put":
            kwargs["json"] = {"name": _name()}
        other = getattr(client, method)(f"{S}/{theirs}", **kwargs)
        gone = getattr(client, method)(f"{S}/{missing}", **kwargs)
        assert (other.status_code, _msg(other)) == (404, "Salary structure not found."), (
            f"R1: {method} on another company's structure must be 404"
        )
        assert (gone.status_code, _msg(gone)) == (other.status_code, _msg(other)), (
            "R1: missing and other-company must look the same"
        )
    assert client.get(f"{S}/{theirs}", headers=company_b.hr_headers).status_code == 200, (
        "R1: the other company's structure must be untouched"
    )


# ------------------------------------------------------------------- R2


def test_R2_name_is_trimmed_and_limited_to_1_to_150_characters(
    client: TestClient, company_a: TenantContext
) -> None:
    plain = _name()
    padded = _make(client, company_a.hr_headers, name=f"   {plain}   ")
    assert padded["name"] == plain, "R2: name must be trimmed"
    for bad in ("", "     ", "x" * 151):
        assert _post(client, company_a.hr_headers, name=bad).status_code == 422, (
            f"R2: name of length {len(bad)} must be 422"
        )
    assert _post(client, company_a.hr_headers, name="y" * 150).status_code == 201, (
        "R2: a 150-character name is allowed"
    )
    sid = padded["id"]
    assert (
        client.put(f"{S}/{sid}", json={"name": " "}, headers=company_a.hr_headers).status_code
        == 422
    ), "R2: a blank name on edit must be 422"


def test_R2_name_is_unique_per_company_ignoring_case(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
) -> None:
    first = _make(client, company_a.hr_headers, name="Engineering Band")
    dup = _post(client, company_a.hr_headers, name="  ENGINEERING band ")
    assert dup.status_code == 409, "R2: a name that differs only by case or spaces is a duplicate"
    assert "already exists" in _msg(dup), "R2: the 409 must say the name exists"
    other = _make(client, company_a.hr_headers, name="Sales Band")
    rename = client.put(
        f"{S}/{other['id']}", json={"name": "engineering BAND"}, headers=company_a.hr_headers
    )
    assert rename.status_code == 409, "R2: renaming onto an existing name is a duplicate"
    same = client.put(
        f"{S}/{first['id']}", json={"name": "ENGINEERING BAND"}, headers=company_a.hr_headers
    )
    assert same.status_code == 200, "R2: re-casing a structure's own name is allowed"
    assert _post(client, company_b.hr_headers, name="Engineering Band").status_code == 201, (
        "R2: another company may use the same name"
    )


def test_R2_a_deleted_structures_name_can_be_used_again(
    client: TestClient, company_a: TenantContext
) -> None:
    first = _make(client, company_a.hr_headers, name="Reusable Band")
    assert client.delete(f"{S}/{first['id']}", headers=company_a.hr_headers).status_code == 204
    assert _post(client, company_a.hr_headers, name="reusable band").status_code == 201, (
        "R2: a soft-deleted structure must not hold its name"
    )


@contextmanager
def race_company() -> Iterator[tuple[uuid.UUID, dict[str, str], Any]]:
    """A company of its own, outside the savepoint-wrapped `db`, with get_db overridden so that
    every request in every thread gets its own session on a real connection."""
    assert settings.TEST_DATABASE_URL is not None
    purge_stale_race_companies()
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=6, max_overflow=4)
    cid = uuid.uuid4()
    try:
        with Session(engine) as setup:
            setup.add(
                Company(
                    id=cid,
                    name="Struct Race Co",
                    code=f"SRC{uuid.uuid4().hex[:4].upper()}",
                    email=f"src-{uuid.uuid4().hex[:6]}@example.com",
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

        def _get_test_db():
            session = Session(engine)
            try:
                yield session
            finally:
                session.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db
        yield cid, {"Authorization": f"Bearer {token}"}, engine
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        purge_company(cid)


def purge_company(cid: uuid.UUID) -> None:
    """Delete everything a race company owns, as the owner role, in as many passes as the
    foreign keys need."""
    owner = create_engine(settings.TEST_MIGRATION_URL)
    try:
        with owner.connect() as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE column_name = 'company_id' AND table_schema = 'public'"
                    )
                )
            ]
        for _ in range(8):
            left = 0
            for table in tables:
                try:
                    with owner.begin() as conn:
                        conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
                        conn.execute(text(f"DELETE FROM {table} WHERE company_id = :c"), {"c": cid})
                except Exception:
                    left += 1
            if not left:
                break
        with owner.begin() as conn:
            conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
            conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": cid})
    finally:
        owner.dispose()


def purge_stale_race_companies() -> None:
    """A race company left behind by a run that was killed half way."""
    owner = create_engine(settings.TEST_MIGRATION_URL)
    try:
        with owner.begin() as conn:
            conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
            ids = [
                r[0]
                for r in conn.execute(
                    text("SELECT id FROM companies WHERE name = 'Struct Race Co'")
                )
            ]
    finally:
        owner.dispose()
    for stale in ids:
        purge_company(stale)


def test_R2_two_simultaneous_creates_of_one_name_give_one_201_and_one_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.payroll.repository import SalaryStructureRepository

    original = getattr(SalaryStructureRepository, "get_by_name", None)

    def _slow(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        assert original is not None
        found = original(self, *args, **kwargs)
        time.sleep(0.5)  # both requests passed the "name taken?" look before either saves
        return found

    if original is not None:  # the name look-up the service uses before it saves
        monkeypatch.setattr(SalaryStructureRepository, "get_by_name", _slow)
    with race_company() as (_cid, headers, _engine):
        barrier = threading.Barrier(2)
        results: list[int] = []
        bodies: list[str] = []

        def _worker() -> None:
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                resp = _post(c, headers, name="Race Band")
                results.append(resp.status_code)
                bodies.append(resp.text)
            except Exception:
                results.append(999)

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert 500 not in results and 999 not in results, f"R2: race gave an error: {results}"
        assert sorted(results) == [201, 409], f"R2: expected one 201 and one 409, got {results}"
        loser = bodies[results.index(409)]
        assert "already exists" in loser, f"R2: the loser gets the specific message: {loser}"


def test_R2_level_country_and_component_count_limits(
    client: TestClient, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    assert _post(client, h, level="L" * 11).status_code == 422, "R2: level over 10 chars"
    assert _post(client, h, level="L" * 10).status_code == 201, "R2: level of 10 chars is fine"
    for bad in ("IND", "I", "I1", "1N", ""):
        assert _post(client, h, country=bad).status_code == 422, f"R2: country {bad!r} must be 422"
    assert _post(client, h, country="IN").status_code == 201
    many = [_c(f"C{i:02d}", "fixed", "1.00") for i in range(31)]
    assert _post(client, h, components=many).status_code == 422, "R2: 31 components"
    assert _post(client, h, components=many[:30]).status_code == 201, "R2: 30 components"


@pytest.mark.parametrize(
    "component",
    [
        _c("OK", name=""),
        _c("OK", name="   "),
        _c("OK", name="n" * 101),
        _c("a1"),
        _c("B"),
        _c("A" * 21),
        _c("BAS IC"),
        _c("BAS-IC"),
        _c("OK", "percentage", "-0.01"),
        _c("OK", "percentage", "100.01"),
        _c("OK", "fixed", "-1"),
        _c("OK", "fixed", "10.123"),
        _c("OK", display_order=-1),
        _c("OK", display_order=1001),
        _c("OK", "fixed", "100000000.00"),
    ],
)
def test_R2_bad_component_fields_give_422(
    client: TestClient, company_a: TenantContext, component: dict[str, Any]
) -> None:
    resp = _post(client, company_a.hr_headers, components=[component])
    assert resp.status_code == 422, f"R2: component {component} must be 422, got {resp.status_code}"


def test_R2_good_component_edges_are_accepted_and_names_trimmed(
    client: TestClient, company_a: TenantContext
) -> None:
    comps = [
        _c("AB", "fixed", "0", name="  Padded  ", display_order=0),
        _c("A_1" + "B" * 17, "fixed", "99999999.99", display_order=1000),
        _c("PCT", "percentage", "100", "ctc"),
        _c("N" * 20, "fixed", "12.5", name="n" * 100),
    ]
    resp = _post(client, company_a.hr_headers, components=comps)
    assert resp.status_code == 201, resp.text
    first = next(c for c in resp.json()["components"] if c["code"] == "AB")
    assert first["name"] == "Padded", "R2: component name must be trimmed"


def test_R2_unknown_fields_and_nulls_on_required_fields_give_422(
    client: TestClient, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    sid = _make(client, h)["id"]
    cases = [
        client.post(S, json={"name": _name(), "company_id": str(uuid.uuid4())}, headers=h),
        client.post(S, json={"name": None}, headers=h),
        client.post(S, json={"name": _name(), "country": None}, headers=h),
        client.post(S, json={"name": _name(), "components": None}, headers=h),
        client.post(S, json={"name": _name(), "components": [_c("OK", bogus=1)]}, headers=h),
        client.post(
            S, json={"name": _name(), "components": [{**_c("OK"), "code": None}]}, headers=h
        ),
        client.post(S, json={"name": _name(), "components": [_c("OK", name=None)]}, headers=h),
        client.post(S, json={"name": _name(), "components": [_c("OK", type=None)]}, headers=h),
        client.put(f"{S}/{sid}", json={"bogus": 1}, headers=h),
        client.put(f"{S}/{sid}", json={"name": None}, headers=h),
        client.put(f"{S}/{sid}", json={"is_active": None}, headers=h),
        client.put(f"{S}/{sid}", json={"components": None}, headers=h),
    ]
    assert [c.status_code for c in cases] == [422] * len(cases), (
        f"R2: unknown fields and nulls must be 422: {[c.status_code for c in cases]}"
    )


# ------------------------------------------------------------------- R3

_BREACHES = [
    ("dup", [_c("AA"), _c("AA")], "unique"),
    ("two_balance", [_c("AA", "balance"), _c("BB", "balance")], "at most one `balance`"),
    (
        "over_100",
        [_c("AA", "percentage", "60", "ctc"), _c("BB", "percentage", "50", "ctc")],
        "over 100%",
    ),
    ("no_basic", [_c("HRA", "percentage", "40", "basic")], "no component is coded 'BASIC'"),
    ("statutory_flag", [_c("PF", "statutory", None, is_statutory=False)], "is_statutory=true"),
    (
        "pct_no_base",
        [_c("AA", "percentage", "10", None, percentage_of=None)],
        "needs both value and percentage_of",
    ),
    ("fixed_no_value", [_c("AA", "fixed", None)], "needs a value"),
    ("balance_value", [{**_c("AA", "balance"), "value": "5.00"}], "must not carry a value"),
]


@pytest.mark.parametrize(("label", "components", "fragment"), _BREACHES)
def test_R3_each_component_breach_gives_the_invalid_structure_error_on_create_and_edit(
    client: TestClient,
    company_a: TenantContext,
    label: str,
    components: list[dict[str, Any]],
    fragment: str,
) -> None:
    h = company_a.hr_headers
    created = _post(client, h, components=components)
    assert created.status_code == 400, f"R3 {label}: create gave {created.status_code}"
    assert created.json()["error"]["code"] == "invalid_structure", f"R3 {label}: wrong code"
    assert fragment in _msg(created), f"R3 {label}: message {_msg(created)!r}"
    sid = _make(client, h)["id"]
    edited = client.put(f"{S}/{sid}", json={"components": components}, headers=h)
    assert edited.status_code == 400 and fragment in _msg(edited), (
        f"R3 {label}: edit {_msg(edited)}"
    )
    kept = client.get(f"{S}/{sid}", headers=h).json()["components"]
    assert [c["code"] for c in kept] == ["BASIC", "HRA", "SPECIAL"], (
        f"R3 {label}: a refused edit must keep the old components"
    )


def test_R3_a_valid_structure_with_every_calculation_type_is_accepted(
    client: TestClient, company_a: TenantContext
) -> None:
    comps = _std() + [
        _c("PF", "statutory", None, is_statutory=True, type="deduction"),
        _c("BONUS", "fixed", "500.00"),
    ]
    resp = _post(client, company_a.hr_headers, components=comps)
    assert resp.status_code == 201, resp.text
    assert len(resp.json()["components"]) == 5


# ------------------------------------------------------------------- R4


def _fixed_balance() -> list[dict[str, Any]]:
    return [_c("BASIC", "fixed", "10000.00", display_order=1), _c("SPECIAL", "balance")]


def test_R4_assignment_is_refused_with_the_numbers_when_earnings_exceed_the_ctc(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    sid = _make(client, company_a.hr_headers, components=_fixed_balance())["id"]
    emp = _staff(client, db, company_a, None)
    resp = _assign(client, company_a.hr_headers, emp["id"], sid, ctc="9000.00")
    assert resp.status_code == 400, f"R4: expected the CTC error, got {resp.status_code}"
    assert resp.json()["error"]["code"] == "insufficient_ctc"
    assert "10000.00" in _msg(resp) and "9000.00" in _msg(resp), (
        f"R4: numbers missing: {_msg(resp)}"
    )
    assert (
        _assign(client, company_a.hr_headers, emp["id"], sid, ctc="10000.00").status_code == 201
    ), "R4: a CTC equal to the fixed earnings leaves a zero balance and is fine"


def test_R4_without_a_balance_component_the_earnings_must_equal_the_ctc(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    comps = [_c("BASIC", "fixed", "10000.00"), _c("HRA", "fixed", "5000.00")]
    sid = _make(client, company_a.hr_headers, components=comps)["id"]
    emp = _staff(client, db, company_a, None)
    bad = _assign(client, company_a.hr_headers, emp["id"], sid, ctc="16000.00")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "insufficient_ctc"
    assert "15000.00" in _msg(bad) and "16000.00" in _msg(bad), f"R4: numbers: {_msg(bad)}"
    good = _assign(client, company_a.hr_headers, emp["id"], sid, ctc="15000.00")
    assert good.status_code == 201, "R4: earnings equal to the CTC are accepted"


def test_R4_an_edit_that_would_break_a_salary_in_force_or_future_is_refused_with_the_count(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    sid = _make(client, h, components=_fixed_balance())["id"]
    now_emp = _staff(client, db, company_a, None)
    future_emp = _staff(client, db, company_a, None)
    ended_emp = _staff(client, db, company_a, None)
    assert _assign(client, h, now_emp["id"], sid, ctc="120000.00").status_code == 201
    assert (
        _assign(
            client, h, future_emp["id"], sid, ctc="120000.00", effective_from=_day(60)
        ).status_code
        == 201
    )
    # a salary that has already ended is not in force and must not count
    other = _make(client, h)["id"]
    assert (
        _assign(
            client, h, ended_emp["id"], sid, ctc="120000.00", effective_from="2020-01-01"
        ).status_code
        == 201
    )
    assert _assign(
        client, h, ended_emp["id"], other, ctc="120000.00", effective_from="2021-01-01",
        revision_reason="moved",
    ).status_code == 201  # fmt: skip
    broken = [_c("BASIC", "fixed", "500000.00"), _c("SPECIAL", "balance")]
    resp = client.put(f"{S}/{sid}", json={"components": broken}, headers=h)
    assert resp.status_code == 409, f"R4: expected 409, got {resp.status_code}: {resp.text}"
    assert "2 salaries" in _msg(resp), f"R4: the 409 must name the count: {_msg(resp)}"
    kept = client.get(f"{S}/{sid}", headers=h).json()["components"]
    assert next(c for c in kept if c["code"] == "BASIC")["value"] == "10000.000", (
        "R4: a refused edit must keep the old components"
    )
    fine = [_c("BASIC", "fixed", "20000.00"), _c("SPECIAL", "balance")]
    assert client.put(f"{S}/{sid}", json={"components": fine}, headers=h).status_code == 200, (
        "R4: an edit that keeps every salary valid is allowed"
    )


# ------------------------------------------------------------------- R5


def test_R5_an_edit_replaces_the_whole_component_list_in_one_save(
    client: TestClient, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    sid = _make(client, h)["id"]
    new = [
        _c("BASIC", "percentage", "60", "ctc", display_order=1),
        _c("SPECIAL", "balance", display_order=2),
    ]
    resp = client.put(f"{S}/{sid}", json={"name": "Renamed Band", "components": new}, headers=h)
    assert resp.status_code == 200, resp.text
    assert [c["code"] for c in resp.json()["components"]] == ["BASIC", "SPECIAL"], (
        "R5: the old HRA line must be gone"
    )
    assert resp.json()["name"] == "Renamed Band"
    bad = client.put(
        f"{S}/{sid}", json={"name": "Never Saved", "components": [_c("AA"), _c("AA")]}, headers=h
    )
    assert bad.status_code == 400
    now = client.get(f"{S}/{sid}", headers=h).json()
    assert now["name"] == "Renamed Band" and len(now["components"]) == 2, (
        "R5: a refused edit must change nothing, not even the name"
    )


@pytest.mark.parametrize("status", [PayrollRunStatus.processing, PayrollRunStatus.pending_approval])
def test_R5_a_component_edit_is_refused_while_a_run_is_processing_or_pending_approval(
    client: TestClient, db: Session, world: dict[str, Any], status: PayrollRunStatus
) -> None:
    ctx, h = world["ctx"], world["hr1"]
    for who in ("emp", "manager"):
        _fill(db, ctx, world[who]["id"], world["year"], world["month"])
    run = _make_run(client, h, world["year"], world["month"])
    _set_run_status(db, ctx, run["id"], status)
    new = [_c("BASIC", "percentage", "60", "ctc"), _c("SPECIAL", "balance")]
    resp = client.put(f"{S}/{world['structure_id']}", json={"components": new}, headers=h)
    assert resp.status_code == 409, f"R5: {status.value}: expected 409, got {resp.status_code}"
    assert "payroll run" in _msg(resp), f"R5: message: {_msg(resp)}"
    codes = [
        c["code"]
        for c in client.get(f"{S}/{world['structure_id']}", headers=h).json()["components"]
    ]
    assert codes == ["BASIC", "HRA", "SPECIAL"], "R5: nothing may change"
    renamed = client.put(f"{S}/{world['structure_id']}", json={"level": "L9"}, headers=h)
    assert renamed.status_code == 200, "R5: only component edits are locked, a level edit is not"
    _set_run_status(db, ctx, run["id"], PayrollRunStatus.approved)
    again = client.put(f"{S}/{world['structure_id']}", json={"components": new}, headers=h)
    assert again.status_code == 200, "R5: once the run is approved the edit is allowed again"


def test_R5_issued_payslips_never_change_and_the_edit_applies_to_later_runs_only(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    ctx, h = world["ctx"], world["hr1"]
    year, month = world["year"], world["month"]
    older_year, older_month = _month_back(2)
    for who in ("emp", "manager"):
        _fill(db, ctx, world[who]["id"], year, month)
        _fill(db, ctx, world[who]["id"], older_year, older_month)
    run = _make_run(client, h, year, month)
    assert client.post(f"{RUNS}/{run['id']}/approve", headers=world["hr2"]).status_code == 200

    def _slip(run_id: str) -> dict:
        page = client.get(f"{PAYSLIPS}/me", headers=world["emp"]["h"]).json()
        return next(i for i in page["items"] if i["payroll_run_id"] == run_id)

    before = _slip(run["id"])
    new = [
        _c("BASIC", "percentage", "60", "ctc", display_order=1),
        _c("HRA", "percentage", "40", "basic", display_order=2),
        _c("SPECIAL", "balance", display_order=3),
    ]
    edit = client.put(f"{S}/{world['structure_id']}", json={"components": new}, headers=h)
    assert edit.status_code == 200, edit.text
    after = _slip(run["id"])
    assert after["earnings_json"] == before["earnings_json"], "R5: the issued payslip changed"
    assert after["net_salary"] == before["net_salary"]
    later = _make_run(client, h, older_year, older_month)
    assert client.post(f"{RUNS}/{later['id']}/approve", headers=world["hr2"]).status_code == 200
    new_slip = _slip(later["id"])
    basic_old = next(e for e in before["earnings_json"] if e["code"] == "BASIC")["amount"]
    basic_new = next(e for e in new_slip["earnings_json"] if e["code"] == "BASIC")["amount"]
    assert Decimal(basic_old) == Decimal("25000.00"), "R5: first run used 50% of 50000"
    assert Decimal(basic_new) == Decimal("30000.00"), "R5: the edit must apply to the later run"


# ------------------------------------------------------------------- R6


def test_R6_delete_is_soft_and_the_structure_disappears_from_reads(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    sid = _make(client, h)["id"]
    assert client.delete(f"{S}/{sid}", headers=h).status_code == 204
    assert client.get(f"{S}/{sid}", headers=h).status_code == 404, "R6: a deleted structure is 404"
    assert sid not in [i["id"] for i in client.get(S, headers=h).json()["items"]]
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    row = db.get(SalaryStructure, uuid.UUID(sid))
    assert row is not None and row.deleted_at is not None, "R6: the row must stay, soft-deleted"
    assert client.delete(f"{S}/{sid}", headers=h).status_code == 404, "R6: delete twice is 404"


def test_R6_delete_is_refused_with_the_count_while_a_current_or_future_salary_uses_it(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    sid = _make(client, h)["id"]
    now_emp = _staff(client, db, company_a, None)
    future_emp = _staff(client, db, company_a, None)
    assert _assign(client, h, now_emp["id"], sid).status_code == 201
    one = client.delete(f"{S}/{sid}", headers=h)
    assert one.status_code == 409 and "1 " in _msg(one), f"R6: current salary: {_msg(one)}"
    assert _assign(client, h, future_emp["id"], sid, effective_from=_day(90)).status_code == 201
    two = client.delete(f"{S}/{sid}", headers=h)
    assert two.status_code == 409 and "2 " in _msg(two), f"R6: current + future: {_msg(two)}"
    assert client.get(f"{S}/{sid}", headers=h).status_code == 200, "R6: still there"


def test_R6_delete_is_allowed_when_only_ended_salaries_used_it(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    old, new = _make(client, h)["id"], _make(client, h)["id"]
    emp = _staff(client, db, company_a, None)
    assert _assign(client, h, emp["id"], old, effective_from="2020-01-01").status_code == 201
    revised = _assign(
        client, h, emp["id"], new, effective_from="2021-01-01", revision_reason="move"
    )
    assert revised.status_code == 201, revised.text
    assert client.delete(f"{S}/{old}", headers=h).status_code == 204, (
        "R6: a structure whose salaries all ended can be deleted"
    )


def test_R6_a_deleted_structure_cannot_be_assigned_404_and_an_inactive_one_409(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    emp = _staff(client, db, company_a, None)
    gone = _make(client, h)["id"]
    assert client.delete(f"{S}/{gone}", headers=h).status_code == 204
    r404 = _assign(client, h, emp["id"], gone)
    assert (r404.status_code, _msg(r404)) == (404, "Salary structure not found.")
    idle = _make(client, h)["id"]
    assert client.put(f"{S}/{idle}", json={"is_active": False}, headers=h).status_code == 200
    r409 = _assign(client, h, emp["id"], idle)
    assert r409.status_code == 409 and "inactive" in _msg(r409), (
        f"R6: {r409.status_code} {r409.text}"
    )
    assert client.put(f"{S}/{idle}", json={"is_active": True}, headers=h).status_code == 200
    assert _assign(client, h, emp["id"], idle).status_code == 201, "R6: active again is fine"


# ------------------------------------------------------------------- R7


def test_R7_create_edit_and_delete_each_write_one_audit_row_without_component_values(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    created = _make(client, h)
    sid = created["id"]
    rows = _audit(db, company_a, "SALARY_STRUCTURE_CREATED")
    assert len(rows) == 1, "R7: one audit row for create"
    assert rows[0].entity_id == uuid.UUID(sid)
    assert rows[0].details == {"structure_id": sid, "component_count": 3}, (
        f"R7: create details: {rows[0].details}"
    )
    new = [_c("BASIC", "percentage", "55.5", "ctc"), _c("SPECIAL", "balance")]
    assert (
        client.put(f"{S}/{sid}", json={"level": "L4", "components": new}, headers=h).status_code
        == 200
    )
    edits = _audit(db, company_a, "SALARY_STRUCTURE_UPDATED")
    assert len(edits) == 1, "R7: one audit row for edit"
    assert edits[0].details == {
        "structure_id": sid,
        "fields": ["components", "level"],
        "component_count": 2,
    }, f"R7: edit details: {edits[0].details}"
    assert "55.5" not in str(edits[0].details), "R7: no component value in the audit"
    assert client.delete(f"{S}/{sid}", headers=h).status_code == 204
    gone = _audit(db, company_a, "SALARY_STRUCTURE_DELETED")
    assert len(gone) == 1 and gone[0].details == {"structure_id": sid}, "R7: delete audit"


def test_R7_a_refused_request_writes_no_audit_row(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    _make(client, h, name="Once Only")
    assert _post(client, h, name="once only").status_code == 409
    assert _post(client, h, components=[_c("AA"), _c("AA")]).status_code == 400
    assert len(_audit(db, company_a, "SALARY_STRUCTURE_CREATED")) == 1, (
        "R7: only the successful create is audited"
    )


def test_R7_the_audit_row_and_the_change_are_one_save(
    client: TestClient, db: Session, company_a: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(self, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("audit store down")

    monkeypatch.setattr(AuditService, "record", _boom)
    name = _name()
    body = {"name": name, "components": _std()}
    with pytest.raises(RuntimeError):
        client.post(S, json=body, headers=company_a.hr_headers)
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    assert db.query(SalaryStructure).filter(SalaryStructure.name == name).count() == 0, (
        "R7: when the audit row fails the structure must not be saved"
    )
    created = db.query(AuditLog).filter(
        AuditLog.company_id == company_a.company_id, AuditLog.action == "SALARY_STRUCTURE_CREATED"
    )
    assert created.count() == 0


# ------------------------------------------------------------------- R8


def test_R8_the_three_write_routes_are_limited_to_30_per_minute(
    client: TestClient, company_a: TenantContext, limits_on
) -> None:
    h = company_a.hr_headers
    posts = [_post(client, h).status_code for _ in range(31)]
    assert posts[:30] == [201] * 30 and posts[30] == 429, f"R8: POST limit wrong: {posts[-3:]}"
    limiter.reset()
    missing = uuid.uuid4()
    puts = [
        client.put(f"{S}/{missing}", json={"level": "L1"}, headers=h).status_code for _ in range(31)
    ]
    assert puts[:30] == [404] * 30 and puts[30] == 429, f"R8: PUT limit wrong: {puts[-3:]}"
    limiter.reset()
    dels = [client.delete(f"{S}/{missing}", headers=h).status_code for _ in range(31)]
    assert dels[:30] == [404] * 30 and dels[30] == 429, f"R8: DELETE limit wrong: {dels[-3:]}"


def test_R8_the_two_read_routes_are_limited_to_60_per_minute(
    client: TestClient, company_a: TenantContext, limits_on
) -> None:
    h = company_a.hr_headers
    lists = [client.get(S, headers=h).status_code for _ in range(61)]
    assert lists[:60] == [200] * 60 and lists[60] == 429, f"R8: list limit wrong: {lists[-3:]}"
    limiter.reset()
    one = [client.get(f"{S}/{uuid.uuid4()}", headers=h).status_code for _ in range(61)]
    assert one[:60] == [404] * 60 and one[60] == 429, f"R8: get limit wrong: {one[-3:]}"


def test_R8_the_list_is_paged_and_ordered_by_name(
    client: TestClient, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    for name in ("bravo", "Alpha", "charlie"):
        _make(client, h, name=name)
    first = client.get(f"{S}?limit=2&page=1", headers=h).json()
    second = client.get(f"{S}?limit=2&page=2", headers=h).json()
    assert [i["name"] for i in first["items"]] == ["Alpha", "bravo"], "R8: page 1 by name"
    assert [i["name"] for i in second["items"]] == ["charlie"], "R8: page 2 by name"
    assert (first["total"], first["pages"], first["has_next"]) == (3, 2, True)
    assert second["has_next"] is False
    assert first["items"][0]["component_count"] == 3
    assert client.get(f"{S}?limit=0", headers=h).status_code == 422, "R8: limit 0 is 422"


# ------------------------------------------------------------------- R9


def test_R9_components_come_back_in_display_order_with_every_model_field(
    client: TestClient, company_a: TenantContext
) -> None:
    h = company_a.hr_headers
    comps = [
        _c("ZED", "fixed", "5.00", display_order=2),
        _c("BASIC", "percentage", "50", "ctc", display_order=1, is_taxable=False),
        _c("PF", "statutory", None, is_statutory=True, type="deduction", display_order=3),
        _c("ALPHA", "fixed", "7.00", display_order=2),
    ]
    created = _make(client, h, components=comps)
    for body in (created, client.get(f"{S}/{created['id']}", headers=h).json()):
        assert [c["code"] for c in body["components"]] == ["BASIC", "ALPHA", "ZED", "PF"], (
            "R9: display order, ties by code"
        )
        first = body["components"][0]
        assert set(first) == {
            "id", "name", "code", "type", "calculation_type", "value", "percentage_of",
            "is_taxable", "is_statutory", "display_order",
        }, f"R9: component fields: {sorted(first)}"  # fmt: skip
        assert first["is_taxable"] is False and first["percentage_of"] == "ctc"
        assert set(body) >= {"id", "name", "country", "level", "is_active", "created_at"}


def test_R9_another_companys_structures_never_appear(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
) -> None:
    mine = _make(client, company_a.hr_headers, name="Mine A")
    theirs = _make(client, company_b.hr_headers, name="Theirs B")
    a_ids = [i["id"] for i in client.get(S, headers=company_a.hr_headers).json()["items"]]
    b_ids = [i["id"] for i in client.get(S, headers=company_b.hr_headers).json()["items"]]
    assert a_ids == [mine["id"]] and b_ids == [theirs["id"]], "R9: lists must be per company"
    assert theirs["name"] not in client.get(S, headers=company_a.hr_headers).text


# ------------------------------------------------------------------ R10


def test_R10_every_rule_from_1_to_9_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_R")]
    for rule in range(1, 10):
        assert any(n.startswith(f"test_R{rule}_") for n in names), f"R10: no test for rule {rule}"
