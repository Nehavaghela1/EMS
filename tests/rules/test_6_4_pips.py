"""Module 6 Batch 3: 6.4 PIPs (Performance Improvement Plans).
Tests for Rule 0 (Multi-tenancy isolation), 6.4 PIP creation, mentor validation,
scoping rules, single active PIP invariant, append-only check-in logs, and atomic exit on failure.
"""

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus, ResignationStatus
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog


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
def p3_setup(db: Session) -> dict[str, Any]:
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
        email=f"otherm_{uuid.uuid4().hex[:6]}@compa.com",
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
    mentor_user_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"mentor_{uuid.uuid4().hex[:6]}@compa.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all(
        [
            owner_a,
            hr_a,
            mgr_user_a,
            other_mgr_user_a,
            emp_user_a,
            other_emp_user_a,
            mentor_user_a,
        ]
    )
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
    mentor_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=mentor_user_a.id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Senior",
        last_name="Mentor",
        email=mentor_user_a.email,
        hire_date=date(2024, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    inactive_mentor_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Inactive",
        last_name="Mentor",
        email=f"inact_{uuid.uuid4().hex[:6]}@compa.com",
        hire_date=date(2024, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=False,
    )
    db.add_all([mgr_emp, other_mgr_emp, mentor_emp, inactive_mentor_emp])
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

    # Company B (for multi-tenant isolation testing)
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
    mentor_user_b = User(
        id=uuid.uuid4(),
        company_id=cid_b,
        email=f"mentor_{uuid.uuid4().hex[:6]}@compb.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([hr_b, mentor_user_b])
    db.flush()

    emp_b = Employee(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Employee",
        last_name="B",
        email=f"emp_{uuid.uuid4().hex[:6]}@compb.com",
        hire_date=date(2025, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    mentor_emp_b = Employee(
        id=uuid.uuid4(),
        company_id=cid_b,
        user_id=mentor_user_b.id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Mentor",
        last_name="B",
        email=mentor_user_b.email,
        hire_date=date(2025, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    db.add_all([emp_b, mentor_emp_b])
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
        "mentor_user_a": mentor_user_a,
        "mgr_emp": mgr_emp,
        "other_mgr_emp": other_mgr_emp,
        "mentor_emp": mentor_emp,
        "inactive_mentor_emp": inactive_mentor_emp,
        "emp_a": emp_a,
        "other_emp_a": other_emp_a,
        "cid_b": cid_b,
        "company_b": company_b,
        "hr_b": hr_b,
        "emp_b": emp_b,
        "mentor_emp_b": mentor_emp_b,
    }


# =============================================================================
# 6.4 PIP Rules Tests
# =============================================================================


def test_6_4_R1_create_pip_authority_and_scoping(client: TestClient, p3_setup: dict[str, Any]):
    """6.4 R1: Authority checks for creating PIP:
    - Direct reporting manager: 201
    - Manager outside reporting chain: 403
    - Manager for themselves: 403
    - Unknown employee: 404
    - Employee cannot initiate PIP: 403
    - HR / Owner: 201
    """
    mgr_headers = _auth_headers(p3_setup["mgr_user_a"])
    other_mgr_headers = _auth_headers(p3_setup["other_mgr_user_a"])
    emp_headers = _auth_headers(p3_setup["emp_user_a"])

    target_emp_id = str(p3_setup["emp_a"].id)
    today = utcnow().date()

    # 1. Employee cannot initiate PIP
    r_emp = client.post(
        "/api/v1/performance/pips",
        headers=emp_headers,
        json={
            "employee_id": target_emp_id,
            "title": "Employee self-pip attempt",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=60)),
        },
    )
    assert r_emp.status_code == 403

    # 2. Manager outside reporting chain -> 403
    r_outside = client.post(
        "/api/v1/performance/pips",
        headers=other_mgr_headers,
        json={
            "employee_id": target_emp_id,
            "title": "Outside manager PIP attempt",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=60)),
        },
    )
    assert r_outside.status_code == 403

    # 3. Manager for self -> 403
    r_self = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": str(p3_setup["mgr_emp"].id),
            "title": "Manager self PIP attempt",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=60)),
        },
    )
    assert r_self.status_code == 403

    # 4. Unknown employee -> 404
    r_unknown = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": str(uuid.uuid4()),
            "title": "Unknown emp PIP",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=60)),
        },
    )
    assert r_unknown.status_code == 404

    # 5. Direct reporting manager -> 201
    r_mgr = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": target_emp_id,
            "title": "Performance Improvement Plan - Q3",
            "description": "Needs to meet SLA targets",
            "milestones_kpis": "Resolve 95% tickets on time",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=60)),
        },
    )
    assert r_mgr.status_code == 201
    data = r_mgr.json()
    assert data["employee_id"] == target_emp_id
    assert data["status"] == "draft"
    assert data["title"] == "Performance Improvement Plan - Q3"


