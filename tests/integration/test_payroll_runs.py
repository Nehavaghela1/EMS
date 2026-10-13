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
from app.modules.payroll.models import (
    PayrollRun,
    PayrollRunStatus,
    PayrollRunType,
)
from app.modules.payroll.repository import PayrollItemRepository
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
    emp = _create_employee(
        db, company_a.company_id, email=f"idempotent-{uuid.uuid4().hex[:6]}@comp-a.com"
    )
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


def test_payroll_run_calculation_end_to_end(
    client: TestClient, company_a: TenantContext, db: Session
):
    structure_id = _setup_salary_structure(client, company_a)

    # Employee 1: Below ESI ceiling (CTC 216,000 / yr = 18,000 / mo)
    emp1 = _create_employee(
        db, company_a.company_id, email=f"emp1-{uuid.uuid4().hex[:6]}@comp-a.com"
    )
    client.post(
        f"/api/v1/payroll/employees/{emp1.id}/assign",
        json={"structure_id": structure_id, "ctc": "216000.00", "effective_from": "2026-01-01"},
        headers=company_a.hr_headers,
    )

    # Employee 2: Above ESI ceiling (CTC 600,000 / yr = 50,000 / mo)
    emp2 = _create_employee(
        db, company_a.company_id, email=f"emp2-{uuid.uuid4().hex[:6]}@comp-a.com"
    )
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


def test_payroll_run_approval_workflow_gate(
    client: TestClient, company_a: TenantContext, db: Session
):
    structure_id = _setup_salary_structure(client, company_a)
    emp = _create_employee(
        db, company_a.company_id, email=f"approval-{uuid.uuid4().hex[:6]}@comp-a.com"
    )
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
    emp_res_before = client.get(
        f"/api/v1/payroll/runs/{run_id}", headers=company_a.employee_headers
    )
    assert emp_res_before.status_code == 403

    # 3. HR approves the run
    approve_res = client.post(
        f"/api/v1/payroll/runs/{run_id}/approve", headers=company_a.hr_headers
    )
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


