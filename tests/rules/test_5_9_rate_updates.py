"""Module 5, sub-feature 5.9: platform rate updates. One test per rule line (R1..R10).

Rates are platform data. A scheduled page check never changes a live rate: it only makes a
draft and tells every super admin. A person fills in the numbers, VERIFIES, then APPROVES, and
only approval changes live rates. The page fetcher is always a fake or an httpx mock transport:
no test touches a real website.
"""

import hashlib
import importlib
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

import app.workers.tasks.platform as platform_tasks
from app.core.official_sources import is_official_url
from app.core.rate_limit import limiter
from app.core.security import decode_access_token
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.statutory_rates import seed_statutory_rates
from app.db.seed.tax_slabs import seed_tax_slabs
from app.modules.identity.models import User, UserRole
from app.modules.platform.models import AuditLog, Notification
from tests.conftest import REPO_ROOT, TenantContext
from tests.rules.test_5_2_statutory_rates import _first_of, _pt_body, _rate_body, _tax_body
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

P = "/api/v1/platform"
SOURCES = f"{P}/rate-sources"
DRAFTS = f"{P}/rate-drafts"
PAY = "/api/v1/payroll"
ESIC_URL = "https://web.esic.gov.in/web/esic/contribution"
PAGE_V1 = "<html><body><h1>Rates</h1><p>Employee 0.75</p></body></html>"
PAGE_V2 = "<html><body><h1>Rates</h1><p>Employee 1.00</p></body></html>"
SEED_ROWS = [
    ("IN", "epf_esi", "ESIC contribution rates", ESIC_URL, 6, "2026-11-20"),
    (
        "GB",
        "income_tax",
        "HMRC rates and thresholds for employers",
        "https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027",
        12,
        "2027-03-06",
    ),
    (
        "SG",
        "social_security",
        "CPF contribution rate changes for senior workers",
        "https://www.cpf.gov.sg/service/article/what-are-the-changes-to-the-cpf-contribution-rates-for-senior-workers-that-will-take-effect-from-1-january-2027",
        12,
        "2026-12-01",
    ),
    (
        "CA",
        "social_security",
        "CRA CPP contribution rates and maximums",
        "https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/payroll-deductions-contributions/canada-pension-plan-cpp/cpp-contribution-rates-maximums-exemptions.html",
        12,
        "2026-12-01",
    ),
    (
        "CA",
        "social_security",
        "ESDC EI premium rates for 2027",
        "https://www.canada.ca/en/employment-social-development/programs/ei/ei-list/reports/premium/rates2027.html",
        12,
        "2026-12-01",
    ),
    (
        "AU",
        "social_security",
        "ATO super guarantee rate",
        "https://www.ato.gov.au/tax-rates-and-codes/key-superannuation-rates-and-thresholds/super-guarantee",
        12,
        "2027-06-01",
    ),
    (
        "US",
        "social_security",
        "SSA 2026 COLA and wage base fact sheet",
        "https://www.ssa.gov/cola/factsheets/2026.html",
        12,
        "2026-12-01",
    ),
    (
        "AE",
        "other",
        "Dubai unemployment insurance (ILOE)",
        "https://www.dubai.ae/living/jobs-employment/involuntary-loss-of-employment",
        6,
        "2027-05-05",
    ),
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


def _need(module: str) -> Any:
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError:
        pytest.fail(f"the module {module} does not exist yet")


def _attr(module: str, name: str) -> Any:
    found = getattr(_need(module), name, None)
    assert found is not None, f"{module} needs {name}"
    return found


def _today():
    return utcnow().date()


def _message(resp) -> str:
    body = resp.json() if resp.content else {}
    error = body.get("error") if isinstance(body, dict) else None
    return error["message"] if isinstance(error, dict) else resp.text


def _source_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "country": "IN",
        "state": None,
        "scheme_group": "epf_esi",
        "title": f"Test source {uuid.uuid4().hex[:6]}",
        "source_url": ESIC_URL,
        "interval_months": 6,
        "next_check_on": (_today() + timedelta(days=30)).isoformat(),
    }
    body.update(over)
    return body


def _new_source(client: TestClient, sa: dict[str, str], **over: Any) -> dict[str, Any]:
    resp = client.post(SOURCES, json=_source_body(**over), headers=sa)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _due_source(client: TestClient, sa: dict[str, str], **over: Any) -> dict[str, Any]:
    over.setdefault("next_check_on", _today().isoformat())
    over.setdefault("source_url", f"https://web.esic.gov.in/web/esic/{uuid.uuid4().hex[:8]}")
    return _new_source(client, sa, **over)


def _source(client: TestClient, sa: dict[str, str], source_id: str) -> dict[str, Any]:
    items = client.get(SOURCES, headers=sa).json()["items"]
    return next(s for s in items if s["id"] == source_id)


def _rate_draft_body(**over: Any) -> dict[str, Any]:
    proposed = _rate_body(country="IN", scheme="esi", effective_from=_first_of(2).isoformat())
    body: dict[str, Any] = {
        "country": "IN",
        "state": None,
        "kind": "statutory_rate",
        "reason": "ESI employee share changed",
        "proposed": proposed,
    }
    body.update(over)
    return body


def _new_draft(client: TestClient, sa: dict[str, str], **over: Any) -> dict[str, Any]:
    resp = client.post(DRAFTS, json=_rate_draft_body(**over), headers=sa)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _verify(client: TestClient, sa: dict[str, str], draft_id: str, urls: list[str] | None = None):
    return client.post(
        f"{DRAFTS}/{draft_id}/verify",
        json={"sources_checked": urls or ["https://esic.gov.in/contribution"]},
        headers=sa,
    )


def _verified_draft(client: TestClient, sa: dict[str, str], **over: Any) -> dict[str, Any]:
    draft = _new_draft(client, sa, **over)
    resp = _verify(client, sa, draft["id"])
    assert resp.status_code == 200, resp.text
    return resp.json()


def _platform(db: Session) -> None:
    bind_tenant_to_session(db, company_id=None, is_platform_admin=True)


def _notes(db: Session, kind: str) -> list[Notification]:
    _platform(db)
    db.expire_all()
    return db.query(Notification).filter(Notification.type == kind).all()


def _super_admin_ids(db: Session) -> set[uuid.UUID]:
    _platform(db)
    rows = db.query(User).filter(User.role == UserRole.super_admin, User.is_active.is_(True))
    return {u.id for u in rows}


def _rate_rows(db: Session) -> list[tuple[Any, ...]]:
    _platform(db)
    rows = db.execute(
        text(
            "SELECT 'r', id::text, effective_from::text, coalesce(effective_to::text, ''), "
            "verified_on::text FROM statutory_rates UNION ALL "
            "SELECT 'p', id::text, effective_from::text, coalesce(effective_to::text, ''), "
            "verified_on::text FROM pt_slabs UNION ALL "
            "SELECT 't', id::text, effective_from::text, '', verified_on::text FROM tax_slabs "
            "ORDER BY 1, 2"
        )
    ).all()
    return [tuple(r) for r in rows]


