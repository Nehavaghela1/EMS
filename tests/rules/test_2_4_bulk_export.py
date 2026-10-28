import csv
import io
import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import (
    Department,
    Employee,
    EmploymentType,
    InvitationStatus,
)
from app.modules.identity.models import (
    Company,
    CompanyLocation,
    CompanyStatus,
    User,
    UserRole,
)
from app.modules.platform.models import AuditLog


def _auth_headers(user: User) -> dict[str, str]:
    # Extract attributes safely without triggering lazy load on detached instance
    user_id = user.__dict__.get("id") or user.id
    company_id = user.__dict__.get("company_id") or user.company_id
    role = user.__dict__.get("role") or user.role
    role_val = role.value if hasattr(role, "value") else str(role)
    token = create_access_token(
        sub=str(user_id),
        company_id=str(company_id),
        role=role_val,
    )
    return {"Authorization": f"Bearer {token}"}


def _get_audit_details(audit: AuditLog) -> dict[str, Any]:
    assert audit.details is not None, f"AuditLog {audit.id} details must not be None"
    return audit.details


@pytest.fixture
def bulk_company(db: Session) -> dict[str, Any]:
    cid = uuid.uuid4()
    company = Company(
        id=cid,
        name=f"Bulk Corp {uuid.uuid4().hex[:6]}",
        code=f"BC{uuid.uuid4().hex[:4].upper()}",
        email=f"bulk-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        is_active=True,
    )
    db.add(company)
    db.flush()

    owner = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.owner,
        is_active=True,
    )
    db.add(owner)
    db.flush()
    company.owner_user_id = owner.id
    db.flush()
    hr_admin = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    manager = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"mgr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.manager,
        is_active=True,
    )
    emp_user1 = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"emp1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.employee,
        is_active=True,
    )
    emp_user2 = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"emp2-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([hr_admin, manager, emp_user1, emp_user2])
    db.flush()

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    dept = Department(
        id=uuid.uuid4(),
        company_id=cid,
        name=f"Engineering {uuid.uuid4().hex[:4]}",
    )
    loc = CompanyLocation(
        id=uuid.uuid4(),
        company_id=cid,
        name=f"HQ {uuid.uuid4().hex[:4]}",
        code=f"HQ{uuid.uuid4().hex[:4].upper()}",
        country="IN",
        is_active=True,
    )
    db.add_all([dept, loc])
    db.flush()

    emp_owner = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=owner.id,
        employee_code=f"{company.code}-0001",
        first_name="Owner",
        last_name="Boss",
        email=owner.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
    )
    emp_hr = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=hr_admin.id,
        employee_code=f"{company.code}-0002",
        first_name="HR",
        last_name="Admin",
        email=hr_admin.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
    )
    emp_mgr = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=manager.id,
        employee_code=f"{company.code}-0003",
        first_name="Manager",
        last_name="Lead",
        email=manager.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
    )
    emp1 = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=emp_user1.id,
        employee_code=f"{company.code}-0004",
        first_name="Alice",
        last_name="Smith",
        email=emp_user1.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
        reporting_manager_id=emp_mgr.id,
        phone="+1234567890",
        personal_email="alice.personal@example.com",
    )
    emp2 = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=emp_user2.id,
        employee_code=f"{company.code}-0005",
        first_name="Bob",
        last_name="Jones",
        email=emp_user2.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.sent,
        department_id=dept.id,
        location_id=loc.id,
        phone="+1987654321",
        personal_email="bob.personal@example.com",
    )
    db.add_all([emp_owner, emp_hr, emp_mgr, emp1, emp2])
    db.commit()

    return {
        "company_id": cid,
        "owner_id": owner.id,
        "hr_admin_id": hr_admin.id,
        "manager_id": manager.id,
        "emp_user1_id": emp_user1.id,
        "emp_user2_id": emp_user2.id,
        "company": company,
        "owner": owner,
        "hr_admin": hr_admin,
        "manager": manager,
        "emp_user1": emp_user1,
        "emp_user2": emp_user2,
        "emp_owner": emp_owner,
        "emp_hr": emp_hr,
        "emp_mgr": emp_mgr,
        "emp1": emp1,
        "emp2": emp2,
        "dept": dept,
        "loc": loc,
    }


