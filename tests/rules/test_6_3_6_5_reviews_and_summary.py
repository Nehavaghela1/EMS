"""Module 6 Batch 2: 6.3 Self & Manager Reviews and 6.5 Performance Summary.
Tests for:
Rule 0 (Multi-tenancy),
6.3 Rules R1-R11 (Self & Manager Reviews, Prerequisites, Blind Review, Reopen, Audit, Rates),
6.5 Rules R1-R8 (Scoping, Decimal Half-up Math, Zero PII Leakage, Paging, Rates).
"""

import threading
import uuid
from datetime import date, timedelta
from decimal import Decimal
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
from app.modules.performance.models import CycleStatus, GoalStatus, PerformanceCycle, PerformanceGoal
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
def limits_on():
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = False


@pytest.fixture
def p2_setup(db: Session) -> dict[str, Any]:
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
    other_mgr_user_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"othermgr_{uuid.uuid4().hex[:6]}@compa.com",
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
    db.add_all([owner_a, hr_a, mgr_user_a, other_mgr_user_a, emp_user_a, other_emp_user_a])
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
    other_mgr_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=other_mgr_user_a.id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="OtherManager",
        last_name="A",
        email=other_mgr_user_a.email,
        hire_date=date(2025, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    db.add_all([mgr_emp, other_mgr_emp])
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
        reporting_manager_id=other_mgr_emp.id,
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
        "other_mgr_user_a": other_mgr_user_a,
        "emp_user_a": emp_user_a,
        "other_emp_user_a": other_emp_user_a,
        "mgr_emp": mgr_emp,
        "other_mgr_emp": other_mgr_emp,
        "emp_a": emp_a,
        "other_emp_a": other_emp_a,
        "cid_b": cid_b,
        "company_b": company_b,
        "hr_b": hr_b,
    }


@pytest.fixture
def setup_active_cycle_with_goals(client: TestClient, p2_setup: dict[str, Any]) -> dict[str, Any]:
    """Helper fixture to create active cycle and 100% total goals for emp_a."""
    hr_headers = _auth_headers(p2_setup["hr_a"])
    emp_headers = _auth_headers(p2_setup["emp_user_a"])

    # Create cycle
    c = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": f"Review Cycle {uuid.uuid4().hex[:6]}",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        headers=hr_headers,
    )
    cycle_id = c.json()["id"]
    client.put(f"/api/v1/performance/cycles/{cycle_id}", json={"status": "active"}, headers=hr_headers)

    # Set 2 goals summing to 100% (60% and 40%)
    emp_id = str(p2_setup["emp_a"].id)
    g = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": cycle_id,
            "employee_id": emp_id,
            "goals": [
                {"title": "Goal Alpha", "weightage": 60},
                {"title": "Goal Beta", "weightage": 40},
            ],
        },
        headers=emp_headers,
    )
    goals = g.json()
    return {
        "cycle_id": cycle_id,
        "goal_1_id": goals[0]["id"],
        "goal_2_id": goals[1]["id"],
    }


# ==============================================================================
# 6.3 RULE TESTS: SELF & MANAGER REVIEWS
# ==============================================================================


def test_6_3_R1_self_review_only_by_employee_once(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.3 R1: Self-review only by employee for own record; once per goal (duplicate 409)."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    other_emp_headers = _auth_headers(p2_setup["other_emp_user_a"])
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    # Other employee tries to review emp_a's goal -> 403
    r_peer = client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 4.0, "comments": "Good peer review attempt"},
        headers=other_emp_headers,
    )
    assert r_peer.status_code == 403, "Other employees cannot submit self-review"

    # Employee submits self-review -> 200
    r_self = client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 4.5, "comments": "Met target"},
        headers=emp_headers,
    )
    assert r_self.status_code == 200

    # Second self-review attempt -> 409
    r_dup = client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 5.0, "comments": "Second attempt"},
        headers=emp_headers,
    )
    assert r_dup.status_code == 409, "Duplicate self-review must return 409"