def test_delete_draft_payroll_run(client: TestClient, db: Session, company_a: TenantContext):
    emp = _create_employee(
        db, company_a.company_id, f"draft-del-{uuid.uuid4().hex[:6]}@example.com"
    )
    struct_id = _setup_salary_structure(client, company_a)
    assign_res = client.post(
        f"/api/v1/payroll/employees/{emp.id}/assign",
        json={"structure_id": struct_id, "ctc": "600000.00", "effective_from": "2026-01-01"},
        headers=company_a.hr_headers,
    )
    assert assign_res.status_code == 201

    # Create run for Month 8 / Year 2026
    run_res = client.post(
        "/api/v1/payroll/runs",
        json={"month": 8, "year": 2026, "run_type": "regular"},
        headers={**company_a.hr_headers, "Idempotency-Key": f"draft-del-{uuid.uuid4()}"},
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["id"]

    # Verify run exists and has EPF / PT deductions calculated
    detail_res = client.get(f"/api/v1/payroll/runs/{run_id}", headers=company_a.hr_headers)
    assert detail_res.status_code == 200
    items = detail_res.json()["items"]
    assert len(items) == 1
    deductions = items[0]["deductions_json"]
    deduction_codes = [d["code"] for d in deductions]
    assert "EPF_EE" in deduction_codes
    assert "PT" in deduction_codes

    # Delete draft run -> 204 No Content
    del_res = client.delete(f"/api/v1/payroll/runs/{run_id}", headers=company_a.hr_headers)
    assert del_res.status_code == 204

    # Run should now be deleted -> 404
    get_res = client.get(f"/api/v1/payroll/runs/{run_id}", headers=company_a.hr_headers)
    assert get_res.status_code == 404


def test_cannot_delete_approved_payroll_run(
    client: TestClient, db: Session, company_a: TenantContext
):
    emp = _create_employee(db, company_a.company_id, f"appr-del-{uuid.uuid4().hex[:6]}@example.com")
    struct_id = _setup_salary_structure(client, company_a)
    assign_res = client.post(
        f"/api/v1/payroll/employees/{emp.id}/assign",
        json={"structure_id": struct_id, "ctc": "600000.00", "effective_from": "2026-01-01"},
        headers=company_a.hr_headers,
    )
    assert assign_res.status_code == 201

    # Create run for Month 9 / Year 2026
    run_res = client.post(
        "/api/v1/payroll/runs",
        json={"month": 9, "year": 2026, "run_type": "regular"},
        headers={**company_a.hr_headers, "Idempotency-Key": f"appr-del-{uuid.uuid4()}"},
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["id"]

    # Approve run
    approve_res = client.post(
        f"/api/v1/payroll/runs/{run_id}/approve", headers=company_a.hr_headers
    )
    assert approve_res.status_code == 200

    # Attempt delete on approved run -> 409 Conflict
    del_res = client.delete(f"/api/v1/payroll/runs/{run_id}", headers=company_a.hr_headers)
    assert del_res.status_code == 409


def test_repository_get_ytd_gross_for_employee(db: Session, company_a: TenantContext):
    """Integration test for PayrollItemRepository.get_ytd_gross_for_employee.
    Tests:
    - creates items in approved, paid, and draft runs
    - includes an approved run in a different financial year (e.g. FY 2025-2026)
    - excludes the specified current run (rebuild exclusion)
    - asserts only approved and paid runs within the target FY are summed
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    email = f"ytd-gross-{uuid.uuid4().hex[:6]}@example.com"
    emp = _create_employee(db, company_a.company_id, email)
    item_repo = PayrollItemRepository(db)

    token = company_a.hr_headers["Authorization"].split(" ")[1]
    from app.core.security import decode_access_token

    actor_id = uuid.UUID(decode_access_token(token)["sub"])

    # 1. Approved run in target FY 2026-2027 (Month 4 / 2026) -> included: 50,000.00
    run_approved = PayrollRun(
        company_id=company_a.company_id,
        month=4,
        year=2026,
        status=PayrollRunStatus.approved,
        run_type=PayrollRunType.regular,
        idempotency_key=f"ytd-g-appr-{uuid.uuid4()}",
        run_by=actor_id,
    )
    db.add(run_approved)
    db.flush()
    item_repo.create(
        company_id=company_a.company_id,
        payroll_run_id=run_approved.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("600000.00"),
        gross_salary=Decimal("50000.00"),
        total_deductions=Decimal("5000.00"),
        net_salary=Decimal("45000.00"),
        employer_cost=Decimal("55000.00"),
        earnings_json=[],
        deductions_json=[],
        employer_contributions_json=[],
        working_days=Decimal("30"),
        present_days=Decimal("30"),
    )

    # 2. Paid run in target FY 2026-2027 (Month 5 / 2026) -> included: 55,000.00
    run_paid = PayrollRun(
        company_id=company_a.company_id,
        month=5,
        year=2026,
        status=PayrollRunStatus.paid,
        run_type=PayrollRunType.regular,
        idempotency_key=f"ytd-g-paid-{uuid.uuid4()}",
        run_by=actor_id,
    )
    db.add(run_paid)
    db.flush()
    item_repo.create(
        company_id=company_a.company_id,
        payroll_run_id=run_paid.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("600000.00"),
        gross_salary=Decimal("55000.00"),
        total_deductions=Decimal("5000.00"),
        net_salary=Decimal("50000.00"),
        employer_cost=Decimal("60000.00"),
        earnings_json=[],
        deductions_json=[],
        employer_contributions_json=[],
        working_days=Decimal("31"),
        present_days=Decimal("31"),
    )

    # 3. Draft run in target FY 2026-2027 (Month 6 / 2026) -> EXCLUDED: 60,000.00
    run_draft = PayrollRun(
        company_id=company_a.company_id,
        month=6,
        year=2026,
        status=PayrollRunStatus.draft,
        run_type=PayrollRunType.regular,
        idempotency_key=f"ytd-g-draft-{uuid.uuid4()}",
        run_by=actor_id,
    )
    db.add(run_draft)
    db.flush()
    item_repo.create(
        company_id=company_a.company_id,
        payroll_run_id=run_draft.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("600000.00"),
        gross_salary=Decimal("60000.00"),
        total_deductions=Decimal("5000.00"),
        net_salary=Decimal("55000.00"),
        employer_cost=Decimal("65000.00"),
        earnings_json=[],
        deductions_json=[],
        employer_contributions_json=[],
        working_days=Decimal("30"),
        present_days=Decimal("30"),
    )

    # 4. Approved run in DIFFERENT FY (Month 3 / 2026 = FY 2025-2026) -> EXCLUDED: 40,000.00
    run_prior_fy = PayrollRun(
        company_id=company_a.company_id,
        month=3,
        year=2026,
        status=PayrollRunStatus.approved,
        run_type=PayrollRunType.regular,
        idempotency_key=f"ytd-g-prior-{uuid.uuid4()}",
        run_by=actor_id,
    )
    db.add(run_prior_fy)
    db.flush()
    item_repo.create(
        company_id=company_a.company_id,
        payroll_run_id=run_prior_fy.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("600000.00"),
        gross_salary=Decimal("40000.00"),
        total_deductions=Decimal("4000.00"),
        net_salary=Decimal("36000.00"),
        employer_cost=Decimal("44000.00"),
        earnings_json=[],
        deductions_json=[],
        employer_contributions_json=[],
        working_days=Decimal("31"),
        present_days=Decimal("31"),
    )

    # 5. Approved run in target FY that is the current run (exclude_run_id) -> EXCLUDED
    run_current = PayrollRun(
        company_id=company_a.company_id,
        month=7,
        year=2026,
        status=PayrollRunStatus.approved,
        run_type=PayrollRunType.regular,
        idempotency_key=f"ytd-g-curr-{uuid.uuid4()}",
        run_by=actor_id,
    )
    db.add(run_current)
    db.flush()
    item_repo.create(
        company_id=company_a.company_id,
        payroll_run_id=run_current.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("600000.00"),
        gross_salary=Decimal("70000.00"),
        total_deductions=Decimal("7000.00"),
        net_salary=Decimal("63000.00"),
        employer_cost=Decimal("77000.00"),
        earnings_json=[],
        deductions_json=[],
        employer_contributions_json=[],
        working_days=Decimal("31"),
        present_days=Decimal("31"),
    )
    db.commit()

    # Query FY 2026-2027 (start_year=2026) excluding run_current:
    # Included: run_approved (50,000.00) + run_paid (55,000.00) = 105,000.00
    ytd_gross = item_repo.get_ytd_gross_for_employee(
        company_id=company_a.company_id,
        employee_id=emp.id,
        start_year=2026,
        exclude_run_id=run_current.id,
    )
    assert ytd_gross == Decimal("105000.00")


def test_repository_get_ytd_tds_for_employee(db: Session, company_a: TenantContext):
    """Integration test for PayrollItemRepository.get_ytd_tds_for_employee.
    Tests:
    - creates items with TDS in deductions_json in approved, paid, and draft runs
    - includes an approved run in a different financial year
    - excludes the specified current run (rebuild exclusion)
    - asserts only approved and paid runs within target FY are summed
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    emp = _create_employee(db, company_a.company_id, f"ytd-tds-{uuid.uuid4().hex[:6]}@example.com")
    item_repo = PayrollItemRepository(db)

    token = company_a.hr_headers["Authorization"].split(" ")[1]
    from app.core.security import decode_access_token

    actor_id = uuid.UUID(decode_access_token(token)["sub"])

    # 1. Approved run in FY 2026-2027 (Month 4) -> TDS: 2,500.00

    run_approved = PayrollRun(
        company_id=company_a.company_id,
        month=4,
        year=2026,
        status=PayrollRunStatus.approved,
        run_type=PayrollRunType.regular,
        idempotency_key=f"ytd-t-appr-{uuid.uuid4()}",
        run_by=actor_id,
    )
    db.add(run_approved)
    db.flush()
    item_repo.create(
        company_id=company_a.company_id,
        payroll_run_id=run_approved.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("600000.00"),
        gross_salary=Decimal("50000.00"),
        total_deductions=Decimal("2500.00"),
        net_salary=Decimal("47500.00"),
        employer_cost=Decimal("55000.00"),
        earnings_json=[],
        deductions_json=[{"code": "TDS", "name": "Income Tax (Estimated)", "amount": "2500.00"}],
        employer_contributions_json=[],
        working_days=Decimal("30"),
        present_days=Decimal("30"),
    )

    # 2. Paid run in FY 2026-2027 (Month 5) -> TDS: 3,000.00
    run_paid = PayrollRun(
        company_id=company_a.company_id,
        month=5,
        year=2026,
        status=PayrollRunStatus.paid,
        run_type=PayrollRunType.regular,
        idempotency_key=f"ytd-t-paid-{uuid.uuid4()}",
        run_by=actor_id,
    )
    db.add(run_paid)
    db.flush()
    item_repo.create(
        company_id=company_a.company_id,
        payroll_run_id=run_paid.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("600000.00"),
        gross_salary=Decimal("50000.00"),
        total_deductions=Decimal("3000.00"),
        net_salary=Decimal("47000.00"),
        employer_cost=Decimal("55000.00"),
        earnings_json=[],
        deductions_json=[{"code": "TDS", "name": "Income Tax (Estimated)", "amount": "3000.00"}],
        employer_contributions_json=[],
        working_days=Decimal("31"),
        present_days=Decimal("31"),
    )

    # 3. Draft run in FY 2026-2027 (Month 6) -> EXCLUDED (draft status): 4,000.00
    run_draft = PayrollRun(
        company_id=company_a.company_id,
        month=6,
        year=2026,
        status=PayrollRunStatus.draft,
        run_type=PayrollRunType.regular,
        idempotency_key=f"ytd-t-draft-{uuid.uuid4()}",
        run_by=actor_id,
    )
    db.add(run_draft)
    db.flush()
    item_repo.create(
        company_id=company_a.company_id,
        payroll_run_id=run_draft.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("600000.00"),
        gross_salary=Decimal("50000.00"),
        total_deductions=Decimal("4000.00"),
        net_salary=Decimal("46000.00"),
        employer_cost=Decimal("55000.00"),
        earnings_json=[],
        deductions_json=[{"code": "TDS", "name": "Income Tax (Estimated)", "amount": "4000.00"}],
        employer_contributions_json=[],
        working_days=Decimal("30"),
        present_days=Decimal("30"),
    )

    # 4. Approved run in DIFFERENT FY (Month 3 / 2026 = FY 2025-2026) -> EXCLUDED: 1,500.00
    run_prior = PayrollRun(
        company_id=company_a.company_id,
        month=3,
        year=2026,
        status=PayrollRunStatus.approved,
        run_type=PayrollRunType.regular,
        idempotency_key=f"ytd-t-prior-{uuid.uuid4()}",
        run_by=actor_id,
    )
    db.add(run_prior)
    db.flush()
    item_repo.create(
        company_id=company_a.company_id,
        payroll_run_id=run_prior.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("600000.00"),
        gross_salary=Decimal("50000.00"),
        total_deductions=Decimal("1500.00"),
        net_salary=Decimal("48500.00"),
        employer_cost=Decimal("55000.00"),
        earnings_json=[],
        deductions_json=[{"code": "TDS", "name": "Income Tax (Estimated)", "amount": "1500.00"}],
        employer_contributions_json=[],
        working_days=Decimal("31"),
        present_days=Decimal("31"),
    )

    # 5. Current run in target FY (exclude_run_id) -> EXCLUDED
    run_current = PayrollRun(
        company_id=company_a.company_id,
        month=7,
        year=2026,
        status=PayrollRunStatus.approved,
        run_type=PayrollRunType.regular,
        idempotency_key=f"ytd-t-curr-{uuid.uuid4()}",
        run_by=actor_id,
    )
    db.add(run_current)
    db.flush()
    item_repo.create(
        company_id=company_a.company_id,
        payroll_run_id=run_current.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("600000.00"),
        gross_salary=Decimal("50000.00"),
        total_deductions=Decimal("5000.00"),
        net_salary=Decimal("45000.00"),
        employer_cost=Decimal("55000.00"),
        earnings_json=[],
        deductions_json=[{"code": "TDS", "name": "Income Tax (Estimated)", "amount": "5000.00"}],
        employer_contributions_json=[],
        working_days=Decimal("31"),
        present_days=Decimal("31"),
    )
    db.commit()

    # Query FY 2026-2027 (start_year=2026) excluding run_current:
    # Included: run_approved (2500.00) + run_paid (3000.00) = 5500.00
    ytd_tds = item_repo.get_ytd_tds_for_employee(
        company_id=company_a.company_id,
        employee_id=emp.id,
        start_year=2026,
        exclude_run_id=run_current.id,
    )
    assert ytd_tds == Decimal("5500.00")
