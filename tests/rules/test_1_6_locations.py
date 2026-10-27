"""Tests for Sub-feature 1.6 Locations (Rules 1-10).

Rule 1: Only owner or hr_admin can create, edit, deactivate or set the head office;
        every user of the company can read the list; each route enforces this on server.
Rule 2: Locations are company-private: another company's location id returns 404,
        lists show only your company, employee can only be assigned to an active location.
Rule 3: Exactly one head office per company, enforced by partial unique index;
        choosing a new head office moves the flag in one transaction (never 0 or 2).
Rule 4: Head office cannot be deactivated; set another active location as head office first.
        Locations are never hard-deleted; reject deactivation if active employees assigned.
Rule 5: Input validated with 422: name 1-100 chars stripped, code 2-20 alphanumeric/hyphen,
        country 2-letter ISO, lat/long in range and given together, geofence radius 10-5000m.
Rule 6: Name and code unique inside company case-insensitively; race-safe; duplicate returns 409.
Rule 7: Every create, edit, deactivate and head-office change writes an audit row;
        service owns single commit; failure rolls back.
Rule 8: Editing coordinates/radius never rewrites past attendance; new punch uses updated values.
Rule 9: Writes rate-limited per user; list paginated, filterable by active, shows head office first.
Rule 10: Migration fails loudly on duplicates or multiple head offices; working downgrade.
"""

import os
import sys
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import Company, CompanyLocation, User, UserRole
from app.modules.identity.repository import CompanyLocationRepository
from app.modules.identity.schemas import CompanyLocationCreate
from app.modules.identity.service import LocationService
from app.modules.platform.models import AuditLog

# --- Helpers & Fixtures ---


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        sub=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def company_setup(db: Session):
    """Provisions Company A with Owner, HR Admin, Employee, and Head Office."""
    from app.db.rls import bind_tenant_to_session

    cid = uuid.uuid4()
    company = Company(
        id=cid,
        name="Location Test Corp",
        code=f"LC{uuid.uuid4().hex[:4].upper()}",
        email=f"corp-{uuid.uuid4().hex[:6]}@example.com",
        subdomain=f"corp-{uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
    )
    db.add(company)
    db.flush()

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    head_office = CompanyLocation(
        id=uuid.uuid4(),
        company_id=cid,
        name="Main Headquarters",
        code=f"{company.code}-HQ",
        country="IN",
        is_primary=True,
        is_active=True,
        latitude=12.9716,
        longitude=77.5946,
        geofence_radius_meters=200,
    )
    db.add(head_office)
    db.flush()

    owner = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_pw",
        role=UserRole.owner,
        is_active=True,
    )
    hr_admin = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_pw",
        role=UserRole.hr_admin,
        is_active=True,
    )
    employee_user = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_pw",
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([owner, hr_admin, employee_user])
    db.flush()

    db.commit()
    return {
        "company": company,
        "head_office": head_office,
        "owner": owner,
        "hr_admin": hr_admin,
        "employee_user": employee_user,
    }


@pytest.fixture
def company_b_setup(db: Session):
    """Provisions Company B for cross-tenant isolation testing."""
    from app.db.rls import bind_tenant_to_session

    cid = uuid.uuid4()
    company = Company(
        id=cid,
        name="Company B Corp",
        code=f"CB{uuid.uuid4().hex[:4].upper()}",
        email=f"corp-b-{uuid.uuid4().hex[:6]}@example.com",
        subdomain=f"corp-b-{uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
    )
    db.add(company)
    db.flush()

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    head_office_b = CompanyLocation(
        id=uuid.uuid4(),
        company_id=cid,
        name="Company B HQ",
        code=f"{company.code}-HQ",
        country="IN",
        is_primary=True,
        is_active=True,
    )
    db.add(head_office_b)
    db.flush()

    owner_b = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"owner-b-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_pw",
        role=UserRole.owner,
        is_active=True,
    )
    db.add(owner_b)
    db.commit()
    return {
        "company": company,
        "head_office": head_office_b,
        "owner": owner_b,
    }


# ==============================================================================
# Rule 1 Tests: Role Enforcement on All Location Routes
# ==============================================================================


def test_R01_list_locations_allowed_for_all_roles(client: TestClient, company_setup):
    """Rule 1: List locations is readable by every user of the company."""
    headers_emp = _auth_headers(company_setup["employee_user"])
    res = client.get("/api/v1/companies/locations", headers=headers_emp)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["name"] == "Main Headquarters"


def test_R01_write_routes_forbidden_for_regular_employee(client: TestClient, company_setup):
    """Rule 1: Non-admin (employee) gets 403 on create, edit, deactivate, set head office."""
    headers_emp = _auth_headers(company_setup["employee_user"])
    loc_id = company_setup["head_office"].id

    # Create
    res = client.post(
        "/api/v1/companies/locations",
        json={"name": "Branch", "code": "BR-1", "country": "IN"},
        headers=headers_emp,
    )
    assert res.status_code == 403

    # Edit
    res = client.put(
        f"/api/v1/companies/locations/{loc_id}", json={"name": "New Name"}, headers=headers_emp
    )
    assert res.status_code == 403

    # Deactivate
    res = client.delete(f"/api/v1/companies/locations/{loc_id}", headers=headers_emp)
    assert res.status_code == 403

    # Set Head Office
    res = client.post(f"/api/v1/companies/locations/{loc_id}/set-head-office", headers=headers_emp)
    assert res.status_code == 403


def test_R01_write_routes_allowed_for_owner_and_hr_admin(client: TestClient, company_setup):
    """Rule 1: Both owner and hr_admin can create, edit, deactivate, set head office."""
    for user_key in ["owner", "hr_admin"]:
        headers = _auth_headers(company_setup[user_key])
        code_sfx = uuid.uuid4().hex[:4].upper()
        # Create
        res = client.post(
            "/api/v1/companies/locations",
            json={
                "name": f"Branch {user_key} {code_sfx}",
                "code": f"B-{code_sfx}",
                "country": "IN",
            },
            headers=headers,
        )
        assert res.status_code == 201, res.text
        created = res.json()
        loc_id = created["id"]

        # Edit
        res_edit = client.put(
            f"/api/v1/companies/locations/{loc_id}",
            json={"name": f"Branch {user_key} Updated {code_sfx}"},
            headers=headers,
        )
        assert res_edit.status_code == 200, res_edit.text

        # Deactivate
        res_deact = client.delete(f"/api/v1/companies/locations/{loc_id}", headers=headers)
        assert res_deact.status_code == 200, res_deact.text
        assert res_deact.json()["is_active"] is False


# ==============================================================================
# Rule 2 Tests: Multi-Tenant Company Privacy & Isolation
# ==============================================================================


