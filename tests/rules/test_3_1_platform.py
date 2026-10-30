import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Department, Employee
from app.modules.identity.models import User, UserRole
from app.modules.platform.models import Announcement, AuditLog, Notification
from app.modules.platform.service import NotificationService
from app.modules.projects.models import Project, ProjectMember, Task
from tests.conftest import TenantContext


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        sub=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


def _create_user_with_employee(
    db: Session,
    company_id: uuid.UUID,
    role: UserRole,
    *,
    first_name: str = "Test",
    last_name: str = "User",
    email: str | None = None,
    code: str | None = None,
    department: Department | None = None,
    manager_employee_id: uuid.UUID | None = None,
    is_active: bool = True,
) -> tuple[User, Employee]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    suffix = uuid.uuid4().hex[:8]
    user_email = email or f"{role.value}-{suffix}@example.com"
    emp_code = code or f"EMP-{suffix}"

    user = User(
        company_id=company_id,
        email=user_email,
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.flush()

    emp = Employee(
        company_id=company_id,
        user_id=user.id,
        first_name=first_name,
        last_name=last_name,
        email=user_email,
        employee_code=emp_code,
        department_id=department.id if department else None,
        reporting_manager_id=manager_employee_id,
        hire_date=date(2024, 1, 1),
        is_active=is_active,
    )
    db.add(emp)
    db.flush()
    return user, emp


def _create_department(
    db: Session, company_id: uuid.UUID, name: str, head_emp_id: uuid.UUID | None = None
) -> Department:
    dept = Department(
        company_id=company_id,
        name=name,
        head_employee_id=head_emp_id,
    )
    db.add(dept)
    db.flush()
    return dept


# ══════════════════════════════════════════════════════════════════
# Contract 3.1: Announcements (N1 - N7)
# ══════════════════════════════════════════════════════════════════


def test_n1_company_wide_posts_roles(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """N1: Company-wide posts only by HR-level (super_admin, hr_admin, owner).
    Manager posting company-wide gets 403. Employee gets 403.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    dept = _create_department(db, company_a.company_id, f"Eng-{uuid.uuid4().hex[:6]}")
    mgr_user, mgr_emp = _create_user_with_employee(
        db, company_a.company_id, UserRole.manager, department=dept
    )
    emp_user, emp_emp = _create_user_with_employee(
        db, company_a.company_id, UserRole.employee, department=dept
    )
    hr_user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)
    db.commit()

    future_exp = (datetime.now(UTC) + timedelta(days=5)).isoformat()

    # HR admin can post company-wide
    r_hr = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(hr_user),
        json={
            "title": "HR Company All",
            "content": "Company wide message",
            "target_role": "all",
            "expires_at": future_exp,
        },
    )
    assert r_hr.status_code == 201, r_hr.text
    assert r_hr.json()["title"] == "HR Company All"

    # Manager posting company-wide (no department_id) -> 403
    r_mgr = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(mgr_user),
        json={
            "title": "Mgr Company All",
            "content": "Mgr trying company wide",
            "target_role": "all",
            "expires_at": future_exp,
        },
    )
    assert r_mgr.status_code == 403, r_mgr.text

    # Employee posting -> 403
    r_emp = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(emp_user),
        json={
            "title": "Emp Post",
            "content": "Employee trying to post",
            "target_role": "all",
            "expires_at": future_exp,
        },
    )
    assert r_emp.status_code == 403, r_emp.text


def test_n1_manager_posting_department_scoping(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """N1: Manager posts only to own department (member of, or head of).
    Posting to another department gives 403.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    dept_own = _create_department(db, company_a.company_id, f"Own-{uuid.uuid4().hex[:6]}")
    dept_other = _create_department(db, company_a.company_id, f"Other-{uuid.uuid4().hex[:6]}")
    dept_head = _create_department(db, company_a.company_id, f"Head-{uuid.uuid4().hex[:6]}")

    mgr_user, mgr_emp = _create_user_with_employee(
        db, company_a.company_id, UserRole.manager, department=dept_own
    )
    dept_head.head_employee_id = mgr_emp.id
    db.commit()

    future_exp = (datetime.now(UTC) + timedelta(days=5)).isoformat()

    # 1. Manager posts to own department -> 201
    r_own = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(mgr_user),
        json={
            "title": "Dept Own Post",
            "content": "Hello own department",
            "target_role": "all",
            "department_id": str(dept_own.id),
            "expires_at": future_exp,
        },
    )
    assert r_own.status_code == 201, r_own.text
    assert r_own.json()["department_id"] == str(dept_own.id)

    # 2. Manager posts to head department -> 201
    r_head = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(mgr_user),
        json={
            "title": "Dept Head Post",
            "content": "Hello head department",
            "target_role": "all",
            "department_id": str(dept_head.id),
            "expires_at": future_exp,
        },
    )
    assert r_head.status_code == 201, r_head.text

    # 3. Manager posts to other department -> 403
    r_other = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(mgr_user),
        json={
            "title": "Dept Other Post",
            "content": "Hello other department",
            "target_role": "all",
            "department_id": str(dept_other.id),
            "expires_at": future_exp,
        },
    )
    assert r_other.status_code == 403, r_other.text


