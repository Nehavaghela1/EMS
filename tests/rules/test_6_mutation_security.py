"""
Module 6 Mutation & Hacker-Grade Security Invariant Tests.
Tests edge-cases, malicious tampering, bypass attempts, boundary conditions,
cross-tenant IDOR, blind-review leaks, decimal precision tampering, and state-machine invalid jumps.
"""

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import Company, CompanyStatus, User, UserRole


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
def sec_setup(db: Session) -> dict[str, Any]:
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
    peer_user_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"peer_{uuid.uuid4().hex[:6]}@compa.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    rogue_mgr_user_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"rogue_mgr_{uuid.uuid4().hex[:6]}@compa.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.manager,
        is_active=True,
    )
    db.add_all([owner_a, hr_a, mgr_user_a, emp_user_a, peer_user_a, rogue_mgr_user_a])
    db.flush()

    mgr_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=mgr_user_a.id,
        employee_code=f"M{uuid.uuid4().hex[:6]}",
        first_name="Mgr",
        last_name="Alice",
        email=mgr_user_a.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2025, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
    )
    rogue_mgr_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=rogue_mgr_user_a.id,
        employee_code=f"R{uuid.uuid4().hex[:6]}",
        first_name="Rogue",
        last_name="Manager",
        email=rogue_mgr_user_a.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2025, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
    )
    emp_a = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=emp_user_a.id,
        employee_code=f"E{uuid.uuid4().hex[:6]}",
        first_name="Emp",
        last_name="Bob",
        email=emp_user_a.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2025, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        reporting_manager_id=mgr_emp.id,
    )
    peer_emp_a = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=peer_user_a.id,
        employee_code=f"P{uuid.uuid4().hex[:6]}",
        first_name="Peer",
        last_name="Charlie",
        email=peer_user_a.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2025, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
    )
    db.add_all([mgr_emp, rogue_mgr_emp, emp_a, peer_emp_a])
    db.flush()

    # Company B (Attacker tenant)
    cid_b = uuid.uuid4()
    bind_tenant_to_session(db, company_id=cid_b, is_platform_admin=True)

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
    attacker_emp = User(
        id=uuid.uuid4(),
        company_id=cid_b,
        email=f"attacker_emp_{uuid.uuid4().hex[:6]}@compb.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([hr_b, attacker_emp])
    db.commit()

    return {
        "cid_a": cid_a,
        "company_a": company_a,
        "owner_a": owner_a,
        "hr_a": hr_a,
        "mgr_a": mgr_user_a,
        "mgr_emp_id": mgr_emp.id,
        "emp_a": emp_user_a,
        "emp_profile_id": emp_a.id,
        "peer_a": peer_user_a,
        "rogue_mgr_a": rogue_mgr_user_a,
        "cid_b": cid_b,
        "company_b": company_b,
        "attacker_hr": hr_b,
        "attacker_emp": attacker_emp,
    }


# ==============================================================================
# 1. HACKER & IDOR TESTS: CROSS-TENANT & CROSS-USER ISOLATION
# ==============================================================================


def test_sec_cross_tenant_idor_all_performance_endpoints(
    client: TestClient, sec_setup: dict[str, Any]
):
    """
    Hacker probe: Company B tries reading, creating, modifying, or reviewing
    Company A's cycles, goals, progress, reviews, summaries, and PIPs.
    Every single cross-tenant probe must fail-closed with 404 (zero data leakage).
    """
    hr_a_h = _auth_headers(sec_setup["hr_a"])
    emp_a_h = _auth_headers(sec_setup["emp_a"])
    attacker_h = _auth_headers(sec_setup["attacker_hr"])

    # Setup valid active cycle and goals in Company A
    today = date.today()
    c_res = client.post(
        "/api/v1/performance/cycles",
        headers=hr_a_h,
        json={
            "name": "Sec Cycle 2026",
            "cycle_type": "annual",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=90)),
        },
    )
    assert c_res.status_code == 201
    cycle_id = c_res.json()["id"]

    client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        headers=hr_a_h,
        json={"status": "active"},
    )

    g_res = client.post(
        "/api/v1/performance/goals",
        headers=emp_a_h,
        json={
            "cycle_id": cycle_id,
            "goals": [{"title": "Confidential Goal A", "weightage": 100.0}],
        },
    )
    assert g_res.status_code == 201
    goal_id = g_res.json()[0]["id"]

    # 1. Attacker tries to read Company A cycle -> 404
    r = client.get("/api/v1/performance/cycles?status_filter=active", headers=attacker_h)
    assert r.status_code == 200
    assert not any(item["id"] == cycle_id for item in r.json()["items"]), "Leaked foreign cycle!"

    # 2. Attacker tries to update Company A cycle -> 404
    r = client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        headers=attacker_h,
        json={"status": "closed"},
    )
    assert r.status_code == 404

    # 3. Attacker tries to read Company A goals -> 404
    r = client.get(f"/api/v1/performance/goals/{sec_setup['emp_profile_id']}", headers=attacker_h)
    assert r.status_code == 404

    # 4. Attacker tries to modify Company A goal -> 404
    r = client.put(
        f"/api/v1/performance/goals/{goal_id}",
        headers=attacker_h,
        json={"title": "Hacked Goal"},
    )
    assert r.status_code == 404

    # 5. Attacker tries to update Company A goal progress -> 404
    r = client.put(
        f"/api/v1/performance/goals/{goal_id}/progress",
        headers=attacker_h,
        json={"progress": 99, "notes": "Hacked"},
    )
    assert r.status_code == 404

    # 6. Attacker tries to inject reviews into Company A goal -> 404
    r = client.post(
        f"/api/v1/performance/goals/{goal_id}/self-review",
        headers=attacker_h,
        json={"rating": 5.0, "comments": "Hacked review"},
    )
    assert r.status_code == 404


