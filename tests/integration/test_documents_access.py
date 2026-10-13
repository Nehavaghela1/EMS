import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole
from tests.conftest import TenantContext
from tests.integration.test_employees import _create_employee


def _link_user_to_employee(
    db: Session, company_id: uuid.UUID, employee_id: str, role: UserRole
) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    employee = db.get(Employee, uuid.UUID(employee_id))
    assert employee is not None
    employee.user_id = user.id
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


def test_employee_lists_own_documents_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """a) employee role lists own documents: allowed"""
    emp1 = _create_employee(
        client, company_a.hr_headers, email=f"emp1-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp1_headers = _link_user_to_employee(db, company_a.company_id, emp1["id"], UserRole.employee)

    res = client.get(f"/api/v1/documents/{emp1['id']}", headers=emp1_headers)
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), list)


def test_employee_lists_colleague_documents_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """b) employee role lists a colleague's documents: 403"""
    emp1 = _create_employee(
        client, company_a.hr_headers, email=f"emp1-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp2 = _create_employee(
        client, company_a.hr_headers, email=f"emp2-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp1_headers = _link_user_to_employee(db, company_a.company_id, emp1["id"], UserRole.employee)

    res = client.get(f"/api/v1/documents/{emp2['id']}", headers=emp1_headers)
    assert res.status_code == 403, res.text


def test_hr_admin_lists_any_employee_documents_in_own_company_allowed(
    client: TestClient, company_a: TenantContext
):
    """c) hr_admin lists any employee's documents in own company: allowed"""
    emp1 = _create_employee(
        client, company_a.hr_headers, email=f"emp1-{uuid.uuid4().hex[:6]}@example.com"
    )

    res = client.get(f"/api/v1/documents/{emp1['id']}", headers=company_a.hr_headers)
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), list)


def test_user_from_another_company_asks_for_employee_denied(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
):
    """d) user from another company asks for an employee ID of the first company: denied"""
    emp_a = _create_employee(
        client, company_a.hr_headers, email=f"emp-a-{uuid.uuid4().hex[:6]}@example.com"
    )

    # Tenant B tries to list Tenant A employee's documents
    res = client.get(f"/api/v1/documents/{emp_a['id']}", headers=company_b.hr_headers)
    assert res.status_code in (403, 404), res.text


def test_unauthenticated_request_unauthorized(client: TestClient, company_a: TenantContext):
    """e) unauthenticated: 401"""
    emp_a = _create_employee(
        client, company_a.hr_headers, email=f"emp-a-{uuid.uuid4().hex[:6]}@example.com"
    )

    res = client.get(f"/api/v1/documents/{emp_a['id']}")
    assert res.status_code == 401, res.text


def test_super_admin_of_company_a_asks_for_employee_of_company_b_denied(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    """f) super_admin of company A asks for an employee of company B: denied"""
    user_a = User(
        company_id=company_a.company_id,
        email=f"superadmin-a-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.super_admin,
        is_active=True,
    )
    db.add(user_a)
    db.commit()
    token_a = create_access_token(
        sub=str(user_a.id),
        company_id=str(company_a.company_id),
        role=UserRole.super_admin.value,
    )
    super_admin_a_headers = {"Authorization": f"Bearer {token_a}"}

    emp_b = _create_employee(
        client, company_b.hr_headers, email=f"emp-b-{uuid.uuid4().hex[:6]}@example.com"
    )

    res = client.get(f"/api/v1/documents/{emp_b['id']}", headers=super_admin_a_headers)
    assert res.status_code in (403, 404), res.text


def test_employee_asking_for_non_existent_id_gets_403(
    client: TestClient, db: Session, company_a: TenantContext
):
    """g) an employee asking for a non-existent ID gets the same 403 as asking
    for a colleague's ID.
    """
    emp1 = _create_employee(
        client, company_a.hr_headers, email=f"emp1-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp1_headers = _link_user_to_employee(db, company_a.company_id, emp1["id"], UserRole.employee)

    non_existent_id = uuid.uuid4()
    res = client.get(f"/api/v1/documents/{non_existent_id}", headers=emp1_headers)
    assert res.status_code == 403, res.text
