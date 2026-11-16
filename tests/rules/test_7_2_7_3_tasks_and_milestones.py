"""Module 7 Batch 2: 7.2 Tasks & Kanban Board, 7.3 Milestones.
Tests verifying all 11 rules for 7.2 and all 6 rules for 7.3.
"""

import uuid
from datetime import date, timedelta
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
def p2_setup(db: Session) -> dict[str, Any]:
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
    other_mgr_u, other_mgr_e = make_user_and_emp("other_mgr", UserRole.manager, cid_a)
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
        "other_mgr_u": other_mgr_u,
        "other_mgr_e": other_mgr_e,
        "emp1_u": emp1_u,
        "emp1_e": emp1_e,
        "emp2_u": emp2_u,
        "emp2_e": emp2_e,
        "non_member_emp_u": non_member_emp_u,
        "non_member_emp_e": non_member_emp_e,
        "sa_u": sa_u,
        "b_owner_u": b_owner_u,
    }


def _create_standard_project(
    client: TestClient, p2_setup: dict, start_date=None, end_date=None
) -> str:
    payload = {
        "name": f"P2 Proj {uuid.uuid4().hex[:6]}",
        "code": f"PRJ-{uuid.uuid4().hex[:4].upper()}",
        "manager_id": str(p2_setup["pm_e"].id),
    }
    if start_date:
        payload["start_date"] = str(start_date)
    if end_date:
        payload["end_date"] = str(end_date)
    r = client.post("/api/v1/projects", json=payload, headers=_auth_headers(p2_setup["hr_u"]))
    assert r.status_code == 201
    proj_id = r.json()["id"]

    # Add emp1 as project member
    r_mem = client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(p2_setup["emp1_e"].id), "role": "member"},
        headers=_auth_headers(p2_setup["hr_u"]),
    )
    assert r_mem.status_code == 201
    return proj_id


# ==============================================================================
# 7.2 TASKS & KANBAN BOARD TESTS
# ==============================================================================


def test_7_2_r1_create_edit_scoping(client: TestClient, db: Session, p2_setup: dict):
    """Rule 1: Project members and PM create and edit tasks in their own projects;
    HR and owner any; a non-member gets 404; Super admin gets 403.
    """
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])
    emp1_headers = _auth_headers(p2_setup["emp1_u"])
    non_mem_headers = _auth_headers(p2_setup["non_member_emp_u"])
    hr_headers = _auth_headers(p2_setup["hr_u"])
    owner_headers = _auth_headers(p2_setup["owner_u"])
    sa_headers = _auth_headers(p2_setup["sa_u"])

    # 1. Emp1 (member) can create task
    r_task1 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Emp1 Task", "priority": "medium", "status": "todo"},
        headers=emp1_headers,
    )
    assert r_task1.status_code == 201
    task1_id = r_task1.json()["id"]

    # 2. PM can create task
    r_task2 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "PM Task", "priority": "high", "status": "todo"},
        headers=pm_headers,
    )
    assert r_task2.status_code == 201

    # 3. HR and Owner can create task
    r_task3 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "HR Task", "priority": "low", "status": "todo"},
        headers=hr_headers,
    )
    assert r_task3.status_code == 201
    r_task4 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Owner Task", "priority": "critical", "status": "todo"},
        headers=owner_headers,
    )
    assert r_task4.status_code == 201

    # 4. Non-member employee gets 404
    r_non_create = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Non Member Task", "priority": "medium", "status": "todo"},
        headers=non_mem_headers,
    )
    assert r_non_create.status_code == 404

    r_non_get = client.get(f"/api/v1/projects/tasks/{task1_id}", headers=non_mem_headers)
    assert r_non_get.status_code == 404

    r_non_put = client.put(
        f"/api/v1/projects/tasks/{task1_id}",
        json={"title": "Hacked Title"},
        headers=non_mem_headers,
    )
    assert r_non_put.status_code == 404

    # 5. Super admin gets 403
    r_sa_create = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "SA Task", "priority": "medium", "status": "todo"},
        headers=sa_headers,
    )
    assert r_sa_create.status_code == 403

    r_sa_get = client.get(f"/api/v1/projects/tasks/{task1_id}", headers=sa_headers)
    assert r_sa_get.status_code == 403


