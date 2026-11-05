"""Module 5, sub-feature 5.8, part B: a super admin sees no company payroll data. One test per
rule line (B1..B6).

Company payroll routes (salaries, runs, payslips, reimbursements, the company statutory
settings, bank details, payment files) refuse a super admin with the same 403 an employee gets.
Platform data (statutory rates, PT slabs, tax slabs) is unchanged. The platform sees only
anonymous per-month payroll statistics.
"""

import re
import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.statutory_rates import seed_statutory_rates
from app.db.seed.tax_slabs import seed_tax_slabs
from app.main import app
from app.modules.identity.models import UserRole
from tests.conftest import TenantContext
from tests.rules.test_5_2_statutory_rates import _pt_body, _rate_body, _tax_body
from tests.rules.test_5_4_payroll_runs import (
    RUNS,
    _extra_user,
    _fill,
    _make_run,
    _month_back,
    _staff,
    _structure,
)
from tests.security.route_policy import POLICY, ROLES
from tests.security.test_route_access_matrix import _discover_app_routes

P = "/api/v1/payroll"
STATS = "/api/v1/platform/payroll-stats"
EMPLOYEE_403 = "You do not have permission to perform this action."

PLATFORM_ROUTES = {
    ("GET", f"{P}/statutory-rates"),
    ("POST", f"{P}/statutory-rates"),
    ("GET", f"{P}/pt-slabs"),
    ("PUT", f"{P}/pt-slabs"),
    ("GET", f"{P}/tax-slabs"),
    ("POST", f"{P}/tax-slabs"),
}
COMPANY_ROUTES = {
    ("GET", f"{P}/structures"),
    ("POST", f"{P}/structures"),
    ("GET", f"{P}/structures/{{structure_id}}"),
    ("PUT", f"{P}/structures/{{structure_id}}"),
    ("DELETE", f"{P}/structures/{{structure_id}}"),
    ("POST", f"{P}/employees/{{employee_id}}/assign"),
    ("GET", f"{P}/employees/{{employee_id}}/salary"),
    ("GET", f"{P}/employees/{{employee_id}}/salary-history"),
    ("GET", f"{P}/statutory-config"),
    ("PUT", f"{P}/statutory-config"),
    ("POST", f"{P}/runs"),
    ("GET", f"{P}/runs"),
    ("GET", f"{P}/runs/{{id}}"),
    ("POST", f"{P}/runs/{{id}}/approve"),
    ("DELETE", f"{P}/runs/{{id}}"),
    ("GET", f"{P}/payslips/me"),
    ("GET", f"{P}/payslips/{{employee_id}}"),
    ("POST", f"{P}/reimbursements"),
    ("GET", f"{P}/reimbursements"),
    ("PUT", f"{P}/reimbursements/{{id}}"),
    ("GET", f"{P}/reimbursements/{{id}}/receipt"),
    ("POST", f"{P}/reimbursements/{{id}}/withdraw"),
    ("GET", f"{P}/bank-account/me"),
    ("PUT", f"{P}/bank-account/me"),
    ("GET", f"{P}/employees/{{employee_id}}/bank-account"),
    ("PUT", f"{P}/employees/{{employee_id}}/bank-account"),
    ("GET", f"{P}/runs/{{id}}/payment-file"),
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


def _payroll_routes() -> set[tuple[str, str]]:
    return {(m, p) for m, p, _ in _discover_app_routes(app) if p.startswith(P)}


# ------------------------------------------------------------------- B1


def test_B1_every_payroll_route_is_classified_company_or_platform() -> None:
    found = _payroll_routes()
    unclassified = found - COMPANY_ROUTES - PLATFORM_ROUTES
    missing = (COMPANY_ROUTES | PLATFORM_ROUTES) - found
    assert not unclassified, f"B1: payroll routes nobody classified: {sorted(unclassified)}"
    assert not missing, f"B1: classified routes that do not exist: {sorted(missing)}"


def test_B1_a_super_admin_gets_403_with_the_employee_message_on_every_company_payroll_route(
    client: TestClient, super_admin_headers: dict[str, str], company_a: TenantContext
) -> None:
    failures: list[str] = []
    dummy = str(uuid.uuid4())
    for method, path in sorted(COMPANY_ROUTES):
        url = re.sub(r"\{[^}]+\}", dummy, path)
        kwargs: dict[str, Any] = {"headers": {**super_admin_headers, "Idempotency-Key": "k-b1"}}
        if method in ("POST", "PUT"):
            kwargs["json"] = {}
        resp = client.request(method, url, **kwargs)
        message = ""
        if resp.headers.get("content-type", "").startswith("application/json"):
            body = resp.json()
            message = body.get("error", {}).get("message", "") if isinstance(body, dict) else ""
        if resp.status_code != 403 or message != EMPLOYEE_403:
            failures.append(f"{method} {path}: {resp.status_code} {message!r}")
    assert not failures, "B1: a super admin must get the plain 403 on:\n" + "\n".join(failures)


def test_B1_hr_admin_and_owner_are_unaffected(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    owner, _ = _extra_user(db, company_a.company_id, UserRole.owner)
    for headers in (company_a.hr_headers, owner):
        assert client.get(f"{P}/structures", headers=headers).status_code == 200
        assert client.get(f"{P}/statutory-config", headers=headers).status_code == 200
        assert client.get(RUNS, headers=headers).status_code == 200


# ------------------------------------------------------------------- B2


def test_B2_platform_rates_still_work_for_super_admin_and_stay_closed_to_others(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    company_a: TenantContext,
) -> None:
    seed_pt_slabs(db)
    seed_tax_slabs(db)
    seed_statutory_rates(db)
    for url in (f"{P}/statutory-rates", f"{P}/pt-slabs", f"{P}/tax-slabs?financial_year=2026-2027"):
        assert client.get(url, headers=super_admin_headers).status_code == 200, (
            f"B2: super admin reads {url}"
        )
        assert client.get(url, headers=company_a.hr_headers).status_code == 200, (
            f"B2: HR-level reads {url}"
        )
        for who in (company_a.employee_headers, company_a.manager_headers):
            assert client.get(url, headers=who).status_code == 403, f"B2: {url} closed to others"
    posts = {
        f"{P}/statutory-rates": _rate_body(),
        f"{P}/tax-slabs": _tax_body(),
    }
    for url, body in posts.items():
        assert client.post(url, json=body, headers=super_admin_headers).status_code == 201, (
            f"B2: super admin writes {url}"
        )
        assert client.post(url, json=body, headers=company_a.hr_headers).status_code == 403
    put = client.put(f"{P}/pt-slabs", json=_pt_body(state="Kerala"), headers=super_admin_headers)
    assert put.status_code == 200, f"B2: super admin writes PT slabs: {put.text}"
    assert (
        client.put(f"{P}/pt-slabs", json=_pt_body(), headers=company_a.hr_headers).status_code
        == 403
    )


# ------------------------------------------------------------------- B3


def test_B3_the_company_id_query_parameter_is_gone(
    client: TestClient,
    super_admin_headers: dict[str, str],
    company_a: TenantContext,
    company_b: TenantContext,
) -> None:
    created = client.post(
        f"{P}/structures",
        json=_structure_body(),
        headers=company_a.hr_headers,
    )
    assert created.status_code == 201, created.text
    params = [
        p["name"]
        for p in app.openapi()["paths"]["/api/v1/payroll/structures"]["get"].get("parameters", [])
    ]
    assert "company_id" not in params, f"B3: company_id is still a parameter: {params}"
    spy = client.get(
        f"{P}/structures?company_id={company_a.company_id}", headers=super_admin_headers
    )
    assert spy.status_code == 403 and "items" not in spy.text, (
        f"B3: a super admin must not reach a company's structures: {spy.status_code}"
    )
    own = client.get(
        f"{P}/structures?company_id={company_a.company_id}", headers=company_b.hr_headers
    )
    assert own.status_code == 200 and own.json()["total"] == 0, (
        f"B3: another company's id must change nothing: {own.text}"
    )


def _structure_body() -> dict[str, Any]:
    return {
        "name": f"S {uuid.uuid4().hex[:6]}",
        "components": [
            {
                "code": "BASIC",
                "name": "Basic",
                "type": "earning",
                "calculation_type": "percentage",
                "value": "50.00",
                "percentage_of": "ctc",
                "display_order": 1,
            }
        ],
    }


# ------------------------------------------------------------------- B4

STAT_KEYS = {
    "month",
    "companies_with_runs",
    "runs_total",
    "runs_by_status",
    "employees_paid",
    "total_net_paid",
}


def _month_key(back: int) -> str:
    year, month = _month_back(back)
    return f"{year}-{month:02d}"


def _stats(client: TestClient, headers: dict[str, str], frm: str, to: str):
    return client.get(f"{STATS}?from={frm}&to={to}", headers=headers)


def _row(resp, key: str) -> dict[str, Any]:
    assert resp.status_code == 200, f"B4: {resp.status_code} {resp.text}"
    found = [r for r in resp.json() if r["month"] == key]
    assert len(found) == 1, f"B4: one object for {key}: {resp.text}"
    return found[0]


def _approved_run(client: TestClient, db: Session, ctx: TenantContext, staff: int) -> Decimal:
    year, month = _month_back()
    assert (
        client.put(
            f"{P}/statutory-config", json={"pt_state": "Gujarat"}, headers=ctx.hr_headers
        ).status_code
        == 200
    )
    owner, _ = _extra_user(db, ctx.company_id, UserRole.owner)
    structure_id = _structure(client, ctx.hr_headers)
    for _ in range(staff):
        emp = _staff(client, db, ctx, structure_id)
        _fill(db, ctx, emp["id"], year, month)
    run = _make_run(client, ctx.hr_headers, year, month)
    approved = client.post(f"{RUNS}/{run['id']}/approve", headers=owner)
    assert approved.status_code == 200, approved.text
    return Decimal(approved.json()["total_net"])


@pytest.fixture(autouse=True)
def _seed_rates(db: Session) -> None:
    seed_pt_slabs(db)
    seed_tax_slabs(db)
    seed_statutory_rates(db)


def test_B4_the_totals_add_up_runs_of_two_different_companies(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    company_a: TenantContext,
    company_b: TenantContext,
) -> None:
    key = _month_key(1)
    before = _row(_stats(client, super_admin_headers, key, key), key)
    net_a = _approved_run(client, db, company_a, 2)
    net_b = _approved_run(client, db, company_b, 1)
    after = _row(_stats(client, super_admin_headers, key, key), key)
    assert after["companies_with_runs"] - before["companies_with_runs"] == 2
    assert after["runs_total"] - before["runs_total"] == 2
    assert after["runs_by_status"]["approved"] - before["runs_by_status"]["approved"] == 2
    assert after["employees_paid"] - before["employees_paid"] == 3
    assert Decimal(after["total_net_paid"]) - Decimal(before["total_net_paid"]) == net_a + net_b, (
        f"B4: both companies' net pay must be added: {before} -> {after}"
    )
    assert re.fullmatch(r"\d+\.\d{2}", after["total_net_paid"]), after["total_net_paid"]


def test_B4_one_object_per_month_with_exactly_these_keys_and_nothing_identifying(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    company_a: TenantContext,
) -> None:
    _approved_run(client, db, company_a, 1)
    resp = _stats(client, super_admin_headers, _month_key(3), _month_key(1))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert [r["month"] for r in rows] == [_month_key(3), _month_key(2), _month_key(1)], (
        f"B4: one object per month in order: {[r['month'] for r in rows]}"
    )
    for r in rows:
        assert set(r) == STAT_KEYS, f"B4: exact keys expected, got {set(r)}"
        assert set(r["runs_by_status"]) == {
            "draft",
            "processing",
            "pending_approval",
            "approved",
            "paid",
            "failed",
        }, f"B4: every status is listed: {r['runs_by_status']}"
    assert str(company_a.company_id) not in resp.text, "B4: a company id leaked"
    assert "Company A" not in resp.text, "B4: a company name leaked"


@pytest.mark.parametrize("who", ["hr_headers", "manager_headers", "employee_headers"])
def test_B4_everyone_but_super_admin_gets_403_and_no_login_401(
    client: TestClient, company_a: TenantContext, who: str
) -> None:
    key = _month_key(1)
    assert _stats(client, getattr(company_a, who), key, key).status_code == 403, f"B4: {who}"
    assert client.get(f"{STATS}?from={key}&to={key}").status_code == 401


def test_B4_an_owner_gets_403(client: TestClient, db: Session, company_a: TenantContext) -> None:
    owner, _ = _extra_user(db, company_a.company_id, UserRole.owner)
    key = _month_key(1)
    assert _stats(client, owner, key, key).status_code == 403


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?from=2026-01",
        "?to=2026-01",
        "?from=2026-13&to=2026-13",
        "?from=2026-1&to=2026-2",
        "?from=abc&to=def",
        "?from=2026-05&to=2026-04",
    ],
)
def test_B4_missing_bad_or_reversed_months_give_422(
    client: TestClient, super_admin_headers: dict[str, str], query: str
) -> None:
    resp = client.get(f"{STATS}{query}", headers=super_admin_headers)
    assert resp.status_code == 422, f"B4: {query!r} must give 422, got {resp.status_code}"