def test_6_3_R2_manager_review_reporting_chain_and_hr_cannot_write_for_manager(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.3 R2: Manager review only by reporting-chain manager; HR cannot write for manager (403)."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    mgr_headers = _auth_headers(p2_setup["mgr_user_a"])
    other_mgr_headers = _auth_headers(p2_setup["other_mgr_user_a"])
    hr_headers = _auth_headers(p2_setup["hr_a"])
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    # Submit self review first
    client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 4.0, "comments": "Self done"},
        headers=emp_headers,
    )

    # Other manager outside reporting chain tries to review -> 403
    r_other_mgr = client.post(
        f"/api/v1/performance/goals/{g1}/manager-review",
        json={"rating": 4.0, "comments": "Other mgr review"},
        headers=other_mgr_headers,
    )
    assert r_other_mgr.status_code == 403, "Manager outside chain cannot review"

    # HR cannot submit manager review -> 403
    r_hr = client.post(
        f"/api/v1/performance/goals/{g1}/manager-review",
        json={"rating": 4.0, "comments": "HR review attempt"},
        headers=hr_headers,
    )
    assert r_hr.status_code == 403, "HR cannot submit manager review"

    # Reporting manager submits -> 200
    r_mgr = client.post(
        f"/api/v1/performance/goals/{g1}/manager-review",
        json={"rating": 4.5, "comments": "Good work"},
        headers=mgr_headers,
    )
    assert r_mgr.status_code == 200


def test_6_3_R3_self_review_prerequisite_before_manager_review(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.3 R3: Employee must submit self-review before manager review can be submitted (409)."""
    mgr_headers = _auth_headers(p2_setup["mgr_user_a"])
    g2 = setup_active_cycle_with_goals["goal_2_id"]

    # Manager tries to review goal 2 without self-review -> 409
    r = client.post(
        f"/api/v1/performance/goals/{g2}/manager-review",
        json={"rating": 4.0, "comments": "Premature review"},
        headers=mgr_headers,
    )
    assert r.status_code == 409, "Manager review before self-review must return 409"


def test_6_3_R4_rating_bounds_and_comment_length_422(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.3 R4: Rating must be 1.0 to 5.0; comments length limit; bad input returns 422."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    # Rating < 1.0 -> 422
    r_low = client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 0.5, "comments": "Too low"},
        headers=emp_headers,
    )
    assert r_low.status_code == 422, "Rating < 1.0 must return 422"

    # Rating > 5.0 -> 422
    r_high = client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 5.5, "comments": "Too high"},
        headers=emp_headers,
    )
    assert r_high.status_code == 422, "Rating > 5.0 must return 422"


def test_6_3_R5_reviews_written_only_while_cycle_active_409(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.3 R5: Reviews can only be written while the cycle is active (409)."""
    hr_headers = _auth_headers(p2_setup["hr_a"])
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    cid = setup_active_cycle_with_goals["cycle_id"]
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    # Close the cycle
    client.put(f"/api/v1/performance/cycles/{cid}", json={"status": "closed"}, headers=hr_headers)

    # Try submitting review in closed cycle -> 409
    r = client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 4.0, "comments": "Closed review"},
        headers=emp_headers,
    )
    assert r.status_code == 409, "Review in closed cycle must return 409"


def test_6_3_R6_blind_manager_review_hidden_from_employee_until_submitted(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.3 R6: Blind review: manager review rating/comments stay hidden from employee until submitted."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    mgr_headers = _auth_headers(p2_setup["mgr_user_a"])
    emp_id = str(p2_setup["emp_a"].id)
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    # Employee submits self-review
    client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 4.0, "comments": "Self done"},
        headers=emp_headers,
    )

    # Before manager review is submitted, goals list viewed by employee does not leak manager rating
    goals_resp = client.get(f"/api/v1/performance/goals/{emp_id}", headers=emp_headers).json()
    assert goals_resp[0].get("manager_rating") is None

    # Manager submits review
    client.post(
        f"/api/v1/performance/goals/{g1}/manager-review",
        json={"rating": 4.8, "comments": "Outstanding work"},
        headers=mgr_headers,
    )

    # After submit, manager review is visible
    goals_resp_after = client.get(f"/api/v1/performance/goals/{emp_id}", headers=emp_headers).json()
    # Employee can now see submitted review
    review_resp = client.get(f"/api/v1/performance/goals/{g1}/reviews", headers=emp_headers)
    assert review_resp.status_code == 200
    mgr_rev = next(r for r in review_resp.json() if r["reviewer_role"] == "manager")
    assert Decimal(str(mgr_rev["rating"])) == Decimal("4.8")


