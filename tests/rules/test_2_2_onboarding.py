"""Tests for Module 2 Sub-feature 2.2: Onboarding & Directory.

Covers Rules R01 to R09:
- R01: Roles and permissions (create, resend-invite, list)
- R02: Input validation and trimming (names, email, hire_date, notice_period_days, unknown fields)
- R03: Work email unique per company ignoring case & concurrent creates
- R04: Concurrency-safe employee codes
- R05: Department, location, manager validation & anti-cycle check
- R06: Invite token hashing, expiration, invalidation on resend, status guards, email enqueue
- R07: List rules (limit, sort, manager scope restriction)
- R08: Token hygiene in responses & cross-company isolation
- R09: Audit logging & rate limiting (POST /employees, POST /employees/{id}/resend-invite)
"""

import threading
import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, hash_token
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import Department, Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import Company, CompanyLocation, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog


def _get_audit_details(audit: AuditLog) -> dict[str, Any]:
    """Helper asserting that AuditLog.details is not None and returns a dict."""
    assert audit.details is not None, f"AuditLog {audit.id} details must not be None"
    return audit.details


def _auth_headers(user: User) -> dict[str, str]:
    """Generate bearer auth headers for a user."""
    token = create_access_token(
        sub=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def onboarding_company(db: Session) -> dict[str, Any]:
    """Fixture providing a primary company with owner, hr, manager, employee users,
    plus a test department and a test location.
    """
    cid = uuid.uuid4()
    company = Company(
        id=cid,
        name=f"Onboard Corp {uuid.uuid4().hex[:6]}",
        code=f"OB-{uuid.uuid4().hex[:4].upper()}",
        email=f"onboard-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        last_employee_seq=2,
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
    employee = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([owner, hr_admin, manager, employee])
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

    # Create manager employee record
    emp_mgr = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=manager.id,
        employee_code=f"{company.code}-0001",
        first_name="Manager",
        last_name="User",
        email=manager.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2025, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
    )
    # Create staff employee record
    emp_staff = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=employee.id,
        employee_code=f"{company.code}-0002",
        first_name="Staff",
        last_name="Member",
        email=employee.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2025, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
        reporting_manager_id=emp_mgr.id,
    )
    db.add_all([emp_mgr, emp_staff])
    db.commit()

    return {
        "company": company,
        "owner": owner,
        "hr_admin": hr_admin,
        "manager": manager,
        "employee": employee,
        "dept": dept,
        "loc": loc,
        "emp_mgr": emp_mgr,
        "emp_staff": emp_staff,
    }


# ==============================================================================
# R01: Roles and Permissions
# ==============================================================================


def test_r01_create_employee_roles_and_permissions(
    client: TestClient, onboarding_company: dict[str, Any]
) -> None:
    """POST /employees: unauthenticated 401, employee 403, manager 403,
    HR admin 201, owner 201.
    """
    owner_headers = _auth_headers(onboarding_company["owner"])
    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    mgr_headers = _auth_headers(onboarding_company["manager"])
    emp_headers = _auth_headers(onboarding_company["employee"])

    payload = {
        "first_name": "New",
        "last_name": "Hire",
        "email": f"hire-{uuid.uuid4().hex[:6]}@example.com",
        "department_id": str(onboarding_company["dept"].id),
        "hire_date": "2025-01-01",
    }

    # 1. Unauthenticated -> 401
    res_no_auth = client.post("/api/v1/employees", json=payload)
    assert res_no_auth.status_code == 401

    # 2. Employee -> 403
    res_emp = client.post("/api/v1/employees", headers=emp_headers, json=payload)
    assert res_emp.status_code == 403

    # 3. Manager -> 403
    res_mgr = client.post("/api/v1/employees", headers=mgr_headers, json=payload)
    assert res_mgr.status_code == 403

    # 4. HR Admin -> 201
    res_hr = client.post("/api/v1/employees", headers=hr_headers, json=payload)
    assert res_hr.status_code == 201
    assert res_hr.json()["first_name"] == "New"
    assert res_hr.json()["email"] == payload["email"]

    # 5. Owner -> 201
    owner_payload = {
        "first_name": "OwnerHire",
        "email": f"ownerhire-{uuid.uuid4().hex[:6]}@example.com",
        "hire_date": "2025-01-01",
    }
    res_owner = client.post("/api/v1/employees", headers=owner_headers, json=owner_payload)
    assert res_owner.status_code == 201
    assert res_owner.json()["first_name"] == "OwnerHire"


def test_r01_resend_invite_roles_and_permissions(
    client: TestClient, onboarding_company: dict[str, Any]
) -> None:
    """POST /employees/{id}/resend-invite: unauthenticated 401, employee 403,
    manager 403, HR admin 200, owner 200.
    """
    owner_headers = _auth_headers(onboarding_company["owner"])
    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    mgr_headers = _auth_headers(onboarding_company["manager"])
    emp_headers = _auth_headers(onboarding_company["employee"])

    # Create an invited employee first
    create_res = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Pending",
            "email": f"pending-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert create_res.status_code == 201
    emp_id = create_res.json()["id"]

    # 1. Unauthenticated -> 401
    assert client.post(f"/api/v1/employees/{emp_id}/resend-invite").status_code == 401

    # 2. Employee -> 403
    assert (
        client.post(f"/api/v1/employees/{emp_id}/resend-invite", headers=emp_headers).status_code
        == 403
    )

    # 3. Manager -> 403
    assert (
        client.post(f"/api/v1/employees/{emp_id}/resend-invite", headers=mgr_headers).status_code
        == 403
    )

    # 4. HR Admin -> 200
    res_hr = client.post(f"/api/v1/employees/{emp_id}/resend-invite", headers=hr_headers)
    assert res_hr.status_code == 200
    assert "invite" in res_hr.json()

    # 5. Owner -> 200
    res_owner = client.post(f"/api/v1/employees/{emp_id}/resend-invite", headers=owner_headers)
    assert res_owner.status_code == 200


def test_r01_list_employees_roles_and_permissions(
    client: TestClient, onboarding_company: dict[str, Any]
) -> None:
    """GET /employees: unauthenticated 401, employee 403, manager 200,
    HR admin 200, owner 200.
    """
    owner_headers = _auth_headers(onboarding_company["owner"])
    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    mgr_headers = _auth_headers(onboarding_company["manager"])
    emp_headers = _auth_headers(onboarding_company["employee"])

    # 1. Unauthenticated -> 401
    assert client.get("/api/v1/employees").status_code == 401

    # 2. Employee -> 403
    assert client.get("/api/v1/employees", headers=emp_headers).status_code == 403

    # 3. Manager -> 200
    assert client.get("/api/v1/employees", headers=mgr_headers).status_code == 200

    # 4. HR Admin -> 200
    assert client.get("/api/v1/employees", headers=hr_headers).status_code == 200

    # 5. Owner -> 200
    assert client.get("/api/v1/employees", headers=owner_headers).status_code == 200


# ==============================================================================
# R02: Input Validation and Trimming
# ==============================================================================


