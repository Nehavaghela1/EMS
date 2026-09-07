import uuid
from datetime import date
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import User, UserRole
from tests.conftest import TenantContext


def _create_employee_with_user(
    db: Session, company_id: uuid.UUID, role: UserRole = UserRole.employee
) -> tuple[Employee, dict[str, str]]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"perf-{uuid.uuid4().hex[:6]}@example.test",
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
        first_name="Perf",
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


def test_performance_cycle_lifecycle(client: TestClient, company_a: TenantContext):
    # 1. HR creates performance cycle (draft)
    create_res = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": "FY 2026-27 Annual Review",
            "cycle_type": "annual",
            "start_date": "2026-04-01",
            "end_date": "2027-03-31",
            "self_review_deadline": "2027-03-15",
            "manager_review_deadline": "2027-03-25",
        },
        headers=company_a.hr_headers,
    )
    assert create_res.status_code == 201
    cycle = create_res.json()
    assert cycle["status"] == "draft"
    cycle_id = cycle["id"]

    # 2. HR activates cycle
    act_res = client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=company_a.hr_headers,
    )
    assert act_res.status_code == 200
    assert act_res.json()["status"] == "active"


def test_goals_weightage_sum_gate_and_review_workflow(
    client: TestClient, company_a: TenantContext, db: Session
):
    emp, emp_headers = _create_employee_with_user(db, company_a.company_id)

    # 1. Create and Activate Cycle
    cycle_res = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": "Q3 2026 Review",
            "cycle_type": "quarterly",
            "start_date": "2026-07-01",
            "end_date": "2026-09-30",
        },
        headers=company_a.hr_headers,
    )
    cycle_id = cycle_res.json()["id"]
    client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=company_a.hr_headers,
    )

    # 2. Employee sets 2 goals with weightages summing to 80 (invalid: must sum to 100)
    goals_res = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": cycle_id,
            "goals": [
                {
                    "title": "Deliver WP-22 Backend",
                    "description": "Build performance endpoints",
                    "weightage": "50.00",
                    "target_value": "100% tests passing",
                },
                {
                    "title": "Optimize Queries",
                    "description": "Improve database speed",
                    "weightage": "30.00",
                    "target_value": "< 50ms latency",
                },
            ],
        },
        headers=emp_headers,
    )
    assert goals_res.status_code == 201
    created_goals = goals_res.json()
    goal1_id = created_goals[0]["id"]
    goal2_id = created_goals[1]["id"]

    # 3. GATE ASSERTION: Self-review MUST fail because weightages sum to 80, not 100
    fail_self_res = client.post(
        f"/api/v1/performance/goals/{goal1_id}/self-review",
        json={"rating": "4.5", "comments": "Completed task"},
        headers=emp_headers,
    )
    assert fail_self_res.status_code == 400
    assert fail_self_res.json()["error"]["code"] == "invalid_weightage_sum"

    # 4. Employee updates Goal 2 weightage to 50.00 so total == 100.00
    client.put(
        f"/api/v1/performance/goals/{goal2_id}",
        json={"weightage": "50.00"},
        headers=emp_headers,
    )

    # 5. Now Self-review succeeds!
    self_res = client.post(
        f"/api/v1/performance/goals/{goal1_id}/self-review",
        json={"rating": "4.5", "comments": "Completed on time"},
        headers=emp_headers,
    )
    assert self_res.status_code == 200
    assert self_res.json()["rating"] == "4.5"

    # 6. Manager submits rating
    mgr_res = client.post(
        f"/api/v1/performance/goals/{goal1_id}/manager-review",
        json={"rating": "5.0", "comments": "Exceeded expectations"},
        headers=company_a.hr_headers,
    )
    assert mgr_res.status_code == 200
    assert mgr_res.json()["rating"] == "5.0"

    # 7. Finalize summary
    summary_res = client.post(
        f"/api/v1/performance/summary/{emp.id}",
        json={
            "cycle_id": cycle_id,
            "overall_comments": "Outstanding performance this quarter",
            "salary_revision_recommended": True,
            "recommended_increment_percent": "12.50",
        },
        headers=company_a.hr_headers,
    )
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["employee_id"] == str(emp.id)
    assert summary["salary_revision_recommended"] is True
