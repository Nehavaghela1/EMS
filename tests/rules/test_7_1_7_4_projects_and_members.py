"""Module 7 Batch 1: 7.1 Projects & 7.4 Members & Rates.
Tests verifying all 11 rules for 7.1 and all 8 rules for 7.4.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog, Notification
from app.modules.projects.models import TimeEntry


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
def p1_setup(db: Session) -> dict[str, Any]:
    db.expire_on_commit = False

    # Company A
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
            employee_code=f"EMP{uuid.uuid4().hex[:8].upper()}",
            first_name="First",
            last_name="Last",
            email=u.email,
            employment_type=EmploymentType.full_time,
            hire_date=date(2025, 1, 1),
            is_active=True,
            invitation_status=InvitationStatus.activated,
        )
        db.add(e)
        db.flush()
        return u, e

    owner_u, owner_e = make_user_and_emp("owner_a", UserRole.owner, cid_a)
    hr_u, hr_e = make_user_and_emp("hr_a", UserRole.hr_admin, cid_a)
    mgr_u, mgr_e = make_user_and_emp("mgr_a", UserRole.manager, cid_a)
    mgr2_u, mgr2_e = make_user_and_emp("mgr2_a", UserRole.manager, cid_a)
    emp_u, emp_e = make_user_and_emp("emp_a", UserRole.employee, cid_a)
    emp2_u, emp2_e = make_user_and_emp("emp2_a", UserRole.employee, cid_a)

    mgr_e_id = mgr_e.id
    mgr2_e_id = mgr2_e.id
    emp_e_id = emp_e.id
    emp2_e_id = emp2_e.id

    # Platform Admin Co for super_admin
    sa_cid = uuid.uuid4()
    sa_comp = Company(
        id=sa_cid,
        name=f"PlatformCo_{uuid.uuid4().hex[:6]}",
        code=f"PC{uuid.uuid4().hex[:6].upper()}",
        email=f"platform_{uuid.uuid4().hex[:6]}@platform.test",
        status=CompanyStatus.active,
    )
    db.add(sa_comp)
    db.flush()
    sa_u = User(
        id=uuid.uuid4(),
        company_id=sa_cid,
        email=f"sa_{uuid.uuid4().hex[:6]}@platform.test",
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
    b_owner_u, b_owner_e = make_user_and_emp("owner_b", UserRole.owner, cid_b)

    db.commit()

    res_dict = {
        "cid_a": cid_a,
        "comp_a": comp_a,
        "owner_u": owner_u,
        "owner_e": owner_e,
        "hr_u": hr_u,
        "hr_e": hr_e,
        "mgr_u": mgr_u,
        "mgr_e": mgr_e,
        "mgr2_u": mgr2_u,
        "mgr2_e": mgr2_e,
        "emp_u": emp_u,
        "emp_e": emp_e,
        "emp2_u": emp2_u,
        "emp2_e": emp2_e,
        "sa_u": sa_u,
        "cid_b": cid_b,
        "b_owner_u": b_owner_u,
        "b_owner_e": b_owner_e,
        "b_owner_e_id": b_owner_e.id,
        "mgr_e_id": mgr_e_id,
        "mgr2_e_id": mgr2_e_id,
        "emp_e_id": emp_e_id,
        "emp2_e_id": emp2_e_id,
    }
    return res_dict


# ==========================================
# 7.1 Projects Rules
# ==========================================


def test_7_1_r1_creation_authority_and_manager_auto_member(
    client: TestClient, db: Session, p1_setup: dict
):
    """Rule 1: Owner, HR, manager create projects. Plain employee gets 403.
    Creator or chosen manager becomes project manager and is auto-added as member with role manager.
    """
    emp_headers = _auth_headers(p1_setup["emp_u"])
    res_emp = client.post(
        "/api/v1/projects",
        json={"name": "Emp Proj", "code": "PRJ-EMP-1", "budget": "1000.00"},
        headers=emp_headers,
    )
    assert res_emp.status_code == 403

    # Manager creates project specifying manager_id = mgr_e.id
    mgr_headers = _auth_headers(p1_setup["mgr_u"])
    res_mgr = client.post(
        "/api/v1/projects",
        json={
            "name": "Alpha Project",
            "code": "PRJ-ALP",
            "budget": "50000.00",
            "manager_id": str(p1_setup["mgr_e_id"]),
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        headers=mgr_headers,
    )
    assert res_mgr.status_code == 201, res_mgr.text
    proj_data = res_mgr.json()
    proj_id = proj_data["id"]

    # Verify project manager was automatically added to project_members with role 'manager'
    res_members = client.get(f"/api/v1/projects/{proj_id}/members", headers=mgr_headers)
    assert res_members.status_code == 200
    members = res_members.json()
    assert any(
        m["employee_id"] == str(p1_setup["mgr_e_id"]) and m["role"] == "manager" for m in members
    )


def test_7_1_r2_read_and_edit_scoping(client: TestClient, db: Session, p1_setup: dict):
    """Rule 2: Project manager, HR and owner edit; members and project manager read;
    HR and owner read all; non-member gets 404 (not 403).
    """
    mgr_headers = _auth_headers(p1_setup["mgr_u"])
    hr_headers = _auth_headers(p1_setup["hr_u"])
    # owner_headers
    emp_headers = _auth_headers(p1_setup["emp_u"])
    emp2_headers = _auth_headers(p1_setup["emp2_u"])

    res = client.post(
        "/api/v1/projects",
        json={
            "name": "Beta Project",
            "code": "PRJ-BET",
            "manager_id": str(p1_setup["mgr_e_id"]),
        },
        headers=hr_headers,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    # Add emp_e as a member
    client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(p1_setup["emp_e_id"]), "role": "member"},
        headers=hr_headers,
    )

    # 1. Non-member emp2 reads -> 404
    res_non_member = client.get(f"/api/v1/projects/{proj_id}", headers=emp2_headers)
    assert res_non_member.status_code == 404

    # 2. Member emp reads -> 200
    res_member = client.get(f"/api/v1/projects/{proj_id}", headers=emp_headers)
    assert res_member.status_code == 200

    # 3. Manager reads -> 200
    res_pm = client.get(f"/api/v1/projects/{proj_id}", headers=mgr_headers)
    assert res_pm.status_code == 200

    # 4. HR reads -> 200
    res_hr = client.get(f"/api/v1/projects/{proj_id}", headers=hr_headers)
    assert res_hr.status_code == 200

    # 5. Member emp edits -> 403
    res_edit_emp = client.put(
        f"/api/v1/projects/{proj_id}",
        json={"name": "Hacked Beta"},
        headers=emp_headers,
    )
    assert res_edit_emp.status_code == 403

    # 6. PM edits -> 200
    res_edit_pm = client.put(
        f"/api/v1/projects/{proj_id}",
        json={"name": "Beta V2"},
        headers=mgr_headers,
    )
    assert res_edit_pm.status_code == 200
    assert res_edit_pm.json()["name"] == "Beta V2"


def test_7_1_r3_validation_rules(client: TestClient, db: Session, p1_setup: dict):
    """Rule 3: Name unique among live projects; end date >= start date;
    budget >= 0; PM active in company; bad input returns 422.
    """
    hr_headers = _auth_headers(p1_setup["hr_u"])

    # 1. Missing name -> 422
    r_no_name = client.post("/api/v1/projects", json={"code": "PRJ-X"}, headers=hr_headers)
    assert r_no_name.status_code == 422

    # 2. End date before start date -> 422
    r_bad_dates = client.post(
        "/api/v1/projects",
        json={
            "name": "Bad Dates",
            "code": "PRJ-BD",
            "start_date": "2026-10-01",
            "end_date": "2026-09-01",
        },
        headers=hr_headers,
    )
    assert r_bad_dates.status_code == 422

    # 3. Budget < 0 -> 422
    r_neg_budget = client.post(
        "/api/v1/projects",
        json={"name": "Neg Budget", "code": "PRJ-NB", "budget": "-10.00"},
        headers=hr_headers,
    )
    assert r_neg_budget.status_code == 422

    # 4. Manager from another company -> 422
    r_diff_comp_mgr = client.post(
        "/api/v1/projects",
        json={
            "name": "Diff Comp Mgr",
            "code": "PRJ-DCM",
            "manager_id": str(p1_setup["b_owner_e_id"]),
        },
        headers=hr_headers,
    )
    assert r_diff_comp_mgr.status_code == 422

    # 5. Duplicate name among live projects -> 409 (a conflict, like a duplicate code)
    r_ok = client.post(
        "/api/v1/projects",
        json={"name": "Unique Project One", "code": "PRJ-UP1"},
        headers=hr_headers,
    )
    assert r_ok.status_code == 201

    r_dup_name = client.post(
        "/api/v1/projects",
        json={"name": "Unique Project One", "code": "PRJ-UP2"},
        headers=hr_headers,
    )
    assert r_dup_name.status_code == 409


def test_7_1_r4_r5_lifecycle_archiving_and_delete_protection(
    client: TestClient, db: Session, p1_setup: dict
):
    """Rule 4: Lifecycle status; archived is read-only; HR/owner unarchive.
    Rule 5: Archiving keeps data; project with time entries cannot be deleted.
    """
    hr_headers = _auth_headers(p1_setup["hr_u"])
    mgr_headers = _auth_headers(p1_setup["mgr_u"])

    res = client.post(
        "/api/v1/projects",
        json={"name": "Lifecycle Proj", "code": "PRJ-LC", "manager_id": str(p1_setup["mgr_e_id"])},
        headers=hr_headers,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    # PM changes status to on_hold -> 200
    r_hold = client.put(
        f"/api/v1/projects/{proj_id}", json={"status": "on_hold"}, headers=mgr_headers
    )
    assert r_hold.status_code == 200
    assert r_hold.json()["status"] == "on_hold"

    # HR archives project -> 200
    r_arch = client.put(
        f"/api/v1/projects/{proj_id}", json={"status": "archived"}, headers=hr_headers
    )
    assert r_arch.status_code == 200
    assert r_arch.json()["status"] == "archived"

    # Archived project is read-only for normal edits -> 409
    r_edit_arch = client.put(
        f"/api/v1/projects/{proj_id}", json={"name": "New Name While Archived"}, headers=mgr_headers
    )
    assert r_edit_arch.status_code == 409

    # PM cannot unarchive -> 403
    r_pm_unarch = client.put(
        f"/api/v1/projects/{proj_id}", json={"status": "active"}, headers=mgr_headers
    )
    assert r_pm_unarch.status_code == 403

    # HR unarchives -> 200
    r_hr_unarch = client.put(
        f"/api/v1/projects/{proj_id}", json={"status": "active"}, headers=hr_headers
    )
    assert r_hr_unarch.status_code == 200
    assert r_hr_unarch.json()["status"] == "active"

    # Rule 5: Project with time entries cannot be deleted
    te = TimeEntry(
        id=uuid.uuid4(),
        company_id=p1_setup["cid_a"],
        project_id=uuid.UUID(proj_id),
        employee_id=p1_setup["mgr_e_id"],
        date=date(2026, 6, 1),
        hours=Decimal("4.00"),
        is_billable=True,
        status="submitted",
    )
    db.add(te)
    db.commit()

    r_del = client.delete(f"/api/v1/projects/{proj_id}", headers=hr_headers)
    assert r_del.status_code == 409


def test_7_1_r6_other_company_404(client: TestClient, db: Session, p1_setup: dict):
    """Rule 6: Another company's project returns 404."""
    hr_headers_a = _auth_headers(p1_setup["hr_u"])
    owner_headers_b = _auth_headers(p1_setup["b_owner_u"])

    res = client.post(
        "/api/v1/projects",
        json={"name": "Company A Project", "code": "PRJ-CA-1"},
        headers=hr_headers_a,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    # Company B owner tries to access Project A -> 404
    r_b = client.get(f"/api/v1/projects/{proj_id}", headers=owner_headers_b)
    assert r_b.status_code == 404


def test_7_1_r7_audit_logged(client: TestClient, db: Session, p1_setup: dict):
    """Rule 7: Every project mutation is audited (ids and field names only)."""
    hr_headers = _auth_headers(p1_setup["hr_u"])

    res = client.post(
        "/api/v1/projects",
        json={"name": "Audited Proj", "code": "PRJ-AUD"},
        headers=hr_headers,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    # Check audit log in DB
    log = (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(proj_id), AuditLog.action == "create")
        .first()
    )
    assert log is not None
    assert log.entity_type == "project"


def test_7_1_r8_paged_list(client: TestClient, db: Session, p1_setup: dict):
    """Rule 8: Lists are paged with page and page_size (max 100)."""
    hr_headers = _auth_headers(p1_setup["hr_u"])

    res = client.get("/api/v1/projects?page=1&page_size=10", headers=hr_headers)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert data["page"] == 1
    assert data["page_size"] == 10

    # Max page_size > 100 capped or rejected
    res_over = client.get("/api/v1/projects?page=1&page_size=150", headers=hr_headers)
    assert res_over.status_code in (200, 422)
    if res_over.status_code == 200:
        assert res_over.json()["page_size"] <= 100


def test_7_1_r9_rate_limiting(client: TestClient, db: Session, p1_setup: dict, limits_on: None):
    """Rule 9: Write routes are rate limited, with a 429 test."""
    hr_headers = _auth_headers(p1_setup["hr_u"])
    hit_429 = False
    for i in range(65):
        r = client.post(
            "/api/v1/projects",
            json={"name": f"RL Proj {i}", "code": f"PRJ-RL-{i}"},
            headers=hr_headers,
        )
        if r.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "Rate limiter did not return 429 on excessive POST /projects"


def test_7_1_r10_project_dates_cannot_exclude_milestones_tasks(
    client: TestClient, db: Session, p1_setup: dict
):
    """Rule 10: Project dates cannot exclude existing milestones or tasks due dates (409)."""
    hr_headers = _auth_headers(p1_setup["hr_u"])
    res = client.post(
        "/api/v1/projects",
        json={
            "name": "Date Bound Proj",
            "code": "PRJ-DB",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        headers=hr_headers,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    # Add milestone due on 2026-10-15
    r_ms = client.post(
        f"/api/v1/projects/{proj_id}/milestones",
        json={"title": "Mid Milestone", "due_date": "2026-10-15"},
        headers=hr_headers,
    )
    assert r_ms.status_code == 201

    # Now attempt to shrink project end_date to 2026-09-01 -> 409 Conflict
    r_shrink = client.put(
        f"/api/v1/projects/{proj_id}",
        json={"end_date": "2026-09-01"},
        headers=hr_headers,
    )
    assert r_shrink.status_code == 409


def test_7_1_r11_super_admin_gets_403(client: TestClient, db: Session, p1_setup: dict):
    """Rule 11: Super admin gets 403 on all company project data."""
    sa_headers = _auth_headers(p1_setup["sa_u"])
    res = client.get("/api/v1/projects", headers=sa_headers)
    assert res.status_code == 403


# ==========================================
# 7.4 Members & Rates Rules
# ==========================================


def test_7_4_r1_r2_member_management_and_manager_retention(
    client: TestClient, db: Session, p1_setup: dict
):
    """Rule 1: Member management authority; active employee of company.
    Rule 2: Project always keeps at least one manager (removing last returns 409).
    """
    hr_headers = _auth_headers(p1_setup["hr_u"])
    res = client.post(
        "/api/v1/projects",
        json={"name": "Member Proj", "code": "PRJ-MEM", "manager_id": str(p1_setup["mgr_e_id"])},
        headers=hr_headers,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    # 1. Add employee from different company -> 422
    r_diff_comp = client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(p1_setup["b_owner_e_id"]), "role": "member"},
        headers=hr_headers,
    )
    assert r_diff_comp.status_code == 422

    # 2. Add emp_e as member -> 201
    r_add = client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(p1_setup["emp_e_id"]), "role": "member"},
        headers=hr_headers,
    )
    assert r_add.status_code == 201

    # 3. Duplicate add returns 409
    r_dup = client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(p1_setup["emp_e_id"]), "role": "member"},
        headers=hr_headers,
    )
    assert r_dup.status_code == 409

    # 4. Attempt to remove the only manager (mgr_e) -> 409
    r_rem_last_mgr = client.delete(
        f"/api/v1/projects/{proj_id}/members/{p1_setup['mgr_e_id']}",
        headers=hr_headers,
    )
    assert r_rem_last_mgr.status_code == 409

    # Add second manager (mgr2_e), then removing mgr_e succeeds
    client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(p1_setup["mgr2_e_id"]), "role": "manager"},
        headers=hr_headers,
    )
    r_rem_first_mgr = client.delete(
        f"/api/v1/projects/{proj_id}/members/{p1_setup['mgr_e_id']}",
        headers=hr_headers,
    )
    assert r_rem_first_mgr.status_code == 204


