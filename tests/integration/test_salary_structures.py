import uuid
from datetime import date, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from tests.conftest import TenantContext


def test_create_salary_structure(client: TestClient, company_a: TenantContext):
    payload = {
        "name": "Standard Software Engineer Band",
        "country": "IN",
        "level": "L3",
        "components": [
            {
                "name": "Basic Pay",
                "code": "BASIC",
                "type": "earning",
                "calculation_type": "percentage",
                "value": "50.00",
                "percentage_of": "ctc",
                "is_taxable": True,
                "is_statutory": False,
                "display_order": 1,
            },
            {
                "name": "House Rent Allowance",
                "code": "HRA",
                "type": "earning",
                "calculation_type": "percentage",
                "value": "40.00",
                "percentage_of": "basic",
                "is_taxable": True,
                "is_statutory": False,
                "display_order": 2,
            },
            {
                "name": "Special Allowance",
                "code": "SPECIAL",
                "type": "earning",
                "calculation_type": "balance",
                "value": None,
                "percentage_of": None,
                "is_taxable": True,
                "is_statutory": False,
                "display_order": 3,
            },
        ],
    }

    res = client.post("/api/v1/payroll/structures", json=payload, headers=company_a.hr_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Standard Software Engineer Band"
    assert data["level"] == "L3"
    assert len(data["components"]) == 3
    assert data["components"][0]["code"] == "BASIC"


def test_create_salary_structure_validations(client: TestClient, company_a: TenantContext):
    # 1. Duplicate component codes
    res = client.post(
        "/api/v1/payroll/structures",
        json={
            "name": "Invalid Struct Dup",
            "components": [
                {
                    "name": "Basic",
                    "code": "BASIC",
                    "type": "earning",
                    "calculation_type": "fixed",
                    "value": "10000",
                },
                {
                    "name": "Basic Duplicate",
                    "code": "BASIC",
                    "type": "earning",
                    "calculation_type": "fixed",
                    "value": "5000",
                },
            ],
        },
        headers=company_a.hr_headers,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_structure"

    # 2. More than 1 balance component
    res = client.post(
        "/api/v1/payroll/structures",
        json={
            "name": "Invalid Struct Multi Balance",
            "components": [
                {
                    "name": "Bal 1",
                    "code": "BAL1",
                    "type": "earning",
                    "calculation_type": "balance",
                },
                {
                    "name": "Bal 2",
                    "code": "BAL2",
                    "type": "earning",
                    "calculation_type": "balance",
                },
            ],
        },
        headers=company_a.hr_headers,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_structure"

    # 3. Percentage of CTC > 100%
    res = client.post(
        "/api/v1/payroll/structures",
        json={
            "name": "Invalid Struct > 100%",
            "components": [
                {
                    "name": "Basic",
                    "code": "BASIC",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "value": "110.00",
                    "percentage_of": "ctc",
                }
            ],
        },
        headers=company_a.hr_headers,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_structure"


def test_non_hr_cannot_create_salary_structure(client: TestClient, company_a: TenantContext):
    res = client.post(
        "/api/v1/payroll/structures",
        json={"name": "Attempt By Employee", "components": []},
        headers=company_a.employee_headers,
    )
    assert res.status_code == 403


def test_list_and_get_salary_structures(client: TestClient, company_a: TenantContext):
    # Create two structures
    client.post(
        "/api/v1/payroll/structures",
        json={"name": "Band A", "components": []},
        headers=company_a.hr_headers,
    )
    client.post(
        "/api/v1/payroll/structures",
        json={"name": "Band B", "components": []},
        headers=company_a.hr_headers,
    )

    res = client.get("/api/v1/payroll/structures?page=1&limit=10", headers=company_a.hr_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 2
    items = data["items"]
    names = [i["name"] for i in items]
    assert "Band A" in names
    assert "Band B" in names

    struct_id = items[0]["id"]
    detail_res = client.get(
        f"/api/v1/payroll/structures/{struct_id}", headers=company_a.hr_headers
    )
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == struct_id


def test_update_salary_structure(client: TestClient, company_a: TenantContext):
    create_res = client.post(
        "/api/v1/payroll/structures",
        json={"name": "Original Name", "components": []},
        headers=company_a.hr_headers,
    )
    struct_id = create_res.json()["id"]

    update_res = client.put(
        f"/api/v1/payroll/structures/{struct_id}",
        json={
            "name": "Updated Name",
            "level": "L4",
            "components": [
                {
                    "name": "Basic",
                    "code": "BASIC",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "value": "60.00",
                    "percentage_of": "ctc",
                }
            ],
        },
        headers=company_a.hr_headers,
    )
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["name"] == "Updated Name"
    assert data["level"] == "L4"
    assert len(data["components"]) == 1
    assert data["components"][0]["code"] == "BASIC"


def test_assign_and_get_employee_salary(
    client: TestClient, company_a: TenantContext, db: Session
):
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    # Create employee record in company_a
    employee = Employee(
        company_id=company_a.company_id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Test",
        last_name="SalaryEmp",
        email=f"salary-{uuid.uuid4().hex[:6]}@example.test",
        employment_type=EmploymentType.full_time,
        hire_date=date.today(),
        is_active=True,
        invitation_status=InvitationStatus.activated,
    )
    db.add(employee)
    db.commit()

    # Create structure
    struct_res = client.post(
        "/api/v1/payroll/structures",
        json={
            "name": "Engineer Grade",
            "components": [
                {
                    "name": "Basic",
                    "code": "BASIC",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "value": "50.00",
                    "percentage_of": "ctc",
                    "display_order": 1,
                },
                {
                    "name": "HRA",
                    "code": "HRA",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "value": "40.00",
                    "percentage_of": "basic",
                    "display_order": 2,
                },
                {
                    "name": "Special Allowance",
                    "code": "SPECIAL",
                    "type": "earning",
                    "calculation_type": "balance",
                    "display_order": 3,
                },
            ],
        },
        headers=company_a.hr_headers,
    )
    struct_id = struct_res.json()["id"]

    # Assign salary
    assign_res = client.post(
        f"/api/v1/payroll/employees/{employee.id}/assign",
        json={
            "structure_id": struct_id,
            "ctc": "1200000.00",  # 12 LPA -> 1,00,000 per month
            "effective_from": date.today().isoformat(),
            "revision_reason": "Joining bonus & offer",
        },
        headers=company_a.hr_headers,
    )
    assert assign_res.status_code == 201
    assign_data = assign_res.json()
    assert assign_data["ctc"] == "1200000.00"
    assert len(assign_data["earnings"]) == 3

    # Verify earnings calculation:
    # CTC = 1,200,000
    # BASIC = 50% of 1,200,000 = 600,000
    # HRA = 40% of BASIC (600,000) = 240,000
    # SPECIAL = Balance = 1,200,000 - (600,000 + 240,000) = 360,000
    # Gross Earnings = 1,200,000
    assert assign_data["gross_earnings"] == "1200000.00"
    basic_earning = next(e for e in assign_data["earnings"] if e["code"] == "BASIC")
    hra_earning = next(e for e in assign_data["earnings"] if e["code"] == "HRA")
    special_earning = next(e for e in assign_data["earnings"] if e["code"] == "SPECIAL")
    assert basic_earning["amount"] == "600000.00"
    assert hra_earning["amount"] == "240000.00"
    assert special_earning["amount"] == "360000.00"

    # HR views employee salary
    hr_salary_res = client.get(
        f"/api/v1/payroll/employees/{employee.id}/salary", headers=company_a.hr_headers
    )
    assert hr_salary_res.status_code == 200
    assert hr_salary_res.json()["ctc"] == "1200000.00"

    # Test assigned structure soft-delete prevention (409)
    delete_res = client.delete(
        f"/api/v1/payroll/structures/{struct_id}", headers=company_a.hr_headers
    )
    assert delete_res.status_code == 409
    assert delete_res.json()["error"]["code"] == "conflict"


def test_assign_salary_overlap_error(
    client: TestClient, company_a: TenantContext, db: Session
):
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    employee = Employee(
        company_id=company_a.company_id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Overlap",
        last_name="Emp",
        email=f"overlap-{uuid.uuid4().hex[:6]}@example.test",
        employment_type=EmploymentType.full_time,
        hire_date=date.today(),
        is_active=True,
        invitation_status=InvitationStatus.activated,
    )
    db.add(employee)
    db.commit()

    struct_res = client.post(
        "/api/v1/payroll/structures",
        json={
            "name": "Overlap Test Struct",
            "components": [
                {
                    "name": "Special Allowance",
                    "code": "SPECIAL",
                    "type": "earning",
                    "calculation_type": "balance",
                }
            ],
        },
        headers=company_a.hr_headers,
    )
    struct_id = struct_res.json()["id"]

    today = date.today()
    # First assignment starting today
    client.post(
        f"/api/v1/payroll/employees/{employee.id}/assign",
        json={
            "structure_id": struct_id,
            "ctc": "600000.00",
            "effective_from": today.isoformat(),
        },
        headers=company_a.hr_headers,
    )

    # Attempt second assignment starting in the past or on same date
    res = client.post(
        f"/api/v1/payroll/employees/{employee.id}/assign",
        json={
            "structure_id": struct_id,
            "ctc": "700000.00",
            "effective_from": (today - timedelta(days=5)).isoformat(),
        },
        headers=company_a.hr_headers,
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "salary_overlap"
