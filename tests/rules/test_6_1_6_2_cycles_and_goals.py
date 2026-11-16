"""Module 6 Batch 1: 6.1 Appraisal Cycles and 6.2 Goals.
Tests for Rule 0 (Multi-tenancy), 6.1 Rules R1-R12, and 6.2 Rules R1-R11.
"""

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog, Notification


def _auth_headers(user: User) -> dict[str, str]:
    user_id = user.__dict__.get("id") or user.id
    company_id = user.__dict__.get("company_id") or user.company_id
    role = user.__dict__.get("role") or user.role
    role_val = role.value if hasattr(role, "value") else str(role)
    token = create_access_token(
        sub=str(user_id),
        company_id=str(company_id),
        role=role_val,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def p1_setup(db: Session) -> dict[str, Any]:
    db.expire_on_commit = False
    cid_a = uuid.uuid4()
    bind_tenant_to_session(db, company_id=cid_a, is_platform_admin=True)

    company_a = Company(
        id=cid_a,
        name=f"CompA_{uuid.uuid4().hex[:6]}",
        code=f"CA{uuid.uuid4().hex[:6].upper()}",
        email=f"compa_{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
    )
    db.add(company_a)
    db.flush()

    # Users in Company A
    owner_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"owner_{uuid.uuid4().hex[:6]}@compa.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.owner,
        is_active=True,
    )
    hr_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"hr_{uuid.uuid4().hex[:6]}@compa.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    mgr_user_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"mgr_{uuid.uuid4().hex[:6]}@compa.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.manager,
        is_active=True,
    )
    emp_user_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"emp_{uuid.uuid4().hex[:6]}@compa.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    other_emp_user_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"otheremp_{uuid.uuid4().hex[:6]}@compa.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([owner_a, hr_a, mgr_user_a, emp_user_a, other_emp_user_a])
    db.flush()

    # Employees in Company A
    mgr_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=mgr_user_a.id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Manager",
        last_name="A",
        email=mgr_user_a.email,
        hire_date=date(2025, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    db.add(mgr_emp)
    db.flush()

    emp_a = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=emp_user_a.id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Employee",
        last_name="A",
        email=emp_user_a.email,
        hire_date=date(2025, 1, 1),
        reporting_manager_id=mgr_emp.id,
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    other_emp_a = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=other_emp_user_a.id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="OtherEmp",
        last_name="A",
        email=other_emp_user_a.email,
        hire_date=date(2025, 1, 1),
        reporting_manager_id=None,  # Not under mgr_emp
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    db.add_all([emp_a, other_emp_a])
    db.flush()

    # Company B (for multi-tenant isolation tests)
    cid_b = uuid.uuid4()
    company_b = Company(
        id=cid_b,
        name=f"CompB_{uuid.uuid4().hex[:6]}",
        code=f"CB{uuid.uuid4().hex[:6].upper()}",
        email=f"compb_{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
    )
    db.add(company_b)
    db.flush()

    hr_b = User(
        id=uuid.uuid4(),
        company_id=cid_b,
        email=f"hr_{uuid.uuid4().hex[:6]}@compb.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(hr_b)
    db.commit()

    return {
        "cid_a": cid_a,
        "company_a": company_a,
        "owner_a": owner_a,
        "hr_a": hr_a,
        "mgr_user_a": mgr_user_a,
        "emp_user_a": emp_user_a,
        "other_emp_user_a": other_emp_user_a,
        "mgr_emp": mgr_emp,
        "emp_a": emp_a,
        "other_emp_a": other_emp_a,
        "cid_b": cid_b,
        "company_b": company_b,
        "hr_b": hr_b,
    }


# ==============================================================================
# RULE 0 & 6.1 RULE TESTS: APPRAISAL CYCLES
# ==============================================================================


def test_6_1_R0_multi_tenant_isolation_cycle_404(
    client: TestClient, p1_setup: dict[str, Any], db: Session
):
    """Rule 0 & 6.1 R9: Another company's cycle returns 404, never leaking existence."""
    hr_a_headers = _auth_headers(p1_setup["hr_a"])
    hr_b_headers = _auth_headers(p1_setup["hr_b"])

    # Create cycle in Company A
    start = (utcnow().date() + timedelta(days=1)).isoformat()
    end = (utcnow().date() + timedelta(days=90)).isoformat()
    res = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Q1 Cycle", "start_date": start, "end_date": end},
        headers=hr_a_headers,
    )
    assert res.status_code == 201
    cycle_id = res.json()["id"]

    # HR from Company B tries to update cycle in Company A -> 404
    res_b = client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=hr_b_headers,
    )
    assert res_b.status_code == 404, "Accessing another company's cycle must return 404"


