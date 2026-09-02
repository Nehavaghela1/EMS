"""WP-10: holiday and leave-type CRUD (routes 55-60), and the leave-type
seeding at company approval that closes the gap WP-05 flagged and carried
since (RECONCILIATION §2.6/§18/§19)."""

import re


def _register(client, name: str, email: str, industry: str | None = None) -> dict:
    payload = {"company_name": name, "company_email": email}
    if industry:
        payload["industry"] = industry
    resp = client.post("/api/v1/companies/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _approve(client, super_admin_headers, company_id: str) -> dict:
    resp = client.post(f"/api/v1/companies/{company_id}/approve", headers=super_admin_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _login(client, email: str, password: str):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _extract_temporary_password(email_outbox: list[dict], to_email: str) -> str:
    matches = [
        e for e in email_outbox if e["to"] == to_email and "Temporary password" in e["text_body"]
    ]
    assert matches, f"no HR admin credentials email found for {to_email}"
    match = re.search(r"Temporary password: (\S+)", matches[-1]["text_body"])
    assert match, matches[-1]["text_body"]
    return match.group(1)


def test_company_approval_seeds_leave_types_from_the_industry_preset(
    client, super_admin_headers, email_outbox
):
    company = _register(client, "Leave Seed Co", "admin@leaveseedco.com", industry="Technology")
    approve = _approve(client, super_admin_headers, company["id"])
    password = _extract_temporary_password(email_outbox, approve["hr_admin_email"])
    token = _login(client, approve["hr_admin_email"], password)
    hr_headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/leave-types", headers=hr_headers)
    assert resp.status_code == 200
    codes = {lt["code"] for lt in resp.json()}
    # Matches app/db/seed/industry_presets.py's _STANDARD_LEAVE_TYPES codes.
    assert {"annual", "sick", "casual", "maternity", "paternity"} <= codes

    annual = next(lt for lt in resp.json() if lt["code"] == "annual")
    assert float(annual["annual_allowance"]) == 18.0
    assert annual["is_encashable"] is True


def test_leave_type_crud(client, company_a):
    created = client.post(
        "/api/v1/leave-types",
        headers=company_a.hr_headers,
        json={"name": "Comp Off", "code": "comp_off", "annual_allowance": "5"},
    )
    assert created.status_code == 201, created.text

    duplicate = client.post(
        "/api/v1/leave-types",
        headers=company_a.hr_headers,
        json={"name": "Comp Off Again", "code": "comp_off", "annual_allowance": "5"},
    )
    assert duplicate.status_code == 409

    listed = client.get("/api/v1/leave-types", headers=company_a.hr_headers)
    assert created.json()["id"] in {lt["id"] for lt in listed.json()}

    updated = client.put(
        f"/api/v1/leave-types/{created.json()['id']}",
        headers=company_a.hr_headers,
        json={"annual_allowance": "6", "is_active": False},
    )
    assert updated.status_code == 200
    assert float(updated.json()["annual_allowance"]) == 6.0
    assert updated.json()["is_active"] is False


def test_holiday_crud_and_year_filter(client, company_a):
    created = client.post(
        "/api/v1/holidays",
        headers=company_a.hr_headers,
        json={"name": "Republic Day", "date": "2030-01-26"},
    )
    assert created.status_code == 201, created.text

    listed_2030 = client.get("/api/v1/holidays?year=2030", headers=company_a.hr_headers)
    assert created.json()["id"] in {h["id"] for h in listed_2030.json()}

    listed_2031 = client.get("/api/v1/holidays?year=2031", headers=company_a.hr_headers)
    assert created.json()["id"] not in {h["id"] for h in listed_2031.json()}

    deleted = client.delete(
        f"/api/v1/holidays/{created.json()['id']}", headers=company_a.hr_headers
    )
    assert deleted.status_code == 204

    listed_after_delete = client.get("/api/v1/holidays?year=2030", headers=company_a.hr_headers)
    assert created.json()["id"] not in {h["id"] for h in listed_after_delete.json()}


def test_duplicate_company_wide_holiday_on_the_same_date_is_rejected(client, company_a):
    first = client.post(
        "/api/v1/holidays",
        headers=company_a.hr_headers,
        json={"name": "Independence Day", "date": "2030-08-15"},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/holidays",
        headers=company_a.hr_headers,
        json={"name": "Independence Day (duplicate)", "date": "2030-08-15"},
    )
    assert second.status_code == 409