def test_n2_audience_visibility_scoping(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """N2: Department post reaches only people in that department.
    Role post reaches only exact matching role.
    HR-level sees all active posts of company.
    User without department sees company-wide and role posts only.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    dept_a = _create_department(db, company_a.company_id, f"A-{uuid.uuid4().hex[:6]}")
    dept_b = _create_department(db, company_a.company_id, f"B-{uuid.uuid4().hex[:6]}")

    hr_user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)
    emp_a, _ = _create_user_with_employee(
        db, company_a.company_id, UserRole.employee, department=dept_a
    )
    emp_b, _ = _create_user_with_employee(
        db, company_a.company_id, UserRole.employee, department=dept_b
    )
    emp_nodept, _ = _create_user_with_employee(
        db, company_a.company_id, UserRole.employee, department=None
    )
    mgr_a, _ = _create_user_with_employee(
        db, company_a.company_id, UserRole.manager, department=dept_a
    )
    db.commit()

    future_exp = (datetime.now(UTC) + timedelta(days=5)).isoformat()

    # Create 4 announcements:
    # 1. Company-wide all
    r1 = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(hr_user),
        json={
            "title": "All Co",
            "content": "Company wide",
            "target_role": "all",
            "expires_at": future_exp,
        },
    )
    assert r1.status_code == 201
    id1 = r1.json()["id"]

    # 2. Dept A post
    r2 = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(hr_user),
        json={
            "title": "Dept A Only",
            "content": "For dept A",
            "target_role": "all",
            "department_id": str(dept_a.id),
            "expires_at": future_exp,
        },
    )
    assert r2.status_code == 201
    id2 = r2.json()["id"]

    # 3. Dept B post
    r3 = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(hr_user),
        json={
            "title": "Dept B Only",
            "content": "For dept B",
            "target_role": "all",
            "department_id": str(dept_b.id),
            "expires_at": future_exp,
        },
    )
    assert r3.status_code == 201
    id3 = r3.json()["id"]

    # 4. Role employee post (no department)
    r4 = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(hr_user),
        json={
            "title": "Role Employee Only",
            "content": "Only for employee role",
            "target_role": "employee",
            "expires_at": future_exp,
        },
    )
    assert r4.status_code == 201
    id4 = r4.json()["id"]

    # Check HR: sees all 4
    hr_list = client.get("/api/v1/announcements", headers=_auth_headers(hr_user)).json()
    hr_ids = {a["id"] for a in hr_list}
    assert {id1, id2, id3, id4}.issubset(hr_ids)

    # Check Emp A (in Dept A): sees 1 (All), 2 (Dept A), 4 (Role Emp); NOT 3 (Dept B)
    emp_a_list = client.get("/api/v1/announcements", headers=_auth_headers(emp_a)).json()
    emp_a_ids = {a["id"] for a in emp_a_list}
    assert id1 in emp_a_ids
    assert id2 in emp_a_ids
    assert id4 in emp_a_ids
    assert id3 not in emp_a_ids  # Dept B post must not reach Emp A

    # Check Emp B (in Dept B): sees 1, 3, 4; NOT 2
    emp_b_list = client.get("/api/v1/announcements", headers=_auth_headers(emp_b)).json()
    emp_b_ids = {a["id"] for a in emp_b_list}
    assert id1 in emp_b_ids
    assert id3 in emp_b_ids
    assert id4 in emp_b_ids
    assert id2 not in emp_b_ids  # Dept A post must not reach Emp B

    # Check Emp without dept: sees 1 and 4; NOT 2 or 3
    nodept_list = client.get("/api/v1/announcements", headers=_auth_headers(emp_nodept)).json()
    nodept_ids = {a["id"] for a in nodept_list}
    assert id1 in nodept_ids
    assert id4 in nodept_ids
    assert id2 not in nodept_ids
    assert id3 not in nodept_ids

    # Check Mgr A (role manager): sees 1 (all) and 2 (Dept A); NOT 4 (employee only)
    mgr_a_list = client.get("/api/v1/announcements", headers=_auth_headers(mgr_a)).json()
    mgr_a_ids = {a["id"] for a in mgr_a_list}
    assert id1 in mgr_a_ids
    assert id2 in mgr_a_ids
    assert id4 not in mgr_a_ids  # role employee post does not reach manager


def test_n2_deleted_department_announcement_hidden(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """N2: Announcements targeting a department must be hidden from members once
    that department is soft-deleted. HR-level users still see them in active company posts.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    dept = _create_department(db, company_a.company_id, f"DelDept-{uuid.uuid4().hex[:6]}")
    hr_user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)
    emp, _ = _create_user_with_employee(
        db, company_a.company_id, UserRole.employee, department=dept
    )
    db.commit()

    future_exp = (datetime.now(UTC) + timedelta(days=5)).isoformat()

    r = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(hr_user),
        json={
            "title": "Dept Announcement",
            "content": "Secret dept notes",
            "target_role": "all",
            "department_id": str(dept.id),
            "expires_at": future_exp,
        },
    )
    assert r.status_code == 201
    ann_id = r.json()["id"]

    # Member sees it initially
    emp_list = client.get("/api/v1/announcements", headers=_auth_headers(emp)).json()
    assert any(a["id"] == ann_id for a in emp_list)

    # Soft-delete the department
    dept.deleted_at = datetime.now(UTC)
    db.commit()

    # Member should NO LONGER see the announcement
    emp_list_after = client.get("/api/v1/announcements", headers=_auth_headers(emp)).json()
    assert not any(a["id"] == ann_id for a in emp_list_after), (
        "Announcement for soft-deleted department must be hidden from member"
    )

    # HR admin STILL sees it
    hr_list_after = client.get("/api/v1/announcements", headers=_auth_headers(hr_user)).json()
    assert any(a["id"] == ann_id for a in hr_list_after), "HR admin must still see announcement"


def test_n3_expiry_and_soft_delete_hidden(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """N3: Expired and soft-deleted announcements never appear in list.
    Newest first, at most 100.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    hr_user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)

    # 1. Active announcement
    ann_active = Announcement(
        company_id=company_a.company_id,
        created_by=hr_user.id,
        title="Active Post",
        content="Still valid",
        target_role="all",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    # 2. Expired announcement
    ann_expired = Announcement(
        company_id=company_a.company_id,
        created_by=hr_user.id,
        title="Expired Post",
        content="Already expired",
        target_role="all",
        expires_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    # 3. Soft-deleted announcement
    ann_deleted = Announcement(
        company_id=company_a.company_id,
        created_by=hr_user.id,
        title="Deleted Post",
        content="Already deleted",
        target_role="all",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        deleted_at=datetime.now(UTC),
    )
    db.add_all([ann_active, ann_expired, ann_deleted])
    db.commit()

    res = client.get("/api/v1/announcements", headers=_auth_headers(hr_user))
    assert res.status_code == 200
    ids = [a["id"] for a in res.json()]
    assert str(ann_active.id) in ids
    assert str(ann_expired.id) not in ids
    assert str(ann_deleted.id) not in ids


def test_n4_validation_rules(client: TestClient, db: Session, company_a: TenantContext) -> None:
    """N4: Title 1-255 trimmed; content 1-5000 trimmed plain text (no control chars);
    expires_at future timezone-aware; department must exist and be active;
    unknown fields 422; department post needs target_role 'all'.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    hr_user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)
    dept = _create_department(db, company_a.company_id, f"V-{uuid.uuid4().hex[:6]}")
    db.commit()

    headers = _auth_headers(hr_user)
    future_iso = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    # 1. Blank/whitespace title -> 422
    r_bt = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={"title": "   ", "content": "Valid content", "expires_at": future_iso},
    )
    assert r_bt.status_code == 422

    # 2. Empty/whitespace content -> 422
    r_bc = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={"title": "Valid title", "content": "   ", "expires_at": future_iso},
    )
    assert r_bc.status_code == 422

    # 3. Content > 5000 chars -> 422
    r_big = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={"title": "Valid title", "content": "x" * 5001, "expires_at": future_iso},
    )
    assert r_big.status_code == 422

    # 4. Content with control characters (bell \x07) -> 422
    r_ctrl = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={"title": "Valid title", "content": "Bad\x07char", "expires_at": future_iso},
    )
    assert r_ctrl.status_code == 422

    # 5. Content with valid newline and tab -> 201
    r_nl = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={
            "title": "Valid title",
            "content": "Line 1\nLine 2\tTabbed",
            "expires_at": future_iso,
        },
    )
    assert r_nl.status_code == 201

    # 6. Past expires_at -> 422
    past_iso = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    r_past = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={"title": "Valid title", "content": "Content", "expires_at": past_iso},
    )
    assert r_past.status_code == 422

    # 7. Naive expires_at (no tz) -> 422
    r_naive = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={"title": "Valid title", "content": "Content", "expires_at": "2030-01-01T12:00:00"},
    )
    assert r_naive.status_code == 422

    # 8. Non-existent department -> 404
    r_no_dept = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={
            "title": "Valid title",
            "content": "Content",
            "department_id": str(uuid.uuid4()),
            "expires_at": future_iso,
        },
    )
    assert r_no_dept.status_code == 404

    # 9. Unknown field -> 422
    r_extra = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={
            "title": "Valid title",
            "content": "Content",
            "unknown_field": "injected",
            "expires_at": future_iso,
        },
    )
    assert r_extra.status_code == 422

    # 10. Department post with target_role != "all" -> 422
    r_dept_role = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={
            "title": "Valid title",
            "content": "Content",
            "department_id": str(dept.id),
            "target_role": "employee",
            "expires_at": future_iso,
        },
    )
    assert r_dept_role.status_code == 422