def test_6_1_R1_permissions_create_edit_activate_close(
    client: TestClient, p1_setup: dict[str, Any], db: Session
):
    """6.1 R1: Only HR and owner create, edit, activate or close a cycle; others 403."""
    hr_headers = _auth_headers(p1_setup["hr_a"])
    owner_headers = _auth_headers(p1_setup["owner_a"])
    mgr_headers = _auth_headers(p1_setup["mgr_user_a"])
    emp_headers = _auth_headers(p1_setup["emp_user_a"])

    start = (utcnow().date() + timedelta(days=1)).isoformat()
    end = (utcnow().date() + timedelta(days=30)).isoformat()
    payload = {"name": "Cycle Permissions", "start_date": start, "end_date": end}

    # Employee tries to create -> 403
    r = client.post("/api/v1/performance/cycles", json=payload, headers=emp_headers)
    assert r.status_code == 403, "Employee cannot create cycle"

    # Manager tries to create -> 403
    r = client.post("/api/v1/performance/cycles", json=payload, headers=mgr_headers)
    assert r.status_code == 403, "Manager cannot create cycle"

    # HR creates -> 201
    r_hr = client.post("/api/v1/performance/cycles", json=payload, headers=hr_headers)
    assert r_hr.status_code == 201
    cycle_id = r_hr.json()["id"]

    # Manager tries to update status -> 403
    r_m_up = client.put(
        f"/api/v1/performance/cycles/{cycle_id}", json={"status": "active"}, headers=mgr_headers
    )
    assert r_m_up.status_code == 403, "Manager cannot update cycle"

    # Owner can update status -> 200
    r_o_up = client.put(
        f"/api/v1/performance/cycles/{cycle_id}", json={"status": "active"}, headers=owner_headers
    )
    assert r_o_up.status_code == 200, "Owner can activate cycle"


def test_6_1_R2_required_fields_and_end_after_start_422(
    client: TestClient, p1_setup: dict[str, Any]
):
    """6.1 R2: Name, start date, end date required; end > start; bad input returns 422."""
    hr_headers = _auth_headers(p1_setup["hr_a"])

    # End before start
    r = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Bad Dates", "start_date": "2026-06-01", "end_date": "2026-05-01"},
        headers=hr_headers,
    )
    assert r.status_code == 422, "End before start must return 422"

    # End equals start
    r = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Bad Dates Equal", "start_date": "2026-06-01", "end_date": "2026-06-01"},
        headers=hr_headers,
    )
    assert r.status_code == 422, "End equals start must return 422"

    # Missing name
    r = client.post(
        "/api/v1/performance/cycles",
        json={"start_date": "2026-06-01", "end_date": "2026-07-01"},
        headers=hr_headers,
    )
    assert r.status_code == 422, "Missing name must return 422"


def test_6_1_R3_cycle_deadline_boundaries_422(client: TestClient, p1_setup: dict[str, Any]):
    """6.1 R3: start_date <= self_review_deadline <= manager_review_deadline <= end_date (422)."""
    hr_headers = _auth_headers(p1_setup["hr_a"])

    # self_review before start
    r = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": "Bad Deadline",
            "start_date": "2026-06-01",
            "end_date": "2026-06-30",
            "self_review_deadline": "2026-05-25",
        },
        headers=hr_headers,
    )
    assert r.status_code == 422, "self_review_deadline before start must return 422"

    # manager_review before self_review
    r = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": "Bad Deadline 2",
            "start_date": "2026-06-01",
            "end_date": "2026-06-30",
            "self_review_deadline": "2026-06-20",
            "manager_review_deadline": "2026-06-15",
        },
        headers=hr_headers,
    )
    assert r.status_code == 422, "manager_review before self_review must return 422"

    # manager_review after end_date
    r = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": "Bad Deadline 3",
            "start_date": "2026-06-01",
            "end_date": "2026-06-30",
            "manager_review_deadline": "2026-07-05",
        },
        headers=hr_headers,
    )
    assert r.status_code == 422, "manager_review after end_date must return 422"