def test_r02_create_employee_input_validation(
    client: TestClient, onboarding_company: dict[str, Any]
) -> None:
    """Bad input gets 422:
    - empty first_name -> 422
    - 101-char first_name -> 422
    - invalid email -> 422
    - missing hire_date -> 422
    - bad date format -> 422
    - negative notice_period_days -> 422
    - unknown field -> 422
    - names trimmed properly: '  Alice  ' -> 'Alice'.
    """
    hr_headers = _auth_headers(onboarding_company["hr_admin"])

    # 1. Empty first_name -> 422
    res_empty_fn = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "",
            "email": f"valid-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert res_empty_fn.status_code == 422

    # 2. 101-char first_name -> 422
    res_long_fn = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "A" * 101,
            "email": f"valid-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert res_long_fn.status_code == 422

    # 3. Invalid email -> 422
    res_bad_email = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Alice",
            "email": "not-an-email",
            "hire_date": "2025-01-01",
        },
    )
    assert res_bad_email.status_code == 422

    # 4. Missing hire_date -> 422
    res_missing_hd = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Alice",
            "email": f"valid-{uuid.uuid4().hex[:6]}@example.com",
        },
    )
    assert res_missing_hd.status_code == 422

    # 5. Bad date format -> 422
    res_bad_date = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Alice",
            "email": f"valid-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "01-01-2025",
        },
    )
    assert res_bad_date.status_code == 422

    # 6. Negative notice_period_days -> 422
    res_neg_notice = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Alice",
            "email": f"valid-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "notice_period_days": -1,
        },
    )
    assert res_neg_notice.status_code == 422

    # 7. Unknown field -> 422 (extra='forbid')
    res_extra = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Alice",
            "email": f"valid-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "unknown_field": "disallowed",
        },
    )
    assert res_extra.status_code == 422

    # 8. Trimming: whitespace around first_name and last_name trimmed
    res_trim = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "  TrimmedName  ",
            "last_name": "  TrimmedLast  ",
            "email": f"trim-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert res_trim.status_code == 201
    assert res_trim.json()["first_name"] == "TrimmedName"
    assert res_trim.json()["last_name"] == "TrimmedLast"


# ==============================================================================
# R03: Work Email Uniqueness (Case-Insensitive & Concurrency)
# ==============================================================================


def test_r03_work_email_case_insensitive_uniqueness(
    client: TestClient, onboarding_company: dict[str, Any]
) -> None:
    """Work email is unique per company ignoring case:
    Creating 'User.Test@example.com' then 'user.test@example.com' gives 409.
    """
    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    email_tag = uuid.uuid4().hex[:6]
    email1 = f"CaseTest.{email_tag}@example.com"
    email2 = f"casetest.{email_tag}@example.com"

    res1 = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={"first_name": "CaseOne", "email": email1, "hire_date": "2025-01-01"},
    )
    assert res1.status_code == 201

    res2 = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={"first_name": "CaseTwo", "email": email2, "hire_date": "2025-01-01"},
    )
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "conflict"
    assert "email already exists" in res2.json()["error"]["message"].lower()


def test_r03_concurrent_same_email_creation_exactly_one_201_one_409() -> None:
    """Two simultaneous creates with the same work email give exactly
    one 201 and one 409, never a 500.
    """
    assert settings.TEST_DATABASE_URL is not None, "TEST_DATABASE_URL must be configured"
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)

    try:
        cid = uuid.uuid4()
        with Session(engine) as setup_sess:
            company = Company(
                id=cid,
                name="Concurrent Emp Co",
                code=f"CEC{uuid.uuid4().hex[:4].upper()}",
                email=f"cec-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
                is_active=True,
            )
            hr_user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.hr_admin,
                is_active=True,
            )
            setup_sess.add_all([company, hr_user])
            setup_sess.commit()
            token = create_access_token(
                sub=str(hr_user.id), company_id=str(cid), role=hr_user.role.value
            )
            headers = {"Authorization": f"Bearer {token}"}

        def _get_test_db():
            sess = Session(engine)
            try:
                yield sess
            finally:
                sess.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db

        barrier = threading.Barrier(2)
        results: list[int] = []
        shared_email = f"concurrent-{uuid.uuid4().hex[:6]}@example.com"

        def worker():
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                r = c.post(
                    "/api/v1/employees",
                    headers=headers,
                    json={
                        "first_name": "Racer",
                        "email": shared_email,
                        "hire_date": "2025-01-01",
                    },
                )
                results.append(r.status_code)
            except Exception:
                results.append(999)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert 500 not in results, f"Server returned 500 during email race: {results}"
        assert sorted(results) == [201, 409], f"Expected exactly one 201 and one 409, got {results}"

    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        assert settings.TEST_MIGRATION_URL is not None, "TEST_MIGRATION_URL must be configured"
        owner_engine = create_engine(settings.TEST_MIGRATION_URL)
        try:
            with Session(owner_engine) as cleanup:
                bind_tenant_to_session(cleanup, company_id=cid, is_platform_admin=True)
                cleanup.execute(
                    text("DELETE FROM audit_logs WHERE company_id = :cid"), {"cid": cid}
                )
                cleanup.execute(text("DELETE FROM employees WHERE company_id = :cid"), {"cid": cid})
                cleanup.execute(text("DELETE FROM users WHERE company_id = :cid"), {"cid": cid})
                cleanup.execute(text("DELETE FROM companies WHERE id = :cid"), {"cid": cid})
                cleanup.commit()
                remaining = cleanup.execute(
                    text("SELECT 1 FROM companies WHERE id = :cid"), {"cid": cid}
                ).scalar()
                assert remaining is None, f"Company {cid} was not deleted during cleanup"
        finally:
            owner_engine.dispose()
        engine.dispose()


# ==============================================================================
# R04: Concurrency-Safe Employee Code Generation
# ==============================================================================


def test_r04_concurrent_creates_produce_unique_employee_codes() -> None:
    """Two simultaneous creates in one company get different, non-colliding employee codes."""
    assert settings.TEST_DATABASE_URL is not None, "TEST_DATABASE_URL must be configured"
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)

    try:
        cid = uuid.uuid4()
        with Session(engine) as setup_sess:
            company = Company(
                id=cid,
                name="Seq Emp Co",
                code=f"SEC{uuid.uuid4().hex[:4].upper()}",
                email=f"sec-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
                is_active=True,
            )
            hr_user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.hr_admin,
                is_active=True,
            )
            setup_sess.add_all([company, hr_user])
            setup_sess.commit()
            token = create_access_token(
                sub=str(hr_user.id), company_id=str(cid), role=hr_user.role.value
            )
            headers = {"Authorization": f"Bearer {token}"}

        def _get_test_db():
            sess = Session(engine)
            try:
                yield sess
            finally:
                sess.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db

        barrier = threading.Barrier(2)
        codes: list[str] = []
        statuses: list[int] = []

        def worker(idx: int):
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                r = c.post(
                    "/api/v1/employees",
                    headers=headers,
                    json={
                        "first_name": f"Worker{idx}",
                        "email": f"worker{idx}-{uuid.uuid4().hex[:6]}@example.com",
                        "hire_date": "2025-01-01",
                    },
                )
                statuses.append(r.status_code)
                if r.status_code == 201:
                    codes.append(r.json()["employee_code"])
            except Exception:
                statuses.append(999)

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert statuses == [201, 201], f"Expected both requests to succeed 201, got {statuses}"
        assert len(codes) == 2
        assert codes[0] != codes[1], f"Expected distinct employee codes, got {codes}"

    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        assert settings.TEST_MIGRATION_URL is not None, "TEST_MIGRATION_URL must be configured"
        owner_engine = create_engine(settings.TEST_MIGRATION_URL)
        try:
            with Session(owner_engine) as cleanup:
                bind_tenant_to_session(cleanup, company_id=cid, is_platform_admin=True)
                cleanup.execute(
                    text("DELETE FROM audit_logs WHERE company_id = :cid"), {"cid": cid}
                )
                cleanup.execute(text("DELETE FROM employees WHERE company_id = :cid"), {"cid": cid})
                cleanup.execute(text("DELETE FROM users WHERE company_id = :cid"), {"cid": cid})
                cleanup.execute(text("DELETE FROM companies WHERE id = :cid"), {"cid": cid})
                cleanup.commit()
                remaining = cleanup.execute(
                    text("SELECT 1 FROM companies WHERE id = :cid"), {"cid": cid}
                ).scalar()
                assert remaining is None, f"Company {cid} was not deleted during cleanup"
        finally:
            owner_engine.dispose()
        engine.dispose()


