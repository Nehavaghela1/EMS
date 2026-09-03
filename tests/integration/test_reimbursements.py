import uuid
from datetime import date
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.tax_slabs import seed_tax_slabs
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import User, UserRole
from app.modules.payroll.models import ReimbursementStatus
from tests.conftest import TenantContext


@pytest.fixture(autouse=True)
def _seed_statutory(db: Session):
    seed_pt_slabs(db)
    seed_tax_slabs(db)


def _create_employee_with_user(
    db: Session, company_id: uuid.UUID, role: UserRole = UserRole.employee
) -> tuple[Employee, dict[str, str]]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.test",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
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
        sub=str(user.id), company_id=str(company_id), role=role.value
    )
    return employee, {"Authorization": f"Bearer {token}"}


def _setup_salary_structure(client: TestClient, company: TenantContext) -> str:
    res = client.post(
        "/api/v1/payroll/structures",
        json={
            "name": "Standard Reimbursement Test Structure",
            "components": [
                {
                    "code": "BASIC",
                    "name": "Basic Pay",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "value": "50.00",
                    "percentage_of": "ctc",
                    "display_order": 1,
                },
                {
                    "code": "SPECIAL",
                    "name": "Special Allowance",
                    "type": "earning",
                    "calculation_type": "balance",
                    "display_order": 2,
                },
            ],
        },
        headers=company.hr_headers,
    )
    assert res.status_code == 201
    return res.json()["id"]


def test_submit_and_review_reimbursement(
    client: TestClient, company_a: TenantContext, db: Session
):
    emp, emp_headers = _create_employee_with_user(db, company_a.company_id)

    # 1. Employee submits a reimbursement claim
    submit_res = client.post(
        "/api/v1/payroll/reimbursements",
        json={
            "type": "travel",
            "amount": "1500.00",
            "expense_date": "2026-05-10",
            "description": "Flight ticket for client meeting",
        },
        headers=emp_headers,
    )
    assert submit_res.status_code == 201
    claim = submit_res.json()
    assert claim["status"] == "pending"
    assert claim["amount"] == "1500.00"
    claim_id = claim["id"]

    # 2. Employee views own claims
    list_res = client.get("/api/v1/payroll/reimbursements", headers=emp_headers)
    assert list_res.status_code == 200
    claims = list_res.json()["items"]
    assert any(c["id"] == claim_id for c in claims)

    # 3. HR approves claim
    review_res = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        json={"action": "approve"},
        headers=company_a.hr_headers,
    )
    assert review_res.status_code == 200
    assert review_res.json()["status"] == "approved"


def test_approved_reimbursement_payroll_integration_gate(
    client: TestClient, company_a: TenantContext, db: Session
):
    structure_id = _setup_salary_structure(client, company_a)
    emp, emp_headers = _create_employee_with_user(db, company_a.company_id)

    # Assign salary to employee (CTC 600,000 / yr = 50,000 / mo)
    assign_res = client.post(
        f"/api/v1/payroll/employees/{emp.id}/assign",
        json={"structure_id": structure_id, "ctc": "600000.00", "effective_from": "2026-01-01"},
        headers=company_a.hr_headers,
    )
    assert assign_res.status_code == 201

    # 1. Submit and Approve a reimbursement of 2,500.00
    claim_res = client.post(
        "/api/v1/payroll/reimbursements",
        json={
            "type": "medical",
            "amount": "2500.00",
            "expense_date": "2026-05-12",
            "description": "Health checkup claim",
        },
        headers=emp_headers,
    )
    assert claim_res.status_code == 201
    claim_id = claim_res.json()["id"]

    client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        json={"action": "approve"},
        headers=company_a.hr_headers,
    )

    # 2. Also submit a rejected claim
    rej_res = client.post(
        "/api/v1/payroll/reimbursements",
        json={
            "type": "food",
            "amount": "800.00",
            "expense_date": "2026-05-14",
            "description": "Lunch claim",
        },
        headers=emp_headers,
    )
    client.put(
        f"/api/v1/payroll/reimbursements/{rej_res.json()['id']}",
        json={"action": "reject", "rejection_reason": "Not policy compliant"},
        headers=company_a.hr_headers,
    )

    # 3. Create payroll run
    idempotency_key = f"reimb-run-{uuid.uuid4()}"
    run_res = client.post(
        "/api/v1/payroll/runs",
        json={"month": 5, "year": 2026, "run_type": "regular"},
        headers={**company_a.hr_headers, "Idempotency-Key": idempotency_key},
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["id"]

    # Approve payroll run
    client.post(f"/api/v1/payroll/runs/{run_id}/approve", headers=company_a.hr_headers)

    # 4. GATE ASSERTION: Fetch run details and check payslip item
    detail_res = client.get(f"/api/v1/payroll/runs/{run_id}", headers=company_a.hr_headers)
    items = detail_res.json()["items"]
    emp_item = next(i for i in items if i["employee_id"] == str(emp.id))

    # Base gross = 48,200. Deductions = 2,000. Net before reimb = 46,200.
    # Approved reimbursement of 2,500 must add to net_salary -> 48,700.00
    assert emp_item["reimbursement_amount"] == "2500.00"
    assert emp_item["net_salary"] == "48700.00"

    # Verify reimbursement status transitioned to 'paid'
    claim_check = client.get("/api/v1/payroll/reimbursements", headers=company_a.hr_headers)
    claims = claim_check.json()["items"]
    paid_claim = next(c for c in claims if c["id"] == claim_id)
    assert paid_claim["status"] == "paid"
    assert paid_claim["added_to_payroll_run_id"] == run_id


def test_payslips_me_and_employee_endpoints(
    client: TestClient, company_a: TenantContext, db: Session
):
    emp, emp_headers = _create_employee_with_user(db, company_a.company_id)

    # GET /payroll/payslips/me for employee
    res_me = client.get("/api/v1/payroll/payslips/me", headers=emp_headers)
    assert res_me.status_code == 200
    assert isinstance(res_me.json(), list)

    # GET /payroll/payslips/{employee_id} for HR admin
    res_emp = client.get(
        f"/api/v1/payroll/payslips/{emp.id}",
        headers=company_a.hr_headers,
    )
    assert res_emp.status_code == 200
    assert isinstance(res_emp.json(), list)