def test_n5_delete_permissions(client: TestClient, db: Session, company_a: TenantContext) -> None:
    """N5: The poster deletes their own post. HR-level deletes any post.
    A manager who is not the poster gets 404.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    dept = _create_department(db, company_a.company_id, f"D-{uuid.uuid4().hex[:6]}")
    mgr1, _ = _create_user_with_employee(
        db, company_a.company_id, UserRole.manager, department=dept
    )
    mgr2, _ = _create_user_with_employee(
        db, company_a.company_id, UserRole.manager, department=dept
    )
    hr_user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)
    db.commit()

    future_iso = (datetime.now(UTC) + timedelta(days=2)).isoformat()

    # Mgr1 creates post
    r1 = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(mgr1),
        json={
            "title": "Mgr1 Post",
            "content": "Content 1",
            "department_id": str(dept.id),
            "target_role": "all",
            "expires_at": future_iso,
        },
    )
    assert r1.status_code == 201
    ann1_id = r1.json()["id"]

    # Mgr2 tries to delete Mgr1's post -> 404 (not 403, do not leak)
    r_del_mgr2 = client.delete(f"/api/v1/announcements/{ann1_id}", headers=_auth_headers(mgr2))
    assert r_del_mgr2.status_code == 404

    # Mgr1 deletes their own post -> 204
    r_del_mgr1 = client.delete(f"/api/v1/announcements/{ann1_id}", headers=_auth_headers(mgr1))
    assert r_del_mgr1.status_code == 204

    # HR creates post, HR deletes it -> 204
    r2 = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(hr_user),
        json={"title": "HR Post", "content": "Content 2", "expires_at": future_iso},
    )
    assert r2.status_code == 201
    ann2_id = r2.json()["id"]

    r_del_hr = client.delete(f"/api/v1/announcements/{ann2_id}", headers=_auth_headers(hr_user))
    assert r_del_hr.status_code == 204


def test_n6_cross_company_isolation(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
) -> None:
    """N6: Company B never sees or touches Company A's announcement (404)."""
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    hr_a, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)
    hr_b, _ = _create_user_with_employee(db, company_b.company_id, UserRole.hr_admin)
    db.commit()

    future_iso = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    r_create = client.post(
        "/api/v1/announcements",
        headers=_auth_headers(hr_a),
        json={"title": "Co A Post", "content": "Content A", "expires_at": future_iso},
    )
    assert r_create.status_code == 201
    ann_id = r_create.json()["id"]

    # Co B lists announcements -> does not see ann_id
    r_b_list = client.get("/api/v1/announcements", headers=_auth_headers(hr_b))
    assert r_b_list.status_code == 200
    assert ann_id not in [a["id"] for a in r_b_list.json()]

    # Co B tries to delete Co A's post -> 404
    r_b_del = client.delete(f"/api/v1/announcements/{ann_id}", headers=_auth_headers(hr_b))
    assert r_b_del.status_code == 404


