"""Tests for Module 2 Sub-feature 2.1: Departments.
Covers Rules 1-10:
- R01: Roles and permissions (403 for employee/mgr on write, 200 for hr/owner, 401, 200 read)
- R02: Input validation and trimming (name length, trimming, description <= 1000, clearance)
- R03: Uniqueness and concurrency (case-insensitive 409, concurrency 201+409, reuse after delete)
- R04: Cross-company isolation (404 on other company's dept, cross-company head rejected)
- R05: Department head rules (active employee requirement, auto-cleared on deactivation)
- R06: Delete rules (409 if active employees, 204 soft-delete, cannot assign deleted dept)
- R07: List rules (limit capped at 100, sort validation, live active employee count)
- R08: Audit logging (DEPARTMENT_CREATED, DEPARTMENT_UPDATED, DEPARTMENT_DELETED, no-op)
- R09: Rate limiting (30/min per user on writes) and atomicity (rollback on failure)
- R10: Meta rule
"""

import threading
import uuid
from datetime import date

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.core.pagination import page_params
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import Department, Employee, EmploymentType
from app.modules.hr.schemas import EmployeeCreateRequest
from app.modules.hr.service import EmployeeService
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog
from tests.conftest import REPO_ROOT


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        sub=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def dept_company(db: Session):
    """Fixture providing a company with owner, hr, manager, and employee users."""
    cid = uuid.uuid4()
    company = Company(
        id=cid,
        name=f"Dept Corp {uuid.uuid4().hex[:6]}",
        code=f"DC-{uuid.uuid4().hex[:4].upper()}",
        email=f"dept-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
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

    emp_service = EmployeeService(db)
    emp_owner, _ = emp_service.create_employee(
        cid,
        EmployeeCreateRequest(
            first_name="Owner",
            last_name="User",
            email=owner.email,
            employment_type=EmploymentType.full_time,
            hire_date=date(2025, 1, 1),
        ),
        actor=owner,
    )
    emp_hr, _ = emp_service.create_employee(
        cid,
        EmployeeCreateRequest(
            first_name="HR",
            last_name="Admin",
            email=hr_admin.email,
            employment_type=EmploymentType.full_time,
            hire_date=date(2025, 1, 1),
        ),
        actor=owner,
    )
    emp_mgr, _ = emp_service.create_employee(
        cid,
        EmployeeCreateRequest(
            first_name="Manager",
            last_name="One",
            email=manager.email,
            employment_type=EmploymentType.full_time,
            hire_date=date(2025, 1, 1),
        ),
        actor=owner,
    )
    emp_staff, _ = emp_service.create_employee(
        cid,
        EmployeeCreateRequest(
            first_name="Staff",
            last_name="Member",
            email=employee.email,
            employment_type=EmploymentType.full_time,
            hire_date=date(2025, 1, 1),
        ),
        actor=owner,
    )

    db.commit()

    return {
        "company": company,
        "owner": owner,
        "hr_admin": hr_admin,
        "manager": manager,
        "employee": employee,
        "emp_owner": emp_owner,
        "emp_hr": emp_hr,
        "emp_mgr": emp_mgr,
        "emp_staff": emp_staff,
    }


# ==============================================================================
# R01: Roles and Permissions
# ==============================================================================


def test_r01_roles_write_routes_permissions(client: TestClient, dept_company):
    """POST, PUT and DELETE: employee and manager get 403, hr_admin and owner succeed,
    unauthenticated get 401.
    """
    owner_headers = _auth_headers(dept_company["owner"])
    hr_headers = _auth_headers(dept_company["hr_admin"])
    mgr_headers = _auth_headers(dept_company["manager"])
    emp_headers = _auth_headers(dept_company["employee"])

    # 1. Unauthenticated (no token) -> 401
    assert client.post("/api/v1/departments", json={"name": "NoAuth"}).status_code == 401
    fake_id = uuid.uuid4()
    assert client.put(f"/api/v1/departments/{fake_id}", json={"name": "NoAuth"}).status_code == 401
    assert client.delete(f"/api/v1/departments/{fake_id}").status_code == 401

    # 2. Employee and Manager -> 403 on POST
    assert (
        client.post(
            "/api/v1/departments", headers=emp_headers, json={"name": "EmpDept"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/departments", headers=mgr_headers, json={"name": "MgrDept"}
        ).status_code
        == 403
    )

    # 3. hr_admin -> 201 on POST
    res_hr = client.post("/api/v1/departments", headers=hr_headers, json={"name": "HR Created"})
    assert res_hr.status_code == 201
    dept_id = res_hr.json()["id"]

    # 4. Employee and Manager -> 403 on PUT and DELETE
    assert (
        client.put(
            f"/api/v1/departments/{dept_id}", headers=emp_headers, json={"name": "EmpEdit"}
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/v1/departments/{dept_id}", headers=mgr_headers, json={"name": "MgrEdit"}
        ).status_code
        == 403
    )
    assert client.delete(f"/api/v1/departments/{dept_id}", headers=emp_headers).status_code == 403
    assert client.delete(f"/api/v1/departments/{dept_id}", headers=mgr_headers).status_code == 403

    # 5. owner -> succeeds on POST, PUT and DELETE
    res_owner_post = client.post(
        "/api/v1/departments", headers=owner_headers, json={"name": "Owner Created"}
    )
    assert res_owner_post.status_code == 201
    owner_dept_id = res_owner_post.json()["id"]

    res_owner_put = client.put(
        f"/api/v1/departments/{owner_dept_id}",
        headers=owner_headers,
        json={"name": "Owner Renamed"},
    )
    assert res_owner_put.status_code == 200
    assert res_owner_put.json()["name"] == "Owner Renamed"

    res_owner_del = client.delete(f"/api/v1/departments/{owner_dept_id}", headers=owner_headers)
    assert res_owner_del.status_code == 204


def test_r01_roles_read_routes_allowed_for_all_logged_in_users(client: TestClient, dept_company):
    """GET list and GET one return 200 for employee and manager."""
    hr_headers = _auth_headers(dept_company["hr_admin"])
    mgr_headers = _auth_headers(dept_company["manager"])
    emp_headers = _auth_headers(dept_company["employee"])

    res = client.post("/api/v1/departments", headers=hr_headers, json={"name": "Public Dept"})
    assert res.status_code == 201
    dept_id = res.json()["id"]

    # Manager reading list and one
    res_mgr_list = client.get("/api/v1/departments", headers=mgr_headers)
    assert res_mgr_list.status_code == 200
    res_mgr_one = client.get(f"/api/v1/departments/{dept_id}", headers=mgr_headers)
    assert res_mgr_one.status_code == 200
    assert res_mgr_one.json()["id"] == dept_id

    # Employee reading list and one
    res_emp_list = client.get("/api/v1/departments", headers=emp_headers)
    assert res_emp_list.status_code == 200
    res_emp_one = client.get(f"/api/v1/departments/{dept_id}", headers=emp_headers)
    assert res_emp_one.status_code == 200
    assert res_emp_one.json()["id"] == dept_id


# ==============================================================================
# R02: Input Validation and Trimming
# ==============================================================================


def test_r02_input_validation_name_boundaries_and_trimming(client: TestClient, dept_company):
    """Name: '' , '   ', one char and 151 chars get 422; '  Sales  ' stored as 'Sales';
    'HR' and 150-char accepted.
    """
    hr_headers = _auth_headers(dept_company["hr_admin"])

    # Invalid empty or whitespace name -> 422
    assert (
        client.post("/api/v1/departments", headers=hr_headers, json={"name": ""}).status_code == 422
    )
    assert (
        client.post("/api/v1/departments", headers=hr_headers, json={"name": "   "}).status_code
        == 422
    )
    assert (
        client.post("/api/v1/departments", headers=hr_headers, json={"name": "A"}).status_code
        == 422
    )

    # 151 characters -> 422
    long_name_151 = "N" * 151
    assert (
        client.post(
            "/api/v1/departments", headers=hr_headers, json={"name": long_name_151}
        ).status_code
        == 422
    )

    # "HR" (2 chars) accepted
    res_hr = client.post("/api/v1/departments", headers=hr_headers, json={"name": "HR"})
    assert res_hr.status_code == 201

    # 150 characters accepted
    long_name_150 = "N" * 150
    res_150 = client.post("/api/v1/departments", headers=hr_headers, json={"name": long_name_150})
    assert res_150.status_code == 201
    assert res_150.json()["name"] == long_name_150

    # Trimming: "  Sales  " is stored as "Sales"
    res_sales = client.post("/api/v1/departments", headers=hr_headers, json={"name": "  Sales  "})
    assert res_sales.status_code == 201
    assert res_sales.json()["name"] == "Sales"
    sales_id = res_sales.json()["id"]

    # PUT trimming and validation
    assert (
        client.put(
            f"/api/v1/departments/{sales_id}", headers=hr_headers, json={"name": ""}
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/departments/{sales_id}", headers=hr_headers, json={"name": "   "}
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/departments/{sales_id}", headers=hr_headers, json={"name": "X"}
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/departments/{sales_id}", headers=hr_headers, json={"name": long_name_151}
        ).status_code
        == 422
    )

    res_put_trim = client.put(
        f"/api/v1/departments/{sales_id}", headers=hr_headers, json={"name": "  Sales Team  "}
    )
    assert res_put_trim.status_code == 200
    assert res_put_trim.json()["name"] == "Sales Team"


def test_r02_input_validation_description_unknown_fields_wrong_types(
    client: TestClient, dept_company
):
    """Description > 1000 get 422; unknown fields get 422; name=123 gets 422;
    clearance_function 'legal' gets 422.
    """
    hr_headers = _auth_headers(dept_company["hr_admin"])

    # Description of 1001 chars -> 422
    desc_1001 = "D" * 1001
    assert (
        client.post(
            "/api/v1/departments",
            headers=hr_headers,
            json={"name": "DescTest", "description": desc_1001},
        ).status_code
        == 422
    )

    # Description of 1000 chars -> 201
    desc_1000 = "D" * 1000
    res_desc = client.post(
        "/api/v1/departments",
        headers=hr_headers,
        json={"name": "Desc1000", "description": desc_1000},
    )
    assert res_desc.status_code == 201
    dept_id = res_desc.json()["id"]

    # Unknown field -> 422 (extra='forbid')
    assert (
        client.post(
            "/api/v1/departments", headers=hr_headers, json={"name": "UnknownField", "foo": "bar"}
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/departments/{dept_id}", headers=hr_headers, json={"foo": "bar"}
        ).status_code
        == 422
    )

    # name wrong type (name=123) -> 422
    assert (
        client.post("/api/v1/departments", headers=hr_headers, json={"name": 123}).status_code
        == 422
    )

    # clearance_function invalid ("legal") -> 422
    assert (
        client.post(
            "/api/v1/departments",
            headers=hr_headers,
            json={"name": "LegalDept", "clearance_function": "legal"},
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/departments/{dept_id}",
            headers=hr_headers,
            json={"clearance_function": "legal"},
        ).status_code
        == 422
    )
    # T1: PUT with explicit null name -> 422
    assert (
        client.put(
            f"/api/v1/departments/{dept_id}",
            headers=hr_headers,
            json={"name": None},
        ).status_code
        == 422
    )


# ==============================================================================
# R03: Uniqueness and Concurrency
# ==============================================================================


def test_r03_name_uniqueness_case_insensitive_and_reuse_after_delete(
    client: TestClient, dept_company
):
    """'Sales' then 'sales' and 'SALES ' get 409 on POST and PUT rename;
    after DELETE, POST 'Sales' gives 201.
    """
    hr_headers = _auth_headers(dept_company["hr_admin"])

    # 1. Create "Sales" -> 201
    res1 = client.post("/api/v1/departments", headers=hr_headers, json={"name": "Sales"})
    assert res1.status_code == 201
    sales_id = res1.json()["id"]

    # 2. Duplicate "sales" and "SALES " -> 409
    assert (
        client.post("/api/v1/departments", headers=hr_headers, json={"name": "sales"}).status_code
        == 409
    )
    assert (
        client.post("/api/v1/departments", headers=hr_headers, json={"name": "SALES "}).status_code
        == 409
    )

    # 3. Create another department "Marketing" and rename it to "sales" -> 409
    res_mkt = client.post("/api/v1/departments", headers=hr_headers, json={"name": "Marketing"})
    assert res_mkt.status_code == 201
    mkt_id = res_mkt.json()["id"]

    assert (
        client.put(
            f"/api/v1/departments/{mkt_id}", headers=hr_headers, json={"name": "sales"}
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/v1/departments/{mkt_id}", headers=hr_headers, json={"name": "SALES "}
        ).status_code
        == 409
    )

    # 4. Delete "Sales" -> 204
    assert client.delete(f"/api/v1/departments/{sales_id}", headers=hr_headers).status_code == 204

    # 5. POST "Sales" again -> 201 (name of deleted department can be reused)
    res_reused = client.post("/api/v1/departments", headers=hr_headers, json={"name": "Sales"})
    assert res_reused.status_code == 201


def test_r03_cross_company_same_name_allowed(client: TestClient, dept_company, db: Session):
    """Another company may use the same department name."""
    from tests.conftest import _make_tenant

    other_tenant = _make_tenant(db, name="Other Co", code=f"OTH{uuid.uuid4().hex[:4].upper()}")
    hr_headers = _auth_headers(dept_company["hr_admin"])

    # Company 1 creates "Operations"
    res1 = client.post("/api/v1/departments", headers=hr_headers, json={"name": "Operations"})
    assert res1.status_code == 201

    # Company 2 creates "Operations" -> 201
    res2 = client.post(
        "/api/v1/departments", headers=other_tenant.hr_headers, json={"name": "Operations"}
    )
    assert res2.status_code == 201


def test_r03_concurrent_duplicate_creation_exactly_one_201_one_409():
    """Two simultaneous POSTs with the same name give exactly one 201
    and one 409 and never a 500.
    """
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    try:
        with Session(engine) as setup_sess:
            cid = uuid.uuid4()
            company = Company(
                id=cid,
                name="Concurrent Dept Co",
                code=f"CDC{uuid.uuid4().hex[:4].upper()}",
                email=f"cdc-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
                is_active=True,
            )
            user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.hr_admin,
                is_active=True,
            )
            setup_sess.add_all([company, user])
            setup_sess.commit()
            token = create_access_token(sub=str(user.id), company_id=str(cid), role=user.role.value)
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

        def worker():
            client = TestClient(fastapi_app)
            try:
                barrier.wait()
                resp = client.post(
                    "/api/v1/departments", headers=headers, json={"name": "ConcurrentDept"}
                )
                results.append(resp.status_code)
            except Exception:
                results.append(999)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert 500 not in results, f"Server returned 500 during race: {results}"
        assert sorted(results) == [201, 409], f"Expected one 201 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_r03_concurrent_case_variant_race():
    """Concurrent case-variant race: 'Race' and 'race ' posted at the same time
    give exactly one 201 and one 409 and no 500.
    """
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    try:
        with Session(engine) as setup_sess:
            cid = uuid.uuid4()
            company = Company(
                id=cid,
                name="Case Race Co",
                code=f"CRC{uuid.uuid4().hex[:4].upper()}",
                email=f"crc-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
                is_active=True,
            )
            user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.hr_admin,
                is_active=True,
            )
            setup_sess.add_all([company, user])
            setup_sess.commit()
            token = create_access_token(sub=str(user.id), company_id=str(cid), role=user.role.value)
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

        def worker(name: str):
            client = TestClient(fastapi_app)
            try:
                barrier.wait()
                resp = client.post("/api/v1/departments", headers=headers, json={"name": name})
                results.append(resp.status_code)
            except Exception:
                results.append(999)

        t1 = threading.Thread(target=worker, args=("Race",))
        t2 = threading.Thread(target=worker, args=("race ",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert 500 not in results, f"Server returned 500 during race: {results}"
        assert sorted(results) == [201, 409], f"Expected one 201 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()


# ==============================================================================
# R04: Cross-Company Isolation
# ==============================================================================


def test_r04_cross_company_isolation(client: TestClient, dept_company, db: Session):
    """Another company's hr_admin gets 404 on GET, PUT, DELETE of this company's dept.
    Setting head to another company's employee rejected.
    Creating/updating employee with another company's dept rejected.
    List shows only own departments.
    """
    from tests.conftest import _make_tenant

    company_b = _make_tenant(db, name="Company B", code=f"COB{uuid.uuid4().hex[:4].upper()}")
    hr_headers_a = _auth_headers(dept_company["hr_admin"])
    hr_headers_b = company_b.hr_headers

    # Company A creates a department
    res_a = client.post("/api/v1/departments", headers=hr_headers_a, json={"name": "Dept A"})
    assert res_a.status_code == 201
    dept_a_id = res_a.json()["id"]

    # Company B hr_admin GET, PUT, DELETE Dept A -> 404
    assert client.get(f"/api/v1/departments/{dept_a_id}", headers=hr_headers_b).status_code == 404
    assert (
        client.put(
            f"/api/v1/departments/{dept_a_id}", headers=hr_headers_b, json={"name": "Hack"}
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/departments/{dept_a_id}", headers=hr_headers_b).status_code == 404
    )

    # Setting head_employee_id to Company B's employee in Dept A -> rejected (400 or 404/422)
    # Create employee in Company B
    emp_b_res = client.post(
        "/api/v1/employees",
        headers=hr_headers_b,
        json={
            "first_name": "EmpB",
            "email": f"empb-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": "2025-01-01",
        },
    )
    assert emp_b_res.status_code == 201
    emp_b_id = emp_b_res.json()["id"]

    res_cross_head = client.put(
        f"/api/v1/departments/{dept_a_id}",
        headers=hr_headers_a,
        json={"head_employee_id": emp_b_id},
    )
    assert res_cross_head.status_code == 400
    assert res_cross_head.json()["error"]["code"] == "invalid_reference"

    # Creating an employee in Company A with Company B's department -> rejected
    res_b_dept = client.post("/api/v1/departments", headers=hr_headers_b, json={"name": "Dept B"})
    assert res_b_dept.status_code == 201
    dept_b_id = res_b_dept.json()["id"]

    res_emp_cross_dept = client.post(
        "/api/v1/employees",
        headers=hr_headers_a,
        json={
            "first_name": "CrossDept",
            "email": f"cross-{uuid.uuid4().hex[:6]}@example.com",
            "department_id": dept_b_id,
            "hire_date": "2025-01-01",
        },
    )
    assert res_emp_cross_dept.status_code == 400
    assert res_emp_cross_dept.json()["error"]["code"] == "invalid_reference"

    # List shows only own departments
    list_a = client.get("/api/v1/departments", headers=hr_headers_a).json()["items"]
    list_b = client.get("/api/v1/departments", headers=hr_headers_b).json()["items"]
    assert any(d["id"] == dept_a_id for d in list_a)
    assert not any(d["id"] == dept_b_id for d in list_a)
    assert any(d["id"] == dept_b_id for d in list_b)
    assert not any(d["id"] == dept_a_id for d in list_b)


# ==============================================================================
# R05: Department Head Rules
# ==============================================================================


def test_r05_department_head_active_requirement_and_auto_clear_on_deactivation(
    client: TestClient, dept_company, db: Session
):
    """PUT head of inactive employee rejected. Active accepted.
    Deactivating head employee auto-clears head with audit row.
    """
    hr_headers = _auth_headers(dept_company["hr_admin"])
    emp_staff = dept_company["emp_staff"]

    # Create department
    res_dept = client.post("/api/v1/departments", headers=hr_headers, json={"name": "HeadTestDept"})
    assert res_dept.status_code == 201
    dept_id = res_dept.json()["id"]

    # Deactivate emp_staff
    res_deact = client.delete(f"/api/v1/employees/{emp_staff.id}", headers=hr_headers)
    assert res_deact.status_code == 204

    # Setting inactive employee as head via PUT -> rejected (400)
    res_set_inactive = client.put(
        f"/api/v1/departments/{dept_id}",
        headers=hr_headers,
        json={"head_employee_id": str(emp_staff.id)},
    )
    assert res_set_inactive.status_code == 400
    assert res_set_inactive.json()["error"]["code"] == "invalid_reference"

    # Creating department with inactive employee as head via POST -> rejected (400)
    res_post_inactive = client.post(
        "/api/v1/departments",
        headers=hr_headers,
        json={"name": "PostInactiveHeadDept", "head_employee_id": str(emp_staff.id)},
    )
    assert res_post_inactive.status_code == 400
    assert res_post_inactive.json()["error"]["code"] == "invalid_reference"

    # Reactivate emp_staff
    res_react = client.post(f"/api/v1/employees/{emp_staff.id}/toggle-active", headers=hr_headers)
    assert res_react.status_code == 200

    # Setting active employee as head -> 200
    res_set_active = client.put(
        f"/api/v1/departments/{dept_id}",
        headers=hr_headers,
        json={"head_employee_id": str(emp_staff.id)},
    )
    assert res_set_active.status_code == 200
    assert res_set_active.json()["head_employee_id"] == str(emp_staff.id)

    # Deactivating the head employee -> auto-clears department head_employee_id
    res_deact2 = client.delete(f"/api/v1/employees/{emp_staff.id}", headers=hr_headers)
    assert res_deact2.status_code == 204

    res_check = client.get(f"/api/v1/departments/{dept_id}", headers=hr_headers)
    assert res_check.status_code == 200
    assert res_check.json()["head_employee_id"] is None

    # Check DEPARTMENT_UPDATED audit row for auto-clear without depending on created_at ordering
    audit_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == dept_company["company"].id,
            AuditLog.action == "DEPARTMENT_UPDATED",
            AuditLog.entity_id == uuid.UUID(dept_id),
        )
        .all()
    )
    assert any(
        r.details.get("head_employee_id", {}).get("from") == str(emp_staff.id)
        and r.details.get("head_employee_id", {}).get("to") is None
        for r in audit_rows
    ), "Audit log must contain auto-clear record with matching from/to"


def test_r05_department_head_auto_clear_on_termination(
    client: TestClient, dept_company, db: Session
):
    """Terminating head employee (POST /api/v1/employees/{id}/terminate)
    auto-clears head with DEPARTMENT_UPDATED audit row.
    """
    hr_headers = _auth_headers(dept_company["hr_admin"])
    emp_mgr = dept_company["emp_mgr"]

    # Create department with manager as head
    res_dept = client.post(
        "/api/v1/departments",
        headers=hr_headers,
        json={"name": "TermHeadDept", "head_employee_id": str(emp_mgr.id)},
    )
    assert res_dept.status_code == 201
    assert res_dept.json()["head_employee_id"] == str(emp_mgr.id)
    dept_id = res_dept.json()["id"]

    # Terminate the head employee
    term_res = client.post(
        f"/api/v1/employees/{emp_mgr.id}/terminate",
        headers=hr_headers,
        json={"termination_date": str(date.today()), "reason": "Restructuring"},
    )
    assert term_res.status_code == 200

    # Department head must now be cleared
    res_check = client.get(f"/api/v1/departments/{dept_id}", headers=hr_headers)
    assert res_check.status_code == 200
    assert res_check.json()["head_employee_id"] is None

    # Audit row written (assert matching from and to is None without created_at ordering dependence)
    audit_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == dept_company["company"].id,
            AuditLog.action == "DEPARTMENT_UPDATED",
            AuditLog.entity_id == uuid.UUID(dept_id),
        )
        .all()
    )
    assert any(
        r.details.get("head_employee_id", {}).get("from") == str(emp_mgr.id)
        and r.details.get("head_employee_id", {}).get("to") is None
        for r in audit_rows
    ), "Audit log must contain auto-clear record with matching from/to"


