"""Module 7 Batch 4: 7.6 Comments & Documents.
Tests verifying all 8 rules for 7.6:
Rule 1: Scoping permissions (members, PM, HR, owner; non-members 404; Super Admin 403).
Rule 2: Plain text 1-2000 chars, escaped on output, invalid input 422.
Rule 3: Delete: author or PM, HR, owner; soft-deleted, audited, hidden from list & download.
Rule 4: Edit comment: author only; is_edited=True.
Rule 5: Allowed file types and 10MB limit; downloads expire in 600s.
Rule 6: Completed or archived projects block comments/uploads with 409 Conflict.
Rule 7: Cross-company comment/document returns 404.
Rule 8: Audited and rate limited (60/min, 429 verified).
"""

import io
import uuid
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog
from app.modules.platform.service import SIGNED_URL_TTL_SECONDS
from app.modules.projects.models import ProjectDocument, TaskComment


def _auth_headers(user: User) -> dict[str, str]:
    user_id = user.__dict__.get("id") or user.id
    company_id = user.__dict__.get("company_id") or user.company_id
    role = user.__dict__.get("role") or user.role
    role_val = role.value if hasattr(role, "value") else str(role)
    token = create_access_token(
        sub=str(user_id),
        company_id=str(company_id) if company_id else None,
        role=role_val,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def p4_setup(db: Session) -> dict[str, Any]:
    db.expire_on_commit = False

    cid_a = uuid.uuid4()
    bind_tenant_to_session(db, company_id=cid_a, is_platform_admin=True)
    comp_a = Company(
        id=cid_a,
        name=f"CompA_{uuid.uuid4().hex[:6]}",
        code=f"CA{uuid.uuid4().hex[:6].upper()}",
        email=f"compa_{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
    )
    db.add(comp_a)
    db.flush()

    def make_user_and_emp(email_prefix: str, role: UserRole, company_id: uuid.UUID):
        u = User(
            id=uuid.uuid4(),
            company_id=company_id,
            email=f"{email_prefix}_{uuid.uuid4().hex[:4]}@example.com",
            hashed_password=hash_password("Pass1234!"),
            role=role,
            is_active=True,
        )
        db.add(u)
        db.flush()
        e = Employee(
            id=uuid.uuid4(),
            company_id=company_id,
            user_id=u.id,
            first_name=email_prefix.capitalize(),
            last_name="Test",
            email=u.email,
            employee_code=f"EMP-{uuid.uuid4().hex[:6].upper()}",
            hire_date=date(2025, 1, 1),
            employment_type=EmploymentType.full_time,
            invitation_status=InvitationStatus.activated,
            is_active=True,
        )
        db.add(e)
        db.flush()
        return u, e

    owner_u, owner_e = make_user_and_emp("owner", UserRole.owner, cid_a)
    hr_u, hr_e = make_user_and_emp("hr", UserRole.hr_admin, cid_a)
    pm_u, pm_e = make_user_and_emp("pm", UserRole.manager, cid_a)
    emp1_u, emp1_e = make_user_and_emp("emp1", UserRole.employee, cid_a)
    emp2_u, emp2_e = make_user_and_emp("emp2", UserRole.employee, cid_a)
    non_member_emp_u, non_member_emp_e = make_user_and_emp("non_member", UserRole.employee, cid_a)

    # Super Admin
    sa_cid = uuid.uuid4()
    sa_comp = Company(
        id=sa_cid,
        name=f"Plat_{uuid.uuid4().hex[:6]}",
        code=f"PL{uuid.uuid4().hex[:6].upper()}",
        email=f"plat_{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
    )
    db.add(sa_comp)
    db.flush()
    sa_u = User(
        id=uuid.uuid4(),
        company_id=sa_cid,
        email=f"sa_{uuid.uuid4().hex[:4]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.super_admin,
        is_active=True,
    )
    db.add(sa_u)
    db.flush()

    # Company B
    cid_b = uuid.uuid4()
    bind_tenant_to_session(db, company_id=cid_b, is_platform_admin=True)
    comp_b = Company(
        id=cid_b,
        name=f"CompB_{uuid.uuid4().hex[:6]}",
        code=f"CB{uuid.uuid4().hex[:6].upper()}",
        email=f"compb_{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
    )
    db.add(comp_b)
    db.flush()
    b_owner_u, b_owner_e = make_user_and_emp("b_owner", UserRole.owner, cid_b)
    b_emp_u, b_emp_e = make_user_and_emp("b_emp", UserRole.employee, cid_b)

    db.commit()

    return {
        "cid_a": cid_a,
        "cid_b": cid_b,
        "owner_u": owner_u,
        "owner_e": owner_e,
        "hr_u": hr_u,
        "hr_e": hr_e,
        "pm_u": pm_u,
        "pm_e": pm_e,
        "emp1_u": emp1_u,
        "emp1_e": emp1_e,
        "emp2_u": emp2_u,
        "emp2_e": emp2_e,
        "non_member_emp_u": non_member_emp_u,
        "non_member_emp_e": non_member_emp_e,
        "sa_u": sa_u,
        "b_owner_u": b_owner_u,
        "b_owner_e": b_owner_e,
        "b_emp_u": b_emp_u,
        "b_emp_e": b_emp_e,
    }


def _create_project_and_task(
    client: TestClient,
    headers_owner: dict[str, str],
    pm_id: uuid.UUID,
    emp1_id: uuid.UUID,
    status: str = "active",
) -> tuple[str, str]:
    # 1. Create project
    proj_res = client.post(
        "/api/v1/projects",
        json={
            "name": f"Doc Project {uuid.uuid4().hex[:4]}",
            "code": f"DP{uuid.uuid4().hex[:4].upper()}",
            "status": status,
            "manager_id": str(pm_id),
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        },
        headers=headers_owner,
    )
    assert proj_res.status_code == 201, proj_res.text
    project_id = proj_res.json()["id"]

    # 2. Add emp1 as project member
    mem_res = client.post(
        f"/api/v1/projects/{project_id}/members",
        json={
            "employee_id": str(emp1_id),
            "role": "member",
            "hourly_rate": "50.00",
            "effective_from": "2025-01-01",
        },
        headers=headers_owner,
    )
    assert mem_res.status_code == 201, mem_res.text

    # 3. Create a task
    task_res = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={
            "title": "Initial Task",
            "status": "todo",
        },
        headers=headers_owner,
    )
    assert task_res.status_code == 201, task_res.text
    task_id = task_res.json()["id"]

    return project_id, task_id