def test_n7_audit_logging_and_rate_limits(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """N7: Audit rows ANNOUNCEMENT_CREATED and ANNOUNCEMENT_DELETED in same commit.
    No title or text in audit details!
    Rate limits: create 10/min (11th gives 429), delete 30/min (31st gives 429),
    list 60/min (61st gives 429).
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    hr_user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)
    dept = _create_department(db, company_a.company_id, f"Aud-{uuid.uuid4().hex[:6]}")
    db.commit()

    headers = _auth_headers(hr_user)
    future_iso = (datetime.now(UTC) + timedelta(days=2)).isoformat()

    # 1. Create announcement and verify audit
    r_create = client.post(
        "/api/v1/announcements",
        headers=headers,
        json={
            "title": "Secret Audit Title",
            "content": "Secret Content",
            "department_id": str(dept.id),
            "target_role": "all",
            "expires_at": future_iso,
        },
    )
    assert r_create.status_code == 201
    ann_id = r_create.json()["id"]

    audit_create = db.scalar(
        select(AuditLog).where(
            AuditLog.company_id == company_a.company_id,
            AuditLog.action == "ANNOUNCEMENT_CREATED",
            AuditLog.entity_id == uuid.UUID(ann_id),
        )
    )
    assert audit_create is not None
    assert audit_create.details is not None
    assert audit_create.details.get("announcement_id") == ann_id
    assert audit_create.details.get("audience_kind") == "department"
    assert audit_create.details.get("department_id") == str(dept.id)
    # Crucial: no title or content leaked into audit log!
    assert "Secret Audit Title" not in str(audit_create.details)
    assert "Secret Content" not in str(audit_create.details)
    assert "title" not in audit_create.details
    assert "content" not in audit_create.details

    # 2. Delete announcement and verify audit
    r_del = client.delete(f"/api/v1/announcements/{ann_id}", headers=headers)
    assert r_del.status_code == 204

    audit_del = db.scalar(
        select(AuditLog).where(
            AuditLog.company_id == company_a.company_id,
            AuditLog.action == "ANNOUNCEMENT_DELETED",
            AuditLog.entity_id == uuid.UUID(ann_id),
        )
    )
    assert audit_del is not None
    assert audit_del.details.get("announcement_id") == ann_id

    # 3. Rate limits
    # (a) POST create: 10/min -> 11th gives 429
    limiter.enabled = True
    try:
        limiter.reset()
        post_statuses = []
        for i in range(11):
            r = client.post(
                "/api/v1/announcements",
                headers=headers,
                json={
                    "title": f"Rate {i}",
                    "content": "Rate limit check",
                    "expires_at": future_iso,
                },
            )
            post_statuses.append(r.status_code)
        assert all(s == 201 for s in post_statuses[:10])
        assert post_statuses[10] == 429
    finally:
        limiter.reset()
        limiter.enabled = False

    # (b) DELETE: 30/min -> 31st gives 429
    # Create 31 announcements directly
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    del_ids = []
    for i in range(31):
        a = Announcement(
            company_id=company_a.company_id,
            created_by=hr_user.id,
            title=f"Del {i}",
            content="Del content",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(a)
        db.flush()
        del_ids.append(str(a.id))
    db.commit()

    limiter.enabled = True
    try:
        limiter.reset()
        del_statuses = []
        for aid in del_ids:
            r = client.delete(f"/api/v1/announcements/{aid}", headers=headers)
            del_statuses.append(r.status_code)
        assert all(s == 204 for s in del_statuses[:30])
        assert del_statuses[30] == 429
    finally:
        limiter.reset()
        limiter.enabled = False

    # (c) GET list: 60/min -> 61st gives 429
    limiter.enabled = True
    try:
        limiter.reset()
        list_statuses = []
        for _ in range(61):
            r = client.get("/api/v1/announcements", headers=headers)
            list_statuses.append(r.status_code)
        assert all(s == 200 for s in list_statuses[:60])
        assert list_statuses[60] == 429
    finally:
        limiter.reset()
        limiter.enabled = False


# ══════════════════════════════════════════════════════════════════
# Contract 3.2: Notifications (T1 - T7)
# ══════════════════════════════════════════════════════════════════


def test_t1_user_notifications_scoping(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
) -> None:
    """T1: A user lists, reads and marks only their own notifications.
    Another user's id gives 404 (same as missing). Cross company gives 404.
    Deactivated user cannot read any.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    u1, _ = _create_user_with_employee(db, company_a.company_id, UserRole.employee)
    u2, _ = _create_user_with_employee(db, company_a.company_id, UserRole.employee)

    # Create notification for u1 while in company_a
    notif1 = Notification(
        company_id=company_a.company_id,
        user_id=u1.id,
        type="test_alert",
        title="Notice 1",
        message="Hello U1",
        is_read=False,
    )
    db.add(notif1)
    db.commit()
    notif1_id = notif1.id

    bind_tenant_to_session(db, company_id=company_b.company_id, is_platform_admin=False)
    u_b, _ = _create_user_with_employee(db, company_b.company_id, UserRole.employee)
    db.commit()

    # U1 marks own notification -> 200
    r_own = client.put(f"/api/v1/notifications/{notif1_id}/read", headers=_auth_headers(u1))
    assert r_own.status_code == 200
    assert r_own.json()["is_read"] is True

    # U2 tries to mark U1's notification -> 404
    r_u2 = client.put(f"/api/v1/notifications/{notif1_id}/read", headers=_auth_headers(u2))
    assert r_u2.status_code == 404

    # Co B tries to mark U1's notification -> 404
    r_b = client.put(f"/api/v1/notifications/{notif1_id}/read", headers=_auth_headers(u_b))
    assert r_b.status_code == 404

    # Deactivated user reading notifications -> 401/403
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    u1.is_active = False
    db.commit()
    r_deact = client.get("/api/v1/notifications", headers=_auth_headers(u1))
    assert r_deact.status_code in (401, 403)


def test_t2_notifications_paging_and_unread_count(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """T2: Newest first, paged (page 1+, limit 1-100 else 422), unread-only filter,
    unread count in reply.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.employee)
    headers = _auth_headers(user)

    for i in range(5):
        n = Notification(
            company_id=company_a.company_id,
            user_id=user.id,
            type="msg",
            title=f"Notif {i}",
            message=f"Msg {i}",
            is_read=(i == 0),  # 1 read, 4 unread
            read_at=datetime.now(UTC) if i == 0 else None,
        )
        db.add(n)
    db.commit()

    # Normal list
    r_all = client.get("/api/v1/notifications", headers=headers)
    assert r_all.status_code == 200
    data = r_all.json()
    assert data["total"] == 5
    assert data["unread_count"] == 4

    # Unread-only filter
    r_unread = client.get("/api/v1/notifications?unread_only=true", headers=headers)
    assert r_unread.status_code == 200
    assert len(r_unread.json()["items"]) == 4

    # Paging validation: page < 1 -> 422
    assert client.get("/api/v1/notifications?page=0", headers=headers).status_code == 422
    # limit < 1 -> 422
    assert client.get("/api/v1/notifications?limit=0", headers=headers).status_code == 422
    # limit > 100 -> 422
    assert client.get("/api/v1/notifications?limit=101", headers=headers).status_code == 422


def test_t3_mark_read_repeat_idempotent_and_mark_all(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """T3: Mark one read sets read_at once; repeating does not overwrite read_at.
    Mark all read touches only caller's unread notifications and returns count.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    u1, _ = _create_user_with_employee(db, company_a.company_id, UserRole.employee)
    u2, _ = _create_user_with_employee(db, company_a.company_id, UserRole.employee)

    n1 = Notification(
        company_id=company_a.company_id,
        user_id=u1.id,
        type="msg",
        title="N1",
        message="M1",
        is_read=False,
    )
    n2 = Notification(
        company_id=company_a.company_id,
        user_id=u1.id,
        type="msg",
        title="N2",
        message="M2",
        is_read=False,
    )
    n_other = Notification(
        company_id=company_a.company_id,
        user_id=u2.id,
        type="msg",
        title="N_Other",
        message="M_Other",
        is_read=False,
    )
    db.add_all([n1, n2, n_other])
    db.commit()

    headers1 = _auth_headers(u1)

    # 1. First mark_read
    r1 = client.put(f"/api/v1/notifications/{n1.id}/read", headers=headers1)
    assert r1.status_code == 200
    first_read_at = r1.json()["read_at"]
    assert first_read_at is not None

    # Repeat mark_read: must preserve original read_at!
    r2 = client.put(f"/api/v1/notifications/{n1.id}/read", headers=headers1)
    assert r2.status_code == 200
    assert r2.json()["read_at"] == first_read_at

    # 2. Mark all read: touches only u1's unread notification (n2), not u2's
    r_all = client.put("/api/v1/notifications/read-all", headers=headers1)
    assert r_all.status_code == 200
    assert r_all.json()["marked_read"] == 1  # only n2 was unread

    # Verify u2's notification is still unread!
    db.expire_all()
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    refreshed_other = db.get(Notification, n_other.id)
    assert refreshed_other.is_read is False


def test_t4_action_url_relative_path_validation(db: Session, company_a: TenantContext) -> None:
    """T4: action_url is relative app path only (starts with single '/' and not '//',
    no scheme, no spaces). Otherwise NotificationService.notify stores None and logs
    warning without raising.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.employee)
    db.commit()

    service = NotificationService(db)

    # 1. Valid relative path
    n_valid = service.notify(
        company_id=company_a.company_id,
        user_id=user.id,
        type="test",
        title="Valid Link",
        message="Message",
        action_url="/leaves/123",
    )
    assert n_valid.action_url == "/leaves/123"

    # 2. External URL -> stored as None
    n_ext = service.notify(
        company_id=company_a.company_id,
        user_id=user.id,
        type="test",
        title="Ext Link",
        message="Message",
        action_url="https://evil.com/phish",
    )
    assert n_ext.action_url is None

    # 3. Protocol-relative // -> stored as None
    n_proto = service.notify(
        company_id=company_a.company_id,
        user_id=user.id,
        type="test",
        title="Proto Link",
        message="Message",
        action_url="//evil.com/phish",
    )
    assert n_proto.action_url is None

    # 4. URL with spaces -> stored as None
    n_space = service.notify(
        company_id=company_a.company_id,
        user_id=user.id,
        type="test",
        title="Space Link",
        message="Message",
        action_url="/path with spaces",
    )
    assert n_space.action_url is None


def test_t4_action_url_backslash_and_control_chars_rejected(
    db: Session, company_a: TenantContext
) -> None:
    """T4: action_url must reject backslash (preventing open redirect like /\\evil.com)
    and control characters (/ok\\nx, /a\\tb, /bad\\x00x). Stored as None.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.employee)
    db.commit()

    service = NotificationService(db)
    bad_urls = [
        "/\\evil.com",
        "/\\\\evil.com",
        "/ok\nx",
        "/a\tb",
        "/bad\x00x",
    ]
    for bad_url in bad_urls:
        n = service.notify(
            company_id=company_a.company_id,
            user_id=user.id,
            type="test",
            title="Bad URL Test",
            message="Msg",
            action_url=bad_url,
        )
        assert n.action_url is None, f"Expected None for dangerous action_url: {bad_url!r}"


def test_t6_notifications_rate_limits(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """T6: Rate limits: list 60/min (61st gives 429), mark one 60/min (61st gives 429),
    mark all 10/min (11th gives 429).
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.employee)

    # Create 61 notifications for mark one test
    notifs = []
    for i in range(61):
        n = Notification(
            company_id=company_a.company_id,
            user_id=user.id,
            type="msg",
            title=f"N {i}",
            message=f"M {i}",
            is_read=False,
        )
        db.add(n)
        notifs.append(n)
    db.commit()

    headers = _auth_headers(user)

    # 1. GET list: 60/min -> 61st gives 429
    limiter.enabled = True
    try:
        limiter.reset()
        list_codes = []
        for _ in range(61):
            r = client.get("/api/v1/notifications", headers=headers)
            list_codes.append(r.status_code)
        assert all(c == 200 for c in list_codes[:60])
        assert list_codes[60] == 429
    finally:
        limiter.reset()
        limiter.enabled = False

    # 2. PUT mark one: 60/min -> 61st gives 429
    limiter.enabled = True
    try:
        limiter.reset()
        mark_codes = []
        for n in notifs:
            r = client.put(f"/api/v1/notifications/{n.id}/read", headers=headers)
            mark_codes.append(r.status_code)
        assert all(c == 200 for c in mark_codes[:60])
        assert mark_codes[60] == 429
    finally:
        limiter.reset()
        limiter.enabled = False

    # 3. PUT mark all: 10/min -> 11th gives 429
    limiter.enabled = True
    try:
        limiter.reset()
        all_codes = []
        for _ in range(11):
            r = client.put("/api/v1/notifications/read-all", headers=headers)
            all_codes.append(r.status_code)
        assert all(c == 200 for c in all_codes[:10])
        assert all_codes[10] == 429
    finally:
        limiter.reset()
        limiter.enabled = False


def test_t7_cleanup_old_notifications_task(
    db: Session, company_a: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T7: Read notifications older than 90 days are deleted.
    Unread notifications are kept (even >90d).
    Read notifications younger than 90 days are kept.
    Beat schedule is registered daily at 02:30 UTC.
    """
    from app.workers import celery_app
    from app.workers.tasks import platform as platform_tasks

    monkeypatch.setattr(platform_tasks, "get_task_db_session", lambda: Session(bind=db.get_bind()))

    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.employee)

    now = datetime.now(UTC)
    old_read_at = now - timedelta(days=95)
    recent_read_at = now - timedelta(days=10)

    # 1. Read > 90 days -> must be deleted
    n_old_read = Notification(
        company_id=company_a.company_id,
        user_id=user.id,
        type="msg",
        title="Old Read",
        message="Should be deleted",
        is_read=True,
        read_at=old_read_at,
    )
    # 2. Unread > 90 days -> must be KEPT
    n_old_unread = Notification(
        company_id=company_a.company_id,
        user_id=user.id,
        type="msg",
        title="Old Unread",
        message="Should be kept",
        is_read=False,
        read_at=None,
    )
    # 3. Read < 90 days -> must be KEPT
    n_recent_read = Notification(
        company_id=company_a.company_id,
        user_id=user.id,
        type="msg",
        title="Recent Read",
        message="Should be kept",
        is_read=True,
        read_at=recent_read_at,
    )
    db.add_all([n_old_read, n_old_unread, n_recent_read])
    db.commit()

    old_read_id = n_old_read.id
    old_unread_id = n_old_unread.id
    recent_read_id = n_recent_read.id

    # Run the task function directly
    deleted_count = platform_tasks.cleanup_old_notifications_task()
    assert deleted_count >= 1

    db.expire_all()
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)

    assert db.get(Notification, old_read_id) is None, "read 91-day row deleted"
    assert db.get(Notification, old_unread_id) is not None, "unread old row kept"
    assert db.get(Notification, recent_read_id) is not None, "read 89-day row kept"

    # Verify beat schedule registration
    beat = celery_app.celery_app.conf.beat_schedule
    task_entry = beat.get("cleanup-old-notifications-daily")
    assert task_entry is not None, "cleanup-old-notifications-daily must be registered in beat"
    assert task_entry["task"] == "app.workers.tasks.platform.cleanup_old_notifications_task"
    cron = task_entry["schedule"]
    assert 2 in cron.hour
    assert 30 in cron.minute