# ==============================================================================
# R05: Foreign Key & Relationship Validation
# ==============================================================================


def test_r05_foreign_reference_validation_and_anti_cycle(
    client: TestClient, onboarding_company: dict[str, Any], db: Session
) -> None:
    """Foreign references validation:
    - Non-existent department_id -> 400 invalid_reference
    - Another company's department_id -> 400 invalid_reference (same error message)
    - Deleted department_id -> 400 invalid_reference
    - Non-existent location_id -> 400 invalid_reference
    - Inactive location_id -> 400 invalid_reference
    - Another company's location_id -> 400 invalid_reference
    - Non-existent reporting_manager_id -> 400 invalid_reference
    - Another company's reporting_manager_id -> 400 invalid_reference
    - Self-as-manager -> 400 invalid_reference
    - Manager cycle (A -> B -> A) -> 400 invalid_reference.
    """
    from tests.conftest import _make_tenant

    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    cid = onboarding_company["company"].id
    other_tenant = _make_tenant(
        db, name="Other Foreign Co", code=f"OFC{uuid.uuid4().hex[:4].upper()}"
    )

    # 1. Non-existent department -> 400
    fake_dept_id = uuid.uuid4()
    res_fake_dept = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Test",
            "email": f"test-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "department_id": str(fake_dept_id),
        },
    )
    assert res_fake_dept.status_code == 400
    assert res_fake_dept.json()["error"]["code"] == "invalid_reference"
    dept_err_msg = res_fake_dept.json()["error"]["message"]

    # 2. Another company's department -> 400 with same error message
    bind_tenant_to_session(db, company_id=other_tenant.company_id, is_platform_admin=False)
    other_dept_id = uuid.uuid4()
    other_dept = Department(
        id=other_dept_id,
        company_id=other_tenant.company_id,
        name=f"OtherDept-{uuid.uuid4().hex[:4]}",
    )
    db.add(other_dept)
    db.commit()
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

    res_cross_dept = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Test",
            "email": f"test-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "department_id": str(other_dept_id),
        },
    )
    assert res_cross_dept.status_code == 400
    assert res_cross_dept.json()["error"]["code"] == "invalid_reference"
    assert res_cross_dept.json()["error"]["message"] == dept_err_msg

    # 3. Deleted department -> 400
    del_dept = Department(
        id=uuid.uuid4(),
        company_id=cid,
        name=f"DeletedDept-{uuid.uuid4().hex[:4]}",
        deleted_at=utcnow(),
    )
    db.add(del_dept)
    db.commit()

    res_del_dept = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Test",
            "email": f"test-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "department_id": str(del_dept.id),
        },
    )
    assert res_del_dept.status_code == 400
    assert res_del_dept.json()["error"]["code"] == "invalid_reference"

    # 4. Non-existent location -> 400
    fake_loc_id = uuid.uuid4()
    res_fake_loc = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Test",
            "email": f"test-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "location_id": str(fake_loc_id),
        },
    )
    assert res_fake_loc.status_code == 400
    assert res_fake_loc.json()["error"]["code"] == "invalid_reference"
    loc_err_msg = res_fake_loc.json()["error"]["message"]

    # 5. Inactive location -> 400
    inactive_loc = CompanyLocation(
        id=uuid.uuid4(),
        company_id=cid,
        name=f"InactiveLoc-{uuid.uuid4().hex[:4]}",
        code=f"INACT{uuid.uuid4().hex[:4].upper()}",
        country="IN",
        is_active=False,
    )
    db.add(inactive_loc)
    db.commit()

    res_inact_loc = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Test",
            "email": f"test-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "location_id": str(inactive_loc.id),
        },
    )
    assert res_inact_loc.status_code == 400
    assert res_inact_loc.json()["error"]["code"] == "invalid_reference"

    # 6. Another company's location -> 400 with same message
    bind_tenant_to_session(db, company_id=other_tenant.company_id, is_platform_admin=False)
    other_loc_id = uuid.uuid4()
    other_loc = CompanyLocation(
        id=other_loc_id,
        company_id=other_tenant.company_id,
        name=f"OtherLoc-{uuid.uuid4().hex[:4]}",
        code=f"OTHL{uuid.uuid4().hex[:4].upper()}",
        country="IN",
        is_active=True,
    )
    db.add(other_loc)
    db.commit()
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

    res_other_loc = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Test",
            "email": f"test-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "location_id": str(other_loc_id),
        },
    )
    assert res_other_loc.status_code == 400
    assert res_other_loc.json()["error"]["code"] == "invalid_reference"
    assert res_other_loc.json()["error"]["message"] == loc_err_msg

    # 7. Non-existent reporting manager -> 400
    fake_mgr_id = uuid.uuid4()
    res_fake_mgr = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Test",
            "email": f"test-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "reporting_manager_id": str(fake_mgr_id),
        },
    )
    assert res_fake_mgr.status_code == 400
    assert res_fake_mgr.json()["error"]["code"] == "invalid_reference"
    mgr_err_msg = res_fake_mgr.json()["error"]["message"]

    # 8. Another company's reporting manager -> 400 with same message
    bind_tenant_to_session(db, company_id=other_tenant.company_id, is_platform_admin=False)
    other_emp_id = uuid.uuid4()
    other_emp = Employee(
        id=other_emp_id,
        company_id=other_tenant.company_id,
        employee_code=f"OFC-{uuid.uuid4().hex[:4].upper()}-0001",
        first_name="OtherEmp",
        email=f"otheremp-{uuid.uuid4().hex[:6]}@example.com",
        hire_date=date(2025, 1, 1),
    )
    db.add(other_emp)
    db.commit()
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

    res_cross_mgr = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Test",
            "email": f"test-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "reporting_manager_id": str(other_emp_id),
        },
    )
    assert res_cross_mgr.status_code == 400
    assert res_cross_mgr.json()["error"]["code"] == "invalid_reference"
    assert res_cross_mgr.json()["error"]["message"] == mgr_err_msg

    # 9. Self as manager on create or update -> 400
    res_create_emp = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "SelfMgrTarget",
            "email": f"selfmgr-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert res_create_emp.status_code == 201
    target_emp_id = res_create_emp.json()["id"]

    res_self_mgr = client.put(
        f"/api/v1/employees/{target_emp_id}",
        headers=hr_headers,
        json={"reporting_manager_id": target_emp_id},
    )
    assert res_self_mgr.status_code == 400
    assert res_self_mgr.json()["error"]["code"] == "invalid_reference"
    assert "own reporting manager" in res_self_mgr.json()["error"]["message"].lower()

    # Also verify POST fails if client tries self ID
    res_post_self = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "SelfPostTarget",
            "email": f"selfpost-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "reporting_manager_id": target_emp_id,
        },
    )
    assert res_post_self.status_code == 201
    new_sub_id = res_post_self.json()["id"]

    # 10. Manager loop (A -> B, B -> A) -> 400
    # Currently new_sub_id reports to target_emp_id (target_emp -> new_sub).
    # Attempting to set target_emp_id's manager to new_sub_id creates a cycle!
    res_cycle = client.put(
        f"/api/v1/employees/{target_emp_id}",
        headers=hr_headers,
        json={"reporting_manager_id": new_sub_id},
    )
    assert res_cycle.status_code == 400
    assert res_cycle.json()["error"]["code"] == "invalid_reference"
    assert "circular" in res_cycle.json()["error"]["message"].lower()