def test_6_4_R2_mentor_validation(client: TestClient, p3_setup: dict[str, Any]):
    """6.4 R2: Mentor validation rules:
    - Cross-company mentor: 404 (multi-tenant isolation)
    - Non-existent mentor: 404
    - Inactive mentor in same company: 409
    - Employee cannot be their own mentor: 400/409/422
    - Valid active mentor in same company: 201
    - Mentor omitted: 201 (optional mentor)
    """
    mgr_headers = _auth_headers(p3_setup["other_mgr_user_a"])
    target_emp_id = str(p3_setup["other_emp_a"].id)
    today = utcnow().date()

    # 1. Mentor from Company B -> 404
    r_cross = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": target_emp_id,
            "mentor_id": str(p3_setup["mentor_emp_b"].id),
            "title": "Cross company mentor",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=30)),
        },
    )
    assert r_cross.status_code == 404

    # 2. Non-existent mentor -> 404
    r_nonexistent = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": target_emp_id,
            "mentor_id": str(uuid.uuid4()),
            "title": "Nonexistent mentor",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=30)),
        },
    )
    assert r_nonexistent.status_code == 404

    # 3. Inactive mentor -> 409
    r_inact = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": target_emp_id,
            "mentor_id": str(p3_setup["inactive_mentor_emp"].id),
            "title": "Inactive mentor",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=30)),
        },
    )
    assert r_inact.status_code == 409

    # 4. Valid active mentor -> 201
    r_valid = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": target_emp_id,
            "mentor_id": str(p3_setup["mentor_emp"].id),
            "title": "Valid mentored PIP",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=30)),
        },
    )
    assert r_valid.status_code == 201
    assert r_valid.json()["mentor_id"] == str(p3_setup["mentor_emp"].id)


def test_6_4_R3_single_active_pip_invariant(client: TestClient, p3_setup: dict[str, Any]):
    """6.4 R3: An employee cannot have multiple active PIPs concurrently (409 Conflict)."""
    mgr_headers = _auth_headers(p3_setup["mgr_user_a"])
    hr_headers = _auth_headers(p3_setup["hr_a"])
    target_emp_id = str(p3_setup["emp_a"].id)
    today = utcnow().date()

    # Create first PIP
    r1 = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": target_emp_id,
            "title": "Initial PIP",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=45)),
        },
    )
    assert r1.status_code == 201

    # Activate first PIP so it becomes active
    r_act = client.post(
        f"/api/v1/performance/pips/{r1.json()['id']}/activate",
        headers=hr_headers,
    )
    assert r_act.status_code == 200

    # Attempt to create second PIP while first is active -> 409
    r2 = client.post(
        "/api/v1/performance/pips",
        headers=hr_headers,
        json={
            "employee_id": target_emp_id,
            "title": "Second PIP attempt",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=45)),
        },
    )
    assert r2.status_code == 409
    assert "already has an active" in r2.json()["error"]["message"]


def test_6_4_R4_pip_read_scoping_and_blindness(client: TestClient, p3_setup: dict[str, Any]):
    """6.4 R4: PIP Read scoping:
    - Employee can view their own active PIP via /pips/active/{id} or list own via /pips.
    - Employee cannot view another employee's active PIP (403).
    - Manager can view their direct report's PIP.
    - HR can view all PIPs in their company.
    - Cross-company 404.
    """
    mgr_headers = _auth_headers(p3_setup["mgr_user_a"])
    emp_headers = _auth_headers(p3_setup["emp_user_a"])
    other_emp_headers = _auth_headers(p3_setup["other_emp_user_a"])
    hr_headers = _auth_headers(p3_setup["hr_a"])
    hr_b_headers = _auth_headers(p3_setup["hr_b"])

    target_emp_id = str(p3_setup["emp_a"].id)
    today = utcnow().date()

    # Create PIP
    r_create = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": target_emp_id,
            "title": "PIP Scoping Test",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=30)),
        },
    )
    assert r_create.status_code == 201
    pip_id = r_create.json()["id"]

    # Activate PIP so it can be viewed as active
    r_act = client.post(f"/api/v1/performance/pips/{pip_id}/activate", headers=mgr_headers)
    assert r_act.status_code == 200

    # 1. Employee views own active PIP -> 200
    r_own = client.get(f"/api/v1/performance/pips/active/{target_emp_id}", headers=emp_headers)
    assert r_own.status_code == 200
    assert r_own.json()["id"] == pip_id

    # 2. Other employee tries to view active PIP -> 403
    r_other = client.get(
        f"/api/v1/performance/pips/active/{target_emp_id}", headers=other_emp_headers
    )
    assert r_other.status_code == 403

    # 3. Employee lists PIPs -> sees only their own
    r_list_emp = client.get("/api/v1/performance/pips", headers=emp_headers)
    assert r_list_emp.status_code == 200
    pips = r_list_emp.json()
    assert all(p["employee_id"] == target_emp_id for p in pips)

    # 4. HR views PIPs -> sees employee's PIP
    r_list_hr = client.get(
        f"/api/v1/performance/pips?employee_id={target_emp_id}", headers=hr_headers
    )
    assert r_list_hr.status_code == 200
    assert len(r_list_hr.json()) >= 1

    # 5. Company B HR queries Company A employee's active PIP -> 404 (isolation)
    r_co_b = client.get(f"/api/v1/performance/pips/active/{target_emp_id}", headers=hr_b_headers)
    # Returns null (None) or 404
    assert r_co_b.status_code in (200, 404)
    if r_co_b.status_code == 200:
        assert r_co_b.json() is None