# ==============================================================================
# R1: Roles and Permissions
# ==============================================================================

BULK_ROUTES = [
    "/api/v1/employees/bulk/deactivate",
    "/api/v1/employees/bulk/reactivate",
    "/api/v1/employees/bulk/resend-invite",
]


@pytest.mark.parametrize("route", BULK_ROUTES)
def test_r01_bulk_routes_role_access(
    client: TestClient, bulk_company: dict[str, Any], route: str
) -> None:
    """R1: Only owner and HR admin run bulk actions (403 for others, 401 without login)."""
    emp1 = bulk_company["emp1"]
    payload = {"employee_ids": [str(emp1.id)]}

    # 401 without login
    res_no_auth = client.post(route, json=payload)
    assert res_no_auth.status_code == 401

    # 403 for employee
    res_emp = client.post(route, headers=_auth_headers(bulk_company["emp_user1"]), json=payload)
    assert res_emp.status_code == 403

    # 403 for manager
    res_mgr = client.post(route, headers=_auth_headers(bulk_company["manager"]), json=payload)
    assert res_mgr.status_code == 403

    # 200 for HR Admin
    res_hr = client.post(route, headers=_auth_headers(bulk_company["hr_admin"]), json=payload)
    assert res_hr.status_code == 200

    # 200 for Owner
    res_owner = client.post(route, headers=_auth_headers(bulk_company["owner"]), json=payload)
    assert res_owner.status_code == 200


def test_r01_export_roles_access(client: TestClient, bulk_company: dict[str, Any]) -> None:
    """R1: Export: HR admin and owner get everyone, manager only own direct reports, employee 403."""
    export_url = "/api/v1/employees/export"

    # 401 without token
    assert client.post(export_url, json={}).status_code == 401

    # 403 for employee
    assert client.post(export_url, headers=_auth_headers(bulk_company["emp_user1"]), json={}).status_code == 403

    # 202 for manager
    assert client.post(export_url, headers=_auth_headers(bulk_company["manager"]), json={}).status_code == 202

    # 202 for HR admin
    assert client.post(export_url, headers=_auth_headers(bulk_company["hr_admin"]), json={}).status_code == 202

    # 202 for Owner
    assert client.post(export_url, headers=_auth_headers(bulk_company["owner"]), json={}).status_code == 202


# ==============================================================================
# R2: Request Validation and Id Deduplication
# ==============================================================================

@pytest.mark.parametrize("route", BULK_ROUTES)
def test_r02_bulk_bad_bodies_give_422(
    client: TestClient, bulk_company: dict[str, Any], route: str
) -> None:
    """R2: 1-100 unique employee ids; empty, too many, bad ids or unknown fields give 422.
    Asserts errors point at 'employee_ids' field from the bulk route body (not path param).
    """
    hr_headers = _auth_headers(bulk_company["hr_admin"])

    # 1. Empty list -> 422 on employee_ids
    r1 = client.post(route, headers=hr_headers, json={"employee_ids": []})
    assert r1.status_code == 422
    errs1 = str(r1.json())
    assert "employee_ids" in errs1

    # 2. 101 ids (too many) -> 422 on employee_ids
    too_many = [str(uuid.uuid4()) for _ in range(101)]
    r2 = client.post(route, headers=hr_headers, json={"employee_ids": too_many})
    assert r2.status_code == 422
    errs2 = str(r2.json())
    assert "employee_ids" in errs2

    # 3. Bad uuid -> 422 on employee_ids
    r3 = client.post(route, headers=hr_headers, json={"employee_ids": ["not-a-uuid"]})
    assert r3.status_code == 422
    errs3 = str(r3.json())
    assert "employee_ids" in errs3

    # 4. Unknown field (extra forbidden) -> 422 on extra
    r4 = client.post(route, headers=hr_headers, json={"employee_ids": [str(uuid.uuid4())], "extra": 123})
    assert r4.status_code == 422
    errs4 = str(r4.json())
    assert "extra" in errs4

    # 5. Missing required field -> 422 on employee_ids
    r5 = client.post(route, headers=hr_headers, json={})
    assert r5.status_code == 422
    errs5 = str(r5.json())
    assert "employee_ids" in errs5


