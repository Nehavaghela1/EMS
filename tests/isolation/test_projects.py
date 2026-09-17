import uuid
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import User, UserRole
from tests.conftest import TenantContext

def _create_user_and_headers(db: Session, company_id: uuid.UUID) -> dict[str, str]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"iso-proj-{uuid.uuid4().hex[:6]}@example.test",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(user)
    db.commit()

    token = create_access_token(
        sub=str(user.id), company_id=str(company_id), role=UserRole.hr_admin.value
    )
    return {"Authorization": f"Bearer {token}"}

def test_projects_tenant_isolation(client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext):
    headers_a = _create_user_and_headers(db, company_a.company_id)
    headers_b = _create_user_and_headers(db, company_b.company_id)

    # 1. Tenant A creates project
    code_a = f"PRJ-A-{uuid.uuid4().hex[:4].upper()}"
    res_a = client.post(
        "/api/v1/projects",
        json={"name": "Tenant A Secret Project", "code": code_a},
        headers=headers_a
    )
    assert res_a.status_code == 201
    project_id_a = res_a.json()["id"]

    # 2. Tenant B listing projects should NOT see Tenant A's project
    res_list_b = client.get("/api/v1/projects", headers=headers_b)
    assert res_list_b.status_code == 200
    ids_b = [p["id"] for p in res_list_b.json()]
    assert project_id_a not in ids_b

    # 3. Tenant B fetching Tenant A's project directly should get 404
    res_get_b = client.get(f"/api/v1/projects/{project_id_a}", headers=headers_b)
    assert res_get_b.status_code == 404

