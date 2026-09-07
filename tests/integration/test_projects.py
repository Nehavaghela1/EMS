import uuid
from datetime import date, timedelta
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
    db: Session, company_id: uuid.UUID, role: UserRole = UserRole.super_admin
) -> tuple[Employee, dict[str, str]]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"proj-{uuid.uuid4().hex[:6]}@example.test",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    employee = Employee(
        company_id=company_id,
        user_id=user.id,
        employee_code=f"PRJ{uuid.uuid4().hex[:6].upper()}",
        first_name="Proj",
        last_name="Tester",
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

def test_project_lifecycle_and_analytics(client: TestClient, db: Session, tenant_a: TenantContext):
    employee, headers = _create_employee_with_user(db, tenant_a.company_id, UserRole.super_admin)

    # 1. Create Project
    code = f"PRJ-{uuid.uuid4().hex[:4].upper()}"
    res = client.post(
        "/api/v1/projects",
        json={
            "name": "E-Commerce Replatform",
            "code": code,
            "description": "Migration to microservices",
            "status": "active",
            "start_date": str(date.today()),
            "deadline": str(date.today() + timedelta(days=90)),
            "budget": "50000.00",
            "client_name": "Acme Corp"
        },
        headers=headers
    )
    assert res.status_code == 201, res.text
    project_id = res.json()["id"]

    # 2. Add Member
    res_mem = client.post(
        f"/api/v1/projects/{project_id}/members",
        json={
            "employee_id": str(employee.id),
            "role": "lead"
        },
        headers=headers
    )
    assert res_mem.status_code == 201, res_mem.text

    # 3. Create Task
    res_task = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={
            "title": "Design DB Schema",
            "description": "Create ERD and models",
            "assigned_to": str(employee.id),
            "priority": "high",
            "status": "in_progress",
            "estimated_hours": "16.00"
        },
        headers=headers
    )
    assert res_task.status_code == 201, res_task.text
    task_id = res_task.json()["id"]

    # 4. Add Comment
    res_comm = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Schema design is 80% ready."},
        headers=headers
    )
    assert res_comm.status_code == 201, res_comm.text

    # 5. Log Time Entry
    res_time = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": project_id,
            "task_id": task_id,
            "date": str(date.today()),
            "hours": "6.50",
            "description": "Worked on initial PostgreSQL schema",
            "is_billable": True
        },
        headers=headers
    )
    assert res_time.status_code == 201, res_time.text
    entry_id = res_time.json()["id"]

    # Approve Time Entry
    res_app = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=headers
    )
    assert res_app.status_code == 200, res_app.text
    assert res_app.json()["status"] == "approved"

    # 6. Create Milestone
    res_ms = client.post(
        f"/api/v1/projects/{project_id}/milestones",
        json={
            "title": "Architecture Blueprint",
            "due_date": str(date.today() + timedelta(days=14)),
            "status": "in_progress",
            "completion_percentage": "50.00"
        },
        headers=headers
    )
    assert res_ms.status_code == 201, res_ms.text

    # 7. Complete Task
    res_done = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "done"},
        headers=headers
    )
    assert res_done.status_code == 200, res_done.text
    assert res_done.json()["completed_at"] is not None

    # 8. Check Summary / Analytics
    res_summary = client.get(f"/api/v1/projects/{project_id}/summary", headers=headers)
    assert res_summary.status_code == 200, res_summary.text
    summary_data = res_summary.json()
    assert summary_data["total_tasks"] == 1
    assert summary_data["completed_tasks"] == 1
    assert summary_data["completion_percentage"] == "100.00"
    assert summary_data["total_logged_hours"] == "6.50"

def test_daily_time_entry_hour_limit(client: TestClient, db: Session, tenant_a: TenantContext):
    employee, headers = _create_employee_with_user(db, tenant_a.company_id, UserRole.super_admin)

    code = f"PRJ-{uuid.uuid4().hex[:4].upper()}"
    res = client.post(
        "/api/v1/projects",
        json={"name": "Limit Test", "code": code},
        headers=headers
    )
    project_id = res.json()["id"]

    # Log 16 hours
    client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": project_id,
            "date": str(date.today()),
            "hours": "16.00",
            "description": "Shift 1"
        },
        headers=headers
    )

    # Attempting to log 10 more hours (total 26 > 24) must fail
    res_fail = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": project_id,
            "date": str(date.today()),
            "hours": "10.00",
            "description": "Shift 2"
        },
        headers=headers
    )
    assert res_fail.status_code == 400