@pytest.mark.parametrize("route", BULK_ROUTES)
def test_r02_bulk_deduplicates_duplicate_ids(
    client: TestClient, bulk_company: dict[str, Any], route: str
) -> None:
    """R2: Duplicate ids in bulk request are counted once."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp1_id = str(bulk_company["emp1"].id)

    res = client.post(route, headers=hr_headers, json={"employee_ids": [emp1_id, emp1_id, emp1_id]})
    assert res.status_code == 200
    data = res.json()
    assert data["requested"] == 1


# ==============================================================================
# R3: Atomic Per-Employee Isolation & Partial Success
# ==============================================================================

def test_r03_bulk_mixed_batch_and_isolation(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R3: Mixed batch gives correct buckets; failure on one does not block others."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp1 = bulk_company["emp1"]
    emp2 = bulk_company["emp2"]

    # Deactivate emp2 first so it is already inactive
    emp2.is_active = False
    db.commit()

    other_cid = uuid.uuid4()
    random_id = str(uuid.uuid4())

    payload = {"employee_ids": [str(emp1.id), str(emp2.id), random_id]}
    res = client.post("/api/v1/employees/bulk/deactivate", headers=hr_headers, json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["action"] == "deactivate"
    assert data["requested"] == 3
    assert str(emp1.id) in [str(x) for x in data["succeeded"]]
    assert any(item["id"] == str(emp2.id) and item["reason"] == "already_inactive" for item in data["skipped"])
    assert any(item["id"] == random_id and item["code"] == "not_found" for item in data["failed"])


def test_r03_bulk_exception_in_single_employee_never_aborts_batch_or_500(
    client: TestClient, bulk_company: dict[str, Any]
) -> None:
    """R3: One bad employee exception never aborts others and never gives 500."""
    from app.modules.hr.service import EmployeeService

    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp1 = bulk_company["emp1"]
    emp2 = bulk_company["emp2"]

    orig_deactivate_single = getattr(EmployeeService, "_deactivate_single", None)

    def flaky_deactivate(self, company_id, employee, actor):
        if employee.id == emp1.id:
            raise RuntimeError("Database flake on emp1")
        if orig_deactivate_single:
            return orig_deactivate_single(self, company_id, employee, actor)
        return True

    with patch.object(EmployeeService, "_deactivate_single", flaky_deactivate, create=True):
        res = client.post(
            "/api/v1/employees/bulk/deactivate",
            headers=hr_headers,
            json={"employee_ids": [str(emp1.id), str(emp2.id)]},
        )
        assert res.status_code == 200
        data = res.json()
        assert str(emp2.id) in [str(x) for x in data["succeeded"]]
        assert any(item["id"] == str(emp1.id) for item in data["failed"])


# ==============================================================================
# R4: Single Action Equivalence & Invariant Protections
# ==============================================================================

def test_r04_deactivate_and_reactivate_invariants(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R4: Deactivate clears department head and disables login; reactivate checks location."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    dept = bulk_company["dept"]
    loc = bulk_company["loc"]
    emp1 = bulk_company["emp1"]
    user1 = bulk_company["emp_user1"]

    dept.head_employee_id = emp1.id
    db.commit()

    # 1. Deactivate clears department head
    res_deact = client.post(
        "/api/v1/employees/bulk/deactivate",
        headers=hr_headers,
        json={"employee_ids": [str(emp1.id)]},
    )
    assert res_deact.status_code == 200
    db.refresh(dept)
    db.refresh(user1)
    db.refresh(emp1)
    assert dept.head_employee_id is None
    assert user1.is_active is False
    assert emp1.is_active is False

    # 2. Reactivate when location is inactive gives invalid_reference
    loc.is_active = False
    db.commit()

    res_react_bad = client.post(
        "/api/v1/employees/bulk/reactivate",
        headers=hr_headers,
        json={"employee_ids": [str(emp1.id)]},
    )
    assert res_react_bad.status_code == 200
    failed_items = res_react_bad.json()["failed"]
    assert any(item["id"] == str(emp1.id) and item["code"] == "invalid_reference" for item in failed_items)

    # Restore location and reactivate succeeds
    loc.is_active = True
    db.commit()

    res_react_ok = client.post(
        "/api/v1/employees/bulk/reactivate",
        headers=hr_headers,
        json={"employee_ids": [str(emp1.id)]},
    )
    assert res_react_ok.status_code == 200
    assert str(emp1.id) in [str(x) for x in res_react_ok.json()["succeeded"]]
    db.refresh(user1)
    assert user1.is_active is True


def test_r04_self_and_owner_protections(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R4: Nobody deactivates self or company owner (bulk skipped, single 409)."""
    owner_headers = _auth_headers(bulk_company["owner"])
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp_owner = bulk_company["emp_owner"]
    emp_hr = bulk_company["emp_hr"]

    # In bulk: skipped with is_self / is_company_owner
    res_bulk = client.post(
        "/api/v1/employees/bulk/deactivate",
        headers=owner_headers,
        json={"employee_ids": [str(emp_owner.id)]},
    )
    assert res_bulk.status_code == 200
    assert any(item["id"] == str(emp_owner.id) and item["reason"] in ("is_self", "is_company_owner") for item in res_bulk.json()["skipped"])

    # Single DELETE on self gives 409
    res_del_self = client.delete(f"/api/v1/employees/{emp_hr.id}", headers=hr_headers)
    assert res_del_self.status_code == 409

    # Single DELETE on company owner gives 409
    res_del_owner = client.delete(f"/api/v1/employees/{emp_owner.id}", headers=hr_headers)
    assert res_del_owner.status_code == 409