# ══════════════════════════════════════════════════════════════════
# Contract 3.4: Global Search (S1 - S7)
# ══════════════════════════════════════════════════════════════════


def test_s1_search_query_validation_and_escaping(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """S1: Login needed; query trimmed 2 to 100 characters; bad query 422.
    '%', '_' and '\' match as plain characters (escaped).
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    user, emp = _create_user_with_employee(
        db, company_a.company_id, UserRole.hr_admin, first_name="Esc%ape", last_name="User"
    )
    # Another employee whose name has "EscXape" (would match if % was unescaped wildcard)
    _, _ = _create_user_with_employee(
        db, company_a.company_id, UserRole.employee, first_name="EscXape", last_name="Wildcard"
    )
    db.commit()

    headers = _auth_headers(user)

    # 1. Unauthenticated -> 401
    assert client.get("/api/v1/search?q=test").status_code == 401

    # 2. Too short query (<2) -> 422
    assert client.get("/api/v1/search?q=a", headers=headers).status_code == 422
    assert client.get("/api/v1/search?q=  a  ", headers=headers).status_code == 422

    # 3. Too long query (>100) -> 422
    assert client.get(f"/api/v1/search?q={'x' * 101}", headers=headers).status_code == 422

    # 4. Search for literal "Esc%" -> must match only Esc%ape, NOT EscXape!
    r_esc = client.get("/api/v1/search?q=Esc%", headers=headers)
    assert r_esc.status_code == 200
    items = r_esc.json()["results"]
    emp_titles = [i["title"] for i in items if i["type"] == "employee"]
    assert any("Esc%ape" in t for t in emp_titles)
    assert not any("EscXape" in t for t in emp_titles)


def test_s2_cross_company_and_deleted_records_hidden(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
) -> None:
    """S2: Same company only; inactive and deleted employees, deleted projects
    and deleted tasks never appear.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    hr_a, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)

    # Inactive employee in Co A
    _, emp_inactive = _create_user_with_employee(
        db, company_a.company_id, UserRole.employee, first_name="InactiveA", is_active=False
    )
    # Deleted employee in Co A
    _, emp_del = _create_user_with_employee(
        db, company_a.company_id, UserRole.employee, first_name="DeletedA"
    )
    emp_del.deleted_at = datetime.now(UTC)
    db.commit()

    # Active employee in Co B
    bind_tenant_to_session(db, company_id=company_b.company_id, is_platform_admin=False)
    _, emp_b = _create_user_with_employee(
        db, company_b.company_id, UserRole.employee, first_name="CompanyBEmployee"
    )
    db.commit()

    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)

    headers_a = _auth_headers(hr_a)

    # 1. Search for InactiveA -> not found
    r_inact = client.get("/api/v1/search?q=InactiveA", headers=headers_a)
    assert r_inact.status_code == 200
    assert len([i for i in r_inact.json()["results"] if i["type"] == "employee"]) == 0

    # 2. Search for DeletedA -> not found
    r_del = client.get("/api/v1/search?q=DeletedA", headers=headers_a)
    assert r_del.status_code == 200
    assert len([i for i in r_del.json()["results"] if i["type"] == "employee"]) == 0

    # 3. Search for CompanyBEmployee -> not found in Co A
    r_b = client.get("/api/v1/search?q=CompanyBEmployee", headers=headers_a)
    assert r_b.status_code == 200
    assert len([i for i in r_b.json()["results"] if i["type"] == "employee"]) == 0