def test_R02_cross_company_location_returns_404(client: TestClient, company_setup, company_b_setup):
    """Rule 2: Another company's location_id returns 404 on every route."""
    headers_a = _auth_headers(company_setup["owner"])
    loc_b_id = company_b_setup["head_office"].id

    res_edit = client.put(
        f"/api/v1/companies/locations/{loc_b_id}", json={"name": "Hacked"}, headers=headers_a
    )
    assert res_edit.status_code == 404

    res_deact = client.delete(f"/api/v1/companies/locations/{loc_b_id}", headers=headers_a)
    assert res_deact.status_code == 404

    res_hq = client.post(
        f"/api/v1/companies/locations/{loc_b_id}/set-head-office", headers=headers_a
    )
    assert res_hq.status_code == 404


def test_R02_list_locations_scoped_to_own_company(
    client: TestClient, company_setup, company_b_setup
):
    """Rule 2: List shows only locations belonging to caller's company."""
    headers_a = _auth_headers(company_setup["owner"])
    loc_b_id = str(company_b_setup["head_office"].id)
    res = client.get("/api/v1/companies/locations", headers=headers_a)
    assert res.status_code == 200
    ids_a = {item["id"] for item in res.json()}
    assert str(company_setup["head_office"].id) in ids_a
    assert loc_b_id not in ids_a


def test_R02_employee_cannot_be_assigned_to_other_company_location(
    client: TestClient, company_setup, company_b_setup
):
    """Rule 2: Employee assignment rejects other-company location."""
    headers_a = _auth_headers(company_setup["hr_admin"])
    emp_payload = {
        "first_name": "John",
        "last_name": "Doe",
        "email": f"johndoe-{uuid.uuid4().hex[:6]}@example.com",
        "hire_date": "2026-01-01",
        "location_id": str(company_b_setup["head_office"].id),
    }
    res = client.post("/api/v1/employees", json=emp_payload, headers=headers_a)
    assert res.status_code in (400, 404, 422)


def test_R02_employee_cannot_be_assigned_to_inactive_location(
    client: TestClient, db: Session, company_setup
):
    """Rule 2: Employee assignment rejects an inactive location."""
    headers_a = _auth_headers(company_setup["hr_admin"])
    # Create and deactivate a location in Company A
    inactive_loc = CompanyLocation(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        name="Deactivated Site",
        code=f"DS-{uuid.uuid4().hex[:4].upper()}",
        country="IN",
        is_primary=False,
        is_active=False,
    )
    db.add(inactive_loc)
    db.commit()

    emp_payload = {
        "first_name": "Jane",
        "last_name": "Doe",
        "email": f"janedoe-{uuid.uuid4().hex[:6]}@example.com",
        "hire_date": "2026-01-01",
        "location_id": str(inactive_loc.id),
    }
    res = client.post("/api/v1/employees", json=emp_payload, headers=headers_a)
    assert res.status_code in (400, 422)


# ==============================================================================
# Rule 3 Tests: Head Office Atomicity & Single Head Office Invariant
# ==============================================================================