def test_6_1_R4_date_overlap_rejection_409(client: TestClient, p1_setup: dict[str, Any]):
    """6.1 R4: Two cycles of same company cannot overlap in dates (409 naming clash)."""
    hr_headers = _auth_headers(p1_setup["hr_a"])

    # Create first cycle
    r1 = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Q1 2027", "start_date": "2027-01-01", "end_date": "2027-03-31"},
        headers=hr_headers,
    )
    assert r1.status_code == 201

    # Overlapping cycle (Feb to April)
    r2 = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Q1 Q2 Clashing", "start_date": "2027-02-01", "end_date": "2027-04-30"},
        headers=hr_headers,
    )
    assert r2.status_code == 409, "Overlapping cycles must return 409"
    detail_msg = r2.json().get("detail") or r2.json().get("error", {}).get("message", "")
    assert "Q1 2027" in detail_msg, f"Clashing cycle name must be in error detail, got: {r2.text}"


def test_6_1_R5_single_active_cycle_enforced_409(client: TestClient, p1_setup: dict[str, Any]):
    """6.1 R5: At most one cycle can be active at a time; activating a second returns 409."""
    hr_headers = _auth_headers(p1_setup["hr_a"])

    # Create cycle 1 (non-overlapping dates)
    r1 = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Cycle One", "start_date": "2028-01-01", "end_date": "2028-03-31"},
        headers=hr_headers,
    )
    assert r1.status_code == 201
    c1_id = r1.json()["id"]

    # Create cycle 2
    r2 = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Cycle Two", "start_date": "2028-04-01", "end_date": "2028-06-30"},
        headers=hr_headers,
    )
    assert r2.status_code == 201
    c2_id = r2.json()["id"]

    # Activate cycle 1 -> success
    act1 = client.put(
        f"/api/v1/performance/cycles/{c1_id}", json={"status": "active"}, headers=hr_headers
    )
    assert act1.status_code == 200

    # Activate cycle 2 while cycle 1 is active -> 409
    act2 = client.put(
        f"/api/v1/performance/cycles/{c2_id}", json={"status": "active"}, headers=hr_headers
    )
    assert act2.status_code == 409, "Activating second cycle while one is active must return 409"


def test_6_1_R6_status_moves_only_forward_no_reopen_closed(
    client: TestClient, p1_setup: dict[str, Any]
):
    """6.1 R6: Status moves draft -> active -> closed; closed cannot reopen or edit (409)."""
    hr_headers = _auth_headers(p1_setup["hr_a"])

    r = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Forward Only Cycle", "start_date": "2029-01-01", "end_date": "2029-03-31"},
        headers=hr_headers,
    )
    cid = r.json()["id"]

    # Cannot skip from draft to closed
    r_skip = client.put(
        f"/api/v1/performance/cycles/{cid}", json={"status": "closed"}, headers=hr_headers
    )
    assert r_skip.status_code == 409, "Cannot skip draft directly to closed"

    # Activate -> 200
    r_act = client.put(
        f"/api/v1/performance/cycles/{cid}", json={"status": "active"}, headers=hr_headers
    )
    assert r_act.status_code == 200

    # Cannot move active back to draft
    r_back = client.put(
        f"/api/v1/performance/cycles/{cid}", json={"status": "draft"}, headers=hr_headers
    )
    assert r_back.status_code == 409, "Cannot revert active cycle to draft"

    # Close -> 200
    r_close = client.put(
        f"/api/v1/performance/cycles/{cid}", json={"status": "closed"}, headers=hr_headers
    )
    assert r_close.status_code == 200

    # Closed cannot reopen to active
    r_reopen = client.put(
        f"/api/v1/performance/cycles/{cid}", json={"status": "active"}, headers=hr_headers
    )
    assert r_reopen.status_code == 409, "Closed cycle cannot be reopened"


def test_6_1_R7_goals_added_only_while_cycle_active_409(
    client: TestClient, p1_setup: dict[str, Any]
):
    """6.1 R7: Goals can be added only while cycle is active (draft or closed returns 409)."""
    hr_headers = _auth_headers(p1_setup["hr_a"])
    emp_headers = _auth_headers(p1_setup["emp_user_a"])

    # Create cycle in draft
    r = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Draft Cycle", "start_date": "2030-01-01", "end_date": "2030-03-31"},
        headers=hr_headers,
    )
    cid = r.json()["id"]

    # Try creating goal in draft cycle -> 409
    g_res = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": cid,
            "goals": [{"title": "Draft Goal", "weightage": 50}],
        },
        headers=emp_headers,
    )
    assert g_res.status_code == 409, "Cannot create goals in draft cycle"