def test_s3_employee_scoping_rules(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """S3: HR-level finds any active employee with email and code (url is /employees/{id}).
    Manager finds own team with email and code; colleagues by name and department only
    (url is None). Cannot find colleagues outside team with email.
    Employee role finds self with email and code; colleagues by name and department only
    (url is None).
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    dept_fin = _create_department(db, company_a.company_id, f"Finance-{uuid.uuid4().hex[:6]}")
    dept_dev = _create_department(db, company_a.company_id, f"Dev-{uuid.uuid4().hex[:6]}")

    hr_user, hr_emp = _create_user_with_employee(
        db,
        company_a.company_id,
        UserRole.hr_admin,
        first_name="Hradmin",
        last_name="Person",
        email="hradmin@testco.com",
        code="EMP-HR",
        department=dept_fin,
    )
    mgr_user, mgr_emp = _create_user_with_employee(
        db,
        company_a.company_id,
        UserRole.manager,
        first_name="ManagerBob",
        last_name="Person",
        email="mgrbob@testco.com",
        code="EMP-MGR",
        department=dept_dev,
    )
    report_user, report_emp = _create_user_with_employee(
        db,
        company_a.company_id,
        UserRole.employee,
        first_name="ReportAlice",
        last_name="Person",
        email="alice@testco.com",
        code="EMP-RPT",
        department=dept_dev,
        manager_employee_id=mgr_emp.id,
    )
    other_user, other_emp = _create_user_with_employee(
        db,
        company_a.company_id,
        UserRole.employee,
        first_name="OtherCharlie",
        last_name="Person",
        email="charlie@testco.com",
        code="EMP-OTH",
        department=dept_fin,
    )
    db.commit()

    # 1. HR Admin searches "Person": sees all with email, code, url
    r_hr = client.get("/api/v1/search?q=Person", headers=_auth_headers(hr_user)).json()
    hr_emps = {i["id"]: i for i in r_hr["results"] if i["type"] == "employee"}
    assert str(other_emp.id) in hr_emps
    other_for_hr = hr_emps[str(other_emp.id)]
    assert "charlie@testco.com" in other_for_hr["subtitle"]
    assert "EMP-OTH" in other_for_hr["subtitle"]
    assert other_for_hr["url"] == f"/employees/{other_emp.id}"

    # 2. Manager searches "Person":
    # - Sees report Alice with email and code, url /employees/...
    # - Sees other Charlie with name and department only, url is None!
    r_mgr = client.get("/api/v1/search?q=Person", headers=_auth_headers(mgr_user)).json()
    mgr_emps = {i["id"]: i for i in r_mgr["results"] if i["type"] == "employee"}

    alice_for_mgr = mgr_emps[str(report_emp.id)]
    assert "alice@testco.com" in alice_for_mgr["subtitle"]
    assert alice_for_mgr["url"] == f"/employees/{report_emp.id}"

    charlie_for_mgr = mgr_emps[str(other_emp.id)]
    assert "charlie@testco.com" not in (charlie_for_mgr["subtitle"] or "")
    assert "EMP-OTH" not in (charlie_for_mgr["subtitle"] or "")
    assert dept_fin.name in (charlie_for_mgr["subtitle"] or "")
    assert charlie_for_mgr["url"] is None

    # Manager cannot find colleague outside team by email
    r_mgr_email = client.get("/api/v1/search?q=charlie@testco", headers=_auth_headers(mgr_user))
    assert len([i for i in r_mgr_email.json()["results"] if i["type"] == "employee"]) == 0

    # 3. Employee (Alice) searches "Person":
    # - Sees self with email and code, url /employees/...
    # - Sees Charlie with department only, url None!
    r_alice = client.get("/api/v1/search?q=Person", headers=_auth_headers(report_user)).json()
    alice_emps = {i["id"]: i for i in r_alice["results"] if i["type"] == "employee"}

    self_for_alice = alice_emps[str(report_emp.id)]
    assert "alice@testco.com" in self_for_alice["subtitle"]
    assert self_for_alice["url"] == f"/employees/{report_emp.id}"

    charlie_for_alice = alice_emps[str(other_emp.id)]
    assert "charlie@testco.com" not in (charlie_for_alice["subtitle"] or "")
    assert "EMP-OTH" not in (charlie_for_alice["subtitle"] or "")
    assert dept_fin.name in (charlie_for_alice["subtitle"] or "")
    assert charlie_for_alice["url"] is None


def test_s4_projects_and_tasks_scoping(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """S4: Projects: HR-level finds all. Everyone else only projects they are member of
    or manage. Tasks only inside those projects, plus tasks assigned to caller.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    hr_user, hr_emp = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)
    emp1, emp1_rec = _create_user_with_employee(db, company_a.company_id, UserRole.employee)
    emp2, emp2_rec = _create_user_with_employee(db, company_a.company_id, UserRole.employee)

    # Project 1: emp1 is member
    p1 = Project(
        company_id=company_a.company_id,
        name="Apollo Mission",
        code="APL-1",
        status="active",
    )
    # Project 2: private to emp2
    p2 = Project(
        company_id=company_a.company_id,
        name="Zeus Mission",
        code="ZEUS-1",
        status="active",
    )
    db.add_all([p1, p2])
    db.flush()

    pm1 = ProjectMember(
        company_id=company_a.company_id,
        project_id=p1.id,
        employee_id=emp1_rec.id,
        role="member",
    )
    pm2 = ProjectMember(
        company_id=company_a.company_id,
        project_id=p2.id,
        employee_id=emp2_rec.id,
        role="member",
    )
    db.add_all([pm1, pm2])

    # Task 1 in P1
    t1 = Task(
        company_id=company_a.company_id,
        project_id=p1.id,
        title="Apollo Launch Checklist",
        status="todo",
    )
    # Task 2 in P2 (not assigned to emp1)
    t2 = Task(
        company_id=company_a.company_id,
        project_id=p2.id,
        title="Zeus Defense System",
        status="todo",
    )
    # Task 3 in P2 (assigned to emp1!)
    t3 = Task(
        company_id=company_a.company_id,
        project_id=p2.id,
        title="Zeus Mission Audit Assigned to Emp1",
        status="todo",
        assigned_to=emp1_rec.id,
    )
    db.add_all([t1, t2, t3])
    db.commit()

    # 1. HR admin searches "Mission": sees all projects (P1, P2) and tasks
    r_hr = client.get("/api/v1/search?q=Mission", headers=_auth_headers(hr_user)).json()
    hr_proj_ids = {i["id"] for i in r_hr["results"] if i["type"] == "project"}
    assert str(p1.id) in hr_proj_ids
    assert str(p2.id) in hr_proj_ids

    # 2. Emp1 searches "Mission":
    # - Sees Project P1 (Apollo Mission)
    # - Does NOT see Project P2 (Zeus Mission, not a member)
    # - Sees Task T3 (assigned to caller, even though in P2)
    r_emp1 = client.get("/api/v1/search?q=Mission", headers=_auth_headers(emp1)).json()
    emp1_projs = {i["id"] for i in r_emp1["results"] if i["type"] == "project"}
    emp1_tasks = {i["id"] for i in r_emp1["results"] if i["type"] == "task"}

    assert str(p1.id) in emp1_projs
    assert str(p2.id) not in emp1_projs  # Cannot see P2!

    assert str(t3.id) in emp1_tasks  # Assigned to emp1

    # Emp1 searches "Defense": Task T2 is in P2 and not assigned -> must NOT appear
    r_t2 = client.get("/api/v1/search?q=Defense", headers=_auth_headers(emp1)).json()
    assert len([i for i in r_t2["results"] if i["type"] == "task"]) == 0