# ==============================================================================
# RULE 1: Only project members, PM, HR, and Owner comment or upload; others 404/403
# ==============================================================================


def test_rule_1_scoping_permissions(client: TestClient, p4_setup: dict[str, Any]):
    headers_owner = _auth_headers(p4_setup["owner_u"])
    headers_hr = _auth_headers(p4_setup["hr_u"])
    headers_pm = _auth_headers(p4_setup["pm_u"])
    headers_emp1 = _auth_headers(p4_setup["emp1_u"])
    headers_non_mem = _auth_headers(p4_setup["non_member_emp_u"])
    headers_sa = _auth_headers(p4_setup["sa_u"])

    project_id, task_id = _create_project_and_task(
        client,
        headers_owner,
        p4_setup["pm_e"].id,
        p4_setup["emp1_e"].id,
    )

    # Comments:
    # 1. Member can comment
    res_emp1 = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Emp1 comment"},
        headers=headers_emp1,
    )
    assert res_emp1.status_code == 201

    # 2. PM can comment
    res_pm = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "PM comment"},
        headers=headers_pm,
    )
    assert res_pm.status_code == 201

    # 3. HR can comment
    res_hr = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "HR comment"},
        headers=headers_hr,
    )
    assert res_hr.status_code == 201

    # 4. Owner can comment
    res_owner = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Owner comment"},
        headers=headers_owner,
    )
    assert res_owner.status_code == 201

    # 5. Non-member gets 404
    res_non_mem = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Non-member comment"},
        headers=headers_non_mem,
    )
    assert res_non_mem.status_code == 404

    # 6. Super Admin gets 403
    res_sa = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "SA comment"},
        headers=headers_sa,
    )
    assert res_sa.status_code == 403

    # Uploads:
    # 1. Non-member upload gets 404
    sample_pdf = b"%PDF-1.4 test dummy pdf content"
    res_upload_non_mem = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("test.pdf", io.BytesIO(sample_pdf), "application/pdf")},
        data={"description": "Non-member doc"},
        headers=headers_non_mem,
    )
    assert res_upload_non_mem.status_code == 404

    # 2. Super Admin upload gets 403
    res_upload_sa = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("test.pdf", io.BytesIO(sample_pdf), "application/pdf")},
        data={"description": "SA doc"},
        headers=headers_sa,
    )
    assert res_upload_sa.status_code == 403

    # 3. Member can upload
    res_upload_emp1 = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("test.pdf", io.BytesIO(sample_pdf), "application/pdf")},
        data={"description": "Emp1 doc"},
        headers=headers_emp1,
    )
    assert res_upload_emp1.status_code == 201


