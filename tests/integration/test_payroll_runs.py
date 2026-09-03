import uuid
from datetime import date
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.rls import bind_tenant_to_session
from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.tax_slabs import seed_tax_slabs
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.payroll.models import PayrollRun, PayrollRunStatus
from tests.conftest import TenantContext


@pytest.fixture(autouse=True)
def _seed_statutory(db: Session):
    seed_pt_slabs(db)
    seed_tax_slabs(db)


def _create_employee(db: Session, company_id: uuid.UUID, email: str) -> Employee:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    employee = Employee(
        company_id=company_id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Test",
        last_name="PayrollEmp",
        email=email,
        employment_type=EmploymentType.full_time,
        hire_date=date.today(),
        is_active=True,
        invitation_status=InvitationStatus.activated,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _setup_salary_structure(client: TestClient, company: TenantContext) -> str:
    res = client.post(
        "/api/v1/payroll/structures",
        json={
            "name": "Standard Regular Structure",
            "description": "Base salary structure",
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
                    "code": "HRA",
                    "name": "House Rent Allowance",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "value": "40.00",
                    "percentage_of": "basic",
                    "display_order": 2,
                },
                {
                    "code": "SPECIAL",
                    "name": "Special Allowance",
                    "type": "earning",
                    "calculation_type": "balance",
                    "display_order": 3,
                },
            ],
        },
        headers=company.hr_headers,
    )
    assert res.status_code == 201
    return res.json()["id"]


def test_payroll_run_idempotency_gate(client: TestClient, company_a: TenantContext, db: Session):
    structure_id = _setup_salary_structure(client, company_a)

    # Create employee and assign salary
    emp = _create_employee(db, company_a.company_id, email=f"idempotent-{uuid.uuid4().hex[:6]}@comp-a.com")
    assign_res = client.post(
        f"/api/v1/payroll/employees/{emp.id}/assign",
        json={
            "structure_id": structure_id,
            "ctc": "600000.00",
            "effective_from": "2026-01-01",
        },
        headers=company_a.hr_headers,
    )
    assert assign_res.status_code == 201

    idempotency_key = f"idem-key-{uuid.uuid4()}"
    headers = {**company_a.hr_headers, "Idempotency-Key": idempotency_key}

    run_payload = {
        "month": 4,
        "year": 2026,
        "run_type": "regular",
    }

    # 1. First POST request
    res1 = client.post("/api/v1/payroll/runs", json=run_payload, headers=headers)
    assert res1.status_code == 202
    run1 = res1.json()

    # 2. Second POST request with identical Idempotency-Key
    res2 = client.post("/api/v1/payroll/runs", json=run_payload, headers=headers)
    assert res2.status_code == 202
    run2 = res2.json()

    # GATE ASSERTION: Exactly same run returned
    assert run1["id"] == run2["id"]

    # Database assertion: exactly 1 run exists for this idempotency key
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    db_runs = db.query(PayrollRun).filter(PayrollRun.idempotency_key == idempotency_key).all()
    assert len(db_runs) == 1