def test_f5_any_active_employee_can_be_reporting_manager(
    client: TestClient, onboarding_company: dict[str, Any], db: Session
) -> None:
    """F5: An employee whose login role is plain 'employee' (and one with no login at all)
    can be set as reporting manager on create and on update; result 201/200 and manager_id saved.
    """
    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    cid = onboarding_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # 1. Create an employee with no login at all (just onboarded, invited/active)
    mgr_no_login_res = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "NoLogin",
            "last_name": "Manager",
            "email": f"nologin-mgr-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert mgr_no_login_res.status_code == 201
    mgr_no_login_id = mgr_no_login_res.json()["id"]

    # 2. Create an employee who has an associated user with role 'employee'
    emp_user = User(
        company_id=cid,
        email=f"emp-role-{uuid.uuid4().hex[:6]}@example.com",
        username=f"emp_role_{uuid.uuid4().hex[:6]}",
        hashed_password=hash_password("EmpPassword123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(emp_user)
    db.flush()

    mgr_with_emp_role = Employee(
        company_id=cid,
        user_id=emp_user.id,
        employee_code=f"EMP{uuid.uuid4().hex[:4].upper()}",
        first_name="PlainEmp",
        last_name="Manager",
        email=emp_user.email,
        hire_date=date(2025, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    db.add(mgr_with_emp_role)
    db.commit()
    mgr_role_emp_id = str(mgr_with_emp_role.id)

    # Test A: Create employee with reporting_manager_id = mgr_no_login_id -> 201 & saved
    res_create_a = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "ReportA",
            "last_name": "Test",
            "email": f"report-a-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "reporting_manager_id": mgr_no_login_id,
        },
    )
    assert res_create_a.status_code == 201
    data_a = res_create_a.json()
    assert data_a["reporting_manager_id"] == mgr_no_login_id
    emp_a_id = data_a["id"]

    # Test B: Update employee to have reporting_manager_id = mgr_role_emp_id -> 200 & saved
    res_update_a = client.put(
        f"/api/v1/employees/{emp_a_id}",
        headers=hr_headers,
        json={"reporting_manager_id": mgr_role_emp_id},
    )
    assert res_update_a.status_code == 200
    data_update = res_update_a.json()
    assert data_update["reporting_manager_id"] == mgr_role_emp_id

    # Test C: Create employee with reporting_manager_id = mgr_role_emp_id -> 201 & saved
    res_create_b = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "ReportB",
            "last_name": "Test",
            "email": f"report-b-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "reporting_manager_id": mgr_role_emp_id,
        },
    )
    assert res_create_b.status_code == 201
    assert res_create_b.json()["reporting_manager_id"] == mgr_role_emp_id


# ==============================================================================
# R06: Invite Token Lifecycle & Enqueue
# ==============================================================================