def test_7_2_r2_r6_validation_and_assignee(client: TestClient, db: Session, p2_setup: dict):
    """Rule 2 & 6: Title required with max length (255); priority from fixed list;
    estimate >= 0; due date valid and bounded by project [start_date, end_date];
    assignee must be an active project member of the same project; bad input returns 422.
    """
    today = date.today()
    proj_id = _create_standard_project(
        client, p2_setup, start_date=today, end_date=today + timedelta(days=30)
    )
    pm_headers = _auth_headers(p2_setup["pm_u"])

    # Empty title -> 422
    r1 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "   ", "priority": "medium"},
        headers=pm_headers,
    )
    assert r1.status_code == 422

    # Invalid priority -> 422
    r2 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Valid Title", "priority": "urgent"},
        headers=pm_headers,
    )
    assert r2.status_code == 422

    # Negative estimate -> 422
    r3 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Valid Title", "priority": "medium", "estimated_hours": -5},
        headers=pm_headers,
    )
    assert r3.status_code == 422

    # Assignee not a project member -> 422
    r4 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={
            "title": "Valid Title",
            "priority": "medium",
            "assigned_to": str(p2_setup["non_member_emp_e"].id),
        },
        headers=pm_headers,
    )
    assert r4.status_code == 422
    err_body = str(r4.json()).lower()
    assert "project member" in err_body

    # Due date before project start date -> 422
    r5 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={
            "title": "Valid Title",
            "priority": "medium",
            "due_date": str(today - timedelta(days=1)),
        },
        headers=pm_headers,
    )
    assert r5.status_code == 422

    # Due date after project end date -> 422
    r6 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={
            "title": "Valid Title",
            "priority": "medium",
            "due_date": str(today + timedelta(days=35)),
        },
        headers=pm_headers,
    )
    assert r6.status_code == 422

    # Valid task with active project member assignee -> 201
    r_ok = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={
            "title": "Valid Task",
            "priority": "high",
            "assigned_to": str(p2_setup["emp1_e"].id),
            "due_date": str(today + timedelta(days=10)),
            "estimated_hours": 12.5,
        },
        headers=pm_headers,
    )
    assert r_ok.status_code == 201


def test_7_2_r3_r4_status_flow_conflict_and_pm_reopen(
    client: TestClient, db: Session, p2_setup: dict
):
    """Rule 3: Status moves todo -> in_progress -> review -> done, one step forward at a time;
    skipping a step returns 409; moving back one step is allowed.
    Rule 4: A done task changes only when the project manager reopens it.
    """
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])
    emp1_headers = _auth_headers(p2_setup["emp1_u"])

    r_create = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Workflow Task", "priority": "medium", "status": "todo"},
        headers=pm_headers,
    )
    assert r_create.status_code == 201
    task_id = r_create.json()["id"]

    # 1. Skip step todo -> review gives 409
    r_skip = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "review"},
        headers=emp1_headers,
    )
    assert r_skip.status_code == 409

    # 2. Skip step todo -> done gives 409
    r_skip_done = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "done"},
        headers=emp1_headers,
    )
    assert r_skip_done.status_code == 409

    # 3. Valid forward step: todo -> in_progress gives 200
    r_step1 = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "in_progress"},
        headers=emp1_headers,
    )
    assert r_step1.status_code == 200
    assert r_step1.json()["status"] == "in_progress"

    # 4. Moving back one step is allowed: in_progress -> todo gives 200
    r_back = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "todo"},
        headers=emp1_headers,
    )
    assert r_back.status_code == 200
    assert r_back.json()["status"] == "todo"

    # Forward: todo -> in_progress -> review
    client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "in_progress"},
        headers=emp1_headers,
    )
    r_review = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "review"},
        headers=emp1_headers,
    )
    assert r_review.status_code == 200

    # Review -> done gives 200
    r_done = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "done"},
        headers=emp1_headers,
    )
    assert r_done.status_code == 200
    assert r_done.json()["status"] == "done"
    assert r_done.json()["completed_at"] is not None

    # Rule 4: Plain member trying to edit or move done task gets 409
    r_emp_done_edit = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"title": "New Title on Done Task"},
        headers=emp1_headers,
    )
    assert r_emp_done_edit.status_code == 409

    r_emp_done_status = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "in_progress"},
        headers=emp1_headers,
    )
    assert r_emp_done_status.status_code == 409

    # Project Manager reopens task: done -> in_progress gives 200
    r_pm_reopen = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "in_progress"},
        headers=pm_headers,
    )
    assert r_pm_reopen.status_code == 200
    assert r_pm_reopen.json()["status"] == "in_progress"
    assert r_pm_reopen.json()["completed_at"] is None