def test_r05_department_head_auto_clear_on_fnf_settlement(
    client: TestClient, dept_company, db: Session
):
    """Department head is cleared with DEPARTMENT_UPDATED audit row on FnF settlement."""
    hr_headers = _auth_headers(dept_company["hr_admin"])
    emp_staff = dept_company["emp_staff"]

    res_dept = client.post(
        "/api/v1/departments",
        headers=hr_headers,
        json={"name": f"FnFHeadDept-{uuid.uuid4().hex[:6]}", "head_employee_id": str(emp_staff.id)},
    )
    assert res_dept.status_code == 201
    assert res_dept.json()["head_employee_id"] == str(emp_staff.id)
    dept_id = res_dept.json()["id"]

    # Update FnF clearance with mark_settled=True
    res_fnf = client.put(
        f"/api/v1/employees/{emp_staff.id}/fnf/clearance",
        headers=hr_headers,
        json={"mark_settled": True},
    )
    assert res_fnf.status_code == 200

    # Department head must be cleared
    res_check = client.get(f"/api/v1/departments/{dept_id}", headers=hr_headers)
    assert res_check.status_code == 200
    assert res_check.json()["head_employee_id"] is None

    audit_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == dept_company["company"].id,
            AuditLog.action == "DEPARTMENT_UPDATED",
            AuditLog.entity_id == uuid.UUID(dept_id),
        )
        .all()
    )
    assert any(
        r.details.get("head_employee_id", {}).get("from") == str(emp_staff.id)
        and r.details.get("head_employee_id", {}).get("to") is None
        for r in audit_rows
    )