def test_r06_invite_token_hashing_and_lifecycle(
    client: TestClient, onboarding_company: dict[str, Any], db: Session
) -> None:
    """Invite token lifecycle:
    - Raw token never in DB (stored hashed)
    - Expired token cannot activate
    - Resend invalidates old token
    - Resend on already activated employee returns 409
    - Resend on deactivated employee returns 409 (not 404)
    - Resend for another company's employee returns 404
    - Email is enqueued only after commit (transaction rollback sends no email).
    """
    from app.workers.tasks.email import send_email_task
    from tests.conftest import _make_tenant

    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    cid = onboarding_company["company"].id
    work_email = f"token-test-{uuid.uuid4().hex[:6]}@example.com"

    # 1. Capture token sent via send_email_task mock
    captured_tokens: list[str] = []

    def fake_delay(*args, **kwargs):
        # Extract token from kwargs or html_body
        text_body = kwargs.get("text_body", "")
        # Link format is FRONTEND_BASE_URL/activate/<raw_token>
        if "/activate/" in text_body:
            token_part = text_body.split("/activate/")[1].split()[0]
            captured_tokens.append(token_part)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(send_email_task, "delay", fake_delay)

        res_create = client.post(
            "/api/v1/employees",
            headers=hr_headers,
            json={"first_name": "TokenEmp", "email": work_email, "hire_date": "2025-01-01"},
        )
        assert res_create.status_code == 201
        emp_id = uuid.UUID(res_create.json()["id"])
        assert len(captured_tokens) == 1
        raw_token1 = captured_tokens[0]

    # Verify DB has hash_token(raw_token1), not raw_token1
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    emp_db = db.scalar(select(Employee).where(Employee.id == emp_id))
    assert emp_db is not None
    assert emp_db.activation_token_hash == hash_token(raw_token1)
    assert raw_token1 not in (emp_db.activation_token_hash or "")

    # Preview works with raw_token1
    res_preview = client.get(f"/api/v1/auth/activate/{raw_token1}")
    assert res_preview.status_code == 200

    # 2. Resend invalidates old token: raw_token1 stops working
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(send_email_task, "delay", fake_delay)
        res_resend = client.post(
            f"/api/v1/employees/{emp_id}/resend-invite",
            headers=hr_headers,
        )
        assert res_resend.status_code == 200
        assert len(captured_tokens) == 2
        raw_token2 = captured_tokens[1]

    assert raw_token1 != raw_token2
    # Old token fails
    res_old_preview = client.get(f"/api/v1/auth/activate/{raw_token1}")
    assert res_old_preview.status_code == 404  # invalid activation token (Route 10 returns 404)

    # New token works
    res_new_preview = client.get(f"/api/v1/auth/activate/{raw_token2}")
    assert res_new_preview.status_code == 200

    # 3. Token expiration test
    emp_db.activation_expires_at = utcnow() - timedelta(minutes=5)
    db.commit()
    res_expired_preview = client.get(f"/api/v1/auth/activate/{raw_token2}")
    assert res_expired_preview.status_code == 404

    # 4. Resend fresh token, activate account, then verify resend -> 409
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(send_email_task, "delay", fake_delay)
        res_resend2 = client.post(
            f"/api/v1/employees/{emp_id}/resend-invite",
            headers=hr_headers,
        )
        assert res_resend2.status_code == 200
        raw_token3 = captured_tokens[2]

    # Activate account
    uname = f"user_{uuid.uuid4().hex[:8]}"
    res_act = client.post(
        "/api/v1/auth/activate",
        json={"token": raw_token3, "username": uname, "password": "Password123!"},
    )
    assert res_act.status_code == 200

    # Resend on activated employee -> 409
    res_resend_act = client.post(
        f"/api/v1/employees/{emp_id}/resend-invite",
        headers=hr_headers,
    )
    assert res_resend_act.status_code == 409
    assert res_resend_act.json()["error"]["code"] == "conflict"

    # 5. Resend on deactivated employee -> 409 (not 404)
    # Create another invited employee and deactivate them
    res_deact_target = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "DeactTarget",
            "email": f"deact-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert res_deact_target.status_code == 201
    deact_emp_id = res_deact_target.json()["id"]

    # Deactivate
    assert client.delete(f"/api/v1/employees/{deact_emp_id}", headers=hr_headers).status_code == 204

    # Resend on deactivated employee must return 409
    res_resend_deact = client.post(
        f"/api/v1/employees/{deact_emp_id}/resend-invite",
        headers=hr_headers,
    )
    assert res_resend_deact.status_code == 409, (
        f"Expected 409 for resending invite to deactivated employee, "
        f"got {res_resend_deact.status_code}"
    )
    assert res_resend_deact.json()["error"]["code"] == "conflict"

    # 6. Resend for another company's employee -> 404
    other_tenant = _make_tenant(
        db, name="Other Tenant Co", code=f"OTC{uuid.uuid4().hex[:4].upper()}"
    )
    bind_tenant_to_session(db, company_id=other_tenant.company_id, is_platform_admin=False)
    other_emp_id = uuid.uuid4()
    other_emp = Employee(
        id=other_emp_id,
        company_id=other_tenant.company_id,
        employee_code=f"OTC-{uuid.uuid4().hex[:4].upper()}-0001",
        first_name="OtherEmp",
        email=f"otheremp-{uuid.uuid4().hex[:6]}@example.com",
        hire_date=date(2025, 1, 1),
    )
    db.add(other_emp)
    db.commit()
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

    res_cross_resend = client.post(
        f"/api/v1/employees/{other_emp_id}/resend-invite",
        headers=hr_headers,
    )
    assert res_cross_resend.status_code == 404
    assert res_cross_resend.json()["error"]["code"] == "not_found"

    # 7. Email enqueued only after commit (transaction failure sends NO email)
    emails_sent_on_failure: list[dict] = []

    def mock_email_on_fail(*args, **kwargs):
        emails_sent_on_failure.append(kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(send_email_task, "delay", mock_email_on_fail)

        # Patch AuditService.record to raise an error inside transaction
        from app.modules.platform.service import AuditService

        def fail_audit(*args, **kwargs):
            raise RuntimeError("Database error during audit write")

        mp.setattr(AuditService, "record", fail_audit)

        safe_client = TestClient(fastapi_app, raise_server_exceptions=False)
        fail_res = safe_client.post(
            "/api/v1/employees",
            headers=hr_headers,
            json={
                "first_name": "RollbackEmp",
                "email": f"rollback-{uuid.uuid4().hex[:6]}@example.com",
                "hire_date": "2025-01-01",
            },
        )
        assert fail_res.status_code == 500
        assert len(emails_sent_on_failure) == 0, "No email must be queued when transaction fails"


# ==============================================================================
# R07: List Rules (Limit, Sort, Manager Scope Restriction)
# ==============================================================================


def test_r07_list_employees_rules(
    client: TestClient, onboarding_company: dict[str, Any], db: Session
) -> None:
    """List rules:
    - limit=100000 gives exactly 422
    - sort=bogus gives 400 invalid_sort
    - manager cannot see anyone outside their direct reports even with
      reporting_manager_id, department_id or company_id query params.
    """
    from tests.conftest import _make_tenant

    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    mgr_headers = _auth_headers(onboarding_company["manager"])
    mgr_emp_id = onboarding_company["emp_mgr"].id

    # 1. limit=100000 -> 422
    res_limit = client.get("/api/v1/employees?limit=100000", headers=hr_headers)
    assert res_limit.status_code == 422

    # 2. sort=bogus -> 400 invalid_sort
    res_sort = client.get("/api/v1/employees?sort=bogus_col", headers=hr_headers)
    assert res_sort.status_code == 400
    assert res_sort.json()["error"]["code"] == "invalid_sort"

    # 3. Manager scope restriction:
    # emp_staff reports to emp_mgr. Create another employee emp_other reporting to NO ONE.
    res_other = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Independent",
            "email": f"indep-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert res_other.status_code == 201
    other_emp_id = res_other.json()["id"]

    # When manager lists employees, only emp_staff should appear, NEVER emp_other or emp_mgr
    res_mgr_list = client.get("/api/v1/employees", headers=mgr_headers)
    assert res_mgr_list.status_code == 200
    mgr_items = res_mgr_list.json()["items"]
    mgr_emp_ids = [e["id"] for e in mgr_items]
    assert str(onboarding_company["emp_staff"].id) in mgr_emp_ids
    assert other_emp_id not in mgr_emp_ids
    assert str(mgr_emp_id) not in mgr_emp_ids

    # Trying to tamper with query parameters:
    # a) Tamper with reporting_manager_id=other_id
    res_tamper_mgr = client.get(
        f"/api/v1/employees?reporting_manager_id={other_emp_id}", headers=mgr_headers
    )
    assert res_tamper_mgr.status_code == 200
    tamper_mgr_ids = [e["id"] for e in res_tamper_mgr.json()["items"]]
    assert other_emp_id not in tamper_mgr_ids
    assert str(onboarding_company["emp_staff"].id) in tamper_mgr_ids

    # b) Tamper with department_id
    res_tamper_dept = client.get(
        f"/api/v1/employees?department_id={onboarding_company['dept'].id}", headers=mgr_headers
    )
    assert res_tamper_dept.status_code == 200
    tamper_dept_ids = [e["id"] for e in res_tamper_dept.json()["items"]]
    assert other_emp_id not in tamper_dept_ids

    # c) Tamper with company_id of another tenant
    other_tenant = _make_tenant(
        db, name="Other Scope Co", code=f"OSC{uuid.uuid4().hex[:4].upper()}"
    )
    res_tamper_cid = client.get(
        f"/api/v1/employees?company_id={other_tenant.company_id}", headers=mgr_headers
    )
    assert res_tamper_cid.status_code == 200
    tamper_cid_ids = [e["id"] for e in res_tamper_cid.json()["items"]]
    assert other_emp_id not in tamper_cid_ids


# ==============================================================================
# R08: Token Hygiene & Isolation
# ==============================================================================


def test_r08_token_hygiene_and_isolation(
    client: TestClient, onboarding_company: dict[str, Any], db: Session
) -> None:
    """Response hygiene and tenant isolation:
    - Responses never contain activation_token_hash or any raw token field
    - Another company's employees never appear in GET /employees or GET /employees/{id}.
    """
    from tests.conftest import _make_tenant

    hr_headers = _auth_headers(onboarding_company["hr_admin"])

    # 1. Create employee and check response
    res_create = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "HygieneEmp",
            "email": f"hygiene-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert res_create.status_code == 201
    data_create = res_create.json()
    emp_id = data_create["id"]

    # Verify no token hash or secret leaked in create response
    assert "activation_token_hash" not in data_create
    assert "token" not in data_create
    assert "hashed_password" not in data_create

    # Verify GET /employees/{id} does not leak token hash
    res_get_one = client.get(f"/api/v1/employees/{emp_id}", headers=hr_headers)
    assert res_get_one.status_code == 200
    data_one = res_get_one.json()
    assert "activation_token_hash" not in data_one
    assert "token" not in data_one

    # Verify GET /employees list does not leak token hash
    res_list = client.get("/api/v1/employees", headers=hr_headers)
    assert res_list.status_code == 200
    for item in res_list.json()["items"]:
        assert "activation_token_hash" not in item
        assert "token" not in item

    # 2. Cross-company isolation
    cid = onboarding_company["company"].id
    other_tenant = _make_tenant(db, name="Other Iso Co", code=f"OIC{uuid.uuid4().hex[:4].upper()}")
    bind_tenant_to_session(db, company_id=other_tenant.company_id, is_platform_admin=False)
    other_emp_id = uuid.uuid4()
    other_emp = Employee(
        id=other_emp_id,
        company_id=other_tenant.company_id,
        employee_code=f"OIC-{uuid.uuid4().hex[:4].upper()}-0001",
        first_name="OtherTenantEmp",
        email=f"otheriso-{uuid.uuid4().hex[:6]}@example.com",
        hire_date=date(2025, 1, 1),
    )
    db.add(other_emp)
    db.commit()
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

    # Other tenant's employee must NOT appear in our list
    res_own_list = client.get("/api/v1/employees", headers=hr_headers)
    own_ids = [e["id"] for e in res_own_list.json()["items"]]
    assert str(other_emp_id) not in own_ids

    # GET /employees/{other_emp_id} must 404
    res_get_cross = client.get(f"/api/v1/employees/{other_emp_id}", headers=hr_headers)
    assert res_get_cross.status_code == 404
    assert res_get_cross.json()["error"]["code"] == "not_found"


# ==============================================================================
# R09: Audit Logging and Rate Limiting
# ==============================================================================


def test_r09_audit_logging_create_and_resend(
    client: TestClient, onboarding_company: dict[str, Any], db: Session
) -> None:
    """EMPLOYEE_CREATED and EMPLOYEE_INVITE_RESENT rows exist with the right
    actor and details, none on a failed request.
    """
    hr_user = onboarding_company["hr_admin"]
    hr_headers = _auth_headers(hr_user)
    cid = onboarding_company["company"].id

    # 1. Failed request writes NO audit log
    initial_audit_count = db.query(AuditLog).filter(AuditLog.company_id == cid).count()
    res_bad = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={"first_name": "BadAudit", "email": "bad@example.com"},  # missing hire_date gives 422
    )
    assert res_bad.status_code == 422
    after_bad_count = db.query(AuditLog).filter(AuditLog.company_id == cid).count()
    assert after_bad_count == initial_audit_count

    # 2. Successful create writes EMPLOYEE_CREATED audit log
    work_email = f"audit-{uuid.uuid4().hex[:6]}@example.com"
    res_ok = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={"first_name": "AuditEmployee", "email": work_email, "hire_date": "2025-01-01"},
    )
    assert res_ok.status_code == 201
    emp_id = uuid.UUID(res_ok.json()["id"])
    emp_code = res_ok.json()["employee_code"]

    audit_create = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_CREATED",
            AuditLog.entity_id == emp_id,
        )
        .all()
    )
    assert len(audit_create) == 1
    assert audit_create[0].actor_user_id == hr_user.id
    assert audit_create[0].entity_type == "employee"
    details_create = _get_audit_details(audit_create[0])
    assert details_create.get("employee_code") == emp_code
    assert details_create.get("email") == work_email

    # 3. Successful resend writes EMPLOYEE_INVITE_RESENT audit log
    res_resend = client.post(
        f"/api/v1/employees/{emp_id}/resend-invite",
        headers=hr_headers,
    )
    assert res_resend.status_code == 200

    audit_resend = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_INVITE_RESENT",
            AuditLog.entity_id == emp_id,
        )
        .all()
    )
    assert len(audit_resend) == 1
    assert audit_resend[0].actor_user_id == hr_user.id
    assert audit_resend[0].entity_type == "employee"
    details_resend = _get_audit_details(audit_resend[0])
    assert details_resend.get("employee_code") == emp_code
    assert details_resend.get("email") == work_email


