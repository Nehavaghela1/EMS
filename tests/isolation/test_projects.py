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
        role=UserRole.super_admin,
        is_active=True,
    )
    db.add(user)
    db.commit()

    token = create_access_token(
        sub=str(user.id), company_id=str(company_id), role=UserRole.super_admin.value
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