# ==============================================================================
# RULE 2: Comments are plain text 1–2000 chars, escaped on output; invalid input returns 422
# ==============================================================================


def test_rule_2_comment_validation_and_escaping(client: TestClient, p4_setup: dict[str, Any]):
    headers_emp1 = _auth_headers(p4_setup["emp1_u"])
    headers_owner = _auth_headers(p4_setup["owner_u"])

    _, task_id = _create_project_and_task(
        client,
        headers_owner,
        p4_setup["pm_e"].id,
        p4_setup["emp1_e"].id,
    )

    # Empty / whitespace comment returns 422
    res_empty = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "   "},
        headers=headers_emp1,
    )
    assert res_empty.status_code == 422

    # Comment over 2000 chars returns 422
    long_comment = "A" * 2001
    res_long = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": long_comment},
        headers=headers_emp1,
    )
    assert res_long.status_code == 422

    # HTML / script tag is escaped on output
    xss_payload = "<script>alert('xss')</script> & <b>bold</b>"
    res_xss = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": xss_payload},
        headers=headers_emp1,
    )
    assert res_xss.status_code == 201
    comment_data = res_xss.json()
    assert "<script>" not in comment_data["comment"]
    assert (
        "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;"
        in comment_data["comment"]
    )


# ==============================================================================
# RULE 3: Delete comment/doc: author, or PM, HR, Owner; soft-deleted; hidden
# ==============================================================================