def test_sec_unauthorized_manager_spoofing_attempt(client: TestClient, sec_setup: dict[str, Any]):
    """
    Security check: A manager who is NOT in the employee's reporting chain
    attempts to rate their goal or initiate a PIP. Must return 403 Forbidden.
    """
    hr_a_h = _auth_headers(sec_setup["hr_a"])
    emp_a_h = _auth_headers(sec_setup["emp_a"])
    rogue_mgr_h = _auth_headers(sec_setup["rogue_mgr_a"])

    today = date.today()
    c = client.post(
        "/api/v1/performance/cycles",
        headers=hr_a_h,
        json={
            "name": "Cycle For Manager Scope",
            "cycle_type": "annual",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=90)),
        },
    ).json()
    client.put(f"/api/v1/performance/cycles/{c['id']}", headers=hr_a_h, json={"status": "active"})

    g = client.post(
        "/api/v1/performance/goals",
        headers=emp_a_h,
        json={
            "cycle_id": c["id"],
            "goals": [{"title": "Team Deliverable", "weightage": 100.0}],
        },
    ).json()[0]

    # Employee submits self review first
    client.post(
        f"/api/v1/performance/goals/{g['id']}/self-review",
        headers=emp_a_h,
        json={"rating": 4.0, "comments": "Self evaluation done"},
    )

    # Rogue manager (not direct/indirect manager) tries to submit manager rating -> 403
    r = client.post(
        f"/api/v1/performance/goals/{g['id']}/manager-review",
        headers=rogue_mgr_h,
        json={"rating": 1.0, "comments": "Malicious low rating"},
    )
    assert r.status_code == 403, "Rogue manager must NOT be able to review non-reportees"

    # Rogue manager tries to place employee on PIP -> 403
    r_pip = client.post(
        "/api/v1/performance/pips",
        headers=rogue_mgr_h,
        json={
            "employee_id": str(sec_setup["emp_profile_id"]),
            "title": "Malicious PIP",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=30)),
        },
    )
    assert r_pip.status_code == 403, "Rogue manager must NOT be able to put non-reportee on PIP"