def test_r09_rate_limiting_create_and_resend(
    client: TestClient, onboarding_company: dict[str, Any]
) -> None:
    """The 31st create by one user in a minute gives 429 (first 30 succeed).
    The 11th resend-invite by one user in a minute gives 429 (first 10 succeed).
    """
    hr_headers = _auth_headers(onboarding_company["hr_admin"])

    limiter.enabled = True
    try:
        # 1. Create rate limiting: 30/minute per user
        limiter.reset()
        create_responses = [
            client.post(
                "/api/v1/employees",
                headers=hr_headers,
                json={
                    "first_name": f"RateEmp{i}",
                    "email": f"rate{i}-{uuid.uuid4().hex[:6]}@example.com",
                    "hire_date": "2025-01-01",
                },
            )
            for i in range(35)
        ]
        create_codes = [r.status_code for r in create_responses]
        assert create_codes[:30] == [201] * 30, (
            f"Expected first 30 creates to succeed 201, got: {create_codes[:30]}"
        )
        assert all(c == 429 for c in create_codes[30:]), (
            f"Expected 31st+ creates to return 429, got: {create_codes[30:]}"
        )

        # 2. Resend invite rate limiting: 10/minute per user
        limiter.enabled = False
        res_setup = client.post(
            "/api/v1/employees",
            headers=hr_headers,
            json={
                "first_name": "ResendRateTarget",
                "email": f"resendrate-{uuid.uuid4().hex[:6]}@example.com",
                "hire_date": "2025-01-01",
            },
        )
        assert res_setup.status_code == 201
        target_emp_id = res_setup.json()["id"]

        limiter.enabled = True
        limiter.reset()
        resend_responses = [
            client.post(
                f"/api/v1/employees/{target_emp_id}/resend-invite",
                headers=hr_headers,
            )
            for _ in range(15)
        ]
        resend_codes = [r.status_code for r in resend_responses]
        assert resend_codes[:10] == [200] * 10, (
            f"Expected first 10 resend-invites to succeed 200, got: {resend_codes[:10]}"
        )
        assert all(c == 429 for c in resend_codes[10:]), (
            f"Expected 11th+ resend-invites to return 429, got: {resend_codes[10:]}"
        )

    finally:
        limiter.enabled = False
        limiter.reset()


# ==============================================================================
# STEP 1: Additional Strict Tests T1 - T6
# ==============================================================================


