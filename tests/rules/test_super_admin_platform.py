"""Tests for super admin platform role enforcement and platform stats.

Covers:
- PART A & C: super admin blocked from company data across all modules (C2)
- PART C: route policy enforcement (C1, C3)
- PART B: platform stats live numbers (B1 - B7)
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.payroll.models import (
    PayrollRun,
    PayrollRunStatus,
)
from app.modules.platform.models import AuditLog
from app.modules.projects.models import Project, TimeEntry
from app.modules.time_leave.models import Attendance, AttendanceStatus
from tests.conftest import TenantContext

# ---------------------------------------------------------------------------
# C2: One test per module asserting super admin gets 403 on COMPANY routes
# ---------------------------------------------------------------------------


def test_C2_super_admin_forbidden_hr_employee_list(
    client: TestClient, super_admin_headers: dict[str, str], company_a: TenantContext
):
    resp = client.get("/api/v1/employees", headers=super_admin_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You do not have permission to perform this action."


def test_C2_super_admin_forbidden_attendance(
    client: TestClient, super_admin_headers: dict[str, str], company_a: TenantContext
):
    resp = client.get("/api/v1/attendance", headers=super_admin_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You do not have permission to perform this action."


def test_C2_super_admin_forbidden_leave_request(
    client: TestClient, super_admin_headers: dict[str, str], company_a: TenantContext
):
    resp = client.get("/api/v1/leaves", headers=super_admin_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You do not have permission to perform this action."


def test_C2_super_admin_forbidden_payroll_run(
    client: TestClient, super_admin_headers: dict[str, str], company_a: TenantContext
):
    resp = client.get("/api/v1/payroll/runs", headers=super_admin_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You do not have permission to perform this action."


def test_C2_super_admin_forbidden_performance_goals(
    client: TestClient, super_admin_headers: dict[str, str], company_a: TenantContext
):
    resp = client.get(f"/api/v1/performance/goals/{uuid.uuid4()}", headers=super_admin_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You do not have permission to perform this action."


def test_C2_super_admin_forbidden_project_detail(
    client: TestClient, super_admin_headers: dict[str, str], company_a: TenantContext
):
    resp = client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=super_admin_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You do not have permission to perform this action."


def test_C2_super_admin_forbidden_announcement_create(
    client: TestClient, super_admin_headers: dict[str, str], company_a: TenantContext
):
    resp = client.post(
        "/api/v1/announcements",
        headers=super_admin_headers,
        json={"title": "Test", "content": "Forbidden", "target_audience": "all"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You do not have permission to perform this action."


# ---------------------------------------------------------------------------
# C3: Super admin gets 200 on representative PLATFORM routes, non-super-admin gets 403
# ---------------------------------------------------------------------------


PLATFORM_SAMPLE_ROUTES = [
    ("GET", "/api/v1/companies"),
    ("GET", "/api/v1/platform/rate-sources"),
    ("GET", "/api/v1/platform/rate-drafts"),
    ("GET", "/api/v1/platform/payroll-stats?from=2026-01&to=2026-01"),
]


@pytest.mark.parametrize("method,url", PLATFORM_SAMPLE_ROUTES)
def test_C3_platform_routes_admit_super_admin_and_forbid_others(
    client: TestClient,
    method: str,
    url: str,
    super_admin_headers: dict[str, str],
    company_a: TenantContext,
):
    # Super admin should be allowed (200)
    resp_sa = client.request(method, url, headers=super_admin_headers)
    assert resp_sa.status_code == 200, f"Super admin failed on {method} {url}: {resp_sa.text}"

    # HR admin should be forbidden (403)
    resp_hr = client.request(method, url, headers=company_a.hr_headers)
    assert resp_hr.status_code == 403, (
        f"HR admin was not forbidden on {method} {url}: {resp_hr.status_code}"
    )


# ---------------------------------------------------------------------------
# PART B: Platform Stats Fixture & Tests (B1 - B7)
# ---------------------------------------------------------------------------


@pytest.fixture
def stats_scenario(db: Session):
    """Fixture creating known companies, users, employees, payroll runs, attendance, and projects.
    Two companies:
    Company Alpha (active): 2 employees, 1 paid payroll run, punch, active project.
    Company Beta (active): 1 employee, 0 payroll runs.
    Company Gamma (pending): 0 employees.
    """
    now = utcnow()
    cur_year = now.year
    cur_month = now.month
    prev_month = 12 if cur_month == 1 else cur_month - 1
    prev_year = cur_year - 1 if cur_month == 1 else cur_year

    # Company Alpha
    c_alpha = Company(
        name="Alpha Corp",
        code=f"ALP{uuid.uuid4().hex[:4].upper()}",
        email=f"alpha-{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
        created_at=now,
    )
    db.add(c_alpha)
    db.flush()
    bind_tenant_to_session(db, company_id=c_alpha.id, is_platform_admin=True)
    # Company Beta
    c_beta = Company(
        name="Beta Ltd",
        code=f"BET{uuid.uuid4().hex[:4].upper()}",
        email=f"beta-{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
        created_at=now,
    )
    # Company Gamma
    c_gamma = Company(
        name="Gamma Pending",
        code=f"GAM{uuid.uuid4().hex[:4].upper()}",
        email=f"gamma-{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.pending,
        created_at=now,
    )
    db.add_all([c_beta, c_gamma])
    db.flush()

    # Users in Alpha
    u_alpha_owner = User(
        company_id=c_alpha.id,
        email=f"owner-{uuid.uuid4().hex[:6]}@alpha.test",
        hashed_password="pw",
        role=UserRole.owner,
        is_active=True,
        last_login_at=now,
    )
    u_alpha_emp = User(
        company_id=c_alpha.id,
        email=f"emp-{uuid.uuid4().hex[:6]}@alpha.test",
        hashed_password="pw",
        role=UserRole.employee,
        is_active=True,
    )
    # User in Beta
    u_beta_owner = User(
        company_id=c_beta.id,
        email=f"owner-{uuid.uuid4().hex[:6]}@beta.test",
        hashed_password="pw",
        role=UserRole.owner,
        is_active=True,
    )
    db.add_all([u_alpha_owner, u_alpha_emp, u_beta_owner])
    db.flush()

    # Employees in Alpha
    e_alpha_1 = Employee(
        company_id=c_alpha.id,
        user_id=u_alpha_owner.id,
        employee_code=f"EMP-A1-{uuid.uuid4().hex[:4]}",
        first_name="Alice",
        last_name="Alpha",
        email=u_alpha_owner.email,
        is_active=True,
        employment_type=EmploymentType.full_time,
        hire_date=date(cur_year, cur_month, 1),
    )
    e_alpha_2 = Employee(
        company_id=c_alpha.id,
        user_id=u_alpha_emp.id,
        employee_code=f"EMP-A2-{uuid.uuid4().hex[:4]}",
        first_name="Bob",
        last_name="Alpha",
        email=u_alpha_emp.email,
        is_active=True,
        employment_type=EmploymentType.full_time,
        hire_date=date(cur_year, cur_month, 1),
    )
    # Employee in Beta
    e_beta_1 = Employee(
        company_id=c_beta.id,
        user_id=u_beta_owner.id,
        employee_code=f"EMP-B1-{uuid.uuid4().hex[:4]}",
        first_name="Charlie",
        last_name="Beta",
        email=u_beta_owner.email,
        is_active=True,
        employment_type=EmploymentType.full_time,
        hire_date=date(prev_year, prev_month, 1),
    )
    db.add_all([e_alpha_1, e_alpha_2, e_beta_1])
    db.flush()

    # Payroll run in Alpha for current month
    run_alpha = PayrollRun(
        company_id=c_alpha.id,
        year=cur_year,
        month=cur_month,
        status=PayrollRunStatus.paid,
        run_by=u_alpha_owner.id,
        idempotency_key=str(uuid.uuid4()),
        total_employees=2,
        total_gross=Decimal("100000.00"),
        total_deductions=Decimal("10000.00"),
        total_net=Decimal("90000.00"),
        total_employer_cost=Decimal("110000.00"),
    )
    # Payroll run in Alpha for previous month
    run_alpha_prev = PayrollRun(
        company_id=c_alpha.id,
        year=prev_year,
        month=prev_month,
        status=PayrollRunStatus.paid,
        run_by=u_alpha_owner.id,
        idempotency_key=str(uuid.uuid4()),
        total_employees=2,
        total_gross=Decimal("80000.00"),
        total_deductions=Decimal("8000.00"),
        total_net=Decimal("72000.00"),
        total_employer_cost=Decimal("88000.00"),
    )
    db.add_all([run_alpha, run_alpha_prev])
    db.flush()

    # Attendance punch in Alpha
    punch = Attendance(
        company_id=c_alpha.id,
        employee_id=e_alpha_1.id,
        date=date(cur_year, cur_month, 1),
        status=AttendanceStatus.present,
    )
    # Active Project in Alpha
    proj = Project(
        company_id=c_alpha.id,
        name="Project Phoenix",
        code=f"PRJ-{uuid.uuid4().hex[:4]}",
        status="active",
    )
    db.add_all([punch, proj])
    db.flush()

    # Time entry in Alpha
    te = TimeEntry(
        company_id=c_alpha.id,
        project_id=proj.id,
        employee_id=e_alpha_1.id,
        date=date(cur_year, cur_month, 1),
        hours=Decimal("8.00"),
        status="approved",
    )
    db.add(te)
    db.commit()

    return {
        "alpha": c_alpha,
        "beta": c_beta,
        "gamma": c_gamma,
        "cur_year": cur_year,
        "cur_month": cur_month,
        "prev_year": prev_year,
        "prev_month": prev_month,
    }


def _scan_for_forbidden_data(data: Any, forbidden_terms: set[str]):
    """Recursively scans serialized JSON objects/strings/keys for forbidden personal data."""
    if isinstance(data, dict):
        for k, v in data.items():
            k_lower = str(k).lower()
            for term in forbidden_terms:
                assert term not in k_lower, f"Forbidden term '{term}' leaked in dict key: {k}"
            _scan_for_forbidden_data(v, forbidden_terms)
    elif isinstance(data, list):
        for item in data:
            _scan_for_forbidden_data(item, forbidden_terms)
    elif isinstance(data, str):
        data_lower = data.lower()
        for term in forbidden_terms:
            assert term not in data_lower, f"Forbidden term '{term}' leaked in text: {data}"


# B7: Check that no endpoint response leaks employee personal data
def test_B3_B7_no_personal_data_in_platform_stats(
    client: TestClient, super_admin_headers: dict[str, str], stats_scenario: dict[str, Any]
):
    forbidden_terms = {
        "alice",
        "bob",
        "charlie",
        "alpha.test",
        "beta.test",
        "employee_id",
        "employee_number",
        "salary_structure",
        "bank_account",
        "rating",
        "document",
    }
    endpoints = [
        "/api/v1/platform/stats/overview",
        "/api/v1/platform/stats/companies",
        "/api/v1/platform/stats/payroll",
        "/api/v1/platform/stats/activity",
        "/api/v1/platform/stats/platform-health",
    ]
    for ep in endpoints:
        resp = client.get(ep, headers=super_admin_headers)
        assert resp.status_code == 200, f"Endpoint {ep} failed: {resp.text}"
        payload = resp.json()
        _scan_for_forbidden_data(payload, forbidden_terms)


def test_B2_B7_stats_overview_figures(
    client: TestClient, super_admin_headers: dict[str, str], stats_scenario: dict[str, Any]
):
    resp = client.get("/api/v1/platform/stats/overview", headers=super_admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["companies_by_status"]["active"] >= 2
    assert data["companies_by_status"]["pending"] >= 1
    assert data["companies_created_this_month"] >= 3
    assert data["total_users"] >= 3
    assert data["total_employees"] >= 3
    assert Decimal(str(data["total_net_paid_this_month"])) >= Decimal("90000.00")
    assert Decimal(str(data["total_net_paid_last_month"])) >= Decimal("72000.00")


def test_B2_B7_stats_companies_paging_search(
    client: TestClient, super_admin_headers: dict[str, str], stats_scenario: dict[str, Any]
):
    alpha = stats_scenario["alpha"]
    resp = client.get(
        f"/api/v1/platform/stats/companies?search={alpha.code}", headers=super_admin_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    row = data["items"][0]
    assert row["company_id"] == str(alpha.id)
    assert row["name"] == "Alpha Corp"
    assert row["code"] == alpha.code
    assert row["status"] == "active"
    assert row["headcount"] == 2
    assert row["active_user_count"] == 2
    assert row["joiners_this_month"] == 2
    assert row["leavers_this_month"] == 0
    assert row["last_payroll_run_date"] is not None


def test_B2_B7_stats_activity(
    client: TestClient, super_admin_headers: dict[str, str], stats_scenario: dict[str, Any]
):
    alpha = stats_scenario["alpha"]
    resp = client.get(
        f"/api/v1/platform/stats/activity?company_id={alpha.id}", headers=super_admin_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 1
    row = [r for r in data["items"] if r["company_id"] == str(alpha.id)][0]
    assert row["punch_count"] >= 1
    assert row["active_projects"] >= 1
    assert Decimal(str(row["approved_hours_logged"])) >= Decimal("8.00")


def test_B2_B7_stats_platform_health(
    client: TestClient, super_admin_headers: dict[str, str], stats_scenario: dict[str, Any]
):
    resp = client.get("/api/v1/platform/stats/platform-health", headers=super_admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs_by_status" in data
    assert "job_failures_last_24h" in data
    assert "rate_drafts_awaiting_verification" in data
    assert "storage_bytes_by_company" in data


def test_B2_B7_empty_company_returns_zeros_not_error(
    client: TestClient, super_admin_headers: dict[str, str], stats_scenario: dict[str, Any]
):
    gamma = stats_scenario["gamma"]
    resp = client.get(
        f"/api/v1/platform/stats/activity?company_id={gamma.id}", headers=super_admin_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    row = [r for r in data["items"] if r["company_id"] == str(gamma.id)][0]
    assert row["punch_count"] == 0
    assert row["active_projects"] == 0
    assert Decimal(str(row["approved_hours_logged"])) == Decimal("0.00")


def test_B5_stats_reads_are_audited(
    client: TestClient,
    db: Session,
    super_admin_headers: dict[str, str],
    stats_scenario: dict[str, Any],
):
    resp = client.get("/api/v1/platform/stats/overview", headers=super_admin_headers)
    assert resp.status_code == 200
    # Verify audit log was recorded
    audit_row = (
        db.query(AuditLog)
        .filter(AuditLog.action == "platform.stats.overview")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit_row is not None
    assert audit_row.details.get("endpoint") == "/platform/stats/overview"


def test_B6_stats_rate_limit(
    client: TestClient, super_admin_headers: dict[str, str], limits_on: None
):
    codes = [
        client.get("/api/v1/platform/stats/overview", headers=super_admin_headers).status_code
        for _ in range(61)
    ]
    assert codes[:60] == [200] * 60 and codes[60] == 429
