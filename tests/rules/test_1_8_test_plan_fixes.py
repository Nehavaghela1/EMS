"""Module 1 fixes for problems found by the end-to-end test plan (21-Nov-2026).

BUG-002 / BUG-089  logout ends the access token as well as the refresh cookie
BUG-004            company registration refuses letters in the phone number
BUG-005            super admin cannot save an empty company name or a letters-only pincode
BUG-006            generated company codes hold only A-Z, 0-9 and the hyphen
BUG-010            emails label times in UTC correctly
BUG-011            a blank optional workspace email gives a clear 422, not a confusing 409
BUG-013            companies without a head office get one from the backfill migration
BUG-016 / BUG-017  logo must be https, an app path or a small image; brand colour is stored
"""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, text

from app.core.email_templates import _fmt
from app.core.security import create_access_token, hash_password
from app.modules.identity.models import Company, CompanyLocation, User, UserRole
from app.modules.identity.service import _generate_company_code

# --- BUG-002 / BUG-089 -------------------------------------------------------------------


def test_logout_revokes_the_access_token_it_was_called_with(client, db, company_a):
    headers = company_a.employee_headers
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204

    # The same access token (still unexpired) is now refused everywhere.
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_logout_leaves_other_sessions_working(client, db, company_a):
    other = company_a.hr_headers
    client.post("/api/v1/auth/logout", headers=company_a.employee_headers)
    assert client.get("/api/v1/auth/me", headers=other).status_code == 200


# --- BUG-004 -----------------------------------------------------------------------------


def _register(client, **overrides):
    sfx = uuid.uuid4().hex[:8]
    body = {"company_name": f"Phone Co {sfx}", "company_email": f"p-{sfx}@example.com"}
    body.update(overrides)
    return client.post("/api/v1/companies/register", json=body)


def test_register_refuses_letters_and_overlong_phone(client, limits_off):
    for bad in ["abcd", "123456789012345678901", "12-ab-34"]:
        resp = _register(client, phone=bad)
        assert resp.status_code == 422, (bad, resp.text)


def test_register_accepts_a_normal_phone(client, limits_off):
    resp = _register(client, phone="+91 98765 43210")
    assert resp.status_code == 201, resp.text
    assert resp.json()["phone"] == "+91 98765 43210"


# --- BUG-005 -----------------------------------------------------------------------------


def test_super_admin_cannot_blank_company_name_or_store_letter_pincode(
    client, db, company_a, super_admin_headers
):
    url = f"/api/v1/companies/{company_a.company_id}"
    h = super_admin_headers
    for bad in [{"name": ""}, {"name": "   "}, {"pincode": "ABCDE"}]:
        assert client.put(url, json=bad, headers=h).status_code == 422, bad

    ok = client.put(url, json={"pincode": "395007"}, headers=super_admin_headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["name"] == "Company A"
    assert ok.json()["pincode"] == "395007"


def test_hr_cannot_blank_own_company_name(client, company_a):
    resp = client.put("/api/v1/companies/me", json={"name": ""}, headers=company_a.hr_headers)
    assert resp.status_code == 422


# --- BUG-006 -----------------------------------------------------------------------------


def test_company_code_keeps_only_letters_and_digits():
    code = _generate_company_code("<img src=x onerror=alert(1)> QA Co")
    base, suffix = code.split("-")
    assert base == "IMGSRC"
    assert base.isalnum() and suffix.isalnum()


def test_company_code_falls_back_when_name_has_no_letters():
    assert _generate_company_code("<<< >>>").startswith("CO-")


def test_registered_company_code_is_login_safe(client, limits_off):
    resp = _register(client, company_name="<b>Acme</b> & Sons")
    assert resp.status_code == 201, resp.text
    base = resp.json()["code"].split("-")[0]
    assert base == "BACMEB"


# --- BUG-010 -----------------------------------------------------------------------------


def test_email_time_is_converted_to_utc_before_the_utc_label():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert _fmt(datetime(2026, 11, 27, 15, 49, tzinfo=ist)) == "November 27, 2026 at 10:19 UTC"
    assert _fmt(datetime(2026, 11, 27, 10, 19, tzinfo=UTC)) == "November 27, 2026 at 10:19 UTC"


# --- BUG-011 -----------------------------------------------------------------------------


def test_blank_workspace_email_already_used_gives_clear_422(client, db, company_a):
    company = db.get(Company, company_a.company_id)
    owner = User(
        company_id=company_a.company_id,
        email=company.email,  # the owner logs in with the company's own email
        hashed_password=hash_password("ValidPassword123!"),
        role=UserRole.owner,
        is_active=True,
    )
    db.add(owner)
    db.flush()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(sub=str(owner.id), company_id=str(company_a.company_id), role="owner")
    }
    resp = client.post(
        "/api/v1/companies/workspaces",
        headers=headers,
        json={"company_name": "Second Workspace", "country": "IN"},
    )
    assert resp.status_code == 422, resp.text
    assert "separate company email" in resp.text


