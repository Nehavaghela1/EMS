import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import User, UserRole
from tests.conftest import TEST_PASSWORD, TenantContext


def _create_user_and_token(db: Session, company_id: uuid.UUID, role: UserRole) -> dict[str, str]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"{role.value}_{uuid.uuid4().hex[:6]}@{company_id}.test",
        hashed_password=hash_password(TEST_PASSWORD),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


def _create_employee_with_user(
    db: Session, company_id: uuid.UUID, role: UserRole = UserRole.employee
) -> tuple[Employee, dict[str, str]]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"{role.value}_{uuid.uuid4().hex[:6]}@{company_id}.test",
        hashed_password=hash_password(TEST_PASSWORD),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    emp = Employee(
        company_id=company_id,
        user_id=user.id,
        employee_code=f"EMP-{uuid.uuid4().hex[:6].upper()}",
        first_name="Project",
        last_name="Emp",
        email=user.email,
        hire_date=date.today(),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    db.add(emp)
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return emp, {"Authorization": f"Bearer {token}"}


def _setup_project_with_members(
    client: TestClient, db: Session, company: TenantContext
) -> tuple[str, str, Employee, Employee, dict[str, str], dict[str, str]]:
    # Create project via HR headers
    p_code = f"PRJ-{uuid.uuid4().hex[:5].upper()}"
    p_res = client.post(
        "/api/v1/projects",
        json={"name": f"Project {p_code}", "code": p_code},
        headers=company.hr_headers,
    )
    assert p_res.status_code == 201, p_res.text
    project_id = p_res.json()["id"]

    emp1, emp1_headers = _create_employee_with_user(db, company.company_id, UserRole.employee)
    emp2, emp2_headers = _create_employee_with_user(db, company.company_id, UserRole.employee)
    emp1_id = emp1.id
    emp2_id = emp2.id

    # Add emp1 as project member
    client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"employee_id": str(emp1_id), "role": "member"},
        headers=company.hr_headers,
    )
    # Add emp2 as project member
    client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"employee_id": str(emp2_id), "role": "member"},
        headers=company.hr_headers,
    )

    # Create a task assigned to emp1
    t_res = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={"title": "Emp1 Task", "assigned_to": str(emp1_id), "status": "todo"},
        headers=company.hr_headers,
    )
    assert t_res.status_code == 201, t_res.text
    task_id = t_res.json()["id"]

    return project_id, task_id, emp1_id, emp2_id, emp1_headers, emp2_headers


def test_owner_log_time_entry_explicit_employee_id(
    client: TestClient, db: Session, company_a, company_b
):
    """Owner of company_a logs time entry for ANOTHER employee in a project
    via explicit employee_id.
    - Owner of same company is allowed (201).
    - Owner of another company is blocked (403 or 404).
    - Ordinary employee trying to log for another employee gets 403 or falls back to own profile.
    """
    (
        project_id,
        task_id,
        emp1_id,
        emp2_id,
        emp1_headers,
        emp2_headers,
    ) = _setup_project_with_members(client, db, company_a)

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)

    # 1. Ordinary employee (emp2) provides employee_id of emp1 -> ignored by role check,
    # tries to log under emp2, but since task is assigned to emp1, raises 403 forbidden.
    emp2_payload = {
        "project_id": project_id,
        "task_id": task_id,
        "employee_id": str(emp1_id),
        "date": str(date.today()),
        "hours": 2.0,
        "description": "Emp2 attempting to log for emp1",
    }
    res_emp2 = client.post("/api/v1/projects/time-entries", json=emp2_payload, headers=emp2_headers)
    assert res_emp2.status_code == 403

    # 2. Owner of company_b is blocked (403 or 404)
    owner_b_payload = {
        "project_id": project_id,
        "task_id": task_id,
        "employee_id": str(emp1_id),
        "date": str(date.today()),
        "hours": 2.0,
        "description": "Owner B logging for emp1",
    }
    res_owner_b = client.post(
        "/api/v1/projects/time-entries", json=owner_b_payload, headers=owner_b_headers
    )
    assert res_owner_b.status_code in (403, 404)

    # 3. Owner of same company logs time explicitly for emp1 -> 201
    # (fails before fix: 400 no_employee_profile)
    owner_a_payload = {
        "project_id": project_id,
        "task_id": task_id,
        "employee_id": str(emp1_id),
        "date": str(date.today()),
        "hours": 2.5,
        "description": "Owner A logging for emp1",
    }
    res_owner_a = client.post(
        "/api/v1/projects/time-entries", json=owner_a_payload, headers=owner_a_headers
    )
    assert res_owner_a.status_code == 201
    assert res_owner_a.json()["employee_id"] == str(emp1_id)
    assert float(res_owner_a.json()["hours"]) == 2.5