def test_rule_3_soft_delete_comment_and_document(
    client: TestClient, p4_setup: dict[str, Any], db: Session
):
    headers_owner = _auth_headers(p4_setup["owner_u"])
    headers_pm = _auth_headers(p4_setup["pm_u"])
    headers_emp1 = _auth_headers(p4_setup["emp1_u"])
    headers_emp2 = _auth_headers(p4_setup["emp2_u"])

    project_id, task_id = _create_project_and_task(
        client,
        headers_owner,
        p4_setup["pm_e"].id,
        p4_setup["emp1_e"].id,
    )

    # Add emp2 as project member
    client.post(
        f"/api/v1/projects/{project_id}/members",
        json={
            "employee_id": str(p4_setup["emp2_e"].id),
            "role": "member",
            "hourly_rate": "40.00",
            "effective_from": "2025-01-01",
        },
        headers=headers_owner,
    )

    # Emp1 posts comment
    c_res = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Comment to delete"},
        headers=headers_emp1,
    )
    comment_id = c_res.json()["id"]

    # Emp2 tries to delete emp1's comment -> 403 Forbidden
    del_forbidden = client.delete(
        f"/api/v1/projects/tasks/{task_id}/comments/{comment_id}",
        headers=headers_emp2,
    )
    assert del_forbidden.status_code == 403

    # Emp1 deletes own comment -> 204 No Content
    del_ok = client.delete(
        f"/api/v1/projects/tasks/{task_id}/comments/{comment_id}",
        headers=headers_emp1,
    )
    assert del_ok.status_code == 204

    # Comment no longer listed
    list_c = client.get(
        f"/api/v1/projects/tasks/{task_id}/comments",
        headers=headers_emp1,
    )
    assert all(c["id"] != comment_id for c in list_c.json())

    # In DB, verify soft deleted
    tc_db = db.query(TaskComment).filter(TaskComment.id == comment_id).first()
    assert tc_db is not None
    assert tc_db.deleted_at is not None

    # Audit log recorded for comment deletion
    audit_c = (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == "task_comment",
            AuditLog.entity_id == comment_id,
            AuditLog.action == "delete_task_comment",
        )
        .first()
    )
    assert audit_c is not None

    # Test Document Soft Delete:
    sample_pdf = b"%PDF-1.4 test doc to delete"
    up_res = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("doc_del.pdf", io.BytesIO(sample_pdf), "application/pdf")},
        data={"description": "Doc to delete"},
        headers=headers_emp1,
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["id"]
    download_url = up_res.json()["download_url"]

    # Emp2 cannot delete emp1's doc -> 403
    del_doc_forb = client.delete(
        f"/api/v1/projects/{project_id}/documents/{doc_id}",
        headers=headers_emp2,
    )
    assert del_doc_forb.status_code == 403

    # PM can delete document -> 204
    del_doc_ok = client.delete(
        f"/api/v1/projects/{project_id}/documents/{doc_id}",
        headers=headers_pm,
    )
    assert del_doc_ok.status_code == 204

    # Document no longer in list
    docs_list = client.get(
        f"/api/v1/projects/{project_id}/documents",
        headers=headers_emp1,
    )
    assert all(d["id"] != doc_id for d in docs_list.json())

    # Direct download route returns 404
    dl_res = client.get(
        f"/api/v1/projects/{project_id}/documents/{doc_id}/download",
        headers=headers_emp1,
    )
    assert dl_res.status_code == 404

    # Signed URL download returns 404
    signed_dl_res = client.get(download_url, headers=headers_emp1)
    assert signed_dl_res.status_code == 404

    # DB verify soft deleted
    pdoc_db = db.query(ProjectDocument).filter(ProjectDocument.id == doc_id).first()
    assert pdoc_db is not None
    assert pdoc_db.deleted_at is not None


# ==============================================================================
# RULE 4: Edit comment: author only; marked is_edited = True
# ==============================================================================


def test_rule_4_edit_comment_author_only(client: TestClient, p4_setup: dict[str, Any]):
    headers_owner = _auth_headers(p4_setup["owner_u"])
    headers_pm = _auth_headers(p4_setup["pm_u"])
    headers_emp1 = _auth_headers(p4_setup["emp1_u"])

    _, task_id = _create_project_and_task(
        client,
        headers_owner,
        p4_setup["pm_e"].id,
        p4_setup["emp1_e"].id,
    )

    # Emp1 posts comment
    c_res = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Initial version"},
        headers=headers_emp1,
    )
    comment_id = c_res.json()["id"]
    assert c_res.json()["is_edited"] is False

    # PM tries to edit emp1's comment -> 403 Forbidden (even PM cannot edit other's comment)
    pm_edit = client.put(
        f"/api/v1/projects/tasks/{task_id}/comments/{comment_id}",
        json={"comment": "PM editing your comment"},
        headers=headers_pm,
    )
    assert pm_edit.status_code == 403

    # Owner tries to edit emp1's comment -> 403 Forbidden
    owner_edit = client.put(
        f"/api/v1/projects/tasks/{task_id}/comments/{comment_id}",
        json={"comment": "Owner editing your comment"},
        headers=headers_owner,
    )
    assert owner_edit.status_code == 403

    # Emp1 edits own comment -> 200 OK
    emp1_edit = client.put(
        f"/api/v1/projects/tasks/{task_id}/comments/{comment_id}",
        json={"comment": "Updated version <b>clean</b>"},
        headers=headers_emp1,
    )
    assert emp1_edit.status_code == 200
    updated_data = emp1_edit.json()
    assert updated_data["is_edited"] is True
    assert updated_data["updated_at"] is not None
    assert "&lt;b&gt;clean&lt;/b&gt;" in updated_data["comment"]


# ==============================================================================
# RULE 5: Documents use FileService (pdf, jpg, docx, etc.), 10MB limit, signed url TTL = 600s
# ==============================================================================