def test_payroll_run_calculation_end_to_end(client: TestClient, company_a: TenantContext, db: Session):
    structure_id = _setup_salary_structure(client, company_a)

    # Employee 1: Below ESI ceiling (CTC 216,000 / yr = 18,000 / mo)
    emp1 = _create_employee(db, company_a.company_id, email=f"emp1-{uuid.uuid4().hex[:6]}@comp-a.com")
    client.post(
        f"/api/v1/payroll/employees/{emp1.id}/assign",
        json={"structure_id": structure_id, "ctc": "216000.00", "effective_from": "2026-01-01"},
        headers=company_a.hr_headers,
    )

    # Employee 2: Above ESI ceiling (CTC 600,000 / yr = 50,000 / mo)
    emp2 = _create_employee(db, company_a.company_id, email=f"emp2-{uuid.uuid4().hex[:6]}@comp-a.com")
    client.post(
        f"/api/v1/payroll/employees/{emp2.id}/assign",
        json={"structure_id": structure_id, "ctc": "600000.00", "effective_from": "2026-01-01"},
        headers=company_a.hr_headers,
    )

    idempotency_key = f"run-e2e-{uuid.uuid4()}"
    headers = {**company_a.hr_headers, "Idempotency-Key": idempotency_key}

    run_res = client.post(
        "/api/v1/payroll/runs",
        json={"month": 5, "year": 2026, "run_type": "regular"},
        headers=headers,
    )
    assert run_res.status_code == 202
    run_data = run_res.json()
    assert run_data["status"] == "pending_approval"
    assert run_data["total_employees"] == 2

    # Fetch run detail
    detail_res = client.get(f"/api/v1/payroll/runs/{run_data['id']}", headers=company_a.hr_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    items = detail["items"]
    assert len(items) == 2

    # Find item for Employee 1 (below ESI ceiling)
    item1 = next(i for i in items if i["employee_id"] == str(emp1.id))
    assert item1["gross_salary"] == "16920.00"
    assert item1["total_deductions"] == "1406.90"
    assert item1["net_salary"] == "15513.10"

    # Find item for Employee 2 (above ESI ceiling)
    item2 = next(i for i in items if i["employee_id"] == str(emp2.id))
    assert item2["gross_salary"] == "48200.00"
    assert item2["total_deductions"] == "2000.00"
    assert item2["net_salary"] == "46200.00"


def test_payroll_run_approval_workflow_gate(client: TestClient, company_a: TenantContext, db: Session):
    structure_id = _setup_salary_structure(client, company_a)
    emp = _create_employee(db, company_a.company_id, email=f"approval-{uuid.uuid4().hex[:6]}@comp-a.com")
    client.post(
        f"/api/v1/payroll/employees/{emp.id}/assign",
        json={"structure_id": structure_id, "ctc": "600000.00", "effective_from": "2026-01-01"},
        headers=company_a.hr_headers,
    )

    # 1. HR creates payroll run
    idempotency_key = f"approval-key-{uuid.uuid4()}"
    run_res = client.post(
        "/api/v1/payroll/runs",
        json={"month": 6, "year": 2026, "run_type": "regular"},
        headers={**company_a.hr_headers, "Idempotency-Key": idempotency_key},
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["id"]

    # 2. GATE ASSERTION: Employee attempts to view payslip BEFORE approval -> 403 Forbidden
    emp_res_before = client.get(f"/api/v1/payroll/runs/{run_id}", headers=company_a.employee_headers)
    assert emp_res_before.status_code == 403

    # 3. HR approves the run
    approve_res = client.post(f"/api/v1/payroll/runs/{run_id}/approve", headers=company_a.hr_headers)
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "approved"

    # 4. HR Admin views full approved run -> 200 OK
    hr_res_after = client.get(f"/api/v1/payroll/runs/{run_id}", headers=company_a.hr_headers)
    assert hr_res_after.status_code == 200
    hr_detail = hr_res_after.json()
    assert len(hr_detail["items"]) == 1
    assert hr_detail["items"][0]["employee_id"] == str(emp.id)


def test_duplicate_regular_run_prevention(client: TestClient, company_a: TenantContext):
    _setup_salary_structure(client, company_a)

    # First regular run for Month 7 / Year 2026
    res1 = client.post(
        "/api/v1/payroll/runs",
        json={"month": 7, "year": 2026, "run_type": "regular"},
        headers={**company_a.hr_headers, "Idempotency-Key": f"reg1-{uuid.uuid4()}"},
    )
    assert res1.status_code == 202

    # Second regular run for SAME Month 7 / Year 2026 with different idempotency key -> 409 Conflict
    res2 = client.post(
        "/api/v1/payroll/runs",
        json={"month": 7, "year": 2026, "run_type": "regular"},
        headers={**company_a.hr_headers, "Idempotency-Key": f"reg2-{uuid.uuid4()}"},
    )
    assert res2.status_code == 409