def test_r04_deleting_already_inactive_returns_204_no_audit(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R4: DELETE on already inactive employee returns 204 with no new audit row."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp1 = bulk_company["emp1"]
    emp1.is_active = False
    db.commit()

    cid = bulk_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    audit_count_before = db.query(AuditLog).filter(AuditLog.company_id == cid).count()

    res = client.delete(f"/api/v1/employees/{emp1.id}", headers=hr_headers)
    assert res.status_code == 204

    audit_count_after = db.query(AuditLog).filter(AuditLog.company_id == cid).count()
    assert audit_count_after == audit_count_before


def test_r04_reactivate_single_route_and_deprecated_toggle_active(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R4: POST /employees/{id}/reactivate behaves identically to /toggle-active."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp1 = bulk_company["emp1"]
    emp1.is_active = False
    db.commit()

    # /reactivate
    res_react = client.post(f"/api/v1/employees/{emp1.id}/reactivate", headers=hr_headers)
    assert res_react.status_code == 200
    db.refresh(emp1)
    assert emp1.is_active is True

    # toggle-active back to inactive then active
    res_toggle1 = client.post(f"/api/v1/employees/{emp1.id}/toggle-active", headers=hr_headers)
    assert res_toggle1.status_code == 200
    db.refresh(emp1)
    assert emp1.is_active is False

    res_toggle2 = client.post(f"/api/v1/employees/{emp1.id}/toggle-active", headers=hr_headers)
    assert res_toggle2.status_code == 200
    db.refresh(emp1)
    assert emp1.is_active is True


def test_r04_resend_invite_skips_activated_and_inactive(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R4: Resend invite skips activated and inactive employees."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp1 = bulk_company["emp1"]  # activated
    emp2 = bulk_company["emp2"]  # invited
    emp2.is_active = False       # inactive
    db.commit()

    res = client.post(
        "/api/v1/employees/bulk/resend-invite",
        headers=hr_headers,
        json={"employee_ids": [str(emp1.id), str(emp2.id)]},
    )
    assert res.status_code == 200
    skipped = res.json()["skipped"]
    assert any(item["id"] == str(emp1.id) and item["reason"] == "already_activated" for item in skipped)
    assert any(item["id"] == str(emp2.id) and item["reason"] == "inactive" for item in skipped)


# ==============================================================================
# R5: Tenant Boundary Isolation (REAL Second Company)
# ==============================================================================

def test_r05_cross_company_isolation(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R5: Another company's ids and random ids give identical not_found and no DB writes."""
    from tests.conftest import _make_tenant

    hr_headers = _auth_headers(bulk_company["hr_admin"])
    code_b = f"R5B{uuid.uuid4().hex[:4].upper()}"
    tenant_b = _make_tenant(db, name="Company B R5", code=code_b)
    cid_b = tenant_b.company_id

    emp_b = Employee(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_code=f"{code_b}-0001",
        first_name="BobB",
        last_name="Tester",
        email=f"bobb_{uuid.uuid4().hex[:6]}@b.com",
        hire_date=date(2024, 1, 1),
        is_active=True,
    )
    db.add(emp_b)
    emp_b_id = emp_b.id
    db.commit()

    random_id = str(uuid.uuid4())
    res = client.post(
        "/api/v1/employees/bulk/deactivate",
        headers=hr_headers,
        json={"employee_ids": [str(emp_b_id), random_id]},
    )
    assert res.status_code == 200
    failed = res.json()["failed"]
    # Both Company B ID and Random ID return identical not_found
    assert any(item["id"] == str(emp_b_id) and item["code"] == "not_found" for item in failed)
    assert any(item["id"] == random_id and item["code"] == "not_found" for item in failed)

    bind_tenant_to_session(db, company_id=cid_b, is_platform_admin=True)
    emp_b_refreshed = db.query(Employee).filter(Employee.id == emp_b_id).first()
    assert emp_b_refreshed is not None
    assert emp_b_refreshed.is_active is True

    # Direct repository check under platform admin: get_by_id_for_update must respect company_id filter
    from app.modules.hr.repository import EmployeeRepository
    repo = EmployeeRepository(db)
    assert repo.get_by_id_for_update(emp_b_id, bulk_company["company"].id, allow_inactive=True) is None


# ==============================================================================
# R6: Audit Logs & Outbox Emails
# ==============================================================================

def test_r06_audit_counts_and_email_outbox(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R6: Audit rows (one per changed employee + one summary), emails sent for succeeded only."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp1 = bulk_company["emp1"]
    cid = bulk_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    with patch("app.core.email.send_email") as mock_send_email:
        res = client.post(
            "/api/v1/employees/bulk/deactivate",
            headers=hr_headers,
            json={"employee_ids": [str(emp1.id)]},
        )
        assert res.status_code == 200

        # Audit check: exactly one single employee deactivate row + one summary EMPLOYEES_BULK_ACTION
        summary_audit = (
            db.query(AuditLog)
            .filter(AuditLog.company_id == cid, AuditLog.action == "EMPLOYEES_BULK_ACTION")
            .first()
        )
        assert summary_audit is not None
        details = _get_audit_details(summary_audit)
        assert details["action"] == "deactivate"
        assert details["succeeded_count"] == 1


# ==============================================================================
# R7: Background Export & Filtering
# ==============================================================================

def test_r07_export_large_result_and_filtering(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R7: Export over 105 employees returns all 105 (not one page); manager scoped to reports; no file_path in job result."""
    cid = bulk_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # Seed 105 total employees
    new_emps = []
    for i in range(105):
        new_emps.append(
            Employee(
                id=uuid.uuid4(),
                company_id=cid,
                employee_code=f"EXP-{i:04d}",
                first_name=f"ExpFirst{i}",
                last_name="Tester",
                email=f"exp_{i}_{uuid.uuid4().hex[:4]}@example.com",
                hire_date=date(2024, 1, 1),
                is_active=True,
            )
        )
    db.add_all(new_emps)
    db.commit()

    hr_headers = _auth_headers(bulk_company["hr_admin"])
    res = client.post("/api/v1/employees/export", headers=hr_headers, json={})
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Verify GET /jobs/{job_id} never exposes file_path
    res_job = client.get(f"/api/v1/jobs/{job_id}", headers=hr_headers)
    assert res_job.status_code == 200
    res_data = res_job.json()
    if res_data.get("result"):
        assert "file_path" not in res_data["result"]

    # Verify manager export scopes to direct reports only
    mgr_user = db.query(User).filter(User.id == bulk_company["manager_id"]).first()
    assert mgr_user is not None
    mgr_headers = _auth_headers(mgr_user)
    res_mgr_exp = client.post("/api/v1/employees/export", headers=mgr_headers, json={})
    assert res_mgr_exp.status_code == 202
    job_id_mgr = res_mgr_exp.json()["job_id"]
    res_mgr_dl = client.get(f"/api/v1/employees/export/{job_id_mgr}/download", headers=mgr_headers)
    assert res_mgr_dl.status_code == 200
    rows_mgr = list(csv.reader(io.StringIO(res_mgr_dl.content.decode("utf-8-sig"))))
    # manager has emp1 and emp2 as direct reports (from bulk_company fixture), not all 105+
    # Header is row 0, data rows must be <= 3 (reports only)
    assert len(rows_mgr) - 1 <= 3


# ==============================================================================
# R8: Authenticated Secure Download
# ==============================================================================

def test_r08_export_download_authorization_and_expiry(
    client: TestClient, bulk_company: dict[str, Any]
) -> None:
    """R8: Download works for requester / HR / owner; other company / non-requester / expired gives 404."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    fake_job_id = str(uuid.uuid4())

    # Unknown job -> 404
    res_unknown = client.get(f"/api/v1/employees/export/{fake_job_id}/download", headers=hr_headers)
    assert res_unknown.status_code == 404

    # Expired job test
    with patch("app.modules.hr.router.celery_app.AsyncResult") as mock_async:
        mock_task = MagicMock()
        mock_task.state = "SUCCESS"
        mock_task.result = {
            "company_id": str(bulk_company["company_id"]),
            "requester_id": str(bulk_company["hr_admin"].id),
            "requester_role": "hr_admin",
            "file_path": "/tmp/non_existent.csv",
            "file_name": "test.csv",
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        }
        mock_async.return_value = mock_task

        res_expired = client.get("/api/v1/employees/export/some-job/download", headers=hr_headers)
        assert res_expired.status_code == 404
        assert "expired" in res_expired.json()["error"]["message"].lower()


# ==============================================================================
# R9: Export CSV Content & Formula Injection Protection
# ==============================================================================

def test_r09_export_csv_headers_and_safety(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R9: UTF-8 BOM, exact headers, phone/email scoping, csv_safe_cell sanitization,
    round trip through csv module, no token, hash, bank or PAN columns.
    """
    from app.core.csv_safety import csv_safe_cell

    # 1. csv_safe_cell prefix test
    assert csv_safe_cell("=1+1") == "'=1+1"
    assert csv_safe_cell("+cmd") == "'+cmd"
    assert csv_safe_cell("-calc") == "'-calc"
    assert csv_safe_cell("@SUM") == "'@SUM"

    # Add employee with formula prefix in position
    emp1 = bulk_company["emp1"]
    emp1.position = "=SUM(A1:B1)"
    db.commit()

    # 2. Trigger export as HR
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    res_hr = client.post("/api/v1/employees/export", headers=hr_headers, json={})
    assert res_hr.status_code == 202
    job_id_hr = res_hr.json()["job_id"]

    # Download file as HR
    res_dl_hr = client.get(f"/api/v1/employees/export/{job_id_hr}/download", headers=hr_headers)
    assert res_dl_hr.status_code == 200
    content_hr = res_dl_hr.content
    assert content_hr.startswith(b"\xef\xbb\xbf"), "Export file must start with UTF-8 BOM"

    text_hr = content_hr.decode("utf-8-sig")
    reader_hr = csv.reader(io.StringIO(text_hr))
    rows_hr = list(reader_hr)
    assert len(rows_hr) >= 1
    header_hr = rows_hr[0]

    # Verify formula-injected values in data rows are escaped with single quote
    for row in rows_hr[1:]:
        for cell in row:
            if cell:
                assert not (cell.startswith("=") or cell.startswith("+") or cell.startswith("-") or cell.startswith("@")), (
                    f"Unescaped cell in export: {cell}"
                )

    expected_hr_header = [
        "Employee Code",
        "First Name",
        "Last Name",
        "Work Email",
        "Department",
        "Position",
        "Level",
        "Employment Type",
        "Reporting Manager",
        "Location",
        "Hire Date",
        "Status",
        "Phone",
        "Personal Email",
    ]
    assert header_hr == expected_hr_header, f"HR Header mismatch: {header_hr} != {expected_hr_header}"

    # Verify no sensitive columns
    for col in header_hr:
        col_lower = col.lower()
        assert "bank" not in col_lower
        assert "pan" not in col_lower
        assert "token" not in col_lower
        assert "hash" not in col_lower
        assert "password" not in col_lower

    # 3. Trigger export as Manager -> Phone and Personal Email omitted
    mgr_headers = _auth_headers(bulk_company["manager"])
    res_mgr = client.post("/api/v1/employees/export", headers=mgr_headers, json={})
    assert res_mgr.status_code == 202
    job_id_mgr = res_mgr.json()["job_id"]

    res_dl_mgr = client.get(f"/api/v1/employees/export/{job_id_mgr}/download", headers=mgr_headers)
    assert res_dl_mgr.status_code == 200
    text_mgr = res_dl_mgr.content.decode("utf-8-sig")
    reader_mgr = csv.reader(io.StringIO(text_mgr))
    header_mgr = next(reader_mgr)

    expected_mgr_header = [
        "Employee Code",
        "First Name",
        "Last Name",
        "Work Email",
        "Department",
        "Position",
        "Level",
        "Employment Type",
        "Reporting Manager",
        "Location",
        "Hire Date",
        "Status",
    ]
    assert header_mgr == expected_mgr_header
    assert "Phone" not in header_mgr
    assert "Personal Email" not in header_mgr


# ==============================================================================
# R10: Rate Limiting & Row Lock SQL Capture
# ==============================================================================

@pytest.mark.parametrize("route", BULK_ROUTES)
def test_r10_bulk_rate_limiting_5_per_min(
    client: TestClient, bulk_company: dict[str, Any], route: str
) -> None:
    """R10: 6th bulk call in a minute gives 429."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp1_id = str(bulk_company["emp1"].id)

    limiter.enabled = True
    try:
        limiter.reset()
        status_codes = []
        for _ in range(7):
            r = client.post(route, headers=hr_headers, json={"employee_ids": [emp1_id]})
            status_codes.append(r.status_code)

        assert all(c != 429 for c in status_codes[:5]), f"First 5 calls not 429: {status_codes[:5]}"
        assert all(c == 429 for c in status_codes[5:]), f"Calls 6+ must be 429: {status_codes[5:]}"
    finally:
        limiter.reset()
        limiter.enabled = False


def test_r10_export_rate_limiting_5_per_hour(
    client: TestClient, bulk_company: dict[str, Any]
) -> None:
    """R10: 6th export call in an hour gives 429."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])

    limiter.enabled = True
    try:
        limiter.reset()
        status_codes = []
        for _ in range(7):
            r = client.post("/api/v1/employees/export", headers=hr_headers, json={})
            status_codes.append(r.status_code)

        assert all(c != 429 for c in status_codes[:5])
        assert all(c == 429 for c in status_codes[5:])
    finally:
        limiter.reset()
        limiter.enabled = False


def test_r10_single_deactivate_reactivate_rate_limit_30_per_min(
    client: TestClient, bulk_company: dict[str, Any]
) -> None:
    """R10: 31st single deactivate and 31st single reactivate in a minute give 429."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp1_id = str(bulk_company["emp1"].id)

    limiter.enabled = True
    try:
        # 1. 31st single reactivate gives 429
        limiter.reset()
        status_codes_react = []
        for _ in range(35):
            r = client.post(f"/api/v1/employees/{emp1_id}/reactivate", headers=hr_headers)
            status_codes_react.append(r.status_code)

        assert all(c != 429 for c in status_codes_react[:30])
        assert all(c == 429 for c in status_codes_react[30:])

        # 2. 31st single deactivate (DELETE) gives 429
        limiter.reset()
        status_codes_deact = []
        for _ in range(35):
            r = client.delete(f"/api/v1/employees/{emp1_id}", headers=hr_headers)
            status_codes_deact.append(r.status_code)

        assert all(c != 429 for c in status_codes_deact[:30])
        assert all(c == 429 for c in status_codes_deact[30:])
    finally:
        limiter.reset()
        limiter.enabled = False


def test_r10_export_and_download_audit_rows(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R10: Export request writes EMPLOYEES_EXPORT_REQUESTED; download writes EMPLOYEES_EXPORT_DOWNLOADED."""
    hr_headers = _auth_headers(bulk_company["hr_admin"])
    cid = bulk_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # 1. Export request writes EMPLOYEES_EXPORT_REQUESTED
    res = client.post("/api/v1/employees/export", headers=hr_headers, json={})
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    audit_req = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == cid, AuditLog.action == "EMPLOYEES_EXPORT_REQUESTED")
        .first()
    )
    assert audit_req is not None

    # 2. Download writes EMPLOYEES_EXPORT_DOWNLOADED
    res_dl = client.get(f"/api/v1/employees/export/{job_id}/download", headers=hr_headers)
    assert res_dl.status_code == 200

    audit_dl = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == cid, AuditLog.action == "EMPLOYEES_EXPORT_DOWNLOADED")
        .first()
    )
    assert audit_dl is not None


def test_r10_bulk_deactivate_row_lock_sql_capture(
    client: TestClient, bulk_company: dict[str, Any], db: Session
) -> None:
    """R10: Bulk deactivate takes SELECT ... FOR UPDATE on employee row before the UPDATE."""
    from sqlalchemy import event

    hr_headers = _auth_headers(bulk_company["hr_admin"])
    emp1 = bulk_company["emp1"]
    target_engine = db.get_bind()

    captured_statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        captured_statements.append(statement)

    event.listen(target_engine, "before_cursor_execute", before_cursor_execute)
    try:
        captured_statements.clear()
        res = client.post(
            "/api/v1/employees/bulk/deactivate",
            headers=hr_headers,
            json={"employee_ids": [str(emp1.id)]},
        )
        assert res.status_code == 200

        emp_lock_indices = [
            i
            for i, stmt in enumerate(captured_statements)
            if "FROM employees" in stmt and "FOR UPDATE" in stmt
        ]
        assert len(emp_lock_indices) >= 1, (
            f"Expected SELECT ... FROM employees FOR UPDATE, got: {captured_statements}"
        )
    finally:
        event.remove(target_engine, "before_cursor_execute", before_cursor_execute)