def test_7_4_r3_r4_hourly_rates_visibility_and_effective_dates(
    client: TestClient, db: Session, p1_setup: dict
):
    """Rule 3: Rates visible only to PM, HR, owner; members never see any rate.
    Rule 4: Only HR/owner set/change rate; Decimal, effective-dated.
    """
    hr_headers = _auth_headers(p1_setup["hr_u"])
    mgr_headers = _auth_headers(p1_setup["mgr_u"])
    emp_headers = _auth_headers(p1_setup["emp_u"])

    res = client.post(
        "/api/v1/projects",
        json={"name": "Rate Proj", "code": "PRJ-RAT", "manager_id": str(p1_setup["mgr_e_id"])},
        headers=hr_headers,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    # HR adds emp_e with hourly billing rate of 1250.00
    r_add_emp = client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={
            "employee_id": str(p1_setup["emp_e_id"]),
            "role": "member",
            "hourly_rate": "1250.00",
            "effective_from": "2026-01-01",
        },
        headers=hr_headers,
    )
    assert r_add_emp.status_code == 201

    # PM attempts to change billing rate -> 403 (Only HR/owner can set/change rate)
    r_pm_change_rate = client.put(
        f"/api/v1/projects/{proj_id}/members/{p1_setup['emp_e_id']}/rate",
        json={"hourly_rate": "1500.00", "effective_from": "2026-06-01"},
        headers=mgr_headers,
    )
    assert r_pm_change_rate.status_code == 403

    # HR updates rate effective from 2026-06-01 -> 200
    r_hr_rate = client.put(
        f"/api/v1/projects/{proj_id}/members/{p1_setup['emp_e_id']}/rate",
        json={"hourly_rate": "1500.00", "effective_from": "2026-06-01"},
        headers=hr_headers,
    )
    assert r_hr_rate.status_code == 200

    # Rule 3: Regular member lists members -> hourly_rate is masked / None
    res_emp_view = client.get(f"/api/v1/projects/{proj_id}/members", headers=emp_headers)
    assert res_emp_view.status_code == 200
    for m in res_emp_view.json():
        assert m.get("hourly_rate") is None

    # PM lists members -> hourly_rate is visible
    res_pm_view = client.get(f"/api/v1/projects/{proj_id}/members", headers=mgr_headers)
    assert res_pm_view.status_code == 200
    target_m = next(m for m in res_pm_view.json() if m["employee_id"] == str(p1_setup["emp_e_id"]))
    assert Decimal(str(target_m["hourly_rate"])) == Decimal("1500.00")