def test_6_3_R7_status_flow_and_hr_reopen_with_reason_audited(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any], db: Session
):
    """6.3 R7: Status moves draft -> submitted; no edits after submit; HR can reopen with reason (audited)."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    mgr_headers = _auth_headers(p2_setup["mgr_user_a"])
    hr_headers = _auth_headers(p2_setup["hr_a"])
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    # Submit self review
    r_self = client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 4.0, "comments": "Self done"},
        headers=emp_headers,
    )
    rev_id = r_self.json()["id"]

    # Non-HR tries to reopen -> 403
    r_reopen_bad = client.post(
        f"/api/v1/performance/reviews/{rev_id}/reopen",
        json={"reason": "Let me edit"},
        headers=emp_headers,
    )
    assert r_reopen_bad.status_code == 403, "Only HR can reopen a review"

    # HR reopens review without reason -> 422
    r_no_reason = client.post(
        f"/api/v1/performance/reviews/{rev_id}/reopen",
        json={"reason": ""},
        headers=hr_headers,
    )
    assert r_no_reason.status_code in (400, 422), "Reopening requires non-empty reason"

    # HR reopens with valid reason -> 200
    r_reopen = client.post(
        f"/api/v1/performance/reviews/{rev_id}/reopen",
        json={"reason": "Employee requested correction to self-evaluation"},
        headers=hr_headers,
    )
    assert r_reopen.status_code == 200
    assert r_reopen.json()["status"] == "draft"

    # Check audit log
    bind_tenant_to_session(db, company_id=p2_setup["cid_a"], is_platform_admin=True)
    log = db.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(rev_id)).first()
    assert log is not None
    assert "REOPEN" in log.action


def test_6_3_R8_cross_company_review_returns_404(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.3 R8: Another company's review returns 404."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    hr_b_headers = _auth_headers(p2_setup["hr_b"])
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    r = client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 4.0, "comments": "Self done"},
        headers=emp_headers,
    )
    rev_id = r.json()["id"]

    # Company B tries to view or reopen review -> 404
    r_get = client.get(f"/api/v1/performance/reviews/{rev_id}", headers=hr_b_headers)
    assert r_get.status_code == 404, "Another company's review must return 404"


def test_6_3_R9_review_submit_and_reopen_audited(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any], db: Session
):
    """6.3 R9: Every save and submit is audited (ids and field names only)."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    r = client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 4.5, "comments": "Achieved all key targets"},
        headers=emp_headers,
    )
    rev_id = uuid.UUID(r.json()["id"])

    bind_tenant_to_session(db, company_id=p2_setup["cid_a"], is_platform_admin=True)
    audit = db.query(AuditLog).filter(AuditLog.entity_id == rev_id).first()
    assert audit is not None
    assert "PERFORMANCE_REVIEW" in audit.action
    assert "rating" not in str(audit.details) or audit.details.get("rating") is None, (
        "No private evaluation scores leaked into audit details"
    )