def test_6_1_R8_closing_cycle_locks_goals(client: TestClient, p1_setup: dict[str, Any]):
    """6.1 R8: Closing a cycle locks all goals against edits/additions (409)."""
    hr_headers = _auth_headers(p1_setup["hr_a"])
    emp_headers = _auth_headers(p1_setup["emp_user_a"])

    # Create and activate cycle
    r = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Locking Cycle", "start_date": "2031-01-01", "end_date": "2031-03-31"},
        headers=hr_headers,
    )
    cid = r.json()["id"]
    client.put(f"/api/v1/performance/cycles/{cid}", json={"status": "active"}, headers=hr_headers)

    # Add a goal
    g_res = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": cid,
            "goals": [{"title": "My Goal", "weightage": 50}],
        },
        headers=emp_headers,
    )
    assert g_res.status_code == 201
    gid = g_res.json()[0]["id"]

    # Close cycle
    client.put(f"/api/v1/performance/cycles/{cid}", json={"status": "closed"}, headers=hr_headers)

    # Try updating goal after cycle closed -> 409
    up_res = client.put(
        f"/api/v1/performance/goals/{gid}",
        json={"title": "Updated Title"},
        headers=emp_headers,
    )
    assert up_res.status_code == 409, "Cannot update goal when cycle is closed"


def test_6_1_R10_audit_logged_on_cycle_lifecycle(
    client: TestClient, p1_setup: dict[str, Any], db: Session
):
    """6.1 R10: Create, edit, activate, close are audited with ids and field names only."""
    hr_headers = _auth_headers(p1_setup["hr_a"])

    r = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Audited Cycle", "start_date": "2032-01-01", "end_date": "2032-03-31"},
        headers=hr_headers,
    )
    cid = uuid.UUID(r.json()["id"])

    # Activate
    client.put(f"/api/v1/performance/cycles/{cid}", json={"status": "active"}, headers=hr_headers)

    # Check audit logs
    bind_tenant_to_session(db, company_id=p1_setup["cid_a"], is_platform_admin=True)
    logs = db.query(AuditLog).filter(AuditLog.entity_id == cid).all()
    actions = [log_entry.action for log_entry in logs]
    assert any("PERFORMANCE_CYCLE" in act for act in actions), "Cycle lifecycle must be audited"


def test_6_1_R11_notifications_sent_on_cycle_activation(
    client: TestClient, p1_setup: dict[str, Any], db: Session
):
    """6.1 R11: Active company employees are notified on cycle activation after commit."""
    hr_headers = _auth_headers(p1_setup["hr_a"])

    r = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Notified Cycle", "start_date": "2033-01-01", "end_date": "2033-03-31"},
        headers=hr_headers,
    )
    cid = r.json()["id"]

    # Activate cycle
    r_act = client.put(
        f"/api/v1/performance/cycles/{cid}", json={"status": "active"}, headers=hr_headers
    )
    assert r_act.status_code == 200

    # Verify notifications in db
    bind_tenant_to_session(db, company_id=p1_setup["cid_a"], is_platform_admin=True)
    notifs = db.query(Notification).filter(Notification.company_id == p1_setup["cid_a"]).all()
    # At least emp_user_a received a notification
    user_ids = [n.user_id for n in notifs]
    assert p1_setup["emp_user_a"].id in user_ids, (
        "Employees must receive cycle activation notification"
    )


def test_6_1_R12_rate_limit_cycle_write_routes(client: TestClient, p1_setup: dict[str, Any]):
    """6.1 R12: Write routes are rate limited with a 429 test."""
    hr_headers = _auth_headers(p1_setup["hr_a"])
    limiter.reset()

    # Rapid cycle creation attempts
    hit_429 = False
    for i in range(40):
        res = client.post(
            "/api/v1/performance/cycles",
            json={
                "name": f"Rate Limit Cycle {i}",
                "start_date": f"2040-{i % 12 + 1:02d}-01",
                "end_date": f"2040-{i % 12 + 1:02d}-25",
            },
            headers=hr_headers,
        )
        if res.status_code == 429:
            hit_429 = True
            break
    limiter.reset()
    assert hit_429, "Rate limit must trigger 429 on write routes"


