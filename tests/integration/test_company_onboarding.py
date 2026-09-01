"""WP-05: registration -> approval, one transaction, and the rollback
guarantee that makes 'one transaction' a real claim rather than a comment.
"""

from app.modules.identity.models import CompanySettings


def _register(client, name: str, email: str, industry: str | None = None) -> dict:
    payload = {"company_name": name, "company_email": email}
    if industry:
        payload["industry"] = industry
    resp = client.post("/api/v1/companies/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_register_creates_a_pending_company_with_no_user(client, db):
    from app.modules.identity.models import User

    company = _register(client, "Onboarding Co", "admin@onboardingco.example.com")

    assert company["status"] == "pending"
    user_count = db.query(User).filter_by(company_id=company["id"]).count()
    assert user_count == 0


def test_approve_seeds_company_settings_departments_and_hr_admin_in_one_transaction(
    client, super_admin_headers
):
    company = _register(
        client, "Approved Co", "admin@approvedco.example.com", industry="Technology"
    )

    resp = client.post(f"/api/v1/companies/{company['id']}/approve", headers=super_admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["company"]["status"] == "active"
    assert body["hr_admin_email"] == "admin@approvedco.example.com"
    assert body["temporary_password"]

    # company_settings exists.
    settings_resp = client.get(
        "/api/v1/companies/me",
        headers={"Authorization": f"Bearer {_login(client, body)}"},
    )
    assert settings_resp.status_code == 200

    # Preset departments were applied (Technology -> 7 departments).
    dept_resp = client.get(
        "/api/v1/departments",
        headers={"Authorization": f"Bearer {_login(client, body)}"},
    )
    assert dept_resp.status_code == 200
    assert dept_resp.json()["total"] == 7
    names = {d["name"] for d in dept_resp.json()["items"]}
    assert "Engineering" in names


def _login(client, approve_body: dict) -> str:
    resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": approve_body["hr_admin_email"],
            "password": approve_body["temporary_password"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_a_failing_seed_step_rolls_back_the_whole_approval(client, super_admin_headers, db):
    """Plants a conflicting company_settings row before approval runs, so the
    seed step genuinely fails mid-transaction — proving atomicity by running
    it, not by asserting it in isolation from the real failure mode.
    """
    from app.db.rls import bind_tenant_to_session
    from app.modules.identity.models import User
    from app.modules.identity.repository import CompanyRepository

    company = _register(client, "Rollback Co", "admin@rollbackco.example.com")
    company_id = company["id"]

    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    db.add(CompanySettings(company_id=company_id))
    db.commit()

    resp = client.post(f"/api/v1/companies/{company_id}/approve", headers=super_admin_headers)
    assert resp.status_code == 409

    # The whole transaction rolled back: still pending, no HR admin created.
    company_repo = CompanyRepository(db)
    reloaded = company_repo.get_by_id(company_id)
    assert reloaded.status.value == "pending"
    assert reloaded.approved_at is None
    assert db.query(User).filter_by(company_id=company_id).count() == 0


def test_reject_requires_a_reason_and_leaves_company_rejected(client, super_admin_headers):
    company = _register(client, "Rejected Co", "admin@rejectedco.example.com")

    resp = client.post(
        f"/api/v1/companies/{company['id']}/reject",
        headers=super_admin_headers,
        json={"reason": "Duplicate registration"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_hr_admin_gets_404_not_403_on_another_companys_department(client, super_admin_headers):
    """The API-level RLS proof: through real HTTP requests, not a manual
    psql session — the thing WP-04 could not do because no protected route
    existed yet.
    """
    company_x = _register(client, "Company X", "admin@companyx.example.com")
    company_y = _register(client, "Company Y", "admin@companyy.example.com")

    approve_x = client.post(
        f"/api/v1/companies/{company_x['id']}/approve", headers=super_admin_headers
    ).json()
    approve_y = client.post(
        f"/api/v1/companies/{company_y['id']}/approve", headers=super_admin_headers
    ).json()

    token_x = _login(client, approve_x)
    token_y = _login(client, approve_y)

    created = client.post(
        "/api/v1/departments",
        headers={"Authorization": f"Bearer {token_x}"},
        json={"name": "X-Only Department"},
    )
    assert created.status_code == 201
    department_id = created.json()["id"]

    forbidden = client.get(
        f"/api/v1/departments/{department_id}", headers={"Authorization": f"Bearer {token_y}"}
    )
    assert forbidden.status_code == 404