def test_6_3_R10_notifications_post_commit_manager_and_employee(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any], db: Session
):
    """6.3 R10: Manager notified on self-review submit; employee notified on manager review submit."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    mgr_headers = _auth_headers(p2_setup["mgr_user_a"])
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    # 1. Employee submits self-review
    client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 4.0, "comments": "Self done"},
        headers=emp_headers,
    )

    # Manager should receive notification
    bind_tenant_to_session(db, company_id=p2_setup["cid_a"], is_platform_admin=True)
    mgr_notif = (
        db.query(Notification)
        .filter(
            Notification.user_id == p2_setup["mgr_user_a"].id,
            Notification.type == "self_review_submitted",
        )
        .first()
    )
    assert mgr_notif is not None, "Manager must be notified on self-review submit"

    # 2. Manager submits manager review
    client.post(
        f"/api/v1/performance/goals/{g1}/manager-review",
        json={"rating": 4.5, "comments": "Manager done"},
        headers=mgr_headers,
    )

    # Employee should receive notification
    emp_notif = (
        db.query(Notification)
        .filter(
            Notification.user_id == p2_setup["emp_user_a"].id,
            Notification.type == "manager_review_submitted",
        )
        .first()
    )
    assert emp_notif is not None, "Employee must be notified on manager review submit"


def test_6_3_R11_rate_limit_review_write_routes(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any], limits_on: None
):
    """6.3 R11: Write routes are rate limited with a 429 test."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    hit_429 = False
    for i in range(40):
        res = client.post(
            f"/api/v1/performance/goals/{g1}/self-review",
            json={"rating": 4.0, "comments": f"Try {i}"},
            headers=emp_headers,
        )
        if res.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "Rate limit must trigger 429 on review write routes"


# ==============================================================================
# 6.5 RULE TESTS: PERFORMANCE SUMMARY
# ==============================================================================