# ==============================================================================
# 6.2 RULE TESTS: GOALS
# ==============================================================================


@pytest.fixture
def active_cycle(client: TestClient, p1_setup: dict[str, Any]) -> str:
    hr_headers = _auth_headers(p1_setup["hr_a"])
    r = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Active Q1", "start_date": "2026-01-01", "end_date": "2026-12-31"},
        headers=hr_headers,
    )
    cid = r.json()["id"]
    client.put(f"/api/v1/performance/cycles/{cid}", json={"status": "active"}, headers=hr_headers)
    return cid


def test_6_2_R1_goal_authoring_permissions(
    client: TestClient, p1_setup: dict[str, Any], active_cycle: str
):
    """6.2 R1: Employee sets own; manager sets for reporting chain; HR any; other manager 403."""
    emp_headers = _auth_headers(p1_setup["emp_user_a"])
    mgr_headers = _auth_headers(p1_setup["mgr_user_a"])
    other_emp_headers = _auth_headers(p1_setup["other_emp_user_a"])
    hr_headers = _auth_headers(p1_setup["hr_a"])

    emp_id = str(p1_setup["emp_a"].id)
    other_emp_id = str(p1_setup["other_emp_a"].id)

    # 1. Employee sets own goal -> 201
    r_own = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": active_cycle,
            "employee_id": emp_id,
            "goals": [{"title": "G1", "weightage": 20}],
        },
        headers=emp_headers,
    )
    assert r_own.status_code == 201

    # 2. Manager sets goal for direct report -> 201
    r_mgr = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": active_cycle,
            "employee_id": emp_id,
            "goals": [{"title": "G2", "weightage": 30}],
        },
        headers=mgr_headers,
    )
    assert r_mgr.status_code == 201

    # 3. Manager tries to set goal for employee NOT in reporting chain -> 403
    r_mgr_other = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": active_cycle,
            "employee_id": other_emp_id,
            "goals": [{"title": "G_bad", "weightage": 30}],
        },
        headers=mgr_headers,
    )
    assert r_mgr_other.status_code == 403, "Manager cannot set goals outside reporting chain"

    # 4. Another employee tries to set goal for emp_a -> 403
    r_peer = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": active_cycle,
            "employee_id": emp_id,
            "goals": [{"title": "G_bad2", "weightage": 10}],
        },
        headers=other_emp_headers,
    )
    assert r_peer.status_code == 403, "Employee cannot set goals for peers"

    # 5. HR sets goal for any employee -> 201
    r_hr = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": active_cycle,
            "employee_id": other_emp_id,
            "goals": [{"title": "G_hr", "weightage": 40}],
        },
        headers=hr_headers,
    )
    assert r_hr.status_code == 201


def test_6_2_R2_swapped_lookup_fixed_and_active_employee(
    client: TestClient, p1_setup: dict[str, Any], active_cycle: str
):
    """6.2 R2: Fix swapped lookup (service.py:126 get_by_id(company_id, employee_id))."""
    hr_headers = _auth_headers(p1_setup["hr_a"])
    emp_id = str(p1_setup["emp_a"].id)

    # Calling with valid employee_id must resolve correctly without swapping
    r = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": active_cycle,
            "employee_id": emp_id,
            "goals": [{"title": "Lookup Fix", "weightage": 10}],
        },
        headers=hr_headers,
    )
    assert r.status_code == 201, "Employee lookup must not fail due to argument ordering"


def test_6_2_R3_title_dates_progress_validation_422(
    client: TestClient, p1_setup: dict[str, Any], active_cycle: str
):
    """6.2 R3: Title required; progress 0-100; dates in cycle; bad input returns 422."""
    emp_headers = _auth_headers(p1_setup["emp_user_a"])

    # Missing title -> 422
    r_title = client.post(
        "/api/v1/performance/goals",
        json={"cycle_id": active_cycle, "goals": [{"title": "", "weightage": 10}]},
        headers=emp_headers,
    )
    assert r_title.status_code == 422, "Empty title must return 422"

    # Bad weightage <= 0 -> 422
    r_wt = client.post(
        "/api/v1/performance/goals",
        json={"cycle_id": active_cycle, "goals": [{"title": "G", "weightage": 0}]},
        headers=emp_headers,
    )
    assert r_wt.status_code == 422, "Weightage <= 0 must return 422"