def test_r05_department_head_auto_clear_on_pip_failed(
    client: TestClient, dept_company, db: Session
):
    """Department head is cleared with DEPARTMENT_UPDATED audit row when PIP fails."""
    hr_headers = _auth_headers(dept_company["hr_admin"])
    emp_staff = dept_company["emp_staff"]

    res_dept = client.post(
        "/api/v1/departments",
        headers=hr_headers,
        json={"name": f"PipHeadDept-{uuid.uuid4().hex[:6]}", "head_employee_id": str(emp_staff.id)},
    )
    assert res_dept.status_code == 201
    assert res_dept.json()["head_employee_id"] == str(emp_staff.id)
    dept_id = res_dept.json()["id"]

    # Create PIP for emp_staff
    res_pip = client.post(
        "/api/v1/performance/pips",
        headers=hr_headers,
        json={
            "employee_id": str(emp_staff.id),
            "title": "Performance PIP",
            "start_date": str(date.today()),
            "end_date": str(date.today()),
        },
    )
    assert res_pip.status_code == 201
    pip_id = res_pip.json()["id"]

    # Evaluate PIP with outcome failed -> deactivates employee and should clear department head!
    res_eval = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=hr_headers,
        json={"outcome": "failed", "outcome_notes": "Did not meet milestones"},
    )
    assert res_eval.status_code == 200

    # Department head must be cleared
    res_check = client.get(f"/api/v1/departments/{dept_id}", headers=hr_headers)
    assert res_check.status_code == 200
    assert res_check.json()["head_employee_id"] is None

    audit_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == dept_company["company"].id,
            AuditLog.action == "DEPARTMENT_UPDATED",
            AuditLog.entity_id == uuid.UUID(dept_id),
        )
        .all()
    )
    assert any(
        r.details.get("head_employee_id", {}).get("from") == str(emp_staff.id)
        and r.details.get("head_employee_id", {}).get("to") is None
        for r in audit_rows
    )