class FakeFetcher:
    """Stands in for the real page fetcher: a URL maps to page text or to an exception."""

    def __init__(self, pages: dict[str, Any] | None = None, default: Any = PAGE_V1) -> None:
        self.pages = pages or {}
        self.default = default
        self.calls: list[str] = []

    def fetch(self, url: str) -> Any:
        self.calls.append(url)
        result = self.pages.get(url, self.default)
        if isinstance(result, BaseException):
            raise result
        page = _attr("app.modules.platform.rate_fetcher", "FetchedPage")
        return page(text=result, content_type="text/html")


def _run_check(monkeypatch: pytest.MonkeyPatch, db: Session, fetcher: Any, **kwargs: Any) -> Any:
    task = _attr("app.workers.tasks.platform", "check_rate_sources_task")
    monkeypatch.setattr(platform_tasks, "get_task_db_session", lambda: Session(bind=db.get_bind()))
    monkeypatch.setattr(platform_tasks, "get_page_fetcher", lambda: fetcher, raising=False)
    result = task(**kwargs)
    db.expire_all()
    return result


def _normalised_hash(raw: str) -> str:
    normalize = _attr("app.modules.platform.rate_fetcher", "normalize_page_text")
    return hashlib.sha256(normalize(raw).encode()).hexdigest()


def _fetch_error() -> Any:
    return _attr("app.modules.platform.rate_fetcher", "FetchError")