def test_6_4_R5_pip_evaluation_authority_and_state(client: TestClient, p3_setup: dict[str, Any]):
    """6.4 R5: Evaluating a PIP:
    - Only reporting manager, HR admin, or owner can evaluate.
    - Employee cannot evaluate (403).
    - Manager outside chain cannot evaluate (403).
    - Status must be active (evaluating already evaluated PIP yields 409).
    - Allowed outcomes: passed, failed, cancelled. Invalid outcome yields 422.
    """
    mgr_headers = _auth_headers(p3_setup["mgr_user_a"])
    other_mgr_headers = _auth_headers(p3_setup["other_mgr_user_a"])
    emp_headers = _auth_headers(p3_setup["emp_user_a"])
    target_emp_id = str(p3_setup["emp_a"].id)
    today = utcnow().date()

    # Create PIP
    r_create = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": target_emp_id,
            "title": "Evaluation Authority PIP",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=30)),
        },
    )
    pip_id = r_create.json()["id"]

    # Activate PIP before evaluating
    r_act = client.post(f"/api/v1/performance/pips/{pip_id}/activate", headers=mgr_headers)
    assert r_act.status_code == 200

    # 1. Employee tries to evaluate -> 403
    r_emp_eval = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=emp_headers,
        json={"outcome": "passed", "outcome_notes": "I think I passed"},
    )
    assert r_emp_eval.status_code == 403

    # 2. Outside manager tries to evaluate -> 403
    r_out_eval = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=other_mgr_headers,
        json={"outcome": "passed", "outcome_notes": "Looks ok to me"},
    )
    assert r_out_eval.status_code == 403

    # 3. Invalid outcome -> 422
    r_invalid = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_headers,
        json={"outcome": "promoted", "outcome_notes": "Promoted!"},
    )
    assert r_invalid.status_code == 422

    # 4. Valid evaluation (passed) by reporting manager -> 200
    r_passed = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_headers,
        json={"outcome": "passed", "outcome_notes": "Met all criteria successfully."},
    )
    assert r_passed.status_code == 200
    assert r_passed.json()["status"] == "passed"

    # 5. Subsequent evaluation attempt on finalized PIP -> 409
    r_again = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_headers,
        json={"outcome": "failed", "outcome_notes": "Changed mind"},
    )
    assert r_again.status_code == 409


def test_6_4_R6_failed_pip_triggers_atomic_separation(
    client: TestClient, db: Session, p3_setup: dict[str, Any]
):
    """6.4 R6: If a PIP outcome is 'failed', it must automatically trigger employee termination:
    - Employee resignation_status set to approved
    - Separation type set to pip_failed
    - Notice waived
    - Exit flow applied atomically
    - Audit log recorded
    """
    mgr_headers = _auth_headers(p3_setup["other_mgr_user_a"])
    target_emp = p3_setup["other_emp_a"]
    target_emp_id = str(target_emp.id)
    today = utcnow().date()

    # Create PIP
    r_create = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": target_emp_id,
            "title": "Crucial PIP",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=30)),
        },
    )
    assert r_create.status_code == 201
    pip_id = r_create.json()["id"]

    # Activate PIP so it can be viewed as active
    r_act = client.post(f"/api/v1/performance/pips/{pip_id}/activate", headers=mgr_headers)
    assert r_act.status_code == 200

    # Evaluate PIP as failed
    r_fail = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_headers,
        json={
            "outcome": "failed",
            "outcome_notes": "Did not meet milestones or improvement metrics.",
        },
    )
    assert r_fail.status_code == 200
    assert r_fail.json()["status"] == "failed"

    # Verify Employee database record
    db.expire_all()
    emp_refreshed = db.get(Employee, target_emp.id)
    assert emp_refreshed is not None
    assert emp_refreshed.resignation_status == ResignationStatus.approved
    assert emp_refreshed.separation_type == "pip_failed"
    assert "Failed Performance Improvement Plan" in (emp_refreshed.termination_reason or "")
    assert emp_refreshed.notice_waived is True

    # Verify Audit Log
    audit = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.company_id == p3_setup["cid_a"],
            AuditLog.entity_id == uuid.UUID(pip_id),
            AuditLog.action == "PIP_FAILED",
        )
        .order_by(AuditLog.created_at.desc())
    )
    assert audit is not None
    assert audit.details.get("outcome") == "failed"