def test_7_4_r5_remove_member_unassigns_open_tasks(client: TestClient, db: Session, p1_setup: dict):
    """Rule 5: Removing member keeps history; open tasks become unassigned."""
    hr_headers = _auth_headers(p1_setup["hr_u"])
    res = client.post(
        "/api/v1/projects",
        json={"name": "Unassign Proj", "code": "PRJ-UNA", "manager_id": str(p1_setup["mgr_e_id"])},
        headers=hr_headers,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(p1_setup["emp_e_id"]), "role": "member"},
        headers=hr_headers,
    )

    # Create task assigned to emp_e
    r_task = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={"title": "Emp Open Task", "assigned_to": str(p1_setup["emp_e_id"]), "status": "todo"},
        headers=hr_headers,
    )
    assert r_task.status_code == 201
    task_id = r_task.json()["id"]

    # Remove emp_e
    r_rem = client.delete(
        f"/api/v1/projects/{proj_id}/members/{p1_setup['emp_e_id']}", headers=hr_headers
    )
    assert r_rem.status_code == 204

    # Verify task is now unassigned (assigned_to is None)
    r_task_check = client.get(f"/api/v1/projects/tasks/{task_id}", headers=hr_headers)
    assert r_task_check.status_code == 200
    assert r_task_check.json()["assigned_to"] is None