def test_s5_ranking_and_cap_10_per_kind(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """S5: At most 10 results per kind. Best match first (starts-with before contains).
    Total count in reply.
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    hr_user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)

    # Create 15 projects with "SearchTest" in name: 5 starts-with, 10 contains
    projs = []
    for i in range(5):
        p = Project(
            company_id=company_a.company_id,
            name=f"SearchTest Start {i}",
            code=f"STR-{i}",
            status="active",
        )
        projs.append(p)
    for i in range(10):
        p = Project(
            company_id=company_a.company_id,
            name=f"Other Contains SearchTest {i}",
            code=f"CNT-{i}",
            status="active",
        )
        projs.append(p)
    db.add_all(projs)
    db.commit()

    headers = _auth_headers(hr_user)
    res = client.get("/api/v1/search?q=SearchTest", headers=headers).json()

    proj_results = [i for i in res["results"] if i["type"] == "project"]
    assert len(proj_results) == 10  # Max 10 per kind
    # First 5 results must be the ones that start with "SearchTest"
    for item in proj_results[:5]:
        assert item["title"].startswith("SearchTest Start")


def test_s5_search_limit_applied_in_sql(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """S5: Global search must apply LIMIT 10 directly in SQL for employees, projects,
    and tasks, rather than fetching all matches to Python memory.
    """
    from sqlalchemy import event

    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    hr_user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)

    # 1. Create 15 matching employees with "LimitTest"
    for i in range(15):
        _create_user_with_employee(
            db,
            company_a.company_id,
            UserRole.employee,
            first_name=f"LimitTestEmp{i:02d}",
            last_name="Worker",
        )

    # 2. Create 15 matching projects with "LimitTest"
    projs = []
    for i in range(15):
        p = Project(
            company_id=company_a.company_id,
            name=f"LimitTestProj {i:02d}",
            code=f"LTP-{i:02d}",
            status="active",
        )
        projs.append(p)
    db.add_all(projs)
    db.flush()

    # 3. Create 15 matching tasks with "LimitTest" in first project
    first_proj = projs[0]
    tasks = []
    for i in range(15):
        t = Task(
            company_id=company_a.company_id,
            project_id=first_proj.id,
            title=f"LimitTestTask {i:02d}",
            status="todo",
        )
        tasks.append(t)
    db.add_all(tasks)
    db.commit()

    executed_queries: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        executed_queries.append(statement)

    bind = db.get_bind()
    event.listen(bind, "before_cursor_execute", before_cursor_execute)
    try:
        headers = _auth_headers(hr_user)
        res = client.get("/api/v1/search?q=LimitTest", headers=headers).json()

        emp_items = [i for i in res["results"] if i["type"] == "employee"]
        proj_items = [i for i in res["results"] if i["type"] == "project"]
        task_items = [i for i in res["results"] if i["type"] == "task"]

        assert len(emp_items) == 10
        assert len(proj_items) == 10
        assert len(task_items) == 10

        # Verify SQL-level LIMIT applied to all 3 entity queries
        emp_queries = [
            q for q in executed_queries if "from employees" in q.lower() and "select" in q.lower()
        ]
        assert len(emp_queries) > 0, "Expected at least one query on employees"
        assert all("limit" in q.lower() for q in emp_queries), (
            f"Employee SQL query must use LIMIT: {emp_queries}"
        )
    finally:
        event.remove(bind, "before_cursor_execute", before_cursor_execute)


def test_s6_replies_safe_fields_and_optional_url(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """S6: Replies never contain salary, phone, personal email or hidden ids.
    Url field is optional (None for directory-only employee).
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    emp1, _ = _create_user_with_employee(db, company_a.company_id, UserRole.employee)
    _, colleague = _create_user_with_employee(
        db,
        company_a.company_id,
        UserRole.employee,
        first_name="ColleagueSafe",
        last_name="Test",
    )
    colleague.phone = "+1234567890"
    colleague.personal_email = "secret_personal@test.com"
    db.commit()

    res = client.get("/api/v1/search?q=ColleagueSafe", headers=_auth_headers(emp1)).json()
    assert len(res["results"]) >= 1
    item = res["results"][0]

    # Check forbidden keys are absent from reply
    forbidden_keys = {"salary", "phone", "personal_email"}
    assert forbidden_keys.isdisjoint(set(item.keys()))
    assert item["url"] is None
    assert "+1234567890" not in str(item)
    assert "secret_personal@test.com" not in str(item)


def test_s7_search_rate_limit_and_no_audit(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    """S7: Rate limit 30/min (31st gives 429). Searches are not audited."""
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    user, _ = _create_user_with_employee(db, company_a.company_id, UserRole.hr_admin)
    db.commit()

    headers = _auth_headers(user)

    # 1. Search is not audited
    before_audit_count = db.scalar(select(AuditLog).where(AuditLog.action.like("%SEARCH%")))
    client.get("/api/v1/search?q=AuditCheck", headers=headers)
    after_audit_count = db.scalar(select(AuditLog).where(AuditLog.action.like("%SEARCH%")))
    assert before_audit_count == after_audit_count

    # 2. Rate limit: 30/min -> 31st gives 429
    limiter.enabled = True
    try:
        limiter.reset()
        codes = []
        for _ in range(31):
            r = client.get("/api/v1/search?q=RateCheck", headers=headers)
            codes.append(r.status_code)
        assert all(c == 200 for c in codes[:30])
        assert codes[30] == 429
    finally:
        limiter.reset()
        limiter.enabled = False


# ══════════════════════════════════════════════════════════════════
# Migration Test: Add department_id to announcements
# ══════════════════════════════════════════════════════════════════


def test_migration_announcement_department_id_round_trip() -> None:
    """Tests the new migration for announcements.department_id:
    downgrade removes department_id, upgrade re-adds it.
    """
    import subprocess

    from sqlalchemy import create_engine

    assert settings.TEST_MIGRATION_URL is not None, "TEST_MIGRATION_URL must be configured"

    repo_root = Path(__file__).resolve().parents[2]
    # Find our new migration file dynamically
    versions_dir = repo_root / "alembic/versions"
    mig_files = list(versions_dir.glob("*_add_announcement_department_id.py"))
    assert len(mig_files) == 1, f"Expected 1 migration file, found: {mig_files}"
    migration_file = mig_files[0]

    down_rev = None
    with open(migration_file) as f:
        for line in f:
            if line.startswith("down_revision"):
                down_rev = line.split("=")[1].strip().strip('"').strip("'")
                break
    assert down_rev is not None, "Could not determine down_revision"

    env = {**os.environ, "ALEMBIC_DATABASE_URL": settings.TEST_MIGRATION_URL}
    owner_engine = create_engine(settings.TEST_MIGRATION_URL)

    try:
        # Downgrade to down_revision
        res_down = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", down_rev],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res_down.returncode == 0, f"Alembic downgrade failed: {res_down.stderr}"

        insp = inspect(owner_engine)
        cols_after_down = [col["name"] for col in insp.get_columns("announcements")]
        assert "department_id" not in cols_after_down
    finally:
        # Upgrade back to head
        res_up = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res_up.returncode == 0, f"Alembic upgrade failed: {res_up.stderr}"

    insp = inspect(owner_engine)
    cols_after_up = [col["name"] for col in insp.get_columns("announcements")]
    assert "department_id" in cols_after_up