def test_B4_at_most_24_months(client: TestClient, super_admin_headers: dict[str, str]) -> None:
    ok = _stats(client, super_admin_headers, _month_key(24), _month_key(1))
    assert ok.status_code == 200 and len(ok.json()) == 24, (
        f"B4: 24 months allowed: {ok.status_code}"
    )
    too_many = _stats(client, super_admin_headers, _month_key(25), _month_key(1))
    assert too_many.status_code == 422, f"B4: 25 months must give 422, got {too_many.status_code}"


def test_B4_reads_are_limited_to_60_per_minute(
    client: TestClient, super_admin_headers: dict[str, str], limits_on: None
) -> None:
    key = _month_key(1)
    codes = [_stats(client, super_admin_headers, key, key).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429, f"B4: read limit wrong: {codes[-3:]}"


# ------------------------------------------------------------------- B5


def test_B5_the_route_policy_lists_every_new_route_with_an_explicit_decision() -> None:
    expected = {
        ("GET", f"{P}/bank-account/me"): "AUTHENTICATED",
        ("PUT", f"{P}/bank-account/me"): "AUTHENTICATED",
        ("GET", f"{P}/employees/{{employee_id}}/bank-account"): "AUTHENTICATED",
        ("PUT", f"{P}/employees/{{employee_id}}/bank-account"): "AUTHENTICATED",
        ("GET", f"{P}/runs/{{id}}/payment-file"): ROLES(UserRole.hr_admin),
        ("GET", STATS): ROLES(UserRole.super_admin),
        ("GET", "/api/v1/regions"): "AUTHENTICATED",
    }
    for key, decision in expected.items():
        assert key in POLICY, f"B5: {key} is not in tests/security/route_policy.py"
        assert POLICY[key] == decision, f"B5: {key}: {POLICY[key]} != {decision}"
    for key in COMPANY_ROUTES:
        decision = POLICY.get(key)
        if isinstance(decision, tuple):
            assert UserRole.super_admin not in decision, (
                f"B5: {key} still allows super_admin in the policy"
            )


# ------------------------------------------------------------------- B6


def test_B6_other_personal_data_outside_payroll_is_not_changed_here(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    # Profile and documents are other modules; a super admin can still reach them today and
    # that is listed as an open item, not changed by this package.
    resp = client.get("/api/v1/employees", headers=super_admin_headers)
    assert resp.status_code == 200, f"B6: the employee directory is unchanged: {resp.status_code}"