def test_owner_create_time_entry_is_admin_or_manager_path(
    client: TestClient, db: Session, company_a, company_b
):
    """Owner of company_a creates a time entry for a task assigned to someone else
    through the is_admin_or_manager path.
    """
    project_id, task_id, emp1_id, emp2_id, emp1_headers, emp2_headers = _setup_project_with_members(
        client, db, company_a
    )

    # Create owner who also has an employee profile
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    owner_emp, owner_a_headers = _create_employee_with_user(
        db, company_a.company_id, UserRole.owner
    )
    owner_emp_id = owner_emp.id
    # Add owner_emp to project members
    client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"employee_id": str(owner_emp_id), "role": "member"},
        headers=company_a.hr_headers,
    )

    # Owner logs time on emp1's task without specifying employee_id (uses owner_emp.id).
    # Since task is assigned to emp1, non-admin/manager gets 403 from service line 387.
    # With is_admin_or_manager=True, owner is permitted to log time on any task.
    payload = {
        "project_id": project_id,
        "task_id": task_id,
        "date": str(date.today()),
        "hours": 1.5,
        "description": "Owner logging on someone else's task",
    }

    # Ordinary employee (emp2) logging on emp1's task gets 403
    res_emp2 = client.post("/api/v1/projects/time-entries", json=payload, headers=emp2_headers)
    assert res_emp2.status_code == 403

    # Owner of company_a gets 201
    # (fails before fix: 403 because is_admin_or_manager is False for owner)
    res_owner = client.post("/api/v1/projects/time-entries", json=payload, headers=owner_a_headers)
    assert res_owner.status_code == 201
    assert res_owner.json()["employee_id"] == str(owner_emp_id)


def test_owner_update_task_assigned_to_another_employee(
    client: TestClient, db: Session, company_a, company_b
):
    """PUT /api/v1/projects/tasks/{task_id}:
    - Owner of the same company updates a task assigned to ANOTHER employee -> 200.
    - Owner of another company gets 403 or 404.
    - Ordinary employee who is not assigned the task gets 403.
    """
    (
        project_id,
        task_id,
        emp1_id,
        emp2_id,
        emp1_headers,
        emp2_headers,
    ) = _setup_project_with_members(client, db, company_a)

    owner_a_headers = _create_user_and_token(db, company_a.company_id, UserRole.owner)
    owner_b_headers = _create_user_and_token(db, company_b.company_id, UserRole.owner)

    update_payload = {"title": "Updated Task Title", "status": "in_progress"}

    # 1. Ordinary employee (emp2) who is not assignee or lead tries to update task -> 403
    res_emp2 = client.put(
        f"/api/v1/projects/tasks/{task_id}", json=update_payload, headers=emp2_headers
    )
    assert res_emp2.status_code == 403
    assert (
        "Only the task assignee or Project Lead can modify this task."
        in res_emp2.json()["error"]["message"]
    )

    # 2. Owner of company_b gets 403 or 404
    res_owner_b = client.put(
        f"/api/v1/projects/tasks/{task_id}", json=update_payload, headers=owner_b_headers
    )
    assert res_owner_b.status_code in (403, 404)

    # 3. Owner of same company updates task assigned to emp1 -> 200
    res_owner_a = client.put(
        f"/api/v1/projects/tasks/{task_id}", json=update_payload, headers=owner_a_headers
    )
    assert res_owner_a.status_code == 200
    assert res_owner_a.json()["title"] == "Updated Task Title"
    assert res_owner_a.json()["status"] == "in_progress"