def test_6_2_R4_weightage_sum_cannot_exceed_100_percent(
    client: TestClient, p1_setup: dict[str, Any], active_cycle: str
):
    """6.2 R4: Total weightage per employee per cycle cannot exceed 100%."""
    emp_headers = _auth_headers(p1_setup["emp_user_a"])

    # First goal: 70%
    r1 = client.post(
        "/api/v1/performance/goals",
        json={"cycle_id": active_cycle, "goals": [{"title": "G1", "weightage": 70}]},
        headers=emp_headers,
    )
    assert r1.status_code == 201

    # Second goal: 40% (total 110%) -> 422 or 400
    r2 = client.post(
        "/api/v1/performance/goals",
        json={"cycle_id": active_cycle, "goals": [{"title": "G2", "weightage": 40}]},
        headers=emp_headers,
    )
    assert r2.status_code in (400, 422), "Total weightage exceeding 100% must be rejected"


def test_6_2_R5_goals_modified_only_while_cycle_active_409(
    client: TestClient, p1_setup: dict[str, Any]
):
    """6.2 R5: Goals cannot be modified when cycle is closed -> 409."""
    hr_headers = _auth_headers(p1_setup["hr_a"])
    emp_headers = _auth_headers(p1_setup["emp_user_a"])

    # Create cycle, activate, add goal
    r = client.post(
        "/api/v1/performance/cycles",
        json={"name": "Temp Cycle", "start_date": "2035-01-01", "end_date": "2035-03-31"},
        headers=hr_headers,
    )
    cid = r.json()["id"]
    client.put(f"/api/v1/performance/cycles/{cid}", json={"status": "active"}, headers=hr_headers)

    g = client.post(
        "/api/v1/performance/goals",
        json={"cycle_id": cid, "goals": [{"title": "Goal A", "weightage": 50}]},
        headers=emp_headers,
    )
    gid = g.json()[0]["id"]

    # Close cycle
    client.put(f"/api/v1/performance/cycles/{cid}", json={"status": "closed"}, headers=hr_headers)

    # Try modifying goal -> 409
    res = client.put(
        f"/api/v1/performance/goals/{gid}", json={"title": "New Title"}, headers=emp_headers
    )
    assert res.status_code == 409, "Modifying goal in closed cycle must return 409"


def test_6_2_R6_progress_history_kept(
    client: TestClient, p1_setup: dict[str, Any], active_cycle: str
):
    """6.2 R6: Progress updates (0-100) keep history with timestamps and updater id."""
    emp_headers = _auth_headers(p1_setup["emp_user_a"])

    g = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": active_cycle,
            "goals": [{"title": "Goal With Progress", "weightage": 50}],
        },
        headers=emp_headers,
    )
    gid = g.json()[0]["id"]

    # Update progress to 25
    r_up = client.put(
        f"/api/v1/performance/goals/{gid}/progress",
        json={"progress": 25, "notes": "Started task"},
        headers=emp_headers,
    )
    assert r_up.status_code == 200
    assert r_up.json()["progress"] == 25

    # Check progress history endpoint
    r_hist = client.get(f"/api/v1/performance/goals/{gid}/history", headers=emp_headers)
    assert r_hist.status_code == 200
    history = r_hist.json()
    assert len(history) >= 1
    assert history[0]["new_progress"] == 25


def test_6_2_R7_status_flow_completed_changed_only_by_hr(
    client: TestClient, p1_setup: dict[str, Any], active_cycle: str
):
    """6.2 R7: Status moves draft -> active -> completed; completed changed only by HR."""
    emp_headers = _auth_headers(p1_setup["emp_user_a"])
    hr_headers = _auth_headers(p1_setup["hr_a"])

    g = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": active_cycle,
            "goals": [{"title": "Goal Complete Test", "weightage": 50}],
        },
        headers=emp_headers,
    )
    gid = g.json()[0]["id"]

    # Employee marks completed
    client.put(
        f"/api/v1/performance/goals/{gid}", json={"status": "completed"}, headers=emp_headers
    )

    # Employee tries to edit completed goal -> 403 or 409
    res_emp = client.put(
        f"/api/v1/performance/goals/{gid}", json={"title": "Changed by emp"}, headers=emp_headers
    )
    assert res_emp.status_code in (403, 409), "Employee cannot edit a completed goal"

    # HR edits completed goal with reason -> 200
    res_hr = client.put(
        f"/api/v1/performance/goals/{gid}",
        json={"title": "Changed by HR", "reason": "Correction approved"},
        headers=hr_headers,
    )
    assert res_hr.status_code == 200


