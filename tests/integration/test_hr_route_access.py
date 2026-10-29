import uuid
from datetime import date, timedelta

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


def test_employee_submits_resignation_for_own_record_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """a) employee submits resignation for own record: allowed"""
    emp1 = _create_employee(
        client, company_a.hr_headers, email=f"emp1-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp1_headers = _link_user_to_employee(db, company_a.company_id, emp1["id"], UserRole.employee)

    res = client.post(
        f"/api/v1/employees/{emp1['id']}/resignation",
        headers=emp1_headers,
        json={
            "resignation_date": str(date.today()),
            "last_working_date": str(date.today() + timedelta(days=30)),
            "reason": "Personal reasons",
        },
    )
    assert res.status_code == 200, res.text


def test_employee_submits_resignation_for_colleague_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """b) employee submits resignation for a colleague: 403"""
    emp1 = _create_employee(
        client, company_a.hr_headers, email=f"emp1-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp2 = _create_employee(
        client, company_a.hr_headers, email=f"emp2-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp1_headers = _link_user_to_employee(db, company_a.company_id, emp1["id"], UserRole.employee)

    res = client.post(
        f"/api/v1/employees/{emp2['id']}/resignation",
        headers=emp1_headers,
        json={
            "resignation_date": str(date.today()),
            "last_working_date": str(date.today() + timedelta(days=30)),
            "reason": "Impersonation attempt",
        },
    )
    assert res.status_code == 403, res.text


def test_hr_admin_submits_resignation_for_any_employee_in_own_company_allowed(
    client: TestClient, company_a: TenantContext
):
    """c) hr_admin submits resignation for any employee in own company: allowed"""
    emp1 = _create_employee(
        client, company_a.hr_headers, email=f"emp1-{uuid.uuid4().hex[:6]}@example.com"
    )

    res = client.post(
        f"/api/v1/employees/{emp1['id']}/resignation",
        headers=company_a.hr_headers,
        json={
            "resignation_date": str(date.today()),
            "last_working_date": str(date.today() + timedelta(days=30)),
            "reason": "Submitted by HR",
        },
    )
    assert res.status_code == 200, res.text


def test_employee_calls_fnf_for_own_record_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """d) employee calls F&F for own record: 403"""
    emp1 = _create_employee(
        client, company_a.hr_headers, email=f"emp1-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp1_headers = _link_user_to_employee(db, company_a.company_id, emp1["id"], UserRole.employee)

    res = client.get(f"/api/v1/employees/{emp1['id']}/fnf", headers=emp1_headers)
    assert res.status_code == 403, res.text


def test_hr_admin_calls_fnf_in_own_company_allowed(client: TestClient, company_a: TenantContext):
    """e) hr_admin calls F&F in own company: allowed"""
    emp1 = _create_employee(
        client, company_a.hr_headers, email=f"emp1-{uuid.uuid4().hex[:6]}@example.com"
    )

    res = client.get(f"/api/v1/employees/{emp1['id']}/fnf", headers=company_a.hr_headers)
    assert res.status_code == 200, res.text


def test_user_from_another_company_calls_either_route_denied(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
):
    """f) user from another company calls either route: 403 or 404"""
    emp_a = _create_employee(
        client, company_a.hr_headers, email=f"emp-a-{uuid.uuid4().hex[:6]}@example.com"
    )

    # 1. Resignation from company B caller
    res_resignation = client.post(
        f"/api/v1/employees/{emp_a['id']}/resignation",
        headers=company_b.hr_headers,
        json={
            "resignation_date": "2026-09-01",
            "last_working_date": "2026-10-01",
            "reason": "Cross-company resignation",
        },
    )
    assert res_resignation.status_code in (403, 404), res_resignation.text

    # 2. FnF from company B caller
    res_fnf = client.get(f"/api/v1/employees/{emp_a['id']}/fnf", headers=company_b.hr_headers)
    assert res_fnf.status_code in (403, 404), res_fnf.text


def test_unauthenticated_request_unauthorized(client: TestClient, company_a: TenantContext):
    """g) unauthenticated: 401"""
    emp_a = _create_employee(
        client, company_a.hr_headers, email=f"emp-a-{uuid.uuid4().hex[:6]}@example.com"
    )

    res_resignation = client.post(
        f"/api/v1/employees/{emp_a['id']}/resignation",
        json={
            "resignation_date": "2026-09-01",
            "last_working_date": "2026-10-01",
            "reason": "Unauthenticated resignation",
        },
    )
    assert res_resignation.status_code == 401, res_resignation.text

    res_fnf = client.get(f"/api/v1/employees/{emp_a['id']}/fnf")
    assert res_fnf.status_code == 401, res_fnf.text
