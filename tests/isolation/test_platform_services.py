import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.identity.models import User, UserRole
from tests.conftest import TenantContext

def _create_user_and_headers(db: Session, company_id: uuid.UUID) -> tuple[User, dict[str, str]]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"iso-plat-{uuid.uuid4().hex[:6]}@example.test",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.super_admin,
        is_active=True,
    )
    db.add(user)
    db.commit()

    token = create_access_token(
        sub=str(user.id), company_id=str(company_id), role=UserRole.super_admin.value
    )
    return user, {"Authorization": f"Bearer {token}"}

def test_platform_services_tenant_isolation(client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext):
    user_a, headers_a = _create_user_and_headers(db, company_a.company_id)
    user_b, headers_b = _create_user_and_headers(db, company_b.company_id)

    # 1. Tenant A creates Announcement
    res_ann_a = client.post(
        "/api/v1/announcements",
        json={"title": "Tenant A Exclusive Announcement", "content": "Private notice"},
        headers=headers_a
    )
    assert res_ann_a.status_code == 201
    ann_id_a = res_ann_a.json()["id"]

    # Tenant B lists announcements -> should NOT see Tenant A's announcement
    res_ann_b = client.get("/api/v1/announcements", headers=headers_b)
    assert res_ann_b.status_code == 200
    b_ids = [a["id"] for a in res_ann_b.json()]
    assert ann_id_a not in b_ids

    # 2. Tenant A uploads File
    files = {"file": ("secret_a.txt", b"Secret data tenant A", "text/plain")}
    res_up_a = client.post("/api/v1/files/upload", files=files, headers=headers_a)
    assert res_up_a.status_code == 201
    file_id_a = res_up_a.json()["file_object_id"]

    # Tenant B tries to generate signed URL for Tenant A's file -> should fail 404
    res_url_b = client.get(f"/api/v1/files/{file_id_a}/url", headers=headers_b)
    assert res_url_b.status_code == 404