# ==============================================================================
# R06: Delete Rules and Employee Lifecycle Journey
# ==============================================================================


def test_r06_delete_with_active_employees_fails_and_soft_delete(client: TestClient, dept_company):
    """Delete with active employees gives 409 with count. Delete empty dept gives 204,
    soft-deleted, not listed, GET 404.
    """
    hr_headers = _auth_headers(dept_company["hr_admin"])

    # 1. Create dept
    res_dept = client.post("/api/v1/departments", headers=hr_headers, json={"name": "AssignedDept"})
    assert res_dept.status_code == 201
    dept_id = res_dept.json()["id"]

    # 2. Assign active employee to it
    res_emp = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "DeptMember",
            "email": f"deptmember-{uuid.uuid4().hex[:6]}@example.com",
            "department_id": dept_id,
            "hire_date": "2025-01-01",
        },
    )
    assert res_emp.status_code == 201
    emp_id = res_emp.json()["id"]

    # 3. Attempt delete -> 409 containing count
    res_del_blocked = client.delete(f"/api/v1/departments/{dept_id}", headers=hr_headers)
    assert res_del_blocked.status_code == 409
    err_msg = res_del_blocked.json()["error"]["message"]
    assert "1" in err_msg or "active employee" in err_msg.lower()

    # 4. Remove employee from department
    client.put(f"/api/v1/employees/{emp_id}", headers=hr_headers, json={"department_id": None})

    # 5. Delete empty dept -> 204
    res_del = client.delete(f"/api/v1/departments/{dept_id}", headers=hr_headers)
    assert res_del.status_code == 204

    # 6. GET department -> 404
    assert client.get(f"/api/v1/departments/{dept_id}", headers=hr_headers).status_code == 404

    # 7. Deleted department is not listed
    dept_list = client.get("/api/v1/departments", headers=hr_headers).json()["items"]
    assert not any(d["id"] == dept_id for d in dept_list)

    # 8. Creating employee with deleted department is rejected
    res_new_emp = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "BadDeptEmp",
            "email": f"baddept-{uuid.uuid4().hex[:6]}@example.com",
            "department_id": dept_id,
            "hire_date": "2025-01-01",
        },
    )
    assert res_new_emp.status_code == 400
    assert res_new_emp.json()["error"]["code"] == "invalid_reference"

    # 9. Updating an existing employee with deleted department is rejected
    res_put_emp = client.put(
        f"/api/v1/employees/{emp_id}",
        headers=hr_headers,
        json={"department_id": dept_id},
    )
    assert res_put_emp.status_code == 400
    assert res_put_emp.json()["error"]["code"] == "invalid_reference"


