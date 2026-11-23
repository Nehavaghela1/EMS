"""Tests for PART S — the super admin dashboard.

Rules:
S1. Three platform stats endpoints exist and nothing renders them. Build the super admin dashboard
    that shows them. Platform role only, via require_platform_role; a company user gets 403.
S2. No company's business data may appear on it — counts and aggregates only, never an employee
    name, salary or payslip.
S3. Tests: a super admin sees the figures; hr_admin, owner, manager and employee each get 403;
    the response carries no employee-level field.
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType
from app.modules.identity.models import User, UserRole
from app.modules.payroll.models import (
    PayrollRun,
    PayrollRunStatus,
    PayrollRunType,
)
from tests.conftest import TenantContext, _make_user_headers

PLATFORM_STATS_ENDPOINTS = [
    "/api/v1/platform/stats/overview",
    "/api/v1/platform/stats/payroll",
    "/api/v1/platform/stats/platform-health",
    "/api/v1/platform/stats/activity",
    "/api/v1/platform/stats/companies",
]


@pytest.fixture
def super_admin_stats_data(db: Session, company_a: TenantContext):
    """Setup active company with payroll and employees to verify aggregates."""
    now = utcnow()
    cur_year = now.year
    cur_month = now.month

    # Setup tenant context
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=True)

    # Create employee with specific names that MUST NOT leak into platform stats
    emp = Employee(
        company_id=company_a.company_id,
        first_name="SuperSecretFirst",
        last_name="SuperSecretLast",
        employee_code=f"SEC-{now.microsecond}",
        email=f"secret-{now.microsecond}@example.com",
        hire_date=now.date(),
        is_active=True,
        employment_type=EmploymentType.full_time,
        created_at=now,
    )
    db.add(emp)
    db.flush()

    # Create a user to be run_by
    user = User(
        company_id=company_a.company_id,
        email=f"hr-{now.microsecond}@example.com",
        hashed_password="pw",
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(user)
    db.flush()

    # Create paid regular payroll run
    run = PayrollRun(
        company_id=company_a.company_id,
        year=cur_year,
        month=cur_month,
        run_type=PayrollRunType.regular,
        status=PayrollRunStatus.paid,
        idempotency_key=f"run-{now.timestamp()}",
        run_by=user.id,
        total_employees=1,
        total_gross=Decimal("150000.00"),
        total_net=Decimal("120000.00"),
        total_employer_cost=Decimal("170000.00"),
        total_deductions=Decimal("30000.00"),
        created_at=now,
    )
    db.add(run)
    db.commit()

    return {
        "company_id": company_a.company_id,
        "employee_id": emp.id,
        "employee_first": emp.first_name,
        "employee_last": emp.last_name,
        "employee_email": emp.email,
        "employee_code": emp.employee_code,
    }


def _scan_for_employee_data(data: Any, forbidden: set[str]):
    """Recursively checks that forbidden employee personal/business data is not present."""
    if isinstance(data, dict):
        for k, v in data.items():
            k_lower = str(k).lower()
            for term in forbidden:
                assert term not in k_lower, f"Forbidden employee-level field leaked in key: {k}"
            _scan_for_employee_data(v, forbidden)
    elif isinstance(data, list):
        for item in data:
            _scan_for_employee_data(item, forbidden)
    elif isinstance(data, str):
        data_lower = data.lower()
        for term in forbidden:
            assert term not in data_lower, f"Forbidden employee value leaked in data: {data}"


# S1 & S3: Super admin sees the figures
def test_s1_s3_super_admin_sees_stats(
    client: TestClient,
    super_admin_headers: dict[str, str],
    super_admin_stats_data: dict[str, Any],
):
    for ep in [
        "/api/v1/platform/stats/overview",
        "/api/v1/platform/stats/payroll",
        "/api/v1/platform/stats/platform-health",
    ]:
        resp = client.get(ep, headers=super_admin_headers)
        assert resp.status_code == 200, (
            f"Expected 200 for super admin on {ep}, got {resp.status_code}: {resp.text}"
        )


# S1 & S3: hr_admin, owner, manager and employee each get 403 on all stats endpoints
@pytest.mark.parametrize("ep", PLATFORM_STATS_ENDPOINTS)
def test_s1_s3_company_roles_get_403(
    client: TestClient,
    db: Session,
    company_a: TenantContext,
    ep: str,
):
    # hr_admin
    resp = client.get(ep, headers=company_a.hr_headers)
    assert resp.status_code == 403, f"Expected 403 for hr_admin on {ep}, got {resp.status_code}"

    # owner
    owner_headers = _make_user_headers(db, company_a.company_id, UserRole.owner)
    resp = client.get(ep, headers=owner_headers)
    assert resp.status_code == 403, f"Expected 403 for owner on {ep}, got {resp.status_code}"

    # manager
    resp = client.get(ep, headers=company_a.manager_headers)
    assert resp.status_code == 403, f"Expected 403 for manager on {ep}, got {resp.status_code}"

    # employee
    resp = client.get(ep, headers=company_a.employee_headers)
    assert resp.status_code == 403, f"Expected 403 for employee on {ep}, got {resp.status_code}"


# S2 & S3: No company's business data appears — aggregates only,
# never an employee name, salary, payslip
def test_s2_s3_no_employee_level_fields_in_response(
    client: TestClient,
    super_admin_headers: dict[str, str],
    super_admin_stats_data: dict[str, Any],
):
    forbidden = {
        "supersecretfirst",
        "supersecretlast",
        super_admin_stats_data["employee_email"].lower(),
        super_admin_stats_data["employee_code"].lower(),
        "employee_name",
        "employee_id",
        "payslip",
        "salary",
        "basic_pay",
        "hra",
        "bank_account",
        "pan_number",
        "aadhaar",
    }

    for ep in PLATFORM_STATS_ENDPOINTS:
        resp = client.get(ep, headers=super_admin_headers)
        assert resp.status_code == 200
        payload = resp.json()
        _scan_for_employee_data(payload, forbidden)