def test_7_2_r5_delete_permissions(client: TestClient, db: Session, p2_setup: dict):
    """Rule 5: Only creator, PM, HR and owner delete a task; others get 403."""
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])
    emp1_headers = _auth_headers(p2_setup["emp1_u"])
    emp2_headers = _auth_headers(p2_setup["emp2_u"])

    # Add emp2 to project as well
    client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(p2_setup["emp2_e"].id), "role": "member"},
        headers=_auth_headers(p2_setup["hr_u"]),
    )

    # Emp1 creates task
    r_create = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Emp1 Deletable Task", "priority": "low"},
        headers=emp1_headers,
    )
    assert r_create.status_code == 201
    task_id = r_create.json()["id"]

    # Emp2 (member, but not creator or PM) tries to delete -> 403
    r_del_emp2 = client.delete(f"/api/v1/projects/tasks/{task_id}", headers=emp2_headers)
    assert r_del_emp2.status_code == 403

    # Emp1 (creator) deletes -> 204
    r_del_emp1 = client.delete(f"/api/v1/projects/tasks/{task_id}", headers=emp1_headers)
    assert r_del_emp1.status_code == 204

    # Now verify PM can delete tasks created by others
    r_create2 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Emp1 Task for PM Delete", "priority": "low"},
        headers=emp1_headers,
    )
    task2_id = r_create2.json()["id"]
    r_del_pm = client.delete(f"/api/v1/projects/tasks/{task2_id}", headers=pm_headers)
    assert r_del_pm.status_code == 204


def test_7_2_r7_parent_project_status_blocks_work(client: TestClient, db: Session, p2_setup: dict):
    """Rule 7: An on-hold, completed or archived project allows reading tasks but blocks
    create, edit and status change (returns 409); cancelling a task is always allowed
    by PM, HR, owner.
    """
    proj_id = _create_standard_project(client, p2_setup)
    hr_headers = _auth_headers(p2_setup["hr_u"])
    pm_headers = _auth_headers(p2_setup["pm_u"])

    # Create active task
    r_task = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Active Task", "priority": "medium", "status": "todo"},
        headers=pm_headers,
    )
    task_id = r_task.json()["id"]

    # Put project on hold
    client.put(f"/api/v1/projects/{proj_id}", json={"status": "on_hold"}, headers=hr_headers)

    # Creating task is blocked -> 409
    r_create_blocked = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Blocked Task", "priority": "medium"},
        headers=pm_headers,
    )
    assert r_create_blocked.status_code == 409

    # Editing task is blocked -> 409
    r_edit_blocked = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"title": "Updated Title"},
        headers=pm_headers,
    )
    assert r_edit_blocked.status_code == 409

    # Status transition is blocked -> 409
    r_status_blocked = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "in_progress"},
        headers=pm_headers,
    )
    assert r_status_blocked.status_code == 409

    # Cancelling a task is allowed by PM, HR, owner -> 200
    r_cancel = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "cancelled"},
        headers=pm_headers,
    )
    assert r_cancel.status_code == 200
    assert r_cancel.json()["status"] == "cancelled"