def test_rule_5_documents_types_size_limit_and_ttl(client: TestClient, p4_setup: dict[str, Any]):
    assert SIGNED_URL_TTL_SECONDS == 600

    headers_owner = _auth_headers(p4_setup["owner_u"])
    headers_emp1 = _auth_headers(p4_setup["emp1_u"])

    project_id, _ = _create_project_and_task(
        client,
        headers_owner,
        p4_setup["pm_e"].id,
        p4_setup["emp1_e"].id,
    )

    # 1. Invalid file extension (.exe) rejected
    bad_bytes = b"bad executable content"
    res_bad_ext = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("malicious.exe", io.BytesIO(bad_bytes), "application/octet-stream")},
        headers=headers_emp1,
    )
    assert res_bad_ext.status_code in (400, 422)

    # 2. File size exceeding 10MB limit rejected (413 Payload Too Large)
    big_pdf = b"%PDF-1.4 " + (b"0" * (10 * 1024 * 1024 + 50))
    res_big = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("large.pdf", io.BytesIO(big_pdf), "application/pdf")},
        headers=headers_emp1,
    )
    assert res_big.status_code == 413

    # 3. Valid PDF succeeds and returns signed URL expiring in 600s
    valid_pdf = b"%PDF-1.4 test project documentation content"
    res_ok = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("spec.pdf", io.BytesIO(valid_pdf), "application/pdf")},
        data={"description": "Project specification"},
        headers=headers_emp1,
    )
    assert res_ok.status_code == 201
    doc_data = res_ok.json()
    assert "download_url" in doc_data
    assert "expires=" in doc_data["download_url"]
    assert "signature=" in doc_data["download_url"]


# ==============================================================================
# RULE 6: Comments and uploads blocked on completed or archived projects (409 Conflict)
# ==============================================================================


def test_rule_6_project_lifecycle_lock(client: TestClient, p4_setup: dict[str, Any]):
    headers_owner = _auth_headers(p4_setup["owner_u"])
    headers_emp1 = _auth_headers(p4_setup["emp1_u"])

    project_id, task_id = _create_project_and_task(
        client,
        headers_owner,
        p4_setup["pm_e"].id,
        p4_setup["emp1_e"].id,
        status="active",
    )

    # Change project to completed
    client.put(
        f"/api/v1/projects/{project_id}",
        json={"status": "completed"},
        headers=headers_owner,
    )

    # 1. Comment on completed project -> 409 Conflict
    res_c_completed = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Trying to comment on completed project"},
        headers=headers_emp1,
    )
    assert res_c_completed.status_code == 409

    # 2. Upload on completed project -> 409 Conflict
    sample_pdf = b"%PDF-1.4 test dummy pdf"
    res_up_completed = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("test.pdf", io.BytesIO(sample_pdf), "application/pdf")},
        headers=headers_emp1,
    )
    assert res_up_completed.status_code == 409

    # Reopen to active, post a comment, then archive project
    client.put(
        f"/api/v1/projects/{project_id}",
        json={"status": "active"},
        headers=headers_owner,
    )
    c_res = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Active comment"},
        headers=headers_emp1,
    )
    comment_id = c_res.json()["id"]

    client.put(
        f"/api/v1/projects/{project_id}",
        json={"status": "archived"},
        headers=headers_owner,
    )

    # 3. Comment on archived project -> 409 Conflict
    res_c_archived = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Trying to comment on archived project"},
        headers=headers_emp1,
    )
    assert res_c_archived.status_code == 409

    # 4. Edit comment on archived project -> 409 Conflict
    res_edit_archived = client.put(
        f"/api/v1/projects/tasks/{task_id}/comments/{comment_id}",
        json={"comment": "Trying to edit on archived project"},
        headers=headers_emp1,
    )
    assert res_edit_archived.status_code == 409

    # 5. Delete comment on archived project -> 409 Conflict
    res_del_archived = client.delete(
        f"/api/v1/projects/tasks/{task_id}/comments/{comment_id}",
        headers=headers_emp1,
    )
    assert res_del_archived.status_code == 409


# ==============================================================================
# RULE 7: Another company's comment or document returns 404 Not Found
# ==============================================================================