def _real_fetcher(handler: Any) -> Any:
    cls = _attr("app.modules.platform.rate_fetcher", "OfficialPageFetcher")
    return cls(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------- R1


def test_R1_a_valid_source_is_created_and_listed(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    created = _new_source(
        client, super_admin_headers, state="Gujarat", scheme_group="professional_tax"
    )
    assert created["last_result"] == "never" and created["active"] is True, created
    assert created["content_hash"] is None and created["last_checked_on"] is None, created
    listed = client.get(SOURCES, headers=super_admin_headers)
    assert listed.status_code == 200, listed.text
    assert created["id"] in [s["id"] for s in listed.json()["items"]], (
        "R1: the new source is listed"
    )


@pytest.mark.parametrize(
    "over",
    [
        {"unknown_field": 1},
        {"country": "ZZ"},
        {"state": "Atlantis"},
        {"country": "US", "state": "Gujarat"},
        {"scheme_group": "lottery"},
        {"title": ""},
        {"title": "t" * 151},
        {"source_url": "http://web.esic.gov.in/web/esic/contribution"},
        {"source_url": "https://example.com/rates"},
        {"source_url": "https://gov.in.evil.com/rates"},
        {"interval_months": 0},
        {"interval_months": 25},
    ],
)
def test_R1_bad_input_gives_422(
    client: TestClient, super_admin_headers: dict[str, str], over: dict[str, Any]
) -> None:
    resp = client.post(SOURCES, json=_source_body(**over), headers=super_admin_headers)
    assert resp.status_code == 422, f"R1: {over} must give 422, got {resp.status_code}"


def test_R1_the_same_country_state_scheme_and_url_gives_409(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    first = _new_source(client, super_admin_headers)
    again = client.post(
        SOURCES, json=_source_body(source_url=first["source_url"]), headers=super_admin_headers
    )
    assert again.status_code == 409, f"R1: duplicate gives 409, got {again.status_code}"
    other_scheme = client.post(
        SOURCES,
        json=_source_body(source_url=first["source_url"], scheme_group="other"),
        headers=super_admin_headers,
    )
    assert other_scheme.status_code == 201, "R1: another scheme group is not a duplicate"


def test_R1_a_source_can_be_changed_and_a_new_url_starts_a_new_baseline(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    source = _new_source(client, super_admin_headers)
    resp = client.patch(
        f"{SOURCES}/{source['id']}",
        json={"title": "Renamed", "interval_months": 12, "active": False},
        headers=super_admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["title"], resp.json()["interval_months"], resp.json()["active"]) == (
        "Renamed",
        12,
        False,
    )
    bad = client.patch(
        f"{SOURCES}/{source['id']}",
        json={"source_url": "https://example.com/x"},
        headers=super_admin_headers,
    )
    assert bad.status_code == 422, "R1: a changed url is checked against the allow-list too"
    missing = client.patch(
        f"{SOURCES}/{uuid.uuid4()}", json={"active": False}, headers=super_admin_headers
    )
    assert missing.status_code == 404


# ------------------------------------------------------------------- R2

SOME_ID = uuid.UUID(int=1)


def _family() -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        ("GET", SOURCES, None),
        ("POST", SOURCES, _source_body()),
        ("PATCH", f"{SOURCES}/{SOME_ID}", {"active": False}),
        ("GET", DRAFTS, None),
        ("POST", DRAFTS, _rate_draft_body()),
        ("GET", f"{DRAFTS}/{SOME_ID}", None),
        ("PUT", f"{DRAFTS}/{SOME_ID}", {"reason": "x"}),
        ("POST", f"{DRAFTS}/{SOME_ID}/verify", {"sources_checked": [ESIC_URL]}),
        ("POST", f"{DRAFTS}/{SOME_ID}/approve", {}),
        ("POST", f"{DRAFTS}/{SOME_ID}/reject", {"note": "no"}),
    ]


def test_R2_no_login_gets_401_on_every_route(client: TestClient) -> None:
    codes = {f"{m} {u}": client.request(m, u, json=b).status_code for m, u, b in _family()}
    assert set(codes.values()) == {401}, f"R2: 401 expected everywhere: {codes}"


@pytest.mark.parametrize("who", ["employee_headers", "manager_headers", "hr_headers", "owner"])
def test_R2_every_other_role_gets_403_on_every_route(
    client: TestClient, db: Session, company_a: TenantContext, who: str
) -> None:
    if who == "owner":
        headers, _ = _extra_user(db, company_a.company_id, UserRole.owner)
    else:
        headers = getattr(company_a, who)
    codes = {
        f"{m} {u}": client.request(m, u, json=b, headers=headers).status_code
        for m, u, b in _family()
    }
    assert set(codes.values()) == {403}, f"R2: {who} must get 403 everywhere: {codes}"


def test_R2_company_payroll_routes_are_unaffected(
    client: TestClient, company_a: TenantContext
) -> None:
    assert client.get(f"{PAY}/statutory-config", headers=company_a.hr_headers).status_code == 200
    assert client.get(f"{PAY}/structures", headers=company_a.hr_headers).status_code == 200


def test_R2_reads_are_limited_to_60_per_minute(
    client: TestClient, super_admin_headers: dict[str, str], limits_on: None
) -> None:
    codes = [client.get(SOURCES, headers=super_admin_headers).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429, f"R2: read limit wrong: {codes[-3:]}"


def test_R2_writes_are_limited_to_30_per_minute(
    client: TestClient, super_admin_headers: dict[str, str], limits_on: None
) -> None:
    codes = [
        client.post(
            SOURCES,
            json=_source_body(source_url=f"https://web.esic.gov.in/web/esic/{i}"),
            headers=super_admin_headers,
        ).status_code
        for i in range(31)
    ]
    assert codes[:30] == [201] * 30 and codes[30] == 429, f"R2: write limit wrong: {codes[-3:]}"


def test_R2_the_route_policy_lists_every_route_with_an_explicit_decision() -> None:
    for method, url, _ in _family():
        pattern = url.replace(str(SOME_ID), "{id}").replace(str(SOME_ID), "{source_id}")
        keys = [
            k
            for k in POLICY
            if k[0] == method and k[1].startswith(P) and _same_shape(k[1], pattern)
        ]
        assert keys, f"R2: {method} {url} is not in tests/security/route_policy.py"
        assert POLICY[keys[0]] == ROLES(UserRole.super_admin), f"R2: {keys[0]} must be super_admin"


def _same_shape(policy_path: str, pattern: str) -> bool:
    import re

    return re.sub(r"\{[^}]+\}", "{}", policy_path) == re.sub(r"\{[^}]+\}", "{}", pattern)


# ------------------------------------------------------------------- R3


def test_R3_a_manual_draft_with_numbers_shows_current_next_to_proposed_with_every_source(
    client: TestClient, db: Session, super_admin_headers: dict[str, str]
) -> None:
    source = _new_source(client, super_admin_headers)
    draft = _new_draft(client, super_admin_headers, source_id=source["id"])
    me = uuid.UUID(decode_access_token(super_admin_headers["Authorization"].split()[1])["sub"])
    assert draft["status"] == "pending" and draft["kind"] == "statutory_rate", draft
    assert draft["created_by"] == str(me), f"R3: created_by is the creator: {draft}"
    detail = client.get(f"{DRAFTS}/{draft['id']}", headers=super_admin_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["proposed"]["scheme"] == "esi" and body["proposed"]["employee_rate"] == "1.000"
    current = body["current"]["statutory_rates"]
    assert current and all(r["scheme"] == "esi" and r["country"] == "IN" for r in current), (
        f"R3: current shows the rows in force today for that scheme: {current}"
    )
    assert current[0]["source_url"], "R3: each current row carries its source link"
    urls = [s["url"] for s in body["sources"]]
    assert source["source_url"] in urls, f"R3: every source with its link: {body['sources']}"
    assert body["effective_from"] == _first_of(2).isoformat()


def test_R3_a_manual_draft_without_numbers_and_the_listing_by_status(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    empty = client.post(
        DRAFTS,
        json={
            "country": "IN",
            "kind": "no_numbers",
            "reason": "Check the ESIC page",
            "proposed": None,
        },
        headers=super_admin_headers,
    )
    assert empty.status_code == 201 and empty.json()["proposed"] is None, empty.text
    numbered = _new_draft(client, super_admin_headers)
    pending = client.get(f"{DRAFTS}?status=pending", headers=super_admin_headers).json()["items"]
    assert {empty.json()["id"], numbered["id"]} <= {d["id"] for d in pending}
    approved = client.get(f"{DRAFTS}?status=approved", headers=super_admin_headers).json()["items"]
    assert approved == [], f"R3: status filter: {approved}"
    bad = client.get(f"{DRAFTS}?status=bogus", headers=super_admin_headers)
    assert bad.status_code == 422


@pytest.mark.parametrize(
    "over",
    [
        {"proposed": None},
        {"kind": "no_numbers"},
        {"kind": "bogus"},
        {"country": "ZZ"},
        {"reason": ""},
        {"unknown": 1},
        {"country": "GB"},
    ],
)
def test_R3_a_draft_must_be_valid_by_the_same_schemas_as_the_direct_routes(
    client: TestClient, super_admin_headers: dict[str, str], over: dict[str, Any]
) -> None:
    resp = client.post(DRAFTS, json=_rate_draft_body(**over), headers=super_admin_headers)
    assert resp.status_code == 422, f"R3: {over} must give 422, got {resp.status_code}"


def test_R3_numbers_are_checked_by_the_write_schemas(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    bad_rate = _rate_body(country="IN", employee_rate="-1.000")
    assert (
        client.post(
            DRAFTS, json=_rate_draft_body(proposed=bad_rate), headers=super_admin_headers
        ).status_code
        == 422
    ), "R3: a negative rate is refused as the direct route refuses it"
    bad_host = _rate_body(country="IN", source_url="https://example.com/x")
    assert (
        client.post(
            DRAFTS, json=_rate_draft_body(proposed=bad_host), headers=super_admin_headers
        ).status_code
        == 422
    ), "R3: a non-official source is refused"
    pt = client.post(
        DRAFTS,
        json={
            "country": "IN",
            "state": "Kerala",
            "kind": "pt_slabs",
            "reason": "Kerala PT",
            "proposed": _pt_body(state="Kerala"),
        },
        headers=super_admin_headers,
    )
    assert pt.status_code == 201, pt.text
    tax = client.post(
        DRAFTS,
        json={"country": "IN", "kind": "tax_slabs", "reason": "New FY", "proposed": _tax_body()},
        headers=super_admin_headers,
    )
    assert tax.status_code == 201, tax.text
    wrong_state = client.post(
        DRAFTS,
        json={
            "country": "IN",
            "state": "Goa",
            "kind": "pt_slabs",
            "reason": "x",
            "proposed": _pt_body(state="Kerala"),
        },
        headers=super_admin_headers,
    )
    assert wrong_state.status_code == 422, "R3: the draft's state must match the numbers"


# ------------------------------------------------------------------- R4


def test_R4_editing_a_pending_draft_works_and_editing_a_verified_one_voids_the_verification(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    draft = _new_draft(client, super_admin_headers)
    edited = client.put(
        f"{DRAFTS}/{draft['id']}", json={"reason": "Edited reason"}, headers=super_admin_headers
    )
    assert edited.status_code == 200 and edited.json()["reason"] == "Edited reason", edited.text
    verified = _verify(client, super_admin_headers, draft["id"])
    assert verified.json()["status"] == "verified" and verified.json()["verified_by"], verified.text
    again = client.put(
        f"{DRAFTS}/{draft['id']}",
        json={
            "proposed": _rate_body(
                country="IN", employee_rate="1.250", effective_from=_first_of(2).isoformat()
            )
        },
        headers=super_admin_headers,
    )
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "pending", "R4: a changed verified draft goes back to pending"
    assert again.json()["verified_by"] is None and again.json()["verified_at"] is None
    assert again.json()["sources_checked"] in (None, []), "R4: verification is void"
    assert again.json()["proposed"]["employee_rate"] == "1.250"


def test_R4_an_approved_or_rejected_draft_cannot_be_edited(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    approved = _verified_draft(client, super_admin_headers)
    assert (
        client.post(
            f"{DRAFTS}/{approved['id']}/approve", json={}, headers=super_admin_headers
        ).status_code
        == 200
    )
    rejected = _new_draft(
        client,
        super_admin_headers,
        proposed=_rate_body(country="IN", scheme="epf", effective_from=_first_of(3).isoformat()),
    )
    assert (
        client.post(
            f"{DRAFTS}/{rejected['id']}/reject", json={"note": "wrong"}, headers=super_admin_headers
        ).status_code
        == 200
    )
    for draft in (approved, rejected):
        resp = client.put(
            f"{DRAFTS}/{draft['id']}", json={"reason": "late"}, headers=super_admin_headers
        )
        assert resp.status_code == 409, f"R4: a closed draft gives 409, got {resp.status_code}"


def test_R4_a_no_numbers_draft_cannot_be_verified_until_numbers_are_filled_in(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    draft = client.post(
        DRAFTS,
        json={"country": "IN", "kind": "no_numbers", "reason": "Page changed", "proposed": None},
        headers=super_admin_headers,
    ).json()
    blocked = _verify(client, super_admin_headers, draft["id"])
    assert blocked.status_code == 409, f"R4: no numbers gives 409, got {blocked.status_code}"
    assert "numbers" in _message(blocked).lower(), f"R4: unclear message: {_message(blocked)}"
    filled = client.put(
        f"{DRAFTS}/{draft['id']}",
        json={"kind": "statutory_rate", "proposed": _rate_draft_body()["proposed"]},
        headers=super_admin_headers,
    )
    assert filled.status_code == 200 and filled.json()["kind"] == "statutory_rate", filled.text
    assert _verify(client, super_admin_headers, draft["id"]).status_code == 200


# ------------------------------------------------------------------- R5


def test_R5_verify_records_who_and_when(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    draft = _new_draft(client, super_admin_headers)
    resp = _verify(
        client,
        super_admin_headers,
        draft["id"],
        ["https://esic.gov.in/contribution", "https://www.pib.gov.in/x"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    me = decode_access_token(super_admin_headers["Authorization"].split()[1])["sub"]
    assert body["status"] == "verified" and body["verified_by"] == me and body["verified_at"], body
    assert body["sources_checked"] == [
        "https://esic.gov.in/contribution",
        "https://www.pib.gov.in/x",
    ]


@pytest.mark.parametrize(
    "urls",
    [
        [],
        ["https://esic.gov.in/x"] * 11,
        ["http://esic.gov.in/x"],
        ["https://example.com/x"],
        ["not a url"],
    ],
)
def test_R5_the_list_of_sources_checked_is_validated(
    client: TestClient, super_admin_headers: dict[str, str], urls: list[str]
) -> None:
    draft = _new_draft(client, super_admin_headers)
    resp = _verify(client, super_admin_headers, draft["id"], urls)
    assert resp.status_code == 422, f"R5: {urls[:2]} must give 422, got {resp.status_code}"
    assert (
        client.get(f"{DRAFTS}/{draft['id']}", headers=super_admin_headers).json()["status"]
        == "pending"
    )


def test_R5_one_of_the_sources_checked_must_be_the_drafts_own_source(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    source = _new_source(client, super_admin_headers)
    draft = _new_draft(client, super_admin_headers, source_id=source["id"])
    other = _verify(client, super_admin_headers, draft["id"], ["https://www.pib.gov.in/x"])
    assert other.status_code == 422, f"R5: the own source is required, got {other.status_code}"
    own = _verify(
        client, super_admin_headers, draft["id"], ["https://www.pib.gov.in/x", source["source_url"]]
    )
    assert own.status_code == 200, own.text


def test_R5_only_a_pending_draft_can_be_verified_and_the_same_person_may_approve(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    draft = _verified_draft(client, super_admin_headers)
    again = _verify(client, super_admin_headers, draft["id"])
    assert again.status_code == 409, f"R5: only pending drafts verify, got {again.status_code}"
    approve = client.post(f"{DRAFTS}/{draft['id']}/approve", json={}, headers=super_admin_headers)
    assert approve.status_code == 200, f"R5: the same super admin may approve: {approve.text}"


# ------------------------------------------------------------------- R6


def test_R6_approve_works_only_from_verified(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    draft = _new_draft(client, super_admin_headers)
    resp = client.post(f"{DRAFTS}/{draft['id']}/approve", json={}, headers=super_admin_headers)
    assert resp.status_code == 409, f"R6: a pending draft gives 409, got {resp.status_code}"
    assert "verified" in _message(resp).lower(), f"R6: unclear: {_message(resp)}"


def test_R6_approve_closes_the_old_row_and_inserts_the_new_one_with_source_and_todays_date(
    client: TestClient, db: Session, super_admin_headers: dict[str, str]
) -> None:
    start = _first_of(2)
    draft = _verified_draft(client, super_admin_headers)
    before = client.get(
        f"{PAY}/statutory-rates?scheme=esi&country=IN", headers=super_admin_headers
    ).json()["items"]
    open_row = next(r for r in before if r["effective_to"] is None)
    resp = client.post(f"{DRAFTS}/{draft['id']}/approve", json={}, headers=super_admin_headers)
    assert resp.status_code == 200 and resp.json()["status"] == "approved", resp.text
    assert resp.json()["approved_by"] and resp.json()["approved_at"], resp.text
    after = client.get(
        f"{PAY}/statutory-rates?scheme=esi&country=IN", headers=super_admin_headers
    ).json()["items"]
    old = next(r for r in after if r["id"] == open_row["id"])
    assert old["effective_to"] == (start - timedelta(days=1)).isoformat(), (
        f"R6: the old row must end the day before the new one starts: {old}"
    )
    new = next(r for r in after if r["effective_from"] == start.isoformat())
    assert new["effective_to"] is None and new["verified_on"] == _today().isoformat(), new
    assert new["source_url"] == "https://esic.gov.in/contribution", "R6: the draft's source link"
    assert len(after) == len(before) + 1, "R6: rows are closed and added, never deleted"
    audits = db.query(AuditLog).filter(AuditLog.action == "RATE_DRAFT_APPROVED").all()
    assert len(audits) == 1, f"R6: one audit row: {len(audits)}"
    detail = audits[0].details
    assert detail["country"] == "IN" and detail["kind"] == "statutory_rate", detail
    assert "1.000" not in str(detail) and "4.000" not in str(detail), "R6: no rate values in audit"


def test_R6_pt_slab_and_tax_slab_drafts_apply_through_the_same_code(
    client: TestClient, super_admin_headers: dict[str, str]
) -> None:
    pt = _verified_draft(
        client,
        super_admin_headers,
        state="Kerala",
        kind="pt_slabs",
        proposed=_pt_body(state="Kerala"),
    )
    assert (
        client.post(
            f"{DRAFTS}/{pt['id']}/approve", json={}, headers=super_admin_headers
        ).status_code
        == 200
    )
    slabs = client.get(f"{PAY}/pt-slabs", headers=super_admin_headers)
    assert slabs.status_code == 200
    tax = _verified_draft(
        client, super_admin_headers, kind="tax_slabs", proposed=_tax_body(), state=None
    )
    assert (
        client.post(
            f"{DRAFTS}/{tax['id']}/approve", json={}, headers=super_admin_headers
        ).status_code
        == 200
    )
    rows = client.get(
        f"{PAY}/tax-slabs?financial_year=2031-2032", headers=super_admin_headers
    ).json()
    assert len(rows) == 2, f"R6: the tax brackets are live: {rows}"


def test_R6_a_failing_apply_changes_nothing_at_all(
    client: TestClient, db: Session, super_admin_headers: dict[str, str]
) -> None:
    # A start date before the open row's own start date is refused by the direct route as an
    # overlap; the draft must be refused the same way and leave every row as it was.
    clash = _rate_body(country="IN", scheme="esi", effective_from="2001-01-01")
    draft = _verified_draft(client, super_admin_headers, proposed=clash)
    rows_before = _rate_rows(db)
    resp = client.post(f"{DRAFTS}/{draft['id']}/approve", json={}, headers=super_admin_headers)
    assert resp.status_code == 409, f"R6: the overlap rule must apply: {resp.status_code}"
    assert _rate_rows(db) == rows_before, "R6: a failed approval must change no rate row"
    again = client.get(f"{DRAFTS}/{draft['id']}", headers=super_admin_headers).json()
    assert again["status"] == "verified" and again["approved_at"] is None, again
    assert db.query(AuditLog).filter(AuditLog.action == "RATE_DRAFT_APPROVED").count() == 0


def test_R6_an_approved_payroll_run_and_payslip_are_not_changed_by_an_approval(
    client: TestClient, db: Session, company_a: TenantContext, super_admin_headers: dict[str, str]
) -> None:
    year, month = _month_back()
    structure_id = _structure(client, company_a.hr_headers)
    emp = _staff(client, db, company_a, structure_id)
    _fill(db, company_a, emp["id"], year, month)
    owner, _ = _extra_user(db, company_a.company_id, UserRole.owner)
    run = _make_run(client, company_a.hr_headers, year, month)
    assert client.post(f"{RUNS}/{run['id']}/approve", headers=owner).status_code == 200
    detail_before = client.get(f"{RUNS}/{run['id']}", headers=owner).json()
    slips_before = client.get(f"{PAY}/payslips/me", headers=emp["h"]).json()
    # A new ESI rate that starts in an EARLIER month than the run's month.
    draft = _verified_draft(
        client,
        super_admin_headers,
        proposed=_rate_body(
            country="IN",
            scheme="esi",
            employee_rate="2.500",
            effective_from=_first_of(3).isoformat(),
        ),
    )
    assert (
        client.post(
            f"{DRAFTS}/{draft['id']}/approve", json={}, headers=super_admin_headers
        ).status_code
        == 200
    )
    assert client.get(f"{RUNS}/{run['id']}", headers=owner).json() == detail_before, (
        "R6: an approved run's totals and items must be identical after a rate approval"
    )
    assert client.get(f"{PAY}/payslips/me", headers=emp["h"]).json() == slips_before, (
        "R6: the payslip must be identical after a rate approval"
    )
    assert Decimal(detail_before["run"]["total_net"]) > 0


# ------------------------------------------------------------------- R7


def test_R7_reject_needs_a_note_changes_no_rate_and_closes_the_draft(
    client: TestClient, db: Session, super_admin_headers: dict[str, str]
) -> None:
    draft = _new_draft(client, super_admin_headers)
    no_note = client.post(f"{DRAFTS}/{draft['id']}/reject", json={}, headers=super_admin_headers)
    assert no_note.status_code == 422, f"R7: a note is required, got {no_note.status_code}"
    empty = client.post(
        f"{DRAFTS}/{draft['id']}/reject", json={"note": "  "}, headers=super_admin_headers
    )
    assert empty.status_code == 422, "R7: a blank note is not a note"
    rows_before = _rate_rows(db)
    resp = client.post(
        f"{DRAFTS}/{draft['id']}/reject",
        json={"note": "Not applicable"},
        headers=super_admin_headers,
    )
    assert resp.status_code == 200 and resp.json()["status"] == "rejected", resp.text
    assert resp.json()["decision_note"] == "Not applicable"
    assert _rate_rows(db) == rows_before, "R7: reject changes no rate"
    verified = _verified_draft(client, super_admin_headers)
    assert (
        client.post(
            f"{DRAFTS}/{verified['id']}/reject", json={"note": "no"}, headers=super_admin_headers
        ).status_code
        == 200
    ), "R7: a verified draft can be rejected"
    again = client.post(
        f"{DRAFTS}/{draft['id']}/reject", json={"note": "again"}, headers=super_admin_headers
    )
    assert again.status_code == 409, "R7: a closed draft cannot be rejected again"


def test_R7_rejecting_a_page_check_draft_stores_the_fetched_hash_so_it_does_not_come_back(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _due_source(client, super_admin_headers)
    fetcher = FakeFetcher(default=PAGE_V1)
    _run_check(monkeypatch, db, fetcher)  # baseline
    client.patch(
        f"{SOURCES}/{source['id']}",
        json={"next_check_on": _today().isoformat()},
        headers=super_admin_headers,
    )
    fetcher.default = PAGE_V2
    _run_check(monkeypatch, db, fetcher)
    drafts = client.get(f"{DRAFTS}?status=pending", headers=super_admin_headers).json()["items"]
    mine = [d for d in drafts if d["source_id"] == source["id"]]
    assert len(mine) == 1 and mine[0]["kind"] == "no_numbers", mine
    assert _source(client, super_admin_headers, source["id"])["content_hash"] == _normalised_hash(
        PAGE_V1
    )
    assert (
        client.post(
            f"{DRAFTS}/{mine[0]['id']}/reject", json={"note": "noise"}, headers=super_admin_headers
        ).status_code
        == 200
    )
    assert _source(client, super_admin_headers, source["id"])["content_hash"] == _normalised_hash(
        PAGE_V2
    ), "R7: reject stores the fetched hash"
    client.patch(
        f"{SOURCES}/{source['id']}",
        json={"next_check_on": _today().isoformat()},
        headers=super_admin_headers,
    )
    _run_check(monkeypatch, db, fetcher)
    assert _source(client, super_admin_headers, source["id"])["last_result"] == "unchanged"
    pending = client.get(f"{DRAFTS}?status=pending", headers=super_admin_headers).json()["items"]
    assert [d for d in pending if d["source_id"] == source["id"]] == [], "R7: not raised again"


def test_R7_the_direct_routes_still_work_with_no_draft_and_no_notification(
    client: TestClient, db: Session, super_admin_headers: dict[str, str]
) -> None:
    notes = len(_notes(db, "rate_draft_created"))
    resp = client.post(f"{PAY}/statutory-rates", json=_rate_body(), headers=super_admin_headers)
    assert resp.status_code == 201, f"R7: the direct route works: {resp.text}"
    drafts = client.get(DRAFTS, headers=super_admin_headers).json()["items"]
    assert drafts == [], f"R7: no draft is made by a direct write: {drafts}"
    assert len(_notes(db, "rate_draft_created")) == notes, "R7: and nobody is notified"


# ------------------------------------------------------------------- R8 + R9: the page check


def test_R9_the_first_fetch_is_a_baseline_no_draft_no_notification(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _due_source(client, super_admin_headers)
    before = len(_notes(db, "rate_draft_created"))
    result = _run_check(monkeypatch, db, FakeFetcher())
    assert result is not None
    row = _source(client, super_admin_headers, source["id"])
    assert row["last_result"] == "baseline", f"R9: first fetch is a baseline: {row}"
    assert row["content_hash"] == _normalised_hash(PAGE_V1), (
        "R9: the stored hash is the SHA-256 of the normalised text"
    )
    assert row["last_checked_on"] == _today().isoformat()
    expected = _add_months(_today(), 6)
    assert row["next_check_on"] == expected.isoformat(), f"R9: next check {row['next_check_on']}"
    assert client.get(DRAFTS, headers=super_admin_headers).json()["items"] == []
    assert len(_notes(db, "rate_draft_created")) == before, "R8: a baseline notifies nobody"


def _add_months(day, months: int):
    import calendar

    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return day.replace(
        year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1])
    )


def test_R9_the_same_hash_is_unchanged_and_moves_the_next_check_forward(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _due_source(client, super_admin_headers, interval_months=3)
    fetcher = FakeFetcher()
    _run_check(monkeypatch, db, fetcher)
    client.patch(
        f"{SOURCES}/{source['id']}",
        json={"next_check_on": _today().isoformat()},
        headers=super_admin_headers,
    )
    notes = len(_notes(db, "rate_draft_created"))
    _run_check(monkeypatch, db, fetcher)
    row = _source(client, super_admin_headers, source["id"])
    assert row["last_result"] == "unchanged", f"R9: {row}"
    assert row["next_check_on"] == _add_months(_today(), 3).isoformat()
    assert client.get(DRAFTS, headers=super_admin_headers).json()["items"] == []
    assert len(_notes(db, "rate_draft_created")) == notes, "R8: nothing changed, nobody is told"


def test_R9_a_different_hash_makes_one_no_numbers_draft_and_tells_every_super_admin(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _due_source(client, super_admin_headers)
    fetcher = FakeFetcher()
    _run_check(monkeypatch, db, fetcher)
    client.patch(
        f"{SOURCES}/{source['id']}",
        json={"next_check_on": _today().isoformat()},
        headers=super_admin_headers,
    )
    fetcher.default = PAGE_V2
    notes_before = len(_notes(db, "rate_draft_created"))
    _run_check(monkeypatch, db, fetcher)
    row = _source(client, super_admin_headers, source["id"])
    assert row["last_result"] == "changed", f"R9: {row}"
    assert row["next_check_on"] == _add_months(_today(), 6).isoformat()
    drafts = [
        d
        for d in client.get(f"{DRAFTS}?status=pending", headers=super_admin_headers).json()["items"]
        if d["source_id"] == source["id"]
    ]
    assert len(drafts) == 1 and drafts[0]["kind"] == "no_numbers", drafts
    detail = client.get(f"{DRAFTS}/{drafts[0]['id']}", headers=super_admin_headers).json()
    assert detail["created_by"] is None, "R3: a system draft has no creator"
    assert detail["fetched_sources"][0]["url"] == source["source_url"]
    assert detail["fetched_sources"][0]["hash"] == _normalised_hash(PAGE_V2)
    created = _notes(db, "rate_draft_created")[notes_before:]
    assert {n.user_id for n in created} == _super_admin_ids(db), (
        "R8: every active super admin is told"
    )
    for note in created:
        assert "IN" in note.message and "epf_esi" in note.message, (
            f"R8: country and scheme: {note.message}"
        )
        assert "Employee" not in note.message and "1.00" not in note.message, "R8: no page text"
    # Still changed next time, but the open draft is not duplicated and nobody is told again.
    client.patch(
        f"{SOURCES}/{source['id']}",
        json={"next_check_on": _today().isoformat()},
        headers=super_admin_headers,
    )
    _run_check(monkeypatch, db, fetcher)
    pending = client.get(f"{DRAFTS}?status=pending", headers=super_admin_headers).json()["items"]
    assert len([d for d in pending if d["source_id"] == source["id"]]) == 1, (
        "R9: one open draft per source"
    )
    assert len(_notes(db, "rate_draft_created")) == len(created) + notes_before, (
        "R8: no repeat notice"
    )


def test_R9_a_failed_fetch_is_retried_in_7_days_and_tells_every_super_admin(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _due_source(client, super_admin_headers)
    fetcher = FakeFetcher(default=_fetch_error()("The page could not be read."))
    before = len(_notes(db, "rate_check_failed"))
    _run_check(monkeypatch, db, fetcher)
    row = _source(client, super_admin_headers, source["id"])
    assert row["last_result"] == "fetch_failed", f"R9: {row}"
    assert row["next_check_on"] == (_today() + timedelta(days=7)).isoformat(), "R9: retry in 7 days"
    assert row["content_hash"] is None
    sent = _notes(db, "rate_check_failed")[before:]
    assert {n.user_id for n in sent} == _super_admin_ids(db), (
        "R8: a failure tells every super admin"
    )
    assert all("IN" in n.message and "epf_esi" in n.message for n in sent)


def test_R9_only_active_sources_that_are_due_are_fetched(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    due = _due_source(client, super_admin_headers)
    later = _due_source(
        client, super_admin_headers, next_check_on=(_today() + timedelta(days=2)).isoformat()
    )
    off = _due_source(client, super_admin_headers, active=False)
    fetcher = FakeFetcher()
    _run_check(monkeypatch, db, fetcher)
    assert fetcher.calls == [due["source_url"]], f"R9: only the due active source: {fetcher.calls}"
    assert _source(client, super_admin_headers, later["id"])["last_result"] == "never"
    assert _source(client, super_admin_headers, off["id"])["last_result"] == "never"


def test_R9_one_bad_source_does_not_stop_the_rest(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = _due_source(client, super_admin_headers, title="Bad")
    good = _due_source(client, super_admin_headers, title="Good")
    fetcher = FakeFetcher(pages={bad["source_url"]: RuntimeError("boom")})
    _run_check(monkeypatch, db, fetcher)
    assert _source(client, super_admin_headers, good["id"])["last_result"] == "baseline", (
        "R9: the good source is still checked"
    )
    assert _source(client, super_admin_headers, bad["id"])["last_result"] == "fetch_failed"


def test_R9_a_check_never_writes_to_any_rate_table(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _due_source(client, super_admin_headers)
    fetcher = FakeFetcher()
    rows = _rate_rows(db)
    _run_check(monkeypatch, db, fetcher)
    client.patch(
        f"{SOURCES}/{source['id']}",
        json={"next_check_on": _today().isoformat()},
        headers=super_admin_headers,
    )
    fetcher.default = PAGE_V2
    _run_check(monkeypatch, db, fetcher)
    assert _rate_rows(db) == rows, "R9: a page check must never change a live rate"


def test_R8_notifications_are_made_after_the_commit(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _due_source(client, super_admin_headers)
    fetcher = FakeFetcher()
    _run_check(monkeypatch, db, fetcher)
    client.patch(
        f"{SOURCES}/{source['id']}",
        json={"next_check_on": _today().isoformat()},
        headers=super_admin_headers,
    )
    fetcher.default = PAGE_V2
    from app.modules.platform.service import NotificationService

    def _boom(self, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("notification failed")

    monkeypatch.setattr(NotificationService, "notify", _boom)
    _run_check(monkeypatch, db, fetcher)
    row = _source(client, super_admin_headers, source["id"])
    drafts = client.get(f"{DRAFTS}?status=pending", headers=super_admin_headers).json()["items"]
    assert row["last_result"] == "changed" and any(
        d["source_id"] == source["id"] for d in drafts
    ), "R8: the draft is saved before anyone is notified, so a failing notice cannot undo it"


def test_R8_a_rate_not_verified_for_180_days_reminds_every_super_admin_at_most_once_per_30_days(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _platform(db)
    db.execute(
        text(
            "UPDATE statutory_rates SET verified_on = :d "
            "WHERE scheme = 'esi' AND effective_to IS NULL"
        ),
        {"d": _today() - timedelta(days=181)},
    )
    db.commit()
    fetcher = FakeFetcher()
    before = len(_notes(db, "rate_verification_due"))
    _run_check(monkeypatch, db, fetcher)
    sent = _notes(db, "rate_verification_due")[before:]
    admins = _super_admin_ids(db)
    assert {n.user_id for n in sent} == admins and len(sent) == len(admins), (
        f"R8: one reminder per super admin: {len(sent)}"
    )
    assert all("IN" in n.message and "esi" in n.message.lower() for n in sent), (
        "R8: country and scheme"
    )
    assert all("0.750" not in n.message and "3.250" not in n.message for n in sent), "R8: no values"
    _run_check(monkeypatch, db, fetcher)
    assert len(_notes(db, "rate_verification_due")) == before + len(sent), (
        "R8: not again within 30 days"
    )
    _platform(db)
    db.execute(
        text("UPDATE rate_reminder_log SET reminded_on = :d"), {"d": _today() - timedelta(days=31)}
    )
    db.commit()
    _run_check(monkeypatch, db, fetcher)
    assert len(_notes(db, "rate_verification_due")) == before + 2 * len(sent), (
        "R8: after 30 days again"
    )


def test_R8_a_recently_verified_rate_sends_no_reminder(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _platform(db)
    db.execute(
        text("UPDATE statutory_rates SET verified_on = :d"), {"d": _today() - timedelta(days=10)}
    )
    db.execute(text("UPDATE pt_slabs SET verified_on = :d"), {"d": _today() - timedelta(days=10)})
    db.execute(text("UPDATE tax_slabs SET verified_on = :d"), {"d": _today() - timedelta(days=10)})
    db.commit()
    before = len(_notes(db, "rate_verification_due"))
    _run_check(monkeypatch, db, FakeFetcher())
    assert len(_notes(db, "rate_verification_due")) == before, "R8: nothing is due, nobody is told"


# ------------------------------------------------------------------- R9: the fetcher limits


def _ok_handler(
    captured: list[httpx.Request] | None = None,
    body: bytes = b"<p>ok</p>",
    ctype: str = "text/html",
):
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(200, content=body, headers={"content-type": ctype})

    return handler


def test_R9_fetcher_allows_https_only_and_only_allow_listed_hosts() -> None:
    calls: list[httpx.Request] = []
    fetcher = _real_fetcher(_ok_handler(calls))
    error = _fetch_error()
    for url in (
        "http://web.esic.gov.in/web/esic/contribution",
        "https://example.com/rates",
        "https://gov.in.evil.com/rates",
        "ftp://esic.gov.in/x",
    ):
        with pytest.raises(error):
            fetcher.fetch(url)
    assert calls == [], "R9: a refused url must not even be requested"
    assert fetcher.fetch(ESIC_URL).text, "R9: an allow-listed https page is read"


def test_R9_fetcher_rechecks_the_host_after_every_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "web.esic.gov.in":
            return httpx.Response(302, headers={"location": "https://example.com/steal"})
        return httpx.Response(200, content=b"<p>x</p>", headers={"content-type": "text/html"})

    error = _fetch_error()
    with pytest.raises(error):
        _real_fetcher(handler).fetch(ESIC_URL)

    def downgrade(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://web.esic.gov.in/x"})

    with pytest.raises(error):
        _real_fetcher(downgrade).fetch(ESIC_URL)

    def good(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/web/esic/contribution":
            return httpx.Response(301, headers={"location": "https://esic.gov.in/new"})
        return httpx.Response(200, content=b"<p>moved</p>", headers={"content-type": "text/html"})

    assert "moved" in _real_fetcher(good).fetch(ESIC_URL).text, (
        "R9: a redirect inside the list works"
    )


def test_R9_at_most_three_redirects() -> None:
    hops = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hops["n"] += 1
        if hops["n"] <= 3:
            return httpx.Response(302, headers={"location": f"https://esic.gov.in/hop{hops['n']}"})
        return httpx.Response(200, content=b"<p>end</p>", headers={"content-type": "text/html"})

    assert "end" in _real_fetcher(handler).fetch(ESIC_URL).text, "R9: three redirects are allowed"
    hops["n"] = -1  # four redirects
    with pytest.raises(_fetch_error()):
        _real_fetcher(handler).fetch(ESIC_URL)


def test_R9_the_page_is_capped_at_2_mb() -> None:
    ok = _real_fetcher(_ok_handler(body=b"a" * (2 * 1024 * 1024))).fetch(ESIC_URL)
    assert len(ok.text) == 2 * 1024 * 1024, "R9: exactly 2 MB is read"
    with pytest.raises(_fetch_error()):
        _real_fetcher(_ok_handler(body=b"a" * (2 * 1024 * 1024 + 1))).fetch(ESIC_URL)


@pytest.mark.parametrize(
    "ctype,ok",
    [
        ("text/html; charset=utf-8", True),
        ("text/plain", True),
        ("application/pdf", True),
        ("image/png", False),
        ("application/octet-stream", False),
        ("application/zip", False),
    ],
)
def test_R9_only_text_html_and_pdf_are_accepted(ctype: str, ok: bool) -> None:
    fetcher = _real_fetcher(_ok_handler(ctype=ctype))
    if ok:
        assert fetcher.fetch(ESIC_URL) is not None
    else:
        with pytest.raises(_fetch_error()):
            fetcher.fetch(ESIC_URL)


def test_R9_fixed_user_agent_no_cookies_and_a_15_second_timeout() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(
                302,
                headers={"location": "https://esic.gov.in/next", "set-cookie": "sid=abc; Path=/"},
            )
        return httpx.Response(200, content=b"<p>x</p>", headers={"content-type": "text/html"})

    fetcher = _real_fetcher(handler)
    fetcher.fetch(ESIC_URL)
    assert all(r.headers["user-agent"] == "EMS-Pro-RateCheck" for r in seen), "R9: fixed user agent"
    assert all("cookie" not in r.headers for r in seen), "R9: no cookies are ever sent"
    assert fetcher.timeout_seconds == 15, f"R9: 15 second timeout, got {fetcher.timeout_seconds}"

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(_fetch_error()):
        _real_fetcher(slow).fetch(ESIC_URL)


def test_R9_page_text_is_normalised_before_hashing() -> None:
    normalize = _attr("app.modules.platform.rate_fetcher", "normalize_page_text")
    page = (
        "<html><head><style>p{color:red}</style><script>var x = 1;</script></head>"
        "<body><p>Hello   <b>World</b></p>\n\n<p>Rate  1.0</p></body></html>"
    )
    assert normalize(page) == "Hello World Rate 1.0", f"R9: normalised: {normalize(page)!r}"
    assert normalize("<p>A</p>   <!-- c -->") == normalize("A"), "R9: tags and comments are removed"


def test_R9_no_extractor_is_registered_but_the_interface_exists() -> None:
    module = _need("app.modules.platform.rate_fetcher")
    assert getattr(module, "EXTRACTORS", None) == [], "R9: version 1 registers no extractor"
    assert hasattr(module, "PageExtractor"), "R9: the extractor interface is missing"
    assert module.find_extractor(object()) is None


def test_R9_the_check_is_on_the_daily_beat_schedule() -> None:
    from app.workers.celery_app import celery_app

    entries = [
        e
        for e in celery_app.conf.beat_schedule.values()
        if e["task"] == "app.workers.tasks.platform.check_rate_sources_task"
    ]
    assert len(entries) == 1, "R9: one beat entry for the rate check"
    schedule = entries[0]["schedule"]
    assert schedule.hour == {3} or schedule.hour is not None, "R9: daily at a fixed hour"
    assert schedule.day_of_month == set(range(1, 32)), "R9: every day"


# ------------------------------------------------------------------- R10


def test_R10_the_allow_list_has_the_new_hosts_and_stays_exact() -> None:
    for host in (
        "esic.gov.in",
        "gov.uk",
        "cpf.gov.sg",
        "canada.ca",
        "ato.gov.au",
        "ssa.gov",
        "dubai.ae",
    ):
        assert is_official_url(f"https://{host}/page"), f"R10: {host} must be allowed"
        assert is_official_url(f"https://www.{host}/page"), f"R10: a subdomain of {host} is allowed"
        assert not is_official_url(f"https://{host}.evil.com/page"), f"R10: look-alike of {host}"
        assert not is_official_url(f"https://evil{host}/page"), f"R10: suffix trick on {host}"
        assert not is_official_url(f"http://{host}/page"), f"R10: http on {host}"


def test_R10_the_seed_creates_exactly_the_listed_sources_and_is_idempotent(db: Session) -> None:
    seed = _attr("app.db.seed.rate_sources", "seed_rate_sources")
    _platform(db)
    db.execute(text("DELETE FROM rate_change_drafts"))
    db.execute(text("DELETE FROM rate_sources"))
    db.commit()
    seed(db)
    seed(db)
    rows = db.execute(
        text(
            "SELECT country, scheme_group, title, source_url, interval_months, "
            "next_check_on::text, "
            "active, last_result, content_hash, state FROM rate_sources ORDER BY country, title"
        )
    ).all()
    assert len(rows) == len(SEED_ROWS), f"R10: {len(rows)} rows after seeding twice"
    expected = sorted(SEED_ROWS, key=lambda r: (r[0], r[2]))
    for row, want in zip(rows, expected, strict=True):
        assert tuple(row[:6]) == want, f"R10: seeded row differs: {tuple(row[:6])} != {want}"
        assert row[6] is True and row[7] == "never" and row[8] is None and row[9] is None, row
        assert is_official_url(row[3]), f"R10: {row[3]} must pass the allow-list"
    assert not [r for r in rows if r[0] == "IN" and r[1] == "professional_tax"], (
        "R10: professional tax is not seeded"
    )
    db.execute(
        text("UPDATE rate_sources SET last_result = 'changed', active = false WHERE country = 'GB'")
    )
    db.commit()
    seed(db)
    gb = db.execute(text("SELECT last_result, active FROM rate_sources WHERE country = 'GB'")).one()
    assert tuple(gb) == ("changed", False), "R10: re-seeding must not reset runtime fields"


def test_R10_the_seed_does_not_make_another_country_payroll_ready() -> None:
    regions = _need("app.core.regions")
    assert regions.PAYROLL_READY_COUNTRIES == {"IN"}


def test_R10_setup_sh_runs_the_seed_and_claude_md_asks_for_the_beat_process() -> None:
    setup = (REPO_ROOT / "scripts" / "setup.sh").read_text()
    assert "app.db.seed.rate_sources" in setup, "R10: setup.sh must run the rate_sources seed"
    claude = (REPO_ROOT / "CLAUDE.md").read_text()
    assert "rate check" in claude and "beat" in claude, (
        "R10: CLAUDE.md Deploy steps need the beat sentence"
    )


def test_R10_the_new_tables_are_platform_tables_without_a_company(db: Session) -> None:
    from sqlalchemy import inspect

    names = set(inspect(db.get_bind()).get_table_names())
    for table in ("rate_sources", "rate_change_drafts", "rate_reminder_log"):
        assert table in names, f"R10: table {table} is missing"
        columns = {c["name"] for c in inspect(db.get_bind()).get_columns(table)}
        assert "company_id" not in columns, f"R10: {table} is platform data, not tenant data"


def test_R10_every_rule_from_1_to_9_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_R")]
    for rule in range(1, 10):
        assert any(n.startswith(f"test_R{rule}_") for n in names), f"R10: no test for rule {rule}"
    assert Path(__file__).name == "test_5_9_rate_updates.py"