def test_7_2_r8_atomic_kanban_reordering(client: TestClient, db: Session, p2_setup: dict):
    """Rule 8: Reordering tasks on the board updates an atomic position integer;
    concurrent reorders resolve safely.
    """
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])

    # Create 3 tasks
    r_t1 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Task 1", "priority": "medium", "position": 0},
        headers=pm_headers,
    )
    r_t2 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Task 2", "priority": "medium", "position": 1},
        headers=pm_headers,
    )
    _ = r_t1.json()["id"]
    t2_id = r_t2.json()["id"]

    # Reorder task 2 to position 0
    r_reorder = client.put(
        f"/api/v1/projects/tasks/{t2_id}/reorder",
        json={"position": 0},
        headers=pm_headers,
    )
    assert r_reorder.status_code == 200
    assert r_reorder.json()["position"] == 0

    # Verify task list ordering
    r_list = client.get(f"/api/v1/projects/{proj_id}/tasks", headers=pm_headers)
    assert r_list.status_code == 200
    items = r_list.json()
    assert items[0]["id"] == t2_id


def test_7_2_r9_audit_logging(client: TestClient, db: Session, p2_setup: dict):
    """Rule 9: Every create, edit, status change, delete and reopen is audited
    (ids and field names only).
    """
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])

    r_task = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Audited Task", "priority": "medium", "status": "todo"},
        headers=pm_headers,
    )
    task_id = r_task.json()["id"]

    client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"priority": "high"},
        headers=pm_headers,
    )

    client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"status": "in_progress"},
        headers=pm_headers,
    )

    logs = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == p2_setup["cid_a"], AuditLog.entity_id == uuid.UUID(task_id))
        .all()
    )
    actions = [log.action for log in logs]
    assert "create_task" in actions or "task_created" in actions
    assert "update_task" in actions or "task_updated" in actions
    for log in logs:
        # Field names and ids only, no leaking secrets
        assert "password" not in str(log.details).lower()


def test_7_2_r10_rate_limiting(client: TestClient, db: Session, p2_setup: dict):
    """Rule 10: Write routes are rate limited, with a 429 test."""
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])

    limiter.enabled = True
    try:
        limiter.reset()
        hit_429 = False
        for i in range(65):
            r = client.post(
                f"/api/v1/projects/{proj_id}/tasks",
                json={"title": f"RL Task {i}", "priority": "low"},
                headers=pm_headers,
            )
            if r.status_code == 429:
                hit_429 = True
                break
        assert hit_429, "Rate limiter did not return 429 on excessive task POSTs"
    finally:
        limiter.reset()
        limiter.enabled = False


def test_7_2_r11_cross_company_404(client: TestClient, db: Session, p2_setup: dict):
    """Rule 11: Another company's task returns 404."""
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])
    b_headers = _auth_headers(p2_setup["b_owner_u"])

    r_task = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Comp A Task", "priority": "medium"},
        headers=pm_headers,
    )
    task_id = r_task.json()["id"]

    # Company B access -> 404
    r_get = client.get(f"/api/v1/projects/tasks/{task_id}", headers=b_headers)
    assert r_get.status_code == 404

    r_put = client.put(
        f"/api/v1/projects/tasks/{task_id}", json={"title": "Hacked"}, headers=b_headers
    )
    assert r_put.status_code == 404

    r_del = client.delete(f"/api/v1/projects/tasks/{task_id}", headers=b_headers)
    assert r_del.status_code == 404


# ==============================================================================
# 7.3 MILESTONES TESTS
# ==============================================================================