def test_t1_employee_validation_edge_cases(
    client: TestClient, onboarding_company: dict[str, Any], db: Session
) -> None:
    """T1:
    - phone > 20 chars -> 422
    - position > 150 chars -> 422
    - level not in ('L1', 'L2', 'L3') -> 422
    - personal_email invalid format -> 422
    - personal_email > 255 chars -> 422
    - notice_period_days > 365 -> 422
    - email with spaces is trimmed and stored lowercase.
    """
    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    cid = onboarding_company["company"].id

    base_payload = {
        "first_name": "ValEmp",
        "email": f"val-{uuid.uuid4().hex[:6]}@example.com",
        "hire_date": "2025-01-01",
    }

    # 1. phone 21 chars -> 422
    res_phone = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={**base_payload, "phone": "1" * 21},
    )
    assert res_phone.status_code == 422, (
        f"Expected 422 for phone 21 chars, got {res_phone.status_code}"
    )

    # 2. position 151 chars -> 422
    res_pos = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={**base_payload, "position": "P" * 151},
    )
    assert res_pos.status_code == 422, (
        f"Expected 422 for position 151 chars, got {res_pos.status_code}"
    )

    # Blank or whitespace-only phone and position -> 422
    assert (
        client.post(
            "/api/v1/employees",
            headers=hr_headers,
            json={**base_payload, "phone": ""},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/employees",
            headers=hr_headers,
            json={**base_payload, "phone": "   "},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/employees",
            headers=hr_headers,
            json={**base_payload, "position": ""},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/employees",
            headers=hr_headers,
            json={**base_payload, "position": "   "},
        ).status_code
        == 422
    )

    # 3. level not allowed (e.g. 'L99') -> 422
    res_lvl = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={**base_payload, "level": "L99"},
    )
    assert res_lvl.status_code == 422, f"Expected 422 for invalid level, got {res_lvl.status_code}"

    # 4. personal_email invalid -> 422
    res_p_email_bad = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={**base_payload, "personal_email": "not-an-email"},
    )
    assert res_p_email_bad.status_code == 422, (
        f"Expected 422 for bad personal_email, got {res_p_email_bad.status_code}"
    )

    # 5. personal_email 256+ chars -> 422
    long_prefix = "a" * 245
    res_p_email_long = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={**base_payload, "personal_email": f"{long_prefix}@example.com"},
    )
    assert res_p_email_long.status_code == 422, (
        f"Expected 422 for personal_email > 255 chars, got {res_p_email_long.status_code}"
    )

    # 6. notice_period_days 366 -> 422
    res_notice_366 = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={**base_payload, "notice_period_days": 366},
    )
    assert res_notice_366.status_code == 422, (
        f"Expected 422 for notice_period_days 366, got {res_notice_366.status_code}"
    )

    # 7. email with leading/trailing spaces and uppercase is trimmed and stored lowercase
    raw_email_local = f"  TrimCase-{uuid.uuid4().hex[:6]}@EXAMPLE.COM  "
    expected_lower = raw_email_local.strip().lower()
    res_trim_email = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "CaseTrim",
            "email": raw_email_local,
            "hire_date": "2025-01-01",
        },
    )
    assert res_trim_email.status_code == 201
    created_id = uuid.UUID(res_trim_email.json()["id"])
    assert res_trim_email.json()["email"] == expected_lower

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    db_emp = db.scalar(select(Employee).where(Employee.id == created_id))
    assert db_emp is not None
    assert db_emp.email == expected_lower


def test_t2_personal_email_visibility_by_role(
    client: TestClient, onboarding_company: dict[str, Any]
) -> None:
    """T2:
    Manager responses (list, managers/search, GET one) contain no personal_email (None).
    HR admin and owner see it.
    """
    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    owner_headers = _auth_headers(onboarding_company["owner"])
    mgr_headers = _auth_headers(onboarding_company["manager"])
    emp_mgr = onboarding_company["emp_mgr"]

    # Create an employee with personal_email reporting to emp_mgr
    secret_p_email = f"personal-{uuid.uuid4().hex[:6]}@example.com"
    secret_phone = "+1234567890"
    res_create = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Reportee",
            "last_name": "One",
            "email": f"rep-{uuid.uuid4().hex[:6]}@example.com",
            "personal_email": secret_p_email,
            "phone": secret_phone,
            "reporting_manager_id": str(emp_mgr.id),
            "hire_date": "2025-01-01",
        },
    )
    assert res_create.status_code == 201
    rep_id = res_create.json()["id"]

    # 1. HR admin GET /employees/{rep_id} sees personal_email
    res_hr_get = client.get(f"/api/v1/employees/{rep_id}", headers=hr_headers)
    assert res_hr_get.status_code == 200
    assert res_hr_get.json()["personal_email"] == secret_p_email

    # 2. Owner GET /employees/{rep_id} sees personal_email
    res_owner_get = client.get(f"/api/v1/employees/{rep_id}", headers=owner_headers)
    assert res_owner_get.status_code == 200
    assert res_owner_get.json()["personal_email"] == secret_p_email

    # 3. Manager GET /employees/{rep_id} does NOT see personal_email (is None)
    res_mgr_get = client.get(f"/api/v1/employees/{rep_id}", headers=mgr_headers)
    assert res_mgr_get.status_code == 200
    assert res_mgr_get.json().get("personal_email") is None, (
        f"Manager saw personal_email: {res_mgr_get.json().get('personal_email')}"
    )

    # 4. Manager GET /employees list does NOT see personal_email
    res_mgr_list = client.get("/api/v1/employees", headers=mgr_headers)
    assert res_mgr_list.status_code == 200
    for item in res_mgr_list.json()["items"]:
        assert item.get("personal_email") is None, (
            f"Manager saw personal_email in list: {item.get('personal_email')}"
        )

    # 5. GET /employees/managers/search does not return personal_email
    res_mgr_search = client.get("/api/v1/employees/managers/search", headers=mgr_headers)
    assert res_mgr_search.status_code == 200
    for item in res_mgr_search.json():
        assert "personal_email" not in item or item.get("personal_email") is None