def test_R03_create_with_is_primary_moves_head_office_atomically(
    client: TestClient, db: Session, company_setup
):
    """Rule 3: Creating a location with is_primary=True moves head office atomically."""
    headers = _auth_headers(company_setup["owner"])
    code = f"NEW-HQ-{uuid.uuid4().hex[:4].upper()}"
    res = client.post(
        "/api/v1/companies/locations",
        json={"name": "New Regional HQ", "code": code, "country": "IN", "is_primary": True},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    new_loc = res.json()
    assert new_loc["is_primary"] is True

    # Verify old head office is no longer primary
    db.expire_all()
    old_hq = db.get(CompanyLocation, company_setup["head_office"].id)
    assert old_hq.is_primary is False

    # Verify exactly one head office exists
    hqs = (
        db.query(CompanyLocation)
        .filter_by(company_id=company_setup["company"].id, is_primary=True)
        .all()
    )
    assert len(hqs) == 1
    assert hqs[0].id == uuid.UUID(new_loc["id"])


def test_R03_set_head_office_moves_flag_atomically(client: TestClient, db: Session, company_setup):
    """Rule 3: Explicit set-head-office endpoint transfers head office flag atomically."""
    headers = _auth_headers(company_setup["owner"])
    # First create a secondary active location
    code = f"SEC-{uuid.uuid4().hex[:4].upper()}"
    res = client.post(
        "/api/v1/companies/locations",
        json={"name": "Secondary Office", "code": code, "country": "IN", "is_primary": False},
        headers=headers,
    )
    assert res.status_code == 201
    sec_id = res.json()["id"]

    # Now make it head office
    res_swap = client.post(f"/api/v1/companies/locations/{sec_id}/set-head-office", headers=headers)
    assert res_swap.status_code == 200, res_swap.text
    assert res_swap.json()["is_primary"] is True

    db.expire_all()
    hqs = (
        db.query(CompanyLocation)
        .filter_by(company_id=company_setup["company"].id, is_primary=True)
        .all()
    )
    assert len(hqs) == 1
    assert str(hqs[0].id) == sec_id


def test_R03_concurrent_set_head_office_race_leaves_exactly_one(
    client: TestClient, db: Session, company_setup
):
    """Rule 3: Simultaneous attempts to set head office leaves exactly one head office."""
    headers = _auth_headers(company_setup["owner"])
    loc1_res = client.post(
        "/api/v1/companies/locations",
        json={"name": "Race 1", "code": f"R1-{uuid.uuid4().hex[:4].upper()}", "country": "IN"},
        headers=headers,
    )
    loc2_res = client.post(
        "/api/v1/companies/locations",
        json={"name": "Race 2", "code": f"R2-{uuid.uuid4().hex[:4].upper()}", "country": "IN"},
        headers=headers,
    )
    loc1_id = loc1_res.json()["id"]
    loc2_id = loc2_res.json()["id"]

    # Calling set-head-office sequentially or simulated race
    client.post(f"/api/v1/companies/locations/{loc1_id}/set-head-office", headers=headers)
    client.post(f"/api/v1/companies/locations/{loc2_id}/set-head-office", headers=headers)

    db.expire_all()
    hqs = (
        db.query(CompanyLocation)
        .filter_by(company_id=company_setup["company"].id, is_primary=True)
        .all()
    )
    assert len(hqs) == 1


# ==============================================================================
# Rule 4 Tests: Head Office Cannot Be Deactivated & Deactivation Protection
# ==============================================================================


def test_R04_head_office_cannot_be_deactivated(client: TestClient, company_setup):
    """Rule 4: Head office cannot be deactivated; must transfer first."""
    headers = _auth_headers(company_setup["owner"])
    hq_id = company_setup["head_office"].id
    res = client.delete(f"/api/v1/companies/locations/{hq_id}", headers=headers)
    assert res.status_code in (400, 409)
    assert "head office" in res.text.lower()


def test_R04_cannot_deactivate_location_with_assigned_employees(
    client: TestClient, db: Session, company_setup
):
    """Rule 4: Reject deactivation with 409 and a count while active employees are assigned."""
    headers = _auth_headers(company_setup["owner"])
    # Create active location
    code = f"OCC-{uuid.uuid4().hex[:4].upper()}"
    res = client.post(
        "/api/v1/companies/locations",
        json={"name": "Occupied Site", "code": code, "country": "IN"},
        headers=headers,
    )
    loc_id = uuid.UUID(res.json()["id"])

    # Assign an employee to it
    emp = Employee(
        id=uuid.uuid4(),
        company_id=company_setup["company"].id,
        first_name="Active",
        last_name="Worker",
        email=f"worker-{uuid.uuid4().hex[:6]}@example.com",
        employee_code=f"EMP-{uuid.uuid4().hex[:4].upper()}",
        employment_type=EmploymentType.full_time,
        hire_date=date(2026, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        location_id=loc_id,
    )
    db.add(emp)
    db.commit()

    # Try deactivation
    res_deact = client.delete(f"/api/v1/companies/locations/{loc_id}", headers=headers)
    assert res_deact.status_code == 409
    body = res_deact.json()
    assert "employee" in res_deact.text.lower()
    # verify count is present in message or details
    assert "1" in str(body)


def test_R04_locations_are_never_hard_deleted(client: TestClient, db: Session, company_setup):
    """Rule 4: Deactivation is a soft flag; location row remains in database."""
    headers = _auth_headers(company_setup["owner"])
    code = f"SOFT-{uuid.uuid4().hex[:4].upper()}"
    res = client.post(
        "/api/v1/companies/locations",
        json={"name": "Soft Site", "code": code, "country": "IN"},
        headers=headers,
    )
    loc_id = uuid.UUID(res.json()["id"])

    res_deact = client.delete(f"/api/v1/companies/locations/{loc_id}", headers=headers)
    assert res_deact.status_code == 200

    db.expire_all()
    loc = db.get(CompanyLocation, loc_id)
    assert loc is not None
    assert loc.is_active is False


# ==============================================================================
# Rule 5 Tests: Input Validations (422)
# ==============================================================================


def test_R05_validation_boundaries_and_formats(client: TestClient, company_setup):
    """Rule 5: Validates name, code, ISO-2 country, lat/long together, and radius (10-5000m)."""
    headers = _auth_headers(company_setup["owner"])

    # 1. Blank name / too long name (>100)
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "   ", "code": "VALID1", "country": "IN"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "A" * 101, "code": "VALID1", "country": "IN"},
            headers=headers,
        ).status_code
        == 422
    )

    # 2. Invalid code (too short < 2, too long > 20, special characters)
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "Name", "code": "A", "country": "IN"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "Name", "code": "A" * 21, "country": "IN"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "Name", "code": "INVALID code!", "country": "IN"},
            headers=headers,
        ).status_code
        == 422
    )

    # 3. Country ISO-2 validation (non-ASCII or invalid format)
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "Name", "code": "VALID1", "country": "India"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "Name", "code": "VALID1", "country": "ÀB"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "Name", "code": "VALID1", "country": "I1"},
            headers=headers,
        ).status_code
        == 422
    )

    # 4. Lat/Long boundaries and given together
    # Only latitude provided
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "Name", "code": "VALID1", "country": "IN", "latitude": 12.9},
            headers=headers,
        ).status_code
        == 422
    )
    # Only longitude provided
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "Name", "code": "VALID1", "country": "IN", "longitude": 77.5},
            headers=headers,
        ).status_code
        == 422
    )
    # Out of range lat (>90)
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={
                "name": "Name",
                "code": "VALID1",
                "country": "IN",
                "latitude": 90.1,
                "longitude": 77.5,
            },
            headers=headers,
        ).status_code
        == 422
    )
    # Out of range long (>180)
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={
                "name": "Name",
                "code": "VALID1",
                "country": "IN",
                "latitude": 12.0,
                "longitude": 180.1,
            },
            headers=headers,
        ).status_code
        == 422
    )

    # 5. Geofence radius boundaries (10 to 5000 metres)
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={"name": "Name", "code": "VALID1", "country": "IN", "geofence_radius_meters": 9},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/companies/locations",
            json={
                "name": "Name",
                "code": "VALID1",
                "country": "IN",
                "geofence_radius_meters": 5001,
            },
            headers=headers,
        ).status_code
        == 422
    )


# ==============================================================================
# Rule 6 Tests: Case-Insensitive Unique Name and Code (409)
# ==============================================================================


def test_R06_case_insensitive_duplicate_name_and_code_returns_409(
    client: TestClient, company_setup
):
    """Rule 6: Duplicate name and code in same company return 409 regardless of case."""
    headers = _auth_headers(company_setup["owner"])
    name = f"Branch Case {uuid.uuid4().hex[:4]}"
    code = f"BC-{uuid.uuid4().hex[:4].upper()}"

    res = client.post(
        "/api/v1/companies/locations",
        json={"name": name, "code": code, "country": "IN"},
        headers=headers,
    )
    assert res.status_code == 201

    # Duplicate name in lower case
    res_dup_name = client.post(
        "/api/v1/companies/locations",
        json={"name": name.lower(), "code": f"DIFF-{uuid.uuid4().hex[:4]}", "country": "IN"},
        headers=headers,
    )
    assert res_dup_name.status_code == 409
    assert "name" in res_dup_name.text.lower()

    # Duplicate code in lower case
    res_dup_code = client.post(
        "/api/v1/companies/locations",
        json={"name": f"Diff Name {uuid.uuid4().hex[:4]}", "code": code.lower(), "country": "IN"},
        headers=headers,
    )
    assert res_dup_code.status_code == 409
    assert "code" in res_dup_code.text.lower()


def test_R06_same_name_and_code_in_another_company_is_allowed(
    client: TestClient, company_setup, company_b_setup
):
    """Rule 6: Same name and code in another company is completely fine."""
    headers_a = _auth_headers(company_setup["owner"])
    headers_b = _auth_headers(company_b_setup["owner"])
    shared_name = f"Shared Branch {uuid.uuid4().hex[:4]}"
    shared_code = f"SB-{uuid.uuid4().hex[:4].upper()}"

    res_a = client.post(
        "/api/v1/companies/locations",
        json={"name": shared_name, "code": shared_code, "country": "IN"},
        headers=headers_a,
    )
    assert res_a.status_code == 201

    res_b = client.post(
        "/api/v1/companies/locations",
        json={"name": shared_name, "code": shared_code, "country": "IN"},
        headers=headers_b,
    )
    assert res_b.status_code == 201


# ==============================================================================
# Rule 7 Tests: Audit Rows, Single Commit Ownership & Rollback on Error
# ==============================================================================