def test_7_3_r1_create_edit_scoping(client: TestClient, db: Session, p2_setup: dict):
    """Rule 1: PM, HR and owner create, edit and delete milestones; members read;
    a non-member gets 404; Super Admin gets 403.
    """
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])
    emp1_headers = _auth_headers(p2_setup["emp1_u"])
    non_mem_headers = _auth_headers(p2_setup["non_member_emp_u"])
    hr_headers = _auth_headers(p2_setup["hr_u"])
    owner_headers = _auth_headers(p2_setup["owner_u"])
    sa_headers = _auth_headers(p2_setup["sa_u"])

    # 1. PM can create milestone
    r_ms = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "M1 Initial", "due_date": str(date.today() + timedelta(days=5))},
        headers=pm_headers,
    )
    assert r_ms.status_code == 201
    ms_id = r_ms.json()["id"]

    # 2. Plain member cannot create milestone -> 403
    r_mem_create = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "Member MS"},
        headers=emp1_headers,
    )
    assert r_mem_create.status_code == 403

    # Plain member can read milestone -> 200
    r_mem_list = client.get(f"/api/v1/projects/{proj_id}/milestones", headers=emp1_headers)
    assert r_mem_list.status_code == 200
    assert any(m["id"] == ms_id for m in r_mem_list.json())

    # 3. Non-member gets 404
    r_non_list = client.get(f"/api/v1/projects/{proj_id}/milestones", headers=non_mem_headers)
    assert r_non_list.status_code == 404

    r_non_put = client.put(
        f"/api/v1/projects/milestones/{ms_id}",
        json={"title": "Hacked MS"},
        headers=non_mem_headers,
    )
    assert r_non_put.status_code == 404

    # 4. Super Admin gets 403
    r_sa_list = client.get(f"/api/v1/projects/{proj_id}/milestones", headers=sa_headers)
    assert r_sa_list.status_code == 403

    # 5. HR and Owner can edit and delete
    r_hr_edit = client.put(
        f"/api/v1/projects/milestones/{ms_id}",
        json={"title": "HR Updated MS"},
        headers=hr_headers,
    )
    assert r_hr_edit.status_code == 200
    assert r_hr_edit.json()["title"] == "HR Updated MS"

    r_owner_del = client.delete(f"/api/v1/projects/milestones/{ms_id}", headers=owner_headers)
    assert r_owner_del.status_code == 204


def test_7_3_r2_r6_validation_and_due_date_bounds(client: TestClient, db: Session, p2_setup: dict):
    """Rule 2: Title is required with length limit; due date must fall within project
    start_date and end_date (if set); bad input returns 422.
    """
    today = date.today()
    proj_id = _create_standard_project(
        client, p2_setup, start_date=today, end_date=today + timedelta(days=20)
    )
    pm_headers = _auth_headers(p2_setup["pm_u"])

    # Blank title -> 422
    r_blank = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "   ", "due_date": str(today + timedelta(days=5))},
        headers=pm_headers,
    )
    assert r_blank.status_code == 422

    # Due date before start date -> 422
    r_before = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "Early MS", "due_date": str(today - timedelta(days=1))},
        headers=pm_headers,
    )
    assert r_before.status_code == 422

    # Due date after end date -> 422
    r_after = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "Late MS", "due_date": str(today + timedelta(days=25))},
        headers=pm_headers,
    )
    assert r_after.status_code == 422

    # Valid milestone -> 201
    r_valid = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "Valid MS", "due_date": str(today + timedelta(days=10))},
        headers=pm_headers,
    )
    assert r_valid.status_code == 201


def test_7_3_r3_completion_gates(client: TestClient, db: Session, p2_setup: dict):
    """Rule 3: A milestone completes only when all associated tasks are done;
    completing with open tasks returns 409; a milestone with only cancelled tasks
    can be completed.
    """
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])

    r_ms = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "Gated MS"},
        headers=pm_headers,
    )
    ms_id = r_ms.json()["id"]

    # Create task linked to milestone
    r_t1 = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Task 1", "priority": "medium", "milestone_id": ms_id, "status": "todo"},
        headers=pm_headers,
    )
    t1_id = r_t1.json()["id"]

    # Attempt to complete milestone while task 1 is todo -> 409
    r_comp_blocked = client.put(
        f"/api/v1/projects/milestones/{ms_id}",
        json={"status": "completed"},
        headers=pm_headers,
    )
    assert r_comp_blocked.status_code == 409
    err_body = str(r_comp_blocked.json()).lower()
    assert "open tasks" in err_body

    # Cancel task 1 -> Now milestone with only cancelled tasks can be completed
    client.put(
        f"/api/v1/projects/tasks/{t1_id}",
        json={"status": "cancelled"},
        headers=pm_headers,
    )
    r_comp_ok = client.put(
        f"/api/v1/projects/milestones/{ms_id}",
        json={"status": "completed"},
        headers=pm_headers,
    )
    assert r_comp_ok.status_code == 200
    assert r_comp_ok.json()["status"] == "completed"
    assert r_comp_ok.json()["completed_at"] is not None