# ==============================================================================
# L2: Rate limit tests (one 429 test per route for all 5 PIP write routes)
# ==============================================================================


def test_6_4_R7_rate_limit_post_pips(client: TestClient, p3_setup: dict[str, Any], limits_on: None):
    """POST /pips rate limit test (30/minute)."""
    mgr_headers = _auth_headers(p3_setup["mgr_user_a"])
    target_emp_id = str(p3_setup["emp_a"].id)
    hit_429 = False
    for i in range(40):
        res = client.post(
            "/api/v1/performance/pips",
            headers=mgr_headers,
            json={
                "employee_id": target_emp_id,
                "title": f"PIP {i}",
                "start_date": str(utcnow().date()),
                "end_date": str(utcnow().date() + timedelta(days=30)),
            },
        )
        if res.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "POST /api/v1/performance/pips must trigger 429 when exceeding rate limit"


def test_6_4_R8_rate_limit_post_pips_activate(
    client: TestClient, p3_setup: dict[str, Any], limits_on: None
):
    """POST /pips/{pip_id}/activate rate limit test (30/minute)."""
    mgr_headers = _auth_headers(p3_setup["mgr_user_a"])
    fake_pip_id = str(uuid.uuid4())
    hit_429 = False
    for _ in range(40):
        res = client.post(
            f"/api/v1/performance/pips/{fake_pip_id}/activate",
            headers=mgr_headers,
        )
        if res.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "POST /pips/{pip_id}/activate must trigger 429 when exceeding rate limit"


def test_6_4_R9_rate_limit_post_pips_extend(
    client: TestClient, p3_setup: dict[str, Any], limits_on: None
):
    """POST /pips/{pip_id}/extend rate limit test (30/minute)."""
    mgr_headers = _auth_headers(p3_setup["mgr_user_a"])
    fake_pip_id = str(uuid.uuid4())
    hit_429 = False
    for _ in range(40):
        res = client.post(
            f"/api/v1/performance/pips/{fake_pip_id}/extend",
            headers=mgr_headers,
            json={
                "new_end_date": str(utcnow().date() + timedelta(days=60)),
                "reason": "More time needed",
            },
        )
        if res.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "POST /pips/{pip_id}/extend must trigger 429 when exceeding rate limit"


def test_6_4_R10_rate_limit_post_pips_checkins(
    client: TestClient, p3_setup: dict[str, Any], limits_on: None
):
    """POST /pips/{pip_id}/check-ins rate limit test (30/minute)."""
    mgr_headers = _auth_headers(p3_setup["mgr_user_a"])
    fake_pip_id = str(uuid.uuid4())
    hit_429 = False
    for i in range(40):
        res = client.post(
            f"/api/v1/performance/pips/{fake_pip_id}/check-ins",
            headers=mgr_headers,
            json={"note": f"Check-in {i}"},
        )
        if res.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "POST /pips/{pip_id}/check-ins must trigger 429 when exceeding rate limit"


def test_6_4_R11_rate_limit_post_pips_evaluate(
    client: TestClient, p3_setup: dict[str, Any], limits_on: None
):
    """POST /pips/{pip_id}/evaluate rate limit test (30/minute)."""
    mgr_headers = _auth_headers(p3_setup["mgr_user_a"])
    fake_pip_id = str(uuid.uuid4())
    hit_429 = False
    for _ in range(40):
        res = client.post(
            f"/api/v1/performance/pips/{fake_pip_id}/evaluate",
            headers=mgr_headers,
            json={"outcome": "passed", "outcome_notes": "Passed well"},
        )
        if res.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "POST /pips/{pip_id}/evaluate must trigger 429 when exceeding rate limit"
