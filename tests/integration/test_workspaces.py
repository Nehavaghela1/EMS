from sqlalchemy.orm import Session
from sqlalchemy import select

from app.modules.identity.models import Company, User, UserRole
from tests.conftest import TenantContext


def test_create_workspace_and_switch(
    client,
    db: Session,
    company_a: TenantContext,
):
    # 1. Create a new workspace using the active HR admin
    payload = {
        "company_name": "Test Workspace Inc",
        "seed_departments": True,
        "seed_shift": True
    }
    
    response = client.post(
        "/api/v1/companies/workspaces",
        json=payload,
        headers=company_a.hr_headers
    )
    assert response.status_code == 201
    data = response.json()
    new_company_id = data["company"]["id"]
    new_access_token = data["access_token"]
    
    # 2. Verify seeded records (departments, shifts) via DB
    # We must bind to the new tenant to check
    from app.db.rls import bind_tenant_to_session
    bind_tenant_to_session(db, company_id=new_company_id, is_platform_admin=True)
    
    from app.modules.hr.models import Department
    from app.modules.time_leave.models import Shift
    
    departments = db.scalars(select(Department).where(Department.company_id == new_company_id)).all()
    assert len(departments) == 4
    
    shifts = db.scalars(select(Shift).where(Shift.company_id == new_company_id)).all()
    assert len(shifts) == 1
    
    # 3. Verify tenant isolation: employees should be 0 in the new company
    from app.modules.hr.models import Employee
    employees = db.scalars(select(Employee).where(Employee.company_id == new_company_id)).all()
    assert len(employees) == 0
    
    # 4. Verify user workspaces endpoint
    list_response = client.get(
        "/api/v1/auth/workspaces",
        headers=company_a.hr_headers
    )
    assert list_response.status_code == 200
    workspaces = list_response.json()
    assert len(workspaces) >= 2 # Original one + the new one
    assert any(w["id"] == new_company_id for w in workspaces)
    
    # 5. Verify workspace switching
    switch_response = client.post(
        "/api/v1/auth/switch-workspace",
        json={"company_id": new_company_id},
        headers=company_a.hr_headers
    )
    assert switch_response.status_code == 200
    switch_data = switch_response.json()
    assert "access_token" in switch_data
    
    # Verify the new token gives access to the new workspace's data
    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {switch_data['access_token']}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["company_id"] == new_company_id
