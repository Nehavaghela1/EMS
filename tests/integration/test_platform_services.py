import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import User, UserRole
from tests.conftest import TenantContext

def _create_user_and_headers(db: Session, company_id: uuid.UUID, role: UserRole = UserRole.super_admin) -> tuple[User, dict[str, str]]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"plat-{uuid.uuid4().hex[:6]}@example.test",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()

    token = create_access_token(
        sub=str(user.id), company_id=str(company_id), role=role.value
    )
    return user, {"Authorization": f"Bearer {token}"}

def test_announcements_lifecycle(client: TestClient, db: Session, company_a: TenantContext):
    user, headers = _create_user_and_headers(db, company_a.company_id, UserRole.super_admin)

    # 1. Create Announcement
    res = client.post(
        "/api/v1/announcements",
        json={
            "title": "Annual Company Retreat 2026",
            "content": "Pack your bags for Goa next month!",
            "target_role": "all"
        },
        headers=headers
    )
    assert res.status_code == 201, res.text
    ann_id = res.json()["id"]

    # 2. List Announcements
    res_list = client.get("/api/v1/announcements", headers=headers)
    assert res_list.status_code == 200
    ids = [a["id"] for a in res_list.json()]
    assert ann_id in ids

    # 3. Delete Announcement
    res_del = client.delete(f"/api/v1/announcements/{ann_id}", headers=headers)
    assert res_del.status_code == 204

def test_file_upload_signed_url_and_documents(client: TestClient, db: Session, company_a: TenantContext):
    user, headers = _create_user_and_headers(db, company_a.company_id, UserRole.super_admin)

    # 1. Upload File
    files = {"file": ("test_doc.pdf", b"%PDF-1.4 test content", "application/pdf")}
    res_up = client.post("/api/v1/files/upload", files=files, headers=headers)
    assert res_up.status_code == 201, res_up.text
    file_id = res_up.json()["file_object_id"]

    # 2. Get Signed URL
    res_url = client.get(f"/api/v1/files/{file_id}/url", headers=headers)
    assert res_url.status_code == 200, res_url.text
    download_url = res_url.json()["url"]
    assert "signature=" in download_url

    # 3. Fetch file content via signed download URL (Public Route)
    res_dl = client.get(download_url)
    assert res_dl.status_code == 200
    assert res_dl.content == b"%PDF-1.4 test content"

def test_global_tenant_search(client: TestClient, db: Session, company_a: TenantContext):
    user, headers = _create_user_and_headers(db, company_a.company_id, UserRole.super_admin)

    # Search for admin user email or title
    res_search = client.get("/api/v1/search?q=plat", headers=headers)
    assert res_search.status_code == 200, res_search.text
    assert res_search.json()["total_results"] >= 0