# --- BUG-013 -----------------------------------------------------------------------------


def _backfill_sql() -> str:
    path = next(Path("alembic/versions").glob("a7c3e9d1f2b4_*.py"))
    spec = importlib.util.spec_from_file_location("backfill_mig", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BACKFILL_HEAD_OFFICE_SQL


def test_head_office_backfill_adds_exactly_one_per_company_without_one(db, company_a):
    from app.db.rls import bind_tenant_to_session

    company = db.get(Company, company_a.company_id)
    company.code = "<OLD-7829"  # an old code with a character locations refuse
    company.created_at = datetime(2026, 1, 1, tzinfo=UTC)  # a company from before locations
    db.flush()
    bind_tenant_to_session(db, company_id=None, is_platform_admin=True)
    db.execute(text(_backfill_sql()))
    db.execute(text(_backfill_sql()))  # running twice adds nothing more

    rows = db.scalars(
        select(CompanyLocation).where(CompanyLocation.company_id == company_a.company_id)
    ).all()
    assert len(rows) == 1
    assert rows[0].is_primary and rows[0].is_active
    assert rows[0].name == "Head Office"
    assert rows[0].code == "OLD-7829-HQ"


def test_head_office_backfill_skips_companies_created_after_it(db, company_b):
    from app.db.rls import bind_tenant_to_session

    bind_tenant_to_session(db, company_id=None, is_platform_admin=True)
    db.execute(text(_backfill_sql()))
    rows = db.scalars(
        select(CompanyLocation).where(CompanyLocation.company_id == company_b.company_id)
    ).all()
    assert rows == []


# --- BUG-016 / BUG-017 -------------------------------------------------------------------

_TINY_PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
    "DwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_logo_url_refuses_scripts_html_and_huge_values(client, company_a):
    h = company_a.hr_headers
    for bad in [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "data:image/png;base64," + "A" * 700_000,
        "http://insecure.example/logo.png",
        "//evil.example/logo.png",
    ]:
        resp = client.put("/api/v1/companies/me", json={"logo_url": bad}, headers=h)
        assert resp.status_code == 422, bad[:40]


def test_logo_url_accepts_https_and_small_images(client, company_a):
    h = company_a.hr_headers
    for good in ["https://cdn.example.com/logo.png", _TINY_PNG]:
        resp = client.put("/api/v1/companies/me", json={"logo_url": good}, headers=h)
        assert resp.status_code == 200, resp.text
        assert resp.json()["logo_url"] == good


def test_brand_color_is_saved_for_the_company(client, company_a):
    h = company_a.hr_headers
    resp = client.put("/api/v1/companies/me", json={"brand_color": "#1D4ED8"}, headers=h)
    assert resp.status_code == 200, resp.text
    assert client.get("/api/v1/companies/me", headers=h).json()["brand_color"] == "#1d4ed8"
    # Every user of the company gets it, not only the browser that saved it.
    emp = client.get("/api/v1/companies/me", headers=company_a.employee_headers)
    assert emp.json()["brand_color"] == "#1d4ed8"

    for bad in ["blue", "#12345", "#GGGGGG"]:
        r = client.put("/api/v1/companies/me", json={"brand_color": bad}, headers=h)
        assert r.status_code == 422, bad


def test_owner_deactivate_reason_is_capped_at_500_chars(client, db, company_a):
    """Every other reason field is capped; this one took any length (BUG-093)."""
    owner = User(
        company_id=company_a.company_id,
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.owner,
        is_active=True,
    )
    db.add(owner)
    db.commit()
    token = create_access_token(
        sub=str(owner.id), company_id=str(company_a.company_id), role=UserRole.owner.value
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/api/v1/companies/me/deactivate",
        json={"reason": "A" * 501, "password": "Test1234pass!"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text

    # A reason of a sane length is still accepted by validation (the password
    # check is what decides the rest).
    ok = client.post(
        "/api/v1/companies/me/deactivate",
        json={"reason": "Closing the pilot account.", "password": "Test1234pass!"},
        headers=headers,
    )
    assert ok.status_code != 422, ok.text
