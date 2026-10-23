"""Tests for Module 1 Hardening:
- ITEM 1: Reserved subdomains in CompanyRegisterRequest and CreateWorkspaceRequest.
- ITEM 2: Country boundary on company profile (owner/HR cannot change country, Super Admin can).
- ITEM 3: Employee reactivation (without location, and journey: inactive location -> update
  -> reactivate).
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.modules.hr.models import EmploymentType
from app.modules.hr.schemas import EmployeeCreateRequest
from app.modules.hr.service import EmployeeService
from app.modules.identity.models import Company, CompanyLocation, CompanyStatus, User, UserRole


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        sub=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def hardening_company(db: Session):
    from app.db.rls import bind_tenant_to_session

    cid = uuid.uuid4()
    company = Company(
        id=cid,
        name="Hardening Corp",
        code=f"HC-{uuid.uuid4().hex[:4].upper()}",
        email=f"hardening-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
    )
    db.add(company)
    db.flush()

    owner = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="fakehashedpassword",
        role=UserRole.owner,
        is_active=True,
    )
    hr_admin = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="fakehashedpassword",
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add_all([owner, hr_admin])
    db.commit()

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    return {
        "company": company,
        "owner": owner,
        "hr_admin": hr_admin,
    }


# ==============================================================================
# ITEM 1: Reserved Subdomains
# ==============================================================================


def test_reserved_subdomains_constant():
    """Ensure RESERVED_SUBDOMAINS contains the required names."""
    from app.modules.identity.schemas import RESERVED_SUBDOMAINS

    required = {
        "admin",
        "administrator",
        "api",
        "app",
        "auth",
        "billing",
        "cdn",
        "dashboard",
        "dev",
        "docs",
        "ftp",
        "help",
        "imap",
        "login",
        "mail",
        "ns1",
        "ns2",
        "platform",
        "pop",
        "portal",
        "root",
        "smtp",
        "ssh",
        "staging",
        "static",
        "status",
        "support",
        "test",
        "web",
        "webmail",
        "www",
        "sso",
        "oauth",
        "accounts",
        "account",
        "assets",
        "internal",
        "sandbox",
        "prod",
        "production",
        "superadmin",
    }
    assert required.issubset(RESERVED_SUBDOMAINS)


def test_registration_rejects_reserved_subdomains(client: TestClient):
    """Company registration rejects reserved subdomains case-insensitively with 422."""
    for sub in ["admin", "WWW", "Api"]:
        res = client.post(
            "/api/v1/companies/register",
            json={
                "company_name": "Reserved Subdomain Test",
                "company_email": f"sub-{uuid.uuid4().hex[:6]}@example.com",
                "subdomain": sub,
                "password": "ValidPassword123!",
            },
        )
        assert res.status_code == 422, f"Subdomain {sub} should be rejected with 422"
        err_msg = str(res.json())
        assert "This subdomain is reserved." in err_msg

    # Accepted normal name
    res_normal = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "Normal Corp",
            "company_email": f"normal-{uuid.uuid4().hex[:6]}@example.com",
            "subdomain": f"acme-corp-{uuid.uuid4().hex[:4]}",
            "password": "ValidPassword123!",
        },
    )
    assert res_normal.status_code == 201

    # Accepted variation like www2
    res_www2 = client.post(
        "/api/v1/companies/register",
        json={
            "company_name": "WWW2 Corp",
            "company_email": f"www2-{uuid.uuid4().hex[:6]}@example.com",
            "subdomain": f"www2-{uuid.uuid4().hex[:4]}",
            "password": "ValidPassword123!",
        },
    )
    assert res_www2.status_code == 201


def test_create_workspace_rejects_reserved_subdomains(client: TestClient, hardening_company):
    """POST /companies/workspaces rejects reserved subdomains case-insensitively with 422."""
    owner_headers = _auth_headers(hardening_company["owner"])
    for sub in ["admin", "WWW", "Api"]:
        res = client.post(
            "/api/v1/companies/workspaces",
            headers=owner_headers,
            json={
                "company_name": "Workspace Reserved Test",
                "subdomain": sub,
            },
        )
        assert res.status_code == 422, f"Subdomain {sub} should be rejected with 422"
        err_msg = str(res.json())
        assert "This subdomain is reserved." in err_msg

    # Accepted normal name
    res_normal = client.post(
        "/api/v1/companies/workspaces",
        headers=owner_headers,
        json={
            "company_name": "Normal Workspace",
            "company_email": f"ws-{uuid.uuid4().hex[:6]}@example.com",
            "subdomain": f"normal-ws-{uuid.uuid4().hex[:4]}",
        },
    )
    assert res_normal.status_code == 201

    # Accepted www2
    res_www2 = client.post(
        "/api/v1/companies/workspaces",
        headers=owner_headers,
        json={
            "company_name": "WWW2 Workspace",
            "company_email": f"ws-{uuid.uuid4().hex[:6]}@example.com",
            "subdomain": f"www2-ws-{uuid.uuid4().hex[:4]}",
        },
    )
    assert res_www2.status_code == 201


# ==============================================================================
# ITEM 2: Country Boundary
# ==============================================================================


def test_country_boundary_owner_and_super_admin(
    client: TestClient, db: Session, hardening_company, super_admin_headers
):
    """ITEM 2:
    - PATCH /companies/me (or PUT /companies/me) with country leaves company.country unchanged
      (CompanyProfileUpdateRequest does not allow changing country).
    - Super Admin PUT /companies/{id} with invalid country gets 422, with 'gb' stores 'GB'.
    """
    comp = hardening_company["company"]
    owner_headers = _auth_headers(hardening_company["owner"])

    # Attempt to change country via company profile endpoint (PUT /companies/me)
    # Even if client passes country="US", it is ignored / not updated
    res_profile = client.put(
        "/api/v1/companies/me",
        headers=owner_headers,
        json={"name": "Updated Hardening Name", "country": "US"},
    )
    assert res_profile.status_code == 200
    db.refresh(comp)
    assert comp.country == "IN", "Company profile update must not change company.country"

    # Super Admin admin update route: PUT /api/v1/companies/{id}
    # 1. Invalid country -> 422
    res_bad_country = client.put(
        f"/api/v1/companies/{comp.id}",
        headers=super_admin_headers,
        json={"country": "USA"},
    )
    assert res_bad_country.status_code == 422

    # 2. Valid country 'gb' -> stores 'GB'
    res_admin_gb = client.put(
        f"/api/v1/companies/{comp.id}",
        headers=super_admin_headers,
        json={"country": "gb"},
    )
    assert res_admin_gb.status_code == 200
    db.refresh(comp)
    assert comp.country == "GB"


# ==============================================================================
# ITEM 3: Employee Reactivation
# ==============================================================================


def test_reactivate_employee_without_location_succeeds(
    client: TestClient, db: Session, hardening_company
):
    """ITEM 3(a): Reactivating an inactive employee with no location_id succeeds."""
    cid = hardening_company["company"].id
    owner = hardening_company["owner"]
    owner_headers = _auth_headers(owner)

    hr_service = EmployeeService(db)
    emp, _ = hr_service.create_employee(
        cid,
        EmployeeCreateRequest(
            first_name="NoLoc",
            last_name="Employee",
            email=f"noloc-{uuid.uuid4().hex[:6]}@example.com",
            location_id=None,
            employment_type=EmploymentType.full_time,
            hire_date=date(2025, 1, 1),
        ),
        actor=owner,
    )
    # Deactivate employee
    hr_service.deactivate_employee(cid, emp.id, actor=owner)
    db.refresh(emp)
    assert emp.is_active is False
    assert emp.location_id is None

    # Reactivate via route POST /api/v1/employees/{id}/toggle-active
    res_reactivate = client.post(
        f"/api/v1/employees/{emp.id}/toggle-active",
        headers=owner_headers,
    )
    assert res_reactivate.status_code == 200
    db.refresh(emp)
    assert emp.is_active is True


def test_inactive_employee_location_journey_update_then_reactivate(
    client: TestClient, db: Session, hardening_company
):
    """ITEM 3(b) Journey test:
    - An inactive employee whose location is inactive cannot be reactivated (existing 4xx).
    - HR/owner updates that employee's location_id to an active location via
      PUT /api/v1/employees/{id}.
    - Reactivation succeeds.
    """
    cid = hardening_company["company"].id
    owner = hardening_company["owner"]
    owner_headers = _auth_headers(owner)

    # 1. Create two locations: loc1 (will be deactivated) and loc2 (active)
    res_loc1 = client.post(
        "/api/v1/companies/locations",
        headers=owner_headers,
        json={"name": "Loc One", "code": f"L1-{uuid.uuid4().hex[:4].upper()}", "country": "IN"},
    )
    assert res_loc1.status_code == 201
    loc1_id = uuid.UUID(res_loc1.json()["id"])

    res_loc2 = client.post(
        "/api/v1/companies/locations",
        headers=owner_headers,
        json={"name": "Loc Two", "code": f"L2-{uuid.uuid4().hex[:4].upper()}", "country": "IN"},
    )
    assert res_loc2.status_code == 201
    loc2_id = uuid.UUID(res_loc2.json()["id"])

    # 2. Create employee assigned to loc1
    hr_service = EmployeeService(db)
    emp, _ = hr_service.create_employee(
        cid,
        EmployeeCreateRequest(
            first_name="Journey",
            last_name="Employee",
            email=f"journey-{uuid.uuid4().hex[:6]}@example.com",
            location_id=loc1_id,
            employment_type=EmploymentType.full_time,
            hire_date=date(2025, 1, 1),
        ),
        actor=owner,
    )

    # 3. Deactivate employee
    hr_service.deactivate_employee(cid, emp.id, actor=owner)
    db.refresh(emp)
    assert emp.is_active is False

    # 4. Deactivate loc1
    loc1 = db.get(CompanyLocation, loc1_id)
    loc1.is_active = False
    db.commit()

    # 5. Attempt reactivation -> fails (400 or 422 with location inactive error)
    res_toggle_fail = client.post(
        f"/api/v1/employees/{emp.id}/toggle-active",
        headers=owner_headers,
    )
    assert res_toggle_fail.status_code in (400, 422)
    db.refresh(emp)
    assert emp.is_active is False

    # 6. HR/owner updates that employee's location_id to active loc2
    res_update = client.put(
        f"/api/v1/employees/{emp.id}",
        headers=owner_headers,
        json={"location_id": str(loc2_id)},
    )
    assert res_update.status_code == 200
    db.refresh(emp)
    assert emp.location_id == loc2_id
    assert emp.is_active is False

    # 7. Reactivation now succeeds
    res_toggle_success = client.post(
        f"/api/v1/employees/{emp.id}/toggle-active",
        headers=owner_headers,
    )
    assert res_toggle_success.status_code == 200
    db.refresh(emp)
    assert emp.is_active is True