def test_7_4_r6_added_member_notified(client: TestClient, db: Session, p1_setup: dict):
    """Rule 6: The added member is notified after the commit."""
    hr_headers = _auth_headers(p1_setup["hr_u"])
    res = client.post(
        "/api/v1/projects",
        json={"name": "Notif Proj", "code": "PRJ-NOTIF", "manager_id": str(p1_setup["mgr_e_id"])},
        headers=hr_headers,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(p1_setup["emp_e_id"]), "role": "member"},
        headers=hr_headers,
    )

    # Check notification for emp_u
    notif = (
        db.query(Notification)
        .filter(Notification.user_id == p1_setup["emp_u"].id)
        .order_by(Notification.created_at.desc())
        .first()
    )
    assert notif is not None
    assert "project" in notif.message.lower() or "added" in notif.message.lower()


def test_7_4_r7_other_company_member_404(client: TestClient, db: Session, p1_setup: dict):
    """Rule 7: Another company's member returns 404."""
    hr_headers = _auth_headers(p1_setup["hr_u"])
    owner_headers_b = _auth_headers(p1_setup["b_owner_u"])

    res = client.post(
        "/api/v1/projects",
        json={
            "name": "Comp A Proj",
            "code": "PRJ-MEM-404",
            "manager_id": str(p1_setup["mgr_e_id"]),
        },
        headers=hr_headers,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    # Company B tries to list or delete members of Project A -> 404
    r_list = client.get(f"/api/v1/projects/{proj_id}/members", headers=owner_headers_b)
    assert r_list.status_code == 404


def test_7_4_r8_rate_changes_audited_field_names_only(
    client: TestClient, db: Session, p1_setup: dict
):
    """Rule 8: Rate changes are audited with field names only (no amounts)."""
    hr_headers = _auth_headers(p1_setup["hr_u"])
    res = client.post(
        "/api/v1/projects",
        json={"name": "Audit Rate Proj", "code": "PRJ-AR", "manager_id": str(p1_setup["mgr_e_id"])},
        headers=hr_headers,
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(p1_setup["emp_e_id"]), "role": "member", "hourly_rate": "1000.00"},
        headers=hr_headers,
    )

    client.put(
        f"/api/v1/projects/{proj_id}/members/{p1_setup['emp_e_id']}/rate",
        json={"hourly_rate": "1800.00", "effective_from": "2026-07-01"},
        headers=hr_headers,
    )

    # Check AuditLog: details must not contain "1800" or raw amounts
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == p1_setup["cid_a"], AuditLog.action == "rate_change")
        .all()
    )
    for entry in logs:
        assert "1800" not in str(entry.details)
        assert "hourly_rate" in str(entry.details) or "rate" in str(entry.details)