def test_r06_deleted_department_employee_reactivation_journey(client: TestClient, dept_company):
    """Journey: inactive employee in dept X, X deleted (no active staff), reactivation rejected,
    HR sets another dept with PUT /employees/{id}, and reactivation succeeds.
    """
    hr_headers = _auth_headers(dept_company["hr_admin"])

    # 1. Create Department X and Department Y
    res_x = client.post("/api/v1/departments", headers=hr_headers, json={"name": "Dept X"})
    assert res_x.status_code == 201
    dept_x_id = res_x.json()["id"]

    res_y = client.post("/api/v1/departments", headers=hr_headers, json={"name": "Dept Y"})
    assert res_y.status_code == 201
    dept_y_id = res_y.json()["id"]

    # 2. Create employee in Dept X
    res_emp = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "JourneyEmp",
            "email": f"journey-{uuid.uuid4().hex[:6]}@example.com",
            "department_id": dept_x_id,
            "hire_date": "2025-01-01",
        },
    )
    assert res_emp.status_code == 201
    emp_id = res_emp.json()["id"]

    # 3. Deactivate employee (now Dept X has 0 active employees)
    assert client.delete(f"/api/v1/employees/{emp_id}", headers=hr_headers).status_code == 204

    # 4. Delete Dept X -> 204
    assert client.delete(f"/api/v1/departments/{dept_x_id}", headers=hr_headers).status_code == 204

    # 5. Reactivation via POST /api/v1/employees/{id}/toggle-active is rejected
    # because Dept X is deleted
    res_reactivate_fail = client.post(
        f"/api/v1/employees/{emp_id}/toggle-active", headers=hr_headers
    )
    assert res_reactivate_fail.status_code == 400
    assert res_reactivate_fail.json()["error"]["code"] == "invalid_reference"

    # 6. HR sets Department Y with PUT /api/v1/employees/{id}
    res_update_dept = client.put(
        f"/api/v1/employees/{emp_id}", headers=hr_headers, json={"department_id": dept_y_id}
    )
    assert res_update_dept.status_code == 200

    # 7. Reactivation succeeds
    res_reactivate_success = client.post(
        f"/api/v1/employees/{emp_id}/toggle-active", headers=hr_headers
    )
    assert res_reactivate_success.status_code == 200
    assert res_reactivate_success.json()["is_active"] is True