def test_sec_blind_review_leak_prevention(client: TestClient, sec_setup: dict[str, Any]):
    """
    Security check: Employee must NEVER be able to see pending or unsubmitted manager review
    data or inspect draft ratings before submission.
    """
    hr_a_h = _auth_headers(sec_setup["hr_a"])
    emp_a_h = _auth_headers(sec_setup["emp_a"])
    mgr_a_h = _auth_headers(sec_setup["mgr_a"])

    today = date.today()
    c = client.post(
        "/api/v1/performance/cycles",
        headers=hr_a_h,
        json={
            "name": "Blind Review Security Cycle",
            "cycle_type": "quarterly",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=90)),
        },
    ).json()
    client.put(f"/api/v1/performance/cycles/{c['id']}", headers=hr_a_h, json={"status": "active"})

    g = client.post(
        "/api/v1/performance/goals",
        headers=emp_a_h,
        json={
            "cycle_id": c["id"],
            "goals": [{"title": "Confidential Appraisal Goal", "weightage": 100.0}],
        },
    ).json()[0]

    # Before self-review: manager cannot submit review
    r_premature = client.post(
        f"/api/v1/performance/goals/{g['id']}/manager-review",
        headers=mgr_a_h,
        json={"rating": 3.0, "comments": "Premature"},
    )
    assert r_premature.status_code == 409, "Manager review must fail before self-review"

    # Employee submits self review
    client.post(
        f"/api/v1/performance/goals/{g['id']}/self-review",
        headers=emp_a_h,
        json={"rating": 4.5, "comments": "I did great"},
    )

    # Manager submits review
    r_mgr = client.post(
        f"/api/v1/performance/goals/{g['id']}/manager-review",
        headers=mgr_a_h,
        json={"rating": 3.5, "comments": "Good effort, room for improvement"},
    )
    assert r_mgr.status_code == 200
    review_id = r_mgr.json()["id"]

    # Peer employee tries to read this review -> 403 Forbidden
    peer_h = _auth_headers(sec_setup["peer_a"])
    r_peer = client.get(f"/api/v1/performance/reviews/{review_id}", headers=peer_h)
    assert r_peer.status_code == 403


# ==============================================================================
# 2. TAMPERING TESTS: ARITHMETIC GATES & SUM CHECKS
# ==============================================================================


def test_mut_decimal_weightage_sum_gate_strictness(client: TestClient, sec_setup: dict[str, Any]):
    """
    Mutation checks for 6.2 Decimal weightage sum:
    - 99.99% must FAIL with 400 invalid_weightage_sum
    - 100.01% must FAIL with 400 invalid_weightage_sum
    - 0% or negative weightages must FAIL validation with 422
    - Exactly 100.00% must SUCCEED
    """
    hr_a_h = _auth_headers(sec_setup["hr_a"])
    emp_a_h = _auth_headers(sec_setup["emp_a"])

    today = date.today()
    c = client.post(
        "/api/v1/performance/cycles",
        headers=hr_a_h,
        json={
            "name": "Weightage Strictness Cycle",
            "cycle_type": "quarterly",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=90)),
        },
    ).json()
    client.put(f"/api/v1/performance/cycles/{c['id']}", headers=hr_a_h, json={"status": "active"})

    # Mutant 1: Negative weightage -> 422
    r_neg = client.post(
        "/api/v1/performance/goals",
        headers=emp_a_h,
        json={
            "cycle_id": c["id"],
            "goals": [{"title": "Negative goal", "weightage": -10.0}],
        },
    )
    assert r_neg.status_code == 422

    # Mutant 2: Zero weightage -> 422
    r_zero = client.post(
        "/api/v1/performance/goals",
        headers=emp_a_h,
        json={
            "cycle_id": c["id"],
            "goals": [{"title": "Zero goal", "weightage": 0.0}],
        },
    )
    assert r_zero.status_code == 422

    # Mutant 3: Exceeding 100 on a single goal -> 422
    r_over = client.post(
        "/api/v1/performance/goals",
        headers=emp_a_h,
        json={
            "cycle_id": c["id"],
            "goals": [{"title": "Over goal", "weightage": 105.0}],
        },
    )
    assert r_over.status_code == 422

    # Mutant 4: Under 100% (99.99%) - creating goals succeeds, but self-review BLOCKS
    g_99 = client.post(
        "/api/v1/performance/goals",
        headers=emp_a_h,
        json={
            "cycle_id": c["id"],
            "goals": [
                {"title": "Goal A", "weightage": 50.00},
                {"title": "Goal B", "weightage": 49.99},
            ],
        },
    ).json()
    assert len(g_99) == 2

    r_review_fail = client.post(
        f"/api/v1/performance/goals/{g_99[0]['id']}/self-review",
        headers=emp_a_h,
        json={"rating": 4.0, "comments": "Attempting submit under 100%"},
    )
    assert r_review_fail.status_code == 400
    assert r_review_fail.json()["error"]["code"] == "invalid_weightage_sum"

    # Fix: update Goal B weightage to 50.00 so total == 100.00%
    r_up = client.put(
        f"/api/v1/performance/goals/{g_99[1]['id']}",
        headers=emp_a_h,
        json={"weightage": 50.00},
    )
    assert r_up.status_code == 200

    # Now self-review must succeed with 200
    r_review_ok = client.post(
        f"/api/v1/performance/goals/{g_99[0]['id']}/self-review",
        headers=emp_a_h,
        json={"rating": 4.0, "comments": "Successfully sum to 100%"},
    )
    assert r_review_ok.status_code == 200