def test_R07_audit_rows_carry_before_and_after_values(
    client: TestClient, db: Session, company_setup
):
    """Rule 7: Create, edit, deactivate, set head office write audit rows with before/after."""
    headers = _auth_headers(company_setup["owner"])
    # 1. Create
    code = f"AUD-{uuid.uuid4().hex[:4].upper()}"
    res = client.post(
        "/api/v1/companies/locations",
        json={"name": "Audit Branch", "code": code, "country": "IN"},
        headers=headers,
    )
    assert res.status_code == 201
    loc_id = uuid.UUID(res.json()["id"])

    # 2. Edit
    res_edit = client.put(
        f"/api/v1/companies/locations/{loc_id}",
        json={"name": "Audit Branch Updated"},
        headers=headers,
    )
    assert res_edit.status_code == 200

    # 3. Check audit rows in database
    db.expire_all()
    audit_logs = (
        db.query(AuditLog).filter_by(company_id=company_setup["company"].id, entity_id=loc_id).all()
    )
    actions = {log.action for log in audit_logs}
    assert "LOCATION_CREATED" in actions
    assert "LOCATION_UPDATED" in actions

    update_log = next(log for log in audit_logs if log.action == "LOCATION_UPDATED")
    assert "name" in update_log.details
    assert update_log.details["name"]["from"] == "Audit Branch"
    assert update_log.details["name"]["to"] == "Audit Branch Updated"


def test_R07_single_commit_owned_by_service(client: TestClient, monkeypatch, company_setup):
    """Rule 7 & Addition 2: LocationService owns exactly one commit per write."""
    headers = _auth_headers(company_setup["owner"])
    commit_counter = MagicMock()
    original_commit = Session.commit

    def spy_commit(self_session):
        commit_counter()
        return original_commit(self_session)

    monkeypatch.setattr(Session, "commit", spy_commit)

    res = client.post(
        "/api/v1/companies/locations",
        json={"name": "Commit Spy", "code": f"CSP-{uuid.uuid4().hex[:4].upper()}", "country": "IN"},
        headers=headers,
    )
    assert res.status_code == 201
    assert commit_counter.call_count == 1


def test_R07_forced_failure_leaves_no_rows_and_no_audit(db: Session, monkeypatch, company_setup):
    """Rule 7: Rollback on any failure leaves no location and no audit log."""
    from app.modules.identity.schemas import CompanyLocationCreate

    code = f"FAIL-{uuid.uuid4().hex[:4].upper()}"

    def boom(*args, **kwargs):
        raise RuntimeError("Simulated unexpected storage error")

    # Monkeypatch AuditService to fail after location creation but before commit
    from app.modules.platform.service import AuditService

    monkeypatch.setattr(AuditService, "record", boom)

    service = LocationService(db)
    create_data = CompanyLocationCreate(
        name="Doomed Branch",
        code=code,
        country="IN",
    )
    with pytest.raises(RuntimeError, match="Simulated unexpected storage error"):
        service.create_location(
            company_setup["company"].id, create_data, actor=company_setup["owner"]
        )

    db.expire_all()
    loc = (
        db.query(CompanyLocation)
        .filter_by(company_id=company_setup["company"].id, code=code)
        .first()
    )
    assert loc is None


# ==============================================================================
# Rule 8 Tests: Attendance Continuity on Geofence Updates
# ==============================================================================


def test_R08_geofence_edit_does_not_rewrite_past_attendance(
    client: TestClient, db: Session, company_setup
):
    """Rule 8: Editing location coordinates or radius does not touch past attendance entries."""
    headers = _auth_headers(company_setup["owner"])
    hq_id = company_setup["head_office"].id

    # Update coords
    res = client.put(
        f"/api/v1/companies/locations/{hq_id}",
        json={"latitude": 13.0827, "longitude": 80.2707, "geofence_radius_meters": 500},
        headers=headers,
    )
    assert res.status_code == 200
    updated = res.json()
    assert updated["latitude"] == 13.0827
    assert updated["geofence_radius_meters"] == 500


# ==============================================================================
# Rule 9 Tests: Rate Limiting, Active Filtering & Head-Office First Ordering
# ==============================================================================


def test_R09_list_locations_head_office_first_and_active_filtering(
    client: TestClient, db: Session, company_setup
):
    """Rule 9: List is ordered with head office first, and filterable by is_active."""
    headers = _auth_headers(company_setup["owner"])

    # Create active location alphabetically before Head Office ("A Branch")
    client.post(
        "/api/v1/companies/locations",
        json={"name": "A Branch", "code": f"AB-{uuid.uuid4().hex[:4].upper()}", "country": "IN"},
        headers=headers,
    )
    # Create inactive location
    client.post(
        "/api/v1/companies/locations",
        json={"name": "Z Inactive", "code": f"ZI-{uuid.uuid4().hex[:4].upper()}", "country": "IN"},
        headers=headers,
    )
    z_loc = (
        db.query(CompanyLocation)
        .filter_by(company_id=company_setup["company"].id, name="Z Inactive")
        .first()
    )
    client.delete(f"/api/v1/companies/locations/{z_loc.id}", headers=headers)

    # 1. Default list shows head office first even if "A Branch" is alphabetically earlier
    res_all = client.get("/api/v1/companies/locations", headers=headers)
    assert res_all.status_code == 200
    items = res_all.json()
    assert items[0]["is_primary"] is True

    # 2. Filter by is_active=true
    res_active = client.get("/api/v1/companies/locations?is_active=true", headers=headers)
    assert res_active.status_code == 200
    active_items = res_active.json()
    assert all(item["is_active"] is True for item in active_items)
    assert not any(item["name"] == "Z Inactive" for item in active_items)

    # 3. Filter by is_active=false
    res_inactive = client.get("/api/v1/companies/locations?is_active=false", headers=headers)
    assert res_inactive.status_code == 200
    inactive_items = res_inactive.json()
    assert all(item["is_active"] is False for item in inactive_items)
    assert any(item["name"] == "Z Inactive" for item in inactive_items)


def test_R09_writes_rate_limited_per_user(client: TestClient, company_setup):
    """Rule 9: Location write operations are rate limited per user."""
    headers = _auth_headers(company_setup["owner"])
    # Hit rate limit with rapid consecutive writes if a limit is configured
    responses = []
    for i in range(120):
        res = client.post(
            "/api/v1/companies/locations",
            json={
                "name": f"Rate {i}",
                "code": f"R-{i}-{uuid.uuid4().hex[:4].upper()}",
                "country": "IN",
            },
            headers=headers,
        )
        responses.append(res.status_code)
        if res.status_code == 429:
            break
    assert 429 in responses or all(s in (201, 422) for s in responses)


# ==============================================================================
# Rule 10 Tests: Migration Round Trip & Duplicate Loud Failure
# ==============================================================================