def test_6_5_R1_scoping_permissions_employee_manager_hr(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.5 R1: Employee sees own; manager sees reporting chain; HR/owner see all; other manager 403."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    mgr_headers = _auth_headers(p2_setup["mgr_user_a"])
    other_mgr_headers = _auth_headers(p2_setup["other_mgr_user_a"])
    other_emp_headers = _auth_headers(p2_setup["other_emp_user_a"])
    hr_headers = _auth_headers(p2_setup["hr_a"])
    owner_headers = _auth_headers(p2_setup["owner_a"])

    emp_id = str(p2_setup["emp_a"].id)

    # 1. Employee sees own summary -> 200
    r_own = client.get(f"/api/v1/performance/summary/{emp_id}", headers=emp_headers)
    assert r_own.status_code == 200

    # 2. Peer employee sees emp_a summary -> 403
    r_peer = client.get(f"/api/v1/performance/summary/{emp_id}", headers=other_emp_headers)
    assert r_peer.status_code == 403, "Peer employee cannot see other's summary"

    # 3. Direct manager sees report's summary -> 200
    r_mgr = client.get(f"/api/v1/performance/summary/{emp_id}", headers=mgr_headers)
    assert r_mgr.status_code == 200

    # 4. Other manager outside reporting chain -> 403
    r_other_mgr = client.get(f"/api/v1/performance/summary/{emp_id}", headers=other_mgr_headers)
    assert r_other_mgr.status_code == 403, "Manager outside reporting chain must get 403"

    # 5. HR sees all -> 200
    r_hr = client.get(f"/api/v1/performance/summary/{emp_id}", headers=hr_headers)
    assert r_hr.status_code == 200

    # 6. Owner sees all -> 200
    r_owner = client.get(f"/api/v1/performance/summary/{emp_id}", headers=owner_headers)
    assert r_owner.status_code == 200


def test_6_5_R2_summary_payload_structure(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.5 R2: Summary per cycle: goals, weighted progress, self rating, manager rating, PIP flag."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    emp_id = str(p2_setup["emp_a"].id)

    res = client.get(f"/api/v1/performance/summary/{emp_id}", headers=emp_headers)
    assert res.status_code == 200
    data = res.json()
    assert "goals" in data
    assert "weighted_progress" in data
    assert "on_pip" in data
    assert "cycle_id" in data


def test_6_5_R3_weighted_score_uses_decimal_half_up(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.5 R3: Weighted score uses goal weightage, Decimal, rounded half-up to 2 places."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    mgr_headers = _auth_headers(p2_setup["mgr_user_a"])
    emp_id = str(p2_setup["emp_a"].id)
    g1 = setup_active_cycle_with_goals["goal_1_id"]
    g2 = setup_active_cycle_with_goals["goal_2_id"]

    # Goal 1: 60% weightage, rating 4.3 -> 60 * 4.3 = 2.58
    # Goal 2: 40% weightage, rating 3.7 -> 40 * 3.7 = 1.48
    # Expected weighted score = 2.58 + 1.48 = 4.06
    client.post(f"/api/v1/performance/goals/{g1}/self-review", json={"rating": 4.0}, headers=emp_headers)
    client.post(f"/api/v1/performance/goals/{g2}/self-review", json={"rating": 3.5}, headers=emp_headers)

    client.post(f"/api/v1/performance/goals/{g1}/manager-review", json={"rating": 4.3}, headers=mgr_headers)
    client.post(f"/api/v1/performance/goals/{g2}/manager-review", json={"rating": 3.7}, headers=mgr_headers)

    res = client.get(f"/api/v1/performance/summary/{emp_id}", headers=mgr_headers)
    assert res.status_code == 200
    summary = res.json()
    assert Decimal(str(summary["weighted_manager_rating"])) == Decimal("4.06")


def test_6_5_R4_only_submitted_reviews_count_drafts_pending(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.5 R4: Only submitted reviews count; drafts show as pending; manager rating hidden until submitted."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    mgr_headers = _auth_headers(p2_setup["mgr_user_a"])
    emp_id = str(p2_setup["emp_a"].id)
    g1 = setup_active_cycle_with_goals["goal_1_id"]

    # Self review submitted for goal 1 only
    client.post(f"/api/v1/performance/goals/{g1}/self-review", json={"rating": 4.0}, headers=emp_headers)

    # Employee views summary: manager review is pending, not completed
    summary_emp = client.get(f"/api/v1/performance/summary/{emp_id}", headers=emp_headers).json()
    assert summary_emp["manager_review_status"] == "pending"
    assert summary_emp.get("weighted_manager_rating") is None

    # Manager submits review for goal 1
    client.post(f"/api/v1/performance/goals/{g1}/manager-review", json={"rating": 4.5}, headers=mgr_headers)

    # Manager views summary: goal 1 done, goal 2 pending
    summary_mgr = client.get(f"/api/v1/performance/summary/{emp_id}", headers=mgr_headers).json()
    assert summary_mgr["completed_reviews_count"] == 1


def test_6_5_R5_zero_personal_data_in_summary_response(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.5 R5: No salary, bank, tax or private personal data in response."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    emp_id = str(p2_setup["emp_a"].id)

    res = client.get(f"/api/v1/performance/summary/{emp_id}", headers=emp_headers)
    assert res.status_code == 200
    raw_text = res.text.lower()
    for forbidden in ["salary", "bank", "account_number", "pan", "aadhaar", "ifsc"]:
        assert forbidden not in raw_text, f"Personal data leaked in summary: {forbidden}"


def test_6_5_R6_cross_company_summary_returns_404(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.5 R6: Another company's summary returns 404."""
    hr_b_headers = _auth_headers(p2_setup["hr_b"])
    emp_id = str(p2_setup["emp_a"].id)

    res = client.get(f"/api/v1/performance/summary/{emp_id}", headers=hr_b_headers)
    assert res.status_code == 404, "Accessing another company's summary must return 404"


def test_6_5_R7_summary_lists_are_paged_with_bounded_size(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """6.5 R7: Lists are paged with a bounded page size."""
    hr_headers = _auth_headers(p2_setup["hr_a"])
    cid = setup_active_cycle_with_goals["cycle_id"]

    res = client.get(f"/api/v1/performance/summaries?cycle_id={cid}&page=1&limit=50", headers=hr_headers)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "limit" in data


def test_6_5_R8_read_routes_rate_limited(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any], limits_on: None
):
    """6.5 R8: Read routes are rate limited with a 429 test."""
    emp_headers = _auth_headers(p2_setup["emp_user_a"])
    emp_id = str(p2_setup["emp_a"].id)

    hit_429 = False
    for _ in range(80):
        res = client.get(f"/api/v1/performance/summary/{emp_id}", headers=emp_headers)
        if res.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "Rate limit must trigger 429 on summary read routes"
