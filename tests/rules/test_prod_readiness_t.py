"""Tests for PART T — The two dashboard findings.

Rules:
T1. frontend/src/modules/platform/pages/DashboardPage.tsx line ~1890: "Manage →" on the Department
    Headcount card links to /departments (was /employees).
T2. frontend/src/modules/hr/pages/EmployeeListPage.tsx line ~484: An employee with no department is
    shown as "Unassigned" and never the company name.
    Also, the dashboard's department_distribution accounts for employees with no department as
    "Unassigned", so the headcount card accounts for every active employee.
T3. Tests: an employee with no department renders "Unassigned" and never the company name;
    the headcount card accounts for every active employee.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Department, Employee, EmploymentType
from tests.conftest import TenantContext


def test_t2_t3_department_distribution_accounts_for_unassigned_employees(
    client: TestClient,
    db: Session,
    company_a: TenantContext,
):
    now = utcnow()
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)

    # Create a department
    dept = Department(
        company_id=company_a.company_id,
        name=f"Engineering-{now.microsecond}",
    )
    db.add(dept)
    db.flush()

    # Employee 1 assigned to department
    emp_assigned = Employee(
        company_id=company_a.company_id,
        department_id=dept.id,
        first_name="Assigned",
        last_name="Worker",
        employee_code=f"ASN-{now.microsecond}",
        email=f"assigned-{now.microsecond}@example.com",
        hire_date=now.date(),
        is_active=True,
        employment_type=EmploymentType.full_time,
    )

    # Employee 2 unassigned (department_id is None)
    emp_unassigned = Employee(
        company_id=company_a.company_id,
        department_id=None,
        first_name="Unassigned",
        last_name="Worker",
        employee_code=f"UNA-{now.microsecond}",
        email=f"unassigned-{now.microsecond}@example.com",
        hire_date=now.date(),
        is_active=True,
        employment_type=EmploymentType.full_time,
    )

    db.add_all([emp_assigned, emp_unassigned])
    db.commit()

    # Fetch HR dashboard
    resp = client.get("/api/v1/dashboard", headers=company_a.hr_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    dist = data["department_distribution"]
    assert dept.name in dist
    assert dist[dept.name] >= 1
    assert "Unassigned" in dist
    assert dist["Unassigned"] >= 1

    # Total in distribution matches total active headcount
    total_distributed = sum(dist.values())
    assert total_distributed == data["headcount"]