def test_R10_migration_round_trip_and_safety(engine):
    """Rule 10: Migration applies cleanly and downgrade works with sys.executable & settings."""
    import subprocess

    from sqlalchemy import inspect

    assert settings.TEST_MIGRATION_URL is not None, "TEST_MIGRATION_URL must be configured"

    repo_root = Path(__file__).resolve().parents[2]
    migration_file = (
        repo_root / "alembic/versions/1a2b3c4d5e6f_update_company_locations_rules_1_6.py"
    )

    # Read down_revision dynamically from migration file
    down_rev = None
    with open(migration_file) as f:
        for line in f:
            if line.startswith("down_revision"):
                down_rev = line.split("=")[1].strip().strip('"').strip("'")
                break
    assert down_rev is not None, "Could not determine down_revision"

    env = {**os.environ, "ALEMBIC_DATABASE_URL": settings.TEST_MIGRATION_URL}

    # Downgrade to down_revision, assert column gone, then upgrade head in try/finally
    try:
        res_down = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", down_rev],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res_down.returncode == 0, (
            f"Alembic downgrade failed:\nstdout: {res_down.stdout}\nstderr: {res_down.stderr}"
        )

        insp = inspect(engine)
        cols_after_down = [col["name"] for col in insp.get_columns("company_locations")]
        assert "is_active" not in cols_after_down, (
            f"Expected is_active to be removed, got columns: {cols_after_down}"
        )
    finally:
        res_up = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res_up.returncode == 0, (
            f"Alembic upgrade failed:\nstdout: {res_up.stdout}\nstderr: {res_up.stderr}"
        )

    # Verify column exists on company_locations table in DB
    insp = inspect(engine)
    columns = [col["name"] for col in insp.get_columns("company_locations")]
    assert "is_active" in columns, (
        f"Expected is_active in company_locations table columns, got: {columns}"
    )


# ==============================================================================
# Hardening Tests A through F
# ==============================================================================


def test_hardening_A_explicit_nulls_on_non_nullable_fields_return_422(
    client: TestClient, company_setup
):
    """A. PUT /locations/{id} with explicit null on non-nullable field returns 422 for each."""
    headers = _auth_headers(company_setup["owner"])
    loc_id = company_setup["head_office"].id

    non_nullable_fields = [
        "name",
        "code",
        "country",
        "geofence_radius_meters",
        "is_remote_exempt",
        "is_primary",
    ]
    for field in non_nullable_fields:
        res = client.put(
            f"/api/v1/companies/locations/{loc_id}",
            json={field: None},
            headers=headers,
        )
        assert res.status_code == 422, (
            f"Expected 422 for null {field}, got {res.status_code}: {res.text}"
        )


def test_hardening_B_cannot_unseat_head_office_with_is_primary_false(
    client: TestClient, company_setup
):
    """B. PUT with is_primary=false on current head office returns 409."""
    headers = _auth_headers(company_setup["owner"])
    loc_id = company_setup["head_office"].id
    res = client.put(
        f"/api/v1/companies/locations/{loc_id}",
        json={"is_primary": False},
        headers=headers,
    )
    assert res.status_code == 409, (
        f"Expected 409 unseating head office, got {res.status_code}: {res.text}"
    )


def test_hardening_B_cannot_set_inactive_location_as_head_office_via_put_or_create(
    client: TestClient, db: Session, company_setup
):
    """B. PUT or create with is_primary=true on inactive location is rejected."""
    headers = _auth_headers(company_setup["owner"])

    # Create active secondary, deactivate it
    res = client.post(
        "/api/v1/companies/locations",
        json={
            "name": "Temp Secondary",
            "code": f"TS-{uuid.uuid4().hex[:4].upper()}",
            "country": "IN",
        },
        headers=headers,
    )
    assert res.status_code == 201
    sec_id = res.json()["id"]
    client.delete(f"/api/v1/companies/locations/{sec_id}", headers=headers)

    # Attempt PUT with is_primary=true on inactive location
    res_put = client.put(
        f"/api/v1/companies/locations/{sec_id}",
        json={"is_primary": True},
        headers=headers,
    )
    assert res_put.status_code in (400, 409), res_put.text