# ==============================================================================
# R07: List Rules
# ==============================================================================


def test_r07_unit_pageparams_limit_capped_at_100():
    """Unit test that the page_params dependency capping/defaults enforce limits."""
    import inspect

    from fastapi.params import Query

    sig = inspect.signature(page_params)
    limit_param = sig.parameters["limit"]
    assert isinstance(limit_param.default, Query)
    # Check attributes or constraints on Query
    q = limit_param.default
    # In Pydantic v2 / FastAPI, constraints are in metadata or attributes
    assert q.default == 20
    # Check le constraint in metadata or attributes
    has_le_100 = False
    for item in getattr(q, "metadata", []):
        if getattr(item, "le", None) == 100 or getattr(item, "upper_bound", None) == 100:
            has_le_100 = True
    msg = f"Query metadata: {getattr(q, 'metadata', None)}"
    assert has_le_100 or getattr(q, "le", None) == 100, msg


def test_r07_route_pagination_search_sort_and_live_active_counts(
    client: TestClient, dept_company, db: Session
):
    """GET /departments?limit=100000 returns <=100 items; sort=bogus returns 400;
    sort=name works; q works; active employees only counted.
    """
    from tests.conftest import _make_tenant

    hr_headers = _auth_headers(dept_company["hr_admin"])

    # 1. limit=100000 returns exactly 422 Unprocessable Entity
    res_limit = client.get("/api/v1/departments?limit=100000", headers=hr_headers)
    assert res_limit.status_code == 422

    # 2. sort=bogus -> 400
    res_sort_bogus = client.get("/api/v1/departments?sort=bogus", headers=hr_headers)
    assert res_sort_bogus.status_code == 400

    # 3. sort=name works
    res_sort_name = client.get("/api/v1/departments?sort=name", headers=hr_headers)
    assert res_sort_name.status_code == 200

    # 4. q search works
    client.post("/api/v1/departments", headers=hr_headers, json={"name": "AlphaSearchDept"})
    res_q = client.get("/api/v1/departments?q=AlphaSearch", headers=hr_headers)
    assert res_q.status_code == 200
    assert any(d["name"] == "AlphaSearchDept" for d in res_q.json()["items"])

    # 5. Live active count calculation
    res_dept_count = client.post(
        "/api/v1/departments", headers=hr_headers, json={"name": "CountDept"}
    )
    assert res_dept_count.status_code == 201
    c_dept_id = res_dept_count.json()["id"]

    # Add active employee
    emp1_res = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "ActiveOne",
            "email": f"active1-{uuid.uuid4().hex[:6]}@example.com",
            "department_id": c_dept_id,
            "hire_date": "2025-01-01",
        },
    )
    assert emp1_res.status_code == 201

    # Add inactive employee
    emp2_res = client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "first_name": "InactiveTwo",
            "email": f"inact2-{uuid.uuid4().hex[:6]}@example.com",
            "department_id": c_dept_id,
            "hire_date": "2025-01-01",
        },
    )
    assert emp2_res.status_code == 201
    emp2_id = emp2_res.json()["id"]
    client.delete(f"/api/v1/employees/{emp2_id}", headers=hr_headers)

    # Add deleted employee (soft-deleted in DB with deleted_at set)
    emp_del = Employee(
        id=uuid.uuid4(),
        company_id=dept_company["company"].id,
        first_name="DeletedThree",
        email=f"del3-{uuid.uuid4().hex[:6]}@example.com",
        employee_code=f"EMP-DEL-{uuid.uuid4().hex[:4]}",
        department_id=uuid.UUID(c_dept_id),
        employment_type=EmploymentType.full_time,
        hire_date=date(2025, 1, 1),
        is_active=True,
        deleted_at=date(2025, 2, 1),
    )
    db.add(emp_del)
    db.flush()

    # Add employee of another company assigned to same dept_id string
    other_tenant = _make_tenant(
        db, name="Other Headcount Co", code=f"OHC{uuid.uuid4().hex[:4].upper()}"
    )
    bind_tenant_to_session(db, company_id=other_tenant.company_id, is_platform_admin=True)
    emp_other = Employee(
        id=uuid.uuid4(),
        company_id=other_tenant.company_id,
        first_name="OtherCoEmp",
        email=f"otherco-{uuid.uuid4().hex[:6]}@example.com",
        employee_code=f"EMP-OTH-{uuid.uuid4().hex[:4]}",
        department_id=uuid.UUID(c_dept_id),
        employment_type=EmploymentType.full_time,
        hire_date=date(2025, 1, 1),
        is_active=True,
    )
    db.add(emp_other)
    db.flush()
    # Restore session context to dept_company
    bind_tenant_to_session(db, company_id=dept_company["company"].id, is_platform_admin=True)

    # Check live count in GET /departments/{id} and list: exactly 1 active employee
    res_single = client.get(f"/api/v1/departments/{c_dept_id}", headers=hr_headers)
    assert res_single.status_code == 200
    assert res_single.json()["employee_count"] == 1


# ==============================================================================
# R08: Audit Logging
# ==============================================================================