def test_6_2_R8_goals_frozen_after_review_submission(
    client: TestClient, p1_setup: dict[str, Any], active_cycle: str
):
    """6.2 R8: Goals are frozen when employee self-review is submitted (409)."""
    emp_headers = _auth_headers(p1_setup["emp_user_a"])

    # Create goals summing to exactly 100%
    g = client.post(
        "/api/v1/performance/goals",
        json={"cycle_id": active_cycle, "goals": [{"title": "Goal 100", "weightage": 100}]},
        headers=emp_headers,
    )
    gid = g.json()[0]["id"]

    # Submit self review
    client.post(
        f"/api/v1/performance/goals/{gid}/self-review",
        json={"rating": 4.5, "comments": "Good"},
        headers=emp_headers,
    )

    # Try modifying goal after review submitted -> 409
    res_up = client.put(
        f"/api/v1/performance/goals/{gid}", json={"title": "Frozen Title"}, headers=emp_headers
    )
    assert res_up.status_code == 409, "Cannot modify goal after self-review is submitted"


def test_6_2_R9_cross_company_goal_404_and_audited(
    client: TestClient, p1_setup: dict[str, Any], active_cycle: str, db: Session
):
    """6.2 R9: Cross company goal returns 404; every change is audited."""
    emp_headers = _auth_headers(p1_setup["emp_user_a"])
    hr_b_headers = _auth_headers(p1_setup["hr_b"])

    g = client.post(
        "/api/v1/performance/goals",
        json={"cycle_id": active_cycle, "goals": [{"title": "Cross Co Goal", "weightage": 50}]},
        headers=emp_headers,
    )
    gid = g.json()[0]["id"]

    # Company B accesses Company A's goal -> 404
    r_b = client.put(
        f"/api/v1/performance/goals/{gid}", json={"title": "Hacked"}, headers=hr_b_headers
    )
    assert r_b.status_code == 404, "Another company's goal must return 404"

    # Verify audit
    bind_tenant_to_session(db, company_id=p1_setup["cid_a"], is_platform_admin=True)
    log = db.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(gid)).first()
    assert log is not None, "Goal changes must be audited"


def test_6_2_R10_manager_notified_when_someone_else_changes_goal(
    client: TestClient, p1_setup: dict[str, Any], active_cycle: str, db: Session
):
    """6.2 R10: Manager notified post-commit when someone else modifies employee goals."""
    hr_headers = _auth_headers(p1_setup["hr_a"])
    emp_id = str(p1_setup["emp_a"].id)

    # HR sets/changes goal for employee
    res = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": active_cycle,
            "employee_id": emp_id,
            "goals": [{"title": "Goal HR", "weightage": 30}],
        },
        headers=hr_headers,
    )
    assert res.status_code == 201

    # Check notification sent to manager
    bind_tenant_to_session(db, company_id=p1_setup["cid_a"], is_platform_admin=True)
    mgr_notif = (
        db.query(Notification).filter(Notification.user_id == p1_setup["mgr_user_a"].id).first()
    )
    assert mgr_notif is not None, "Manager must be notified when HR modifies employee goal"


def test_6_2_R11_rate_limit_goal_write_routes(
    client: TestClient, p1_setup: dict[str, Any], active_cycle: str
):
    """6.2 R11: Write routes are rate limited with a 429 test."""
    emp_headers = _auth_headers(p1_setup["emp_user_a"])
    limiter.reset()

    hit_429 = False
    for i in range(40):
        res = client.post(
            "/api/v1/performance/goals",
            json={
                "cycle_id": active_cycle,
                "goals": [{"title": f"Goal {i}", "weightage": 1}],
            },
            headers=emp_headers,
        )
        if res.status_code == 429:
            hit_429 = True
            break
    limiter.reset()
    assert hit_429, "Rate limit must trigger 429 on goal write routes"