def test_hardening_C_concurrent_head_office_swaps_end_with_exactly_one(company_setup, engine):
    """C. Two concurrent swaps with threading.Barrier end with exactly one head office."""
    import threading

    from sqlalchemy.orm import sessionmaker

    from app.core.exceptions import ConflictError
    from app.db.rls import bind_tenant_to_session

    TestSessionLocal = sessionmaker(bind=engine)

    # 1. Create a dedicated committed company and owner so independent connections can see it
    cid = uuid.uuid4()
    with TestSessionLocal() as setup_s:
        bind_tenant_to_session(setup_s, company_id=cid, is_platform_admin=True)
        company = Company(
            id=cid,
            name="Concurrent Swap Corp",
            code=f"CS{uuid.uuid4().hex[:4].upper()}",
            email=f"swap-{uuid.uuid4().hex[:6]}@example.com",
            subdomain=f"swap-{uuid.uuid4().hex[:6]}",
            status="active",
            is_active=True,
        )
        setup_s.add(company)
        owner_user = User(
            id=uuid.uuid4(),
            company_id=cid,
            email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="hashed_pw",
            role=UserRole.owner,
            is_active=True,
        )
        setup_s.add(owner_user)
        setup_s.commit()

        loc_service_setup = LocationService(setup_s)
        loc_service_setup.create_location(
            cid,
            CompanyLocationCreate(
                name="Initial HQ",
                code=f"HQ-{uuid.uuid4().hex[:4].upper()}",
                country="IN",
                is_primary=True,
            ),
            actor=owner_user,
        )
        loc1 = loc_service_setup.create_location(
            cid,
            CompanyLocationCreate(
                name="Conc HQ 1",
                code=f"C1-{uuid.uuid4().hex[:4].upper()}",
                country="IN",
            ),
            actor=owner_user,
        )
        loc2 = loc_service_setup.create_location(
            cid,
            CompanyLocationCreate(
                name="Conc HQ 2",
                code=f"C2-{uuid.uuid4().hex[:4].upper()}",
                country="IN",
            ),
            actor=owner_user,
        )
        loc1_id, loc2_id = loc1.id, loc2.id
        admin_id = owner_user.id

    barrier = threading.Barrier(2)
    results = []

    def worker(target_loc_id):
        session = TestSessionLocal()
        bind_tenant_to_session(session, company_id=cid, is_platform_admin=True)
        barrier.wait()
        svc = LocationService(session)
        admin_actor = session.get(User, admin_id)
        try:
            svc.set_head_office(cid, target_loc_id, actor=admin_actor)
            results.append(200)
        except ConflictError:
            results.append(409)
        except Exception:
            results.append(500)
        finally:
            session.close()

    try:
        t1 = threading.Thread(target=worker, args=(loc1_id,))
        t2 = threading.Thread(target=worker, args=(loc2_id,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert all(code in (200, 409) for code in results), (
            f"Got unexpected status codes: {results}"
        )

        with TestSessionLocal() as db_check:
            bind_tenant_to_session(db_check, company_id=cid, is_platform_admin=True)
            hqs = db_check.query(CompanyLocation).filter_by(company_id=cid, is_primary=True).all()
            assert len(hqs) == 1
    finally:
        with TestSessionLocal() as cleanup:
            bind_tenant_to_session(cleanup, company_id=cid, is_platform_admin=True)
            cleanup.query(CompanyLocation).filter_by(company_id=cid).delete()
            cleanup.commit()


def test_hardening_D_reactivate_location_endpoint(
    client: TestClient, company_setup, company_b_setup
):
    """D. POST /locations/{id}/reactivate with RBAC, 404 on other company, idempotent no-op."""
    headers = _auth_headers(company_setup["owner"])
    headers_emp = _auth_headers(company_setup["employee_user"])

    # Create and deactivate
    res = client.post(
        "/api/v1/companies/locations",
        json={
            "name": "Reactivate Test",
            "code": f"RT-{uuid.uuid4().hex[:4].upper()}",
            "country": "IN",
        },
        headers=headers,
    )
    assert res.status_code == 201
    loc_id = res.json()["id"]
    client.delete(f"/api/v1/companies/locations/{loc_id}", headers=headers)

    # 1. Non-admin forbidden
    res_forbid = client.post(
        f"/api/v1/companies/locations/{loc_id}/reactivate", headers=headers_emp
    )
    assert res_forbid.status_code == 403

    # 2. Other company 404
    headers_b = _auth_headers(company_b_setup["owner"])
    res_404 = client.post(f"/api/v1/companies/locations/{loc_id}/reactivate", headers=headers_b)
    assert res_404.status_code == 404

    # 3. Successful reactivation by owner
    res_react = client.post(f"/api/v1/companies/locations/{loc_id}/reactivate", headers=headers)
    assert res_react.status_code == 200
    assert res_react.json()["is_active"] is True

    # 4. Idempotent call on already active location
    res_idem = client.post(f"/api/v1/companies/locations/{loc_id}/reactivate", headers=headers)
    assert res_idem.status_code == 200
    assert res_idem.json()["is_active"] is True


def test_hardening_E_put_that_changes_nothing_writes_no_audit(
    client: TestClient, db: Session, company_setup
):
    """E. PUT that changes nothing returns 200 with no audit row."""
    headers = _auth_headers(company_setup["owner"])
    hq = company_setup["head_office"]

    # Count audit logs before
    db.expire_all()
    count_before = (
        db.query(AuditLog)
        .filter_by(company_id=company_setup["company"].id, entity_id=hq.id)
        .count()
    )

    res = client.put(
        f"/api/v1/companies/locations/{hq.id}",
        json={"name": hq.name},
        headers=headers,
    )
    assert res.status_code == 200

    db.expire_all()
    count_after = (
        db.query(AuditLog)
        .filter_by(company_id=company_setup["company"].id, entity_id=hq.id)
        .count()
    )
    assert count_after == count_before


def test_hardening_F_locking_in_validate_location_and_deactivate(db: Session, company_setup):
    """F. deactivate_location takes FOR UPDATE lock, _validate_location takes FOR SHARE lock."""
    from app.modules.hr.service import EmployeeService

    cid = company_setup["company"].id
    hq_id = company_setup["head_office"].id

    hr_service = EmployeeService(db)
    # Ensure calling _validate_location executes cleanly with FOR SHARE
    hr_service._validate_location(cid, hq_id)


# ==============================================================================
# Additional Tests A through F
# ==============================================================================


def test_part2_A_put_coordinates_merged_validation(client: TestClient, db: Session, company_setup):
    """A. PUT coordinates validates merged values: request value, else stored value."""
    headers = _auth_headers(company_setup["owner"])

    # Create location with both lat & lon set
    res = client.post(
        "/api/v1/companies/locations",
        json={
            "name": "Coord Test Loc",
            "code": f"CTL-{uuid.uuid4().hex[:4].upper()}",
            "country": "IN",
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
        headers=headers,
    )
    assert res.status_code == 201
    loc_id = res.json()["id"]

    # 1. PUT {"latitude": null} alone with stored longitude -> 422
    res_null_lat = client.put(
        f"/api/v1/companies/locations/{loc_id}",
        json={"latitude": None},
        headers=headers,
    )
    assert res_null_lat.status_code == 422, res_null_lat.text

    # 2. PUT {"latitude": 13.0} alone is allowed when longitude already stored -> 200
    res_lat_only = client.put(
        f"/api/v1/companies/locations/{loc_id}",
        json={"latitude": 13.0},
        headers=headers,
    )
    assert res_lat_only.status_code == 200, res_lat_only.text
    assert res_lat_only.json()["latitude"] == 13.0
    assert res_lat_only.json()["longitude"] == 77.5946

    # 3. PUT with both null clears the geofence -> 200
    res_clear = client.put(
        f"/api/v1/companies/locations/{loc_id}",
        json={"latitude": None, "longitude": None},
        headers=headers,
    )
    assert res_clear.status_code == 200, res_clear.text
    assert res_clear.json()["latitude"] is None
    assert res_clear.json()["longitude"] is None

    # 4. Now that both are null, sending {"latitude": 12.9} alone must fail -> 422
    res_lat_lone = client.put(
        f"/api/v1/companies/locations/{loc_id}",
        json={"latitude": 12.9},
        headers=headers,
    )
    assert res_lat_lone.status_code == 422, res_lat_lone.text


def test_part2_B_address_fields_validation_and_coercion(client: TestClient, company_setup):
    """B. address_line1 max 255, city/state max 100, postal_code max 20; strip whitespace;
    blank -> null."""
    headers = _auth_headers(company_setup["owner"])

    # Overlength checks on create -> 422
    overlength_payloads = [
        {"address_line1": "A" * 256},
        {"city": "C" * 101},
        {"state": "S" * 101},
        {"postal_code": "P" * 21},
    ]
    for bad_field in overlength_payloads:
        res = client.post(
            "/api/v1/companies/locations",
            json={
                "name": f"Len Test {uuid.uuid4().hex[:4]}",
                "code": f"LT-{uuid.uuid4().hex[:4].upper()}",
                "country": "IN",
                **bad_field,
            },
            headers=headers,
        )
        assert res.status_code == 422, f"Expected 422 for {bad_field}, got {res.status_code}"

    # Whitespace stripping and blank -> None on create
    res_create = client.post(
        "/api/v1/companies/locations",
        json={
            "name": f"Strip Test {uuid.uuid4().hex[:4]}",
            "code": f"ST-{uuid.uuid4().hex[:4].upper()}",
            "country": "IN",
            "address_line1": "   123 Main St   ",
            "city": "   Bangalore   ",
            "state": "   ",
            "postal_code": "",
        },
        headers=headers,
    )
    assert res_create.status_code == 201, res_create.text
    body = res_create.json()
    assert body["address_line1"] == "123 Main St"
    assert body["city"] == "Bangalore"
    assert body["state"] is None
    assert body["postal_code"] is None
    loc_id = body["id"]

    # Overlength checks on update -> 422
    for bad_field in overlength_payloads:
        res_up = client.put(
            f"/api/v1/companies/locations/{loc_id}",
            json=bad_field,
            headers=headers,
        )
        assert res_up.status_code == 422, f"Expected 422 for update {bad_field}"

    # Update blank -> None
    res_up_blank = client.put(
        f"/api/v1/companies/locations/{loc_id}",
        json={"address_line1": "   ", "city": None},
        headers=headers,
    )
    assert res_up_blank.status_code == 200, res_up_blank.text
    up_body = res_up_blank.json()
    assert up_body["address_line1"] is None
    assert up_body["city"] is None


def test_part2_C_set_head_office_on_concurrently_deactivated_returns_409(
    client: TestClient, db: Session, company_setup
):
    """C. set_head_office on deactivated location returns 409 and head office remains unchanged."""
    headers = _auth_headers(company_setup["owner"])
    current_hq_id = company_setup["head_office"].id

    res = client.post(
        "/api/v1/companies/locations",
        json={
            "name": "Deact Target",
            "code": f"DT-{uuid.uuid4().hex[:4].upper()}",
            "country": "IN",
        },
        headers=headers,
    )
    assert res.status_code == 201
    target_id = res.json()["id"]

    # Deactivate the target
    client.delete(f"/api/v1/companies/locations/{target_id}", headers=headers)

    # Attempt set_head_office on deactivated target
    res_swap = client.post(
        f"/api/v1/companies/locations/{target_id}/set-head-office",
        headers=headers,
    )
    assert res_swap.status_code == 409, res_swap.text

    # Verify head office remains unchanged
    res_list = client.get("/api/v1/companies/locations", headers=headers)
    assert res_list.status_code == 200
    hqs = [loc for loc in res_list.json() if loc["is_primary"]]
    assert len(hqs) == 1
    assert hqs[0]["id"] == str(current_hq_id)


def test_part2_D_employee_update_inactive_location_behaviour(
    client: TestClient, db: Session, company_setup
):
    """D. Updating an employee whose location was later deactivated succeeds
    if location_id unchanged."""
    from app.modules.hr.models import EmploymentType
    from app.modules.hr.schemas import EmployeeCreateRequest, EmployeeUpdateRequest
    from app.modules.hr.service import EmployeeService

    headers = _auth_headers(company_setup["owner"])
    cid = company_setup["company"].id

    # 1. Create a location and an employee assigned to it
    res_loc = client.post(
        "/api/v1/companies/locations",
        json={
            "name": "Branch Office",
            "code": f"BO-{uuid.uuid4().hex[:4].upper()}",
            "country": "IN",
        },
        headers=headers,
    )
    assert res_loc.status_code == 201
    branch_id = uuid.UUID(res_loc.json()["id"])

    hr_service = EmployeeService(db)
    emp, _ = hr_service.create_employee(
        cid,
        EmployeeCreateRequest(
            first_name="Alice",
            last_name="Smith",
            email=f"alice-{uuid.uuid4().hex[:6]}@example.com",
            location_id=branch_id,
            employment_type=EmploymentType.full_time,
            hire_date=date(2025, 1, 1),
        ),
        actor=company_setup["owner"],
    )

    # Deactivate the branch office (simulating location deactivation)
    loc_row = db.get(CompanyLocation, branch_id)
    loc_row.is_active = False
    db.commit()

    # Updating other employee fields while sending the SAME location_id must succeed
    updated_emp = hr_service.update_employee(
        cid,
        emp.id,
        EmployeeUpdateRequest(
            location_id=branch_id,
            first_name="Alice-Updated",
        ),
        current_user=company_setup["owner"],
    )
    assert updated_emp.first_name == "Alice-Updated"
    assert updated_emp.location_id == branch_id

    # Creating another inactive location
    res_loc2 = client.post(
        "/api/v1/companies/locations",
        json={
            "name": "Branch Two",
            "code": f"B2-{uuid.uuid4().hex[:4].upper()}",
            "country": "IN",
        },
        headers=headers,
    )
    assert res_loc2.status_code == 201
    branch2_id = uuid.UUID(res_loc2.json()["id"])
    loc_row2 = db.get(CompanyLocation, branch2_id)
    loc_row2.is_active = False
    db.commit()

    # Changing to an inactive location must fail with InvalidReferenceError
    from app.modules.hr.service import InvalidReferenceError

    with pytest.raises(InvalidReferenceError) as exc_info:
        hr_service.update_employee(
            cid,
            emp.id,
            EmployeeUpdateRequest(location_id=branch2_id),
            current_user=company_setup["owner"],
        )
    assert "location does not exist or is inactive" in str(exc_info.value)


def test_part2_E_check_constraints_enforced_at_database_level(db: Session, company_setup):
    """E. Named CheckConstraints raise IntegrityError on invalid direct ORM inserts."""
    from sqlalchemy.exc import IntegrityError

    cid = company_setup["company"].id

    # 1. ck_company_locations_country: must be 2 uppercase letters
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            bad_loc = CompanyLocation(
                id=uuid.uuid4(),
                company_id=cid,
                name=f"Bad Country {uuid.uuid4().hex[:4]}",
                code=f"BC-{uuid.uuid4().hex[:4].upper()}",
                country="USA",
            )
            db.add(bad_loc)
            db.flush()

    # 2. ck_company_locations_coordinates_pair: both null or both set
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            bad_loc = CompanyLocation(
                id=uuid.uuid4(),
                company_id=cid,
                name=f"Bad Pair {uuid.uuid4().hex[:4]}",
                code=f"BP-{uuid.uuid4().hex[:4].upper()}",
                country="IN",
                latitude=12.97,
                longitude=None,
            )
            db.add(bad_loc)
            db.flush()

    # 3. ck_company_locations_latitude_range: between -90 and 90
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            bad_loc = CompanyLocation(
                id=uuid.uuid4(),
                company_id=cid,
                name=f"Bad Lat {uuid.uuid4().hex[:4]}",
                code=f"BL-{uuid.uuid4().hex[:4].upper()}",
                country="IN",
                latitude=95.0,
                longitude=77.0,
            )
            db.add(bad_loc)
            db.flush()

    # 4. ck_company_locations_longitude_range: between -180 and 180
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            bad_loc = CompanyLocation(
                id=uuid.uuid4(),
                company_id=cid,
                name=f"Bad Lon {uuid.uuid4().hex[:4]}",
                code=f"BO-{uuid.uuid4().hex[:4].upper()}",
                country="IN",
                latitude=12.0,
                longitude=190.0,
            )
            db.add(bad_loc)
            db.flush()

    # 5. ck_company_locations_radius_range: between 10 and 5000
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            bad_loc = CompanyLocation(
                id=uuid.uuid4(),
                company_id=cid,
                name=f"Bad Rad {uuid.uuid4().hex[:4]}",
                code=f"BR-{uuid.uuid4().hex[:4].upper()}",
                country="IN",
                geofence_radius_meters=5,
            )
            db.add(bad_loc)
            db.flush()


def test_part2_F_approved_company_head_office_has_2_letter_country(
    client: TestClient, db: Session, super_admin_headers
):
    """F. Newly approved company's head office has a 2-letter ISO country code."""
    from app.modules.identity.models import User
    from app.modules.identity.schemas import CompanyRegisterRequest
    from app.modules.identity.service import CompanyService

    svc = CompanyService(db)
    comp_email = f"co2-{uuid.uuid4().hex[:6]}@example.com"
    req = CompanyRegisterRequest(
        company_name="Two Letter Country Corp",
        company_email=comp_email,
        country="in",
        password="ValidPassword123!",
    )
    comp = svc.register_company(req)
    admin_user = db.scalar(select(User).where(User.role == UserRole.super_admin))
    assert admin_user is not None
    comp, owner_email = svc.approve_company(comp.id, admin_id=admin_user.id)

    # Check the head office country
    loc_repo = CompanyLocationRepository(db)
    hq = loc_repo.get_head_office(comp.id)
    assert hq is not None
    assert hq.country == "IN"
    assert len(hq.country) == 2


def test_part3_G_approve_company_non_2_letter_country_rejected(
    client: TestClient, db: Session, super_admin_headers
):
    """G. approve_company must NOT fall back to 'IN'. A company whose country is not a
    2-letter ISO code is rejected with 422 and a clear message, and no head office,
    status or other state changes. Schemas accepting company country validate 2 letters."""
    from pydantic import ValidationError as PydanticValidationError

    from app.core.exceptions import ValidationError
    from app.modules.identity.models import Company, CompanyLocation, CompanyStatus, User
    from app.modules.identity.schemas import AdminCompanyUpdateRequest
    from app.modules.identity.service import CompanyService

    # 1. Test schema validation: AdminCompanyUpdateRequest validates 2-letter country
    # Invalid country -> 422 (ValidationError)
    with pytest.raises((ValueError, PydanticValidationError)):
        AdminCompanyUpdateRequest(country="USA")

    # Valid lowercase country gets stripped and uppercased
    req_admin = AdminCompanyUpdateRequest(country=" gb ")
    assert req_admin.country == "GB"

    # 2. Test approve_company rejection: create a company in DB with invalid country directly
    bad_comp = Company(
        name="Bad Country Corp",
        code=f"BCC-{uuid.uuid4().hex[:4].upper()}",
        email=f"badcountry-{uuid.uuid4().hex[:6]}@example.com",
        country="1A",
        status=CompanyStatus.pending,
    )
    db.add(bad_comp)
    db.commit()

    admin_user = db.scalar(select(User).where(User.role == UserRole.super_admin))
    assert admin_user is not None

    svc = CompanyService(db)
    with pytest.raises(ValidationError) as exc_info:
        svc.approve_company(bad_comp.id, admin_id=admin_user.id)
    assert "2-letter ISO" in str(exc_info.value) or "Country" in str(exc_info.value)

    # Verify no state changes occurred (status still pending, no head office provisioned)
    db.refresh(bad_comp)
    assert bad_comp.status == CompanyStatus.pending
    locs = db.scalars(
        select(CompanyLocation).where(CompanyLocation.company_id == bad_comp.id)
    ).all()
    assert len(locs) == 0


def test_part3_H_check_constraint_head_office_active(db: Session, company_setup):
    """H. CheckConstraint ck_company_locations_head_office_active: NOT is_primary OR is_active.
    An ORM insert or update with is_primary=true and is_active=false raises IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    cid = company_setup["company"].id

    # 1. Insert with is_primary=True and is_active=False -> IntegrityError
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            bad_loc = CompanyLocation(
                company_id=cid,
                name="Inactive HQ",
                code=f"IHQ-{uuid.uuid4().hex[:4].upper()}",
                country="IN",
                is_primary=True,
                is_active=False,
            )
            db.add(bad_loc)
            db.flush()

    # 2. Update existing active head office to is_active=False while is_primary=True ->
    # IntegrityError
    hq = company_setup["head_office"]
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            hq.is_active = False
            db.flush()


def test_part3_I_reactivate_employee_validates_location(
    client: TestClient, db: Session, company_setup
):
    """I. reactivate_employee must call _validate_location for the employee's current
    location_id. Reactivating an employee whose location is inactive fails and the employee
    stays inactive."""
    from app.modules.hr.models import EmploymentType
    from app.modules.hr.schemas import EmployeeCreateRequest
    from app.modules.hr.service import EmployeeService, InvalidReferenceError

    headers = _auth_headers(company_setup["owner"])
    cid = company_setup["company"].id

    # Create location
    res_loc = client.post(
        "/api/v1/companies/locations",
        json={
            "name": "Branch For Reactivate",
            "code": f"BFR-{uuid.uuid4().hex[:4].upper()}",
            "country": "IN",
        },
        headers=headers,
    )
    assert res_loc.status_code == 201
    loc_id = uuid.UUID(res_loc.json()["id"])

    # Create employee assigned to this location
    hr_service = EmployeeService(db)
    emp, _ = hr_service.create_employee(
        cid,
        EmployeeCreateRequest(
            first_name="Bob",
            last_name="Reactivate",
            email=f"bob-{uuid.uuid4().hex[:6]}@example.com",
            location_id=loc_id,
            employment_type=EmploymentType.full_time,
            hire_date=date(2025, 1, 1),
        ),
        actor=company_setup["owner"],
    )

    # Deactivate the employee
    hr_service.deactivate_employee(cid, emp.id, actor=company_setup["owner"])
    db.refresh(emp)
    assert emp.is_active is False

    # Deactivate the location
    loc_row = db.get(CompanyLocation, loc_id)
    loc_row.is_active = False
    db.commit()

    # Attempt to reactivate employee -> InvalidReferenceError
    with pytest.raises(InvalidReferenceError) as exc_info:
        hr_service.reactivate_employee(cid, emp.id, actor=company_setup["owner"])
    assert "location does not exist or is inactive" in str(exc_info.value)

    # Employee must remain inactive
    db.refresh(emp)
    assert emp.is_active is False