def test_r08_audit_rows_create_update_delete_and_noop(
    client: TestClient, dept_company, db: Session
):
    """Create, update and delete write exactly one audit row
    (DEPARTMENT_CREATED, DEPARTMENT_UPDATED, DEPARTMENT_DELETED).
    Update details show old and new values. No-op update writes no audit row.
    """
    hr_user = dept_company["hr_admin"]
    hr_headers = _auth_headers(hr_user)
    cid = dept_company["company"].id

    # 1. CREATE -> DEPARTMENT_CREATED
    res_c = client.post(
        "/api/v1/departments",
        headers=hr_headers,
        json={"name": "AuditDept", "description": "Initial"},
    )
    assert res_c.status_code == 201
    dept_id = uuid.UUID(res_c.json()["id"])

    audit_c = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "DEPARTMENT_CREATED",
            AuditLog.entity_id == dept_id,
        )
        .all()
    )
    assert len(audit_c) == 1
    assert audit_c[0].actor_user_id == hr_user.id
    assert audit_c[0].entity_type == "department"

    # 2. UPDATE with changes -> DEPARTMENT_UPDATED with diff
    res_u = client.put(
        f"/api/v1/departments/{dept_id}",
        headers=hr_headers,
        json={"name": "AuditDeptUpdated", "clearance_function": "finance"},
    )
    assert res_u.status_code == 200

    audit_u = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "DEPARTMENT_UPDATED",
            AuditLog.entity_id == dept_id,
        )
        .all()
    )
    assert len(audit_u) == 1
    diff = audit_u[0].details
    assert diff.get("name", {}).get("from") == "AuditDept"
    assert diff.get("name", {}).get("to") == "AuditDeptUpdated"
    assert diff.get("clearance_function", {}).get("to") == "finance"

    # 3. NO-OP UPDATE -> returns 200 and writes NO new row
    res_noop = client.put(
        f"/api/v1/departments/{dept_id}",
        headers=hr_headers,
        json={"name": "AuditDeptUpdated"},
    )
    assert res_noop.status_code == 200
    audit_u_after = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "DEPARTMENT_UPDATED",
            AuditLog.entity_id == dept_id,
        )
        .all()
    )
    assert len(audit_u_after) == 1, "No-op update must not write a new audit row"

    # 4. DELETE -> DEPARTMENT_DELETED
    res_d = client.delete(f"/api/v1/departments/{dept_id}", headers=hr_headers)
    assert res_d.status_code == 204

    audit_d = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "DEPARTMENT_DELETED",
            AuditLog.entity_id == dept_id,
        )
        .all()
    )
    assert len(audit_d) == 1
    assert audit_d[0].actor_user_id == hr_user.id


# ==============================================================================
# R09: Rate Limiting and Atomicity
# ==============================================================================


def test_r09_rate_limiting_write_routes(client: TestClient, dept_company):
    """The 31st write (POST, PUT, DELETE) within a minute by the same user gets 429;
    first 30 succeed. GET is not limited.
    """
    hr_headers = _auth_headers(dept_company["hr_admin"])

    limiter.enabled = True
    try:
        # 1. POST rate limit
        limiter.reset()
        responses = [
            client.post("/api/v1/departments", headers=hr_headers, json={"name": f"RateDept{i}"})
            for i in range(35)
        ]
        codes = [r.status_code for r in responses]
        assert codes[:30] == [201] * 30
        assert all(c == 429 for c in codes[30:]), f"Expected 429 after 30 POSTs, got {codes[30:]}"

        # GET is not limited at that rate
        res_get = client.get("/api/v1/departments", headers=hr_headers)
        assert res_get.status_code == 200

        # 2. PUT rate limit: 31st PUT gets 429, first 30 succeed
        limiter.enabled = False
        dept_res = client.post(
            "/api/v1/departments", headers=hr_headers, json={"name": "PutRateDept"}
        )
        assert dept_res.status_code == 201
        p_dept_id = dept_res.json()["id"]

        limiter.enabled = True
        limiter.reset()
        put_responses = [
            client.put(
                f"/api/v1/departments/{p_dept_id}",
                headers=hr_headers,
                json={"description": f"desc {i}"},
            )
            for i in range(35)
        ]
        put_codes = [r.status_code for r in put_responses]
        assert put_codes[:30] == [200] * 30
        assert all(c == 429 for c in put_codes[30:]), (
            f"Expected 429 after 30 PUTs, got {put_codes[30:]}"
        )

        # 3. DELETE rate limit: create 35 depts with limiter disabled, then test DELETE rate limit
        limiter.enabled = False
        del_ids = []
        for i in range(35):
            r = client.post(
                "/api/v1/departments", headers=hr_headers, json={"name": f"DelRateDept{i}"}
            )
            assert r.status_code == 201
            del_ids.append(r.json()["id"])

        limiter.enabled = True
        limiter.reset()
        del_responses = [
            client.delete(f"/api/v1/departments/{did}", headers=hr_headers) for did in del_ids
        ]
        del_codes = [r.status_code for r in del_responses]
        assert del_codes[:30] == [204] * 30
        assert all(c == 429 for c in del_codes[30:]), (
            f"Expected 429 after 30 DELETEs, got {del_codes[30:]}"
        )
    finally:
        limiter.enabled = False
        limiter.reset()


def test_r09_atomicity_audit_failure_rolls_back_department(
    client: TestClient, dept_company, db: Session
):
    """With audit call patched to raise, POST returns 500 and NO department row exists."""
    from app.modules.platform.service import AuditService

    hr_headers = _auth_headers(dept_company["hr_admin"])
    dept_name = f"AtomicityDept-{uuid.uuid4().hex[:6]}"

    with pytest.MonkeyPatch.context() as mp:

        def fake_record(*args, **kwargs):
            raise RuntimeError("Database error during audit write")

        mp.setattr(AuditService, "record", fake_record)

        # Use TestClient with raise_server_exceptions=False
        from app.main import app

        safe_client = TestClient(app, raise_server_exceptions=False)

        resp = safe_client.post("/api/v1/departments", headers=hr_headers, json={"name": dept_name})
        assert resp.status_code == 500

    # Verify department was NOT created in DB
    dept_in_db = (
        db.query(Department)
        .filter(Department.company_id == dept_company["company"].id, Department.name == dept_name)
        .first()
    )
    assert dept_in_db is None, "Department row must not exist after rollback on audit failure"


# ==============================================================================
# T7: Migration Tests (7c8d9e0f1a2b)
# ==============================================================================


