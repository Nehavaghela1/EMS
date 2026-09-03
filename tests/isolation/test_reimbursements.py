import uuid
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import User, UserRole
from tests.conftest import TenantContext


def _create_employee_with_user(
    db: Session, company_id: uuid.UUID
) -> tuple[Employee, dict[str, str]]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.test",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(user)
    db.flush()

    employee = Employee(
        company_id=company_id,
        user_id=user.id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Emp",
        last_name="Test",
        email=user.email,
        employment_type=EmploymentType.full_time,
        hire_date=date.today(),
        is_active=True,
        invitation_status=InvitationStatus.activated,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    token = create_access_token(
        sub=str(user.id), company_id=str(company_id), role=UserRole.employee.value
    )
    return employee, {"Authorization": f"Bearer {token}"}


def test_reimbursements_are_tenant_isolated(
    client: TestClient, company_a: TenantContext, company_b: TenantContext, db: Session
):
    emp_a, emp_a_headers = _create_employee_with_user(db, company_a.company_id)

    # 1. Employee of Company A submits a claim
    submit_res = client.post(
        "/api/v1/payroll/reimbursements",
        json={
            "type": "travel",
            "amount": "1200.00",
            "expense_date": "2026-05-15",
            "description": "Company A travel claim",
        },
        headers=emp_a_headers,
    )
    assert submit_res.status_code == 201
    claim_id = submit_res.json()["id"]

    # 2. HR Admin of Company B attempts to approve Company A's claim -> 404 Not Found
    review_res = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        json={"action": "approve"},
        headers=company_b.hr_headers,
    )
    assert review_res.status_code == 404

    # 3. HR Admin of Company B lists claims -> sees 0 claims (Company A's claim invisible)
    list_res = client.get("/api/v1/payroll/reimbursements", headers=company_b.hr_headers)
    assert list_res.status_code == 200
    b_claims = list_res.json()["items"]
    assert not any(c["id"] == claim_id for c in b_claims)