def test_t3_used_token_fails_and_inactive_or_deleted_manager_gives_400(
    client: TestClient, onboarding_company: dict[str, Any], db: Session
) -> None:
    """T3:
    - A used activation token fails on second activation attempt (404/409).
    - Setting a deactivated or deleted reporting manager gives 400 invalid_reference.
    """
    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    cid = onboarding_company["company"].id

    from app.workers.tasks.email import send_email_task

    captured_tokens: list[str] = []

    def capture_task(*args, **kwargs):
        text_body = kwargs.get("text_body", "")
        prefix = "/activate/"
        if prefix in text_body:
            tok = text_body.split(prefix)[1].split()[0].strip()
            captured_tokens.append(tok)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(send_email_task, "delay", capture_task)
        res_create = client.post(
            "/api/v1/employees",
            headers=hr_headers,
            json={
                "first_name": "UseTokenEmp",
                "email": f"usetok-{uuid.uuid4().hex[:6]}@example.com",
                "hire_date": "2025-01-01",
            },
        )
        assert res_create.status_code == 201
        raw_token = captured_tokens[0]

    # First activation succeeds
    uname = f"u_{uuid.uuid4().hex[:8]}"
    res_act1 = client.post(
        "/api/v1/auth/activate",
        json={"token": raw_token, "username": uname, "password": "Password123!"},
    )
    assert res_act1.status_code == 200

    # Second activation fails (used token must not work)
    res_act2 = client.post(
        "/api/v1/auth/activate",
        json={"token": raw_token, "username": f"another_{uname}", "password": "Password123!"},
    )
    assert res_act2.status_code == 404, (
        f"Expected 404 on reused activation token, got {res_act2.status_code}"
    )
    assert res_act2.json()["error"]["code"] == "not_found"

    # Deactivated or deleted reporting manager check:
    # Create candidate manager
    res_cand = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "CandMgr",
            "email": f"candmgr-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert res_cand.status_code == 201
    cand_mgr_id = uuid.UUID(res_cand.json()["id"])

    # Deactivate cand_mgr
    assert client.delete(f"/api/v1/employees/{cand_mgr_id}", headers=hr_headers).status_code == 204

    # Attempt to create employee with deactivated manager -> 400 invalid_reference
    res_inact_mgr = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "SubStaff",
            "email": f"substaff-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "reporting_manager_id": str(cand_mgr_id),
        },
    )
    assert res_inact_mgr.status_code == 400
    assert res_inact_mgr.json()["error"]["code"] == "invalid_reference"

    # Soft delete cand_mgr
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    db_cand = db.scalar(select(Employee).where(Employee.id == cand_mgr_id))
    assert db_cand is not None
    db_cand.deleted_at = utcnow()
    db.commit()

    # Attempt to create employee with deleted manager -> 400 invalid_reference
    res_del_mgr = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "SubStaff2",
            "email": f"substaff2-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
            "reporting_manager_id": str(cand_mgr_id),
        },
    )
    assert res_del_mgr.status_code == 400
    assert res_del_mgr.json()["error"]["code"] == "invalid_reference"


def test_t4_manager_list_and_search_scoped_to_direct_reports(
    client: TestClient, onboarding_company: dict[str, Any]
) -> None:
    """T4:
    A manager's list AND managers/search equal exactly their direct reports,
    even with tampered query parameters.
    """
    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    mgr_headers = _auth_headers(onboarding_company["manager"])
    emp_staff = onboarding_company["emp_staff"]

    # Create unmanaged employee
    res_unmanaged = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "Unmanaged",
            "email": f"unmanaged-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert res_unmanaged.status_code == 201
    unmanaged_id = res_unmanaged.json()["id"]

    # 1. Manager's list equals EXACTLY the set of direct reports
    res_list = client.get("/api/v1/employees", headers=mgr_headers)
    assert res_list.status_code == 200
    list_ids = {e["id"] for e in res_list.json()["items"]}
    expected_direct_reports = {str(emp_staff.id)}
    assert list_ids == expected_direct_reports, (
        f"Expected {expected_direct_reports}, got {list_ids}"
    )

    # Tampered query parameters (e.g. reporting_manager_id) cannot leak others
    res_tampered_list = client.get(
        f"/api/v1/employees?reporting_manager_id={unmanaged_id}",
        headers=mgr_headers,
    )
    assert res_tampered_list.status_code == 200
    tampered_list_ids = {e["id"] for e in res_tampered_list.json()["items"]}
    assert tampered_list_ids == expected_direct_reports

    # 2. Manager's managers/search equals EXACTLY their direct reports
    res_search = client.get("/api/v1/employees/managers/search", headers=mgr_headers)
    assert res_search.status_code == 200
    search_ids = {e["id"] for e in res_search.json()}
    assert search_ids == expected_direct_reports, (
        f"Expected {expected_direct_reports}, got {search_ids}"
    )

    # Tampered search query parameter cannot expand beyond direct reports
    res_tampered_search = client.get(
        "/api/v1/employees/managers/search?q=Unmanaged",
        headers=mgr_headers,
    )
    assert res_tampered_search.status_code == 200
    tampered_search_ids = {e["id"] for e in res_tampered_search.json()}
    assert tampered_search_ids == set()


def test_t5_get_employee_by_id_access_matrix(
    client: TestClient, onboarding_company: dict[str, Any], db: Session
) -> None:
    """T5:
    GET /employees/{id}:
    - Manager sees own direct report -> 200
    - Manager outside the team -> exact denial (403 ForbiddenError)
    - Employee gets exact denial (403 ForbiddenError)
    - HR admin -> 200
    - Owner -> 200
    - Another company's employee -> 404
    """
    from tests.conftest import _make_tenant

    hr_headers = _auth_headers(onboarding_company["hr_admin"])
    owner_headers = _auth_headers(onboarding_company["owner"])
    mgr_headers = _auth_headers(onboarding_company["manager"])
    staff_headers = _auth_headers(onboarding_company["employee"])
    emp_staff = onboarding_company["emp_staff"]
    cid = onboarding_company["company"].id

    # Create another employee not reporting to emp_mgr
    res_outside = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "OutsideEmp",
            "email": f"outside-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert res_outside.status_code == 201
    outside_id = res_outside.json()["id"]

    # 1. Manager sees own direct report -> 200
    res_mgr_report = client.get(f"/api/v1/employees/{emp_staff.id}", headers=mgr_headers)
    assert res_mgr_report.status_code == 200

    # 2. Manager accesses outside employee -> 403 ForbiddenError
    res_mgr_outside = client.get(f"/api/v1/employees/{outside_id}", headers=mgr_headers)
    assert res_mgr_outside.status_code == 403
    assert res_mgr_outside.json()["error"]["code"] == "forbidden"
    assert "permission to view this employee" in res_mgr_outside.json()["error"]["message"]

    # 3. Staff employee accesses outside employee -> 403 ForbiddenError
    res_staff_outside = client.get(f"/api/v1/employees/{outside_id}", headers=staff_headers)
    assert res_staff_outside.status_code == 403
    assert res_staff_outside.json()["error"]["code"] == "forbidden"

    # 4. HR admin sees outside employee -> 200
    assert client.get(f"/api/v1/employees/{outside_id}", headers=hr_headers).status_code == 200

    # 5. Owner sees outside employee -> 200
    assert client.get(f"/api/v1/employees/{outside_id}", headers=owner_headers).status_code == 200

    # 6. Another company's employee -> 404
    other_tenant = _make_tenant(db, name="T5 Co", code=f"T5C{uuid.uuid4().hex[:4].upper()}")
    bind_tenant_to_session(db, company_id=other_tenant.company_id, is_platform_admin=False)
    cross_id = uuid.uuid4()
    cross_emp = Employee(
        id=cross_id,
        company_id=other_tenant.company_id,
        employee_code=f"T5C-{uuid.uuid4().hex[:4].upper()}-0001",
        first_name="CrossEmp",
        email=f"cross-{uuid.uuid4().hex[:6]}@example.com",
        hire_date=date(2025, 1, 1),
    )
    db.add(cross_emp)
    db.commit()
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

    res_cross = client.get(f"/api/v1/employees/{cross_id}", headers=hr_headers)
    assert res_cross.status_code == 404
    assert res_cross.json()["error"]["code"] == "not_found"