def test_7_3_r4_delete_unlinks_tasks_safely(client: TestClient, db: Session, p2_setup: dict):
    """Rule 4: Deleting a milestone unlinks associated tasks (milestone_id -> NULL),
    never deletes them.
    """
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])

    r_ms = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "To Delete MS"},
        headers=pm_headers,
    )
    ms_id = r_ms.json()["id"]

    r_t = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Safe Task", "priority": "medium", "milestone_id": ms_id},
        headers=pm_headers,
    )
    t_id = r_t.json()["id"]

    # Delete milestone
    r_del = client.delete(f"/api/v1/projects/milestones/{ms_id}", headers=pm_headers)
    assert r_del.status_code == 204

    # Verify task still exists and milestone_id is None
    r_t_check = client.get(f"/api/v1/projects/tasks/{t_id}", headers=pm_headers)
    assert r_t_check.status_code == 200
    assert r_t_check.json()["milestone_id"] is None


def test_7_3_r5_cross_company_404(client: TestClient, db: Session, p2_setup: dict):
    """Rule 5: Another company's milestone returns 404."""
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])
    b_headers = _auth_headers(p2_setup["b_owner_u"])

    r_ms = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "Comp A MS"},
        headers=pm_headers,
    )
    ms_id = r_ms.json()["id"]

    # Company B get -> 404
    r_get = client.get(f"/api/v1/projects/{proj_id}/milestones", headers=b_headers)
    assert r_get.status_code == 404

    r_put = client.put(
        f"/api/v1/projects/milestones/{ms_id}", json={"title": "Hacked"}, headers=b_headers
    )
    assert r_put.status_code == 404

    r_del = client.delete(f"/api/v1/projects/milestones/{ms_id}", headers=b_headers)
    assert r_del.status_code == 404


def test_7_3_r6_audit_logging_and_rate_limits(client: TestClient, db: Session, p2_setup: dict):
    """Rule 6: Every create, edit and delete is audited (ids and field names only);
    writes are rate limited, with a 429 test.
    """
    proj_id = _create_standard_project(client, p2_setup)
    pm_headers = _auth_headers(p2_setup["pm_u"])

    # 1. Audit check
    r_ms = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "Audited Milestone"},
        headers=pm_headers,
    )
    ms_id = r_ms.json()["id"]

    client.put(
        f"/api/v1/projects/milestones/{ms_id}",
        json={"description": "Updated Description"},
        headers=pm_headers,
    )

    client.delete(f"/api/v1/projects/milestones/{ms_id}", headers=pm_headers)

    logs = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == p2_setup["cid_a"], AuditLog.entity_id == uuid.UUID(ms_id))
        .all()
    )
    actions = [log.action for log in logs]
    assert any("milestone" in a.lower() for a in actions)

    # 2. Rate limit test
    limiter.enabled = True
    try:
        limiter.reset()
        hit_429 = False
        for i in range(65):
            r = client.post(
                f"/api/v1/projects/{proj_id}/milestones",
                json={"title": f"RL MS {i}"},
                headers=pm_headers,
            )
            if r.status_code == 429:
                hit_429 = True
                break
        assert hit_429, "Rate limiter did not return 429 on excessive milestone POSTs"
    finally:
        limiter.reset()
        limiter.enabled = False