def test_task_update_permissions(client: TestClient, db: Session, company_a: TenantContext):
    # Setup admin
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    admin_headers = _create_user_and_headers(db, company_a.company_id)

    # Create project
    p_res = client.post(
        "/api/v1/projects",
        json={"name": "Permissions Project", "code": f"PRJ-{uuid.uuid4().hex[:4].upper()}"},
        headers=admin_headers
    )
    assert p_res.status_code == 201
    project_id = p_res.json()["id"]

    # Create Employee 1 (Assignee)
    user_1 = User(
        company_id=company_a.company_id,
        email=f"emp1-{uuid.uuid4().hex[:6]}@example.test",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(user_1)
    db.commit()
    emp_1 = Employee(
        company_id=company_a.company_id,
        user_id=user_1.id,
        employee_code=f"EMP-{uuid.uuid4().hex[:4].upper()}",
        first_name="Nik",
        last_name="Vaghela",
        email=user_1.email,
        hire_date=date.today(),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
    )
    db.add(emp_1)

    # Create Employee 2 (Teammate - e.g., Yashvi)
    user_2 = User(
        company_id=company_a.company_id,
        email=f"emp2-{uuid.uuid4().hex[:6]}@example.test",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(user_2)
    db.commit()
    emp_2 = Employee(
        company_id=company_a.company_id,
        user_id=user_2.id,
        employee_code=f"EMP-{uuid.uuid4().hex[:4].upper()}",
        first_name="Yashvi",
        last_name="Patel",
        email=user_2.email,
        hire_date=date.today(),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
    )
    db.add(emp_2)
    db.commit()

    token_1 = create_access_token(sub=str(user_1.id), company_id=str(company_a.company_id), role=UserRole.employee.value)
    token_2 = create_access_token(sub=str(user_2.id), company_id=str(company_a.company_id), role=UserRole.employee.value)
    headers_emp1 = {"Authorization": f"Bearer {token_1}"}
    headers_emp2 = {"Authorization": f"Bearer {token_2}"}

    # Add both to project members
    client.post(f"/api/v1/projects/{project_id}/members", json={"employee_id": str(emp_1.id), "role": "member"}, headers=admin_headers)
    client.post(f"/api/v1/projects/{project_id}/members", json={"employee_id": str(emp_2.id), "role": "member"}, headers=admin_headers)

    # Admin creates task assigned to Employee 1 (Nik)
    t_res = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={"title": "Nik's Feature Task", "assigned_to": str(emp_1.id), "status": "todo"},
        headers=admin_headers
    )
    assert t_res.status_code == 201
    task_id = t_res.json()["id"]

    # 1. Teammate (Yashvi) tries to modify Nik's task -> Should be 403 Forbidden
    res_forbidden = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "done"},
        headers=headers_emp2
    )
    assert res_forbidden.status_code == 403
    assert "Only the task assignee or Project Lead" in res_forbidden.json()["error"]["message"]

    # 2. Assignee (Nik) modifies his own task -> Allowed
    res_nik = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "done"},
        headers=headers_emp1
    )
    assert res_nik.status_code == 200
    assert res_nik.json()["status"] == "done"

    # 3. Promote Yashvi to Project Lead -> She can now modify Nik's task
    client.delete(
        f"/api/v1/projects/{project_id}/members/{emp_2.id}",
        headers=admin_headers
    )
    client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"employee_id": str(emp_2.id), "role": "lead"},
        headers=admin_headers
    )
    # Re-test Yashvi modifying task -> Allowed now that she is lead
    res_lead = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "in_progress"},
        headers=headers_emp2
    )
    assert res_lead.status_code == 200
    assert res_lead.json()["status"] == "in_progress"

    # Demote Yashvi back to member for time entry tests
    client.delete(
        f"/api/v1/projects/{project_id}/members/{emp_2.id}",
        headers=admin_headers
    )
    client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"employee_id": str(emp_2.id), "role": "member"},
        headers=admin_headers
    )

    # 4. Timesheet Logging Tests:
    # 4a. Yashvi tries to log time against Nik's task -> 403 Forbidden
    time_payload_forbidden = {
        "project_id": project_id,
        "task_id": task_id,
        "date": str(date.today()),
        "hours": 4.5,
        "description": "Attempting to log on Nik's task"
    }
    res_time_forbidden = client.post(
        "/api/v1/projects/time-entries",
        json=time_payload_forbidden,
        headers=headers_emp2
    )
    assert res_time_forbidden.status_code == 403
    assert "You cannot log time against a task assigned to another teammate" in res_time_forbidden.json()["error"]["message"]

    # 4b. Nik logs time against his own task -> Allowed and does not throw TypeError on employee_id
    time_payload_nik = {
        "project_id": project_id,
        "task_id": task_id,
        "date": str(date.today()),
        "hours": 3.0,
        "description": "Logged 3 hours on Nik's feature task"
    }
    res_time_nik = client.post(
        "/api/v1/projects/time-entries",
        json=time_payload_nik,
        headers=headers_emp1
    )
    assert res_time_nik.status_code == 201
    assert float(res_time_nik.json()["hours"]) == 3.0
    assert res_time_nik.json()["task_id"] == task_id
    assert res_time_nik.json()["employee_id"] == str(emp_1.id)

    # 4c. General time entry without task -> Allowed for any project member
    general_time_payload = {
        "project_id": project_id,
        "date": str(date.today()),
        "hours": 2.0,
        "description": "Weekly alignment and planning meeting"
    }
    res_time_general = client.post(
        "/api/v1/projects/time-entries",
        json=general_time_payload,
        headers=headers_emp2
    )
    assert res_time_general.status_code == 201
    assert float(res_time_general.json()["hours"]) == 2.0
    # 5. Project Documents Tests:
    # 5a. Upload via /files/upload and attach via JSON POST /{project_id}/documents
    f_res = client.post(
        "/api/v1/files/upload",
        files={"file": ("specs.pdf", b"%PDF-1.4 test content", "application/pdf")},
        headers=admin_headers
    )
    assert f_res.status_code == 201
    file_upload_data = f_res.json()
    file_object_id = file_upload_data["file_object_id"]

    # Test attaching with file_object_id alias
    doc_json_res = client.post(
        f"/api/v1/projects/{project_id}/documents",
        json={
            "file_object_id": file_object_id,
            "file_name": "Project Specifications.pdf",
            "file_size": file_upload_data["file_size"],
            "file_type": file_upload_data["file_type"],
            "description": "Initial architecture and specs"
        },
        headers=headers_emp1
    )
    assert doc_json_res.status_code == 201
    assert doc_json_res.json()["name"] == "Project Specifications.pdf"
    assert doc_json_res.json()["file_id"] == file_object_id
    assert "signature=" in doc_json_res.json()["download_url"]

    # 5b. Direct multipart upload to POST /{project_id}/documents
    doc_mp_res = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("wireframes.png", b"\x89PNG\r\n\x1a\n fake image content", "image/png")},
        data={"description": "Figma export wireframes"},
        headers=headers_emp2
    )
    assert doc_mp_res.status_code == 201
    assert doc_mp_res.json()["name"] == "wireframes.png"
    assert doc_mp_res.json()["description"] == "Figma export wireframes"
    assert "signature=" in doc_mp_res.json()["download_url"]

    # 5c. List documents includes both and includes signed download URLs
    doc_list_res = client.get(f"/api/v1/projects/{project_id}/documents", headers=headers_emp1)
    assert doc_list_res.status_code == 200
    docs = doc_list_res.json()
    assert len(docs) == 2
    assert all("signature=" in d["download_url"] for d in docs)