def test_rule_7_cross_company_isolation(client: TestClient, p4_setup: dict[str, Any]):
    headers_owner = _auth_headers(p4_setup["owner_u"])
    headers_emp1 = _auth_headers(p4_setup["emp1_u"])
    headers_b_owner = _auth_headers(p4_setup["b_owner_u"])

    project_id, task_id = _create_project_and_task(
        client,
        headers_owner,
        p4_setup["pm_e"].id,
        p4_setup["emp1_e"].id,
    )

    c_res = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Company A comment"},
        headers=headers_emp1,
    )
    comment_id = c_res.json()["id"]

    sample_pdf = b"%PDF-1.4 test doc"
    up_res = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("doc.pdf", io.BytesIO(sample_pdf), "application/pdf")},
        headers=headers_emp1,
    )
    doc_id = up_res.json()["id"]

    # Company B tries to view comments -> 404
    b_view_c = client.get(
        f"/api/v1/projects/tasks/{task_id}/comments",
        headers=headers_b_owner,
    )
    assert b_view_c.status_code == 404

    # Company B tries to edit comment -> 404
    b_edit_c = client.put(
        f"/api/v1/projects/tasks/{task_id}/comments/{comment_id}",
        json={"comment": "Cross tenant edit"},
        headers=headers_b_owner,
    )
    assert b_edit_c.status_code == 404

    # Company B tries to delete comment -> 404
    b_del_c = client.delete(
        f"/api/v1/projects/tasks/{task_id}/comments/{comment_id}",
        headers=headers_b_owner,
    )
    assert b_del_c.status_code == 404

    # Company B tries to view documents -> 404
    b_view_docs = client.get(
        f"/api/v1/projects/{project_id}/documents",
        headers=headers_b_owner,
    )
    assert b_view_docs.status_code == 404

    # Company B tries to delete document -> 404
    b_del_doc = client.delete(
        f"/api/v1/projects/{project_id}/documents/{doc_id}",
        headers=headers_b_owner,
    )
    assert b_del_doc.status_code == 404

    # Company B tries to download document -> 404
    b_dl_doc = client.get(
        f"/api/v1/projects/{project_id}/documents/{doc_id}/download",
        headers=headers_b_owner,
    )
    assert b_dl_doc.status_code == 404


# ==============================================================================
# RULE 8: Auditing & Rate limiting (60/min)
# ==============================================================================


def test_rule_8_auditing_and_rate_limiting(
    client: TestClient, p4_setup: dict[str, Any], db: Session
):
    headers_owner = _auth_headers(p4_setup["owner_u"])
    headers_emp1 = _auth_headers(p4_setup["emp1_u"])

    project_id, task_id = _create_project_and_task(
        client,
        headers_owner,
        p4_setup["pm_e"].id,
        p4_setup["emp1_e"].id,
    )

    # 1. Audit log verification on comment create, edit, delete
    c_res = client.post(
        f"/api/v1/projects/tasks/{task_id}/comments",
        json={"comment": "Audit test comment"},
        headers=headers_emp1,
    )
    comment_id = c_res.json()["id"]

    audit_create = (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == "task_comment",
            AuditLog.entity_id == comment_id,
            AuditLog.action == "create_task_comment",
        )
        .first()
    )
    assert audit_create is not None

    client.put(
        f"/api/v1/projects/tasks/{task_id}/comments/{comment_id}",
        json={"comment": "Audit test updated"},
        headers=headers_emp1,
    )
    audit_update = (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == "task_comment",
            AuditLog.entity_id == comment_id,
            AuditLog.action == "update_task_comment",
        )
        .first()
    )
    assert audit_update is not None

    # 2. Rate limiting verification (60/minute)
    orig_enabled = limiter.enabled
    try:
        limiter.enabled = True
        got_429 = False
        for i in range(65):
            res = client.post(
                f"/api/v1/projects/tasks/{task_id}/comments",
                json={"comment": f"Spam test {i}"},
                headers=headers_emp1,
            )
            if res.status_code == 429:
                got_429 = True
                break
        assert got_429, "Expected 429 Too Many Requests when exceeding 60/min limit"
    finally:
        limiter.enabled = orig_enabled