def test_t7_migration_departments_lower_name_index():
    """T7: Migration tests:
    a) at revision b3a17e0892c1, seed two ACTIVE departments whose names differ only in case
       -> upgrade to 7c8d9e0f1a2b raises RuntimeError naming the duplicates under FORCE RLS.
    b) a soft-deleted duplicate + an active one -> upgrade succeeds.
    c) upgrade -> downgrade -> upgrade round trip. The index names are correct at each step.
    d) downgrade when a soft-deleted and an active department share the exact name
       -> raises a clear RuntimeError, not a raw DB error.
    Leave the DB at head afterwards. Clean up anything committed.
    """
    assert settings.TEST_MIGRATION_URL is not None, "TEST_MIGRATION_URL must be configured"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)

        owner_engine = create_engine(settings.TEST_MIGRATION_URL)
        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        comp_id = uuid.uuid4()
        comp_code = f"MIG{comp_id.hex[:10].upper()}"
        d1_id = uuid.uuid4()
        d2_id = uuid.uuid4()

        try:
            # Setup company
            with owner_engine.connect() as conn:
                with conn.begin():
                    conn.execute(
                        text(
                            """
                            INSERT INTO companies (
                                id, name, code, email, status, country,
                                currency, last_employee_seq, created_at, updated_at
                            )
                            VALUES (
                                :comp_id, 'Migration Dept Corp', :comp_code, :email,
                                'active', 'IN', 'INR', 0, NOW(), NOW()
                            )
                            """
                        ),
                        {
                            "comp_id": comp_id,
                            "comp_code": comp_code,
                            "email": f"{comp_code.lower()}@test.test",
                        },
                    )

            # Downgrade to b3a17e0892c1
            command.downgrade(cfg, "b3a17e0892c1")

            # --- Subtest (a): Two active departments differing only in case raise RuntimeError ---
            with owner_engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY;"))
                    conn.execute(
                        text(
                            """
                            INSERT INTO departments (id, company_id, name, created_at, updated_at)
                            VALUES (:d1_id, :comp_id, 'Engineering', NOW(), NOW()),
                                   (:d2_id, :comp_id, 'engineering', NOW(), NOW())
                            """
                        ),
                        {"d1_id": d1_id, "d2_id": d2_id, "comp_id": comp_id},
                    )
                    conn.execute(text("ALTER TABLE departments FORCE ROW LEVEL SECURITY;"))

            with pytest.raises(RuntimeError) as exc_info:
                command.upgrade(cfg, "7c8d9e0f1a2b")
            assert "duplicate" in str(exc_info.value).lower()
            assert "engineering" in str(exc_info.value).lower()

            # Clean up d2 so we can test (b)
            with owner_engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY;"))
                    conn.execute(
                        text("DELETE FROM departments WHERE id = :d2_id"),
                        {"d2_id": d2_id},
                    )
                    conn.execute(text("ALTER TABLE departments FORCE ROW LEVEL SECURITY;"))

            # --- Subtest (b): A soft-deleted duplicate + an active one -> upgrade succeeds ---
            with owner_engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY;"))
                    conn.execute(
                        text(
                            """
                            INSERT INTO departments (
                                id, company_id, name, deleted_at, created_at, updated_at
                            )
                            VALUES (:d2_id, :comp_id, 'engineering', NOW(), NOW(), NOW())
                            """
                        ),
                        {"d2_id": d2_id, "comp_id": comp_id},
                    )
                    conn.execute(text("ALTER TABLE departments FORCE ROW LEVEL SECURITY;"))

            # Upgrade should now succeed
            command.upgrade(cfg, "7c8d9e0f1a2b")

            # Clean up d1 and d2
            with owner_engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY;"))
                    conn.execute(
                        text("DELETE FROM departments WHERE id IN (:d1_id, :d2_id)"),
                        {"d1_id": d1_id, "d2_id": d2_id},
                    )
                    conn.execute(text("ALTER TABLE departments FORCE ROW LEVEL SECURITY;"))

            # --- Subtest (c): Round trip upgrade -> downgrade -> upgrade and index verification ---
            # Currently at 7c8d9e0f1a2b. Check index uq_departments_company_lower_name exists
            insp = inspect(owner_engine)
            indexes = [idx["name"] for idx in insp.get_indexes("departments")]
            assert "uq_departments_company_lower_name" in indexes
            assert "uq_departments_company_id_name" not in indexes

            # Downgrade to b3a17e0892c1
            command.downgrade(cfg, "b3a17e0892c1")
            insp = inspect(owner_engine)
            indexes = [idx["name"] for idx in insp.get_indexes("departments")]
            assert "uq_departments_company_id_name" in indexes
            assert "uq_departments_company_lower_name" not in indexes

            # Upgrade back to 7c8d9e0f1a2b
            command.upgrade(cfg, "7c8d9e0f1a2b")
            insp = inspect(owner_engine)
            indexes = [idx["name"] for idx in insp.get_indexes("departments")]
            assert "uq_departments_company_lower_name" in indexes
            assert "uq_departments_company_id_name" not in indexes

            # --- Subtest (d): Downgrade when duplicate active & deleted exists -> RuntimeError ---
            with owner_engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY;"))
                    conn.execute(
                        text(
                            """
                            INSERT INTO departments (
                                id, company_id, name, deleted_at, created_at, updated_at
                            )
                            VALUES (:d1_id, :comp_id, 'ExactName', NOW(), NOW(), NOW())
                            """
                        ),
                        {"d1_id": d1_id, "comp_id": comp_id},
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO departments (id, company_id, name, created_at, updated_at)
                            VALUES (:d2_id, :comp_id, 'ExactName', NOW(), NOW())
                            """
                        ),
                        {"d2_id": d2_id, "comp_id": comp_id},
                    )
                    conn.execute(text("ALTER TABLE departments FORCE ROW LEVEL SECURITY;"))

            # Downgrade should fail with a clear RuntimeError, NOT a raw DB error
            with pytest.raises(RuntimeError) as exc_down:
                command.downgrade(cfg, "b3a17e0892c1")
            assert (
                "cannot restore" in str(exc_down.value).lower()
                or "duplicate" in str(exc_down.value).lower()
            )

        finally:
            # Cleanup: ensure DB is back at head and test rows removed
            try:
                command.upgrade(cfg, "head")
            finally:
                with owner_engine.connect() as conn:
                    with conn.begin():
                        conn.execute(text("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY;"))
                        conn.execute(
                            text("DELETE FROM departments WHERE id IN (:d1_id, :d2_id)"),
                            {"d1_id": d1_id, "d2_id": d2_id},
                        )
                        conn.execute(
                            text("DELETE FROM companies WHERE id = :comp_id"),
                            {"comp_id": comp_id},
                        )
                        conn.execute(text("ALTER TABLE departments FORCE ROW LEVEL SECURITY;"))
                owner_engine.dispose()