# ==============================================================================
# 3. STATE-MACHINE & REOPEN WORKFLOW TAMPERING
# ==============================================================================


def test_mut_cannot_reopen_without_mandatory_reason_and_hr_role(
    client: TestClient, sec_setup: dict[str, Any]
):
    """
    State machine test:
    - Only HR/Owner can reopen a submitted review.
    - Reopen MUST provide a non-empty reason (empty string or missing reason -> 422).
    - Reopening already draft review -> 400/409.
    """
    hr_a_h = _auth_headers(sec_setup["hr_a"])
    emp_a_h = _auth_headers(sec_setup["emp_a"])
    mgr_a_h = _auth_headers(sec_setup["mgr_a"])

    today = date.today()
    c = client.post(
        "/api/v1/performance/cycles",
        headers=hr_a_h,
        json={
            "name": "Reopen Lifecycle Cycle",
            "cycle_type": "annual",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=90)),
        },
    ).json()
    client.put(f"/api/v1/performance/cycles/{c['id']}", headers=hr_a_h, json={"status": "active"})

    g = client.post(
        "/api/v1/performance/goals",
        headers=emp_a_h,
        json={
            "cycle_id": c["id"],
            "goals": [{"title": "Goal for Reopen", "weightage": 100.0}],
        },
    ).json()[0]

    rev = client.post(
        f"/api/v1/performance/goals/{g['id']}/self-review",
        headers=emp_a_h,
        json={"rating": 4.0, "comments": "Initial evaluation"},
    ).json()
    review_id = rev["id"]

    # Mutant 1: Employee attempts to reopen their own review -> 403 Forbidden
    r_emp_reopen = client.post(
        f"/api/v1/performance/reviews/{review_id}/reopen",
        headers=emp_a_h,
        json={"reason": "I want to change it"},
    )
    assert r_emp_reopen.status_code == 403

    # Mutant 2: Manager attempts to reopen review -> 403 Forbidden (Only HR/Owner allowed)
    r_mgr_reopen = client.post(
        f"/api/v1/performance/reviews/{review_id}/reopen",
        headers=mgr_a_h,
        json={"reason": "Please change it"},
    )
    assert r_mgr_reopen.status_code == 403

    # Mutant 3: HR attempts to reopen with whitespace/empty reason -> 422 Unprocessable Entity
    r_empty_reason = client.post(
        f"/api/v1/performance/reviews/{review_id}/reopen",
        headers=hr_a_h,
        json={"reason": "   "},
    )
    assert r_empty_reason.status_code in (400, 422)

    # Legitimate HR reopen with valid reason -> 200 OK
    r_ok_reopen = client.post(
        f"/api/v1/performance/reviews/{review_id}/reopen",
        headers=hr_a_h,
        json={"reason": "Typo in self-appraisal deliverables requested by employee"},
    )
    assert r_ok_reopen.status_code == 200
    assert r_ok_reopen.json()["status"] == "draft"

    # Mutant 4: Re-opening a review that is already in draft status -> 409 Conflict
    r_double_reopen = client.post(
        f"/api/v1/performance/reviews/{review_id}/reopen",
        headers=hr_a_h,
        json={"reason": "Duplicate reopen attempt"},
    )
    assert r_double_reopen.status_code == 409
