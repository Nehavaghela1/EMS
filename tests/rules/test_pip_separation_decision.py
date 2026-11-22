"""Tests for PIP Separation Decision Workflow (T1 - T8).

Covers:
- T1: A failed PIP leaves the employee active with no last working date and no resignation status.
- T2: The manager who evaluated cannot confirm the separation (403); a different HR admin can.
- T3: separate sets the last working date HR gave, and notice is NOT waived unless HR explicitly chose waived.
- T4: extend reopens the PIP with the new end date; retain clears pending_separation.
- T5: Another company's PIP is 404 on the decision route.
- T6: Both audit rows exist with the correct actor on each.
- T7: A decision on a PIP that did not fail returns 409.
- T8: Rate limit the new route at 30/minute with a 429 test using the shared limits_on fixture.
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
from app.modules.performance.models import PerformancePIP
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
def pip_decision_setup(db: Session) -> dict[str, Any]:
    db.expire_on_commit = False
    cid_a = uuid.uuid4()
    cid_b = uuid.uuid4()
    bind_tenant_to_session(db, company_id=cid_a, is_platform_admin=True)

    company_a = Company(
        id=cid_a,
        name=f"CompA_{uuid.uuid4().hex[:6]}",
        code=f"CA{uuid.uuid4().hex[:6].upper()}",
        email=f"compa_{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
    )
    company_b = Company(
        id=cid_b,
        name=f"CompB_{uuid.uuid4().hex[:6]}",
        code=f"CB{uuid.uuid4().hex[:6].upper()}",
        email=f"compb_{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
    )
    db.add_all([company_a, company_b])
    db.flush()

    # Users in Company A
    mgr_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"mgr_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password123!"),
        role=UserRole.manager,
        is_active=True,
    )
    hr1_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"hr1_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password123!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    hr2_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"hr2_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password123!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    emp_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"emp_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password123!"),
        role=UserRole.employee,
        is_active=True,
    )

    # Users in Company B
    hr_b_user = User(
        id=uuid.uuid4(),
        company_id=cid_b,
        email=f"hrb_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password123!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add_all([mgr_user, hr1_user, hr2_user, emp_user, hr_b_user])
    db.flush()

    # Employees in Company A
    mgr_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=mgr_user.id,
        first_name="Manager",
        last_name="One",
        email=mgr_user.email,
        employee_code=f"MGR{uuid.uuid4().hex[:4].upper()}",
        hire_date=date(2023, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    db.add(mgr_emp)
    db.flush()

    target_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=emp_user.id,
        first_name="Report",
        last_name="Target",
        email=emp_user.email,
        employee_code=f"EMP{uuid.uuid4().hex[:4].upper()}",
        hire_date=date(2023, 1, 1),
        employment_type=EmploymentType.full_time,
        reporting_manager_id=mgr_emp.id,
        invitation_status=InvitationStatus.activated,
        is_active=True,
    )
    db.add(target_emp)
    db.commit()

    return {
        "cid_a": cid_a,
        "cid_b": cid_b,
        "mgr_user": mgr_user,
        "hr1_user": hr1_user,
        "hr2_user": hr2_user,
        "emp_user": emp_user,
        "hr_b_user": hr_b_user,
        "mgr_emp": mgr_emp,
        "target_emp": target_emp,
    }


def _create_active_pip(client: TestClient, headers: dict[str, str], emp_id: str) -> str:
    today = utcnow().date()
    r = client.post(
        "/api/v1/performance/pips",
        headers=headers,
        json={
            "employee_id": emp_id,
            "title": "Performance Improvement Plan",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=30)),
        },
    )
    assert r.status_code == 201
    pip_id = r.json()["id"]
    r_act = client.post(f"/api/v1/performance/pips/{pip_id}/activate", headers=headers)
    assert r_act.status_code == 200
    return pip_id


def test_t1_failed_pip_leaves_employee_active_pending_separation(
    client: TestClient, db: Session, pip_decision_setup: dict[str, Any]
):
    """T1. A failed PIP leaves the employee active with no last working date and no resignation status."""
    mgr_h = _auth_headers(pip_decision_setup["mgr_user"])
    target_emp = pip_decision_setup["target_emp"]
    pip_id = _create_active_pip(client, mgr_h, str(target_emp.id))

    r_fail = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_h,
        json={"outcome": "failed", "outcome_notes": "Objectives failed"},
    )
    assert r_fail.status_code == 200
    assert r_fail.json()["status"] == "failed"

    db.expire_all()
    emp_db = db.get(Employee, target_emp.id)
    assert emp_db is not None
    assert emp_db.is_active is True
    assert emp_db.resignation_status == ResignationStatus.none
    assert emp_db.last_working_date is None
    assert emp_db.pending_separation is True


def test_t2_evaluator_cannot_confirm_separation_second_approver_can(
    client: TestClient, db: Session, pip_decision_setup: dict[str, Any]
):
    """T2. The manager who evaluated cannot confirm the separation (403); a different HR admin can."""
    hr1_h = _auth_headers(pip_decision_setup["hr1_user"])
    hr2_h = _auth_headers(pip_decision_setup["hr2_user"])
    target_emp = pip_decision_setup["target_emp"]
    pip_id = _create_active_pip(client, hr1_h, str(target_emp.id))

    # HR1 evaluates PIP as failed
    r_fail = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=hr1_h,
        json={"outcome": "failed", "outcome_notes": "HR1 evaluated failure"},
    )
    assert r_fail.status_code == 200

    # HR1 tries to decide separation -> 403 (maker-checker / second-approver rule)
    target_lwd = str(utcnow().date() + timedelta(days=14))
    r_decide_hr1 = client.post(
        f"/api/v1/performance/pips/{pip_id}/separation-decision",
        headers=hr1_h,
        json={"decision": "separate", "last_working_date": target_lwd, "notice_choice": "served"},
    )
    assert r_decide_hr1.status_code == 403

    # HR2 (different HR admin) can confirm separation -> 200
    r_decide_hr2 = client.post(
        f"/api/v1/performance/pips/{pip_id}/separation-decision",
        headers=hr2_h,
        json={"decision": "separate", "last_working_date": target_lwd, "notice_choice": "served"},
    )
    assert r_decide_hr2.status_code == 200
    assert r_decide_hr2.json()["decision"] == "separate"


def test_t3_separate_sets_last_working_date_and_notice_choice(
    client: TestClient, db: Session, pip_decision_setup: dict[str, Any]
):
    """T3. separate sets the last working date HR gave, and notice is NOT waived unless HR explicitly chose waived."""
    mgr_h = _auth_headers(pip_decision_setup["mgr_user"])
    hr1_h = _auth_headers(pip_decision_setup["hr1_user"])
    target_emp = pip_decision_setup["target_emp"]
    pip_id = _create_active_pip(client, mgr_h, str(target_emp.id))

    r_fail = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_h,
        json={"outcome": "failed", "outcome_notes": "Failed"},
    )
    assert r_fail.status_code == 200

    target_lwd = utcnow().date() + timedelta(days=30)
    # Default is notice served (or explicit notice_choice='served')
    r_decide = client.post(
        f"/api/v1/performance/pips/{pip_id}/separation-decision",
        headers=hr1_h,
        json={"decision": "separate", "last_working_date": str(target_lwd), "notice_choice": "served"},
    )
    assert r_decide.status_code == 200

    db.expire_all()
    emp_db = db.get(Employee, target_emp.id)
    assert emp_db is not None
    assert emp_db.last_working_date == target_lwd
    assert emp_db.resignation_status == ResignationStatus.approved
    assert emp_db.notice_waived is False
    assert emp_db.pending_separation is False


def test_t4_extend_reopens_pip_and_retain_clears_pending_separation(
    client: TestClient, db: Session, pip_decision_setup: dict[str, Any]
):
    """T4. extend reopens the PIP with the new end date; retain clears pending_separation."""
    mgr_h = _auth_headers(pip_decision_setup["mgr_user"])
    hr1_h = _auth_headers(pip_decision_setup["hr1_user"])
    target_emp = pip_decision_setup["target_emp"]
    pip_id = _create_active_pip(client, mgr_h, str(target_emp.id))

    # Evaluate failed
    r_fail = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_h,
        json={"outcome": "failed", "outcome_notes": "Failed"},
    )
    assert r_fail.status_code == 200

    # Decision: extend
    today = utcnow().date()
    new_end = str(today + timedelta(days=60))
    r_extend = client.post(
        f"/api/v1/performance/pips/{pip_id}/separation-decision",
        headers=hr1_h,
        json={"decision": "extend", "new_end_date": new_end, "reason": "Give another chance"},
    )
    assert r_extend.status_code == 200

    db.expire_all()
    pip_db = db.get(PerformancePIP, uuid.UUID(pip_id))
    assert pip_db is not None
    assert pip_db.status == "extended"
    assert str(pip_db.end_date) == new_end
    emp_db = db.get(Employee, target_emp.id)
    assert emp_db.pending_separation is False

    # Now evaluate failed again from extended state
    r_fail2 = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_h,
        json={"outcome": "failed", "outcome_notes": "Still failed"},
    )
    assert r_fail2.status_code == 200

    db.expire_all()
    emp_db = db.get(Employee, target_emp.id)
    assert emp_db.pending_separation is True

    # Decision: retain
    r_retain = client.post(
        f"/api/v1/performance/pips/{pip_id}/separation-decision",
        headers=hr1_h,
        json={"decision": "retain", "reason": "Role transferred to another team"},
    )
    assert r_retain.status_code == 200

    db.expire_all()
    emp_db = db.get(Employee, target_emp.id)
    assert emp_db.pending_separation is False
    assert emp_db.resignation_status == ResignationStatus.none


def test_t5_cross_company_pip_is_404(
    client: TestClient, db: Session, pip_decision_setup: dict[str, Any]
):
    """T5. Another company's PIP is 404 on the decision route."""
    mgr_h = _auth_headers(pip_decision_setup["mgr_user"])
    hr_b_h = _auth_headers(pip_decision_setup["hr_b_user"])
    target_emp = pip_decision_setup["target_emp"]
    pip_id = _create_active_pip(client, mgr_h, str(target_emp.id))

    client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_h,
        json={"outcome": "failed", "outcome_notes": "Failed"},
    )

    r_decide = client.post(
        f"/api/v1/performance/pips/{pip_id}/separation-decision",
        headers=hr_b_h,
        json={"decision": "retain", "reason": "Attempting cross tenant access"},
    )
    assert r_decide.status_code == 404


def test_t6_both_audit_rows_exist_with_correct_actor(
    client: TestClient, db: Session, pip_decision_setup: dict[str, Any]
):
    """T6. Both audit rows exist with the correct actor on each."""
    mgr_h = _auth_headers(pip_decision_setup["mgr_user"])
    hr1_h = _auth_headers(pip_decision_setup["hr1_user"])
    target_emp = pip_decision_setup["target_emp"]
    pip_id = _create_active_pip(client, mgr_h, str(target_emp.id))

    client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_h,
        json={"outcome": "failed", "outcome_notes": "Failed"},
    )

    client.post(
        f"/api/v1/performance/pips/{pip_id}/separation-decision",
        headers=hr1_h,
        json={"decision": "retain", "reason": "Retained by HR"},
    )

    audit_eval = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.company_id == pip_decision_setup["cid_a"],
            AuditLog.entity_id == uuid.UUID(pip_id),
            AuditLog.action == "PIP_FAILED",
        )
    )
    assert audit_eval is not None
    assert audit_eval.actor_user_id == pip_decision_setup["mgr_user"].id

    audit_decision = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.company_id == pip_decision_setup["cid_a"],
            AuditLog.entity_id == uuid.UUID(pip_id),
            AuditLog.action == "PIP_SEPARATION_DECISION",
        )
    )
    assert audit_decision is not None
    assert audit_decision.actor_user_id == pip_decision_setup["hr1_user"].id
    assert audit_decision.details.get("decision") == "retain"


def test_t7_decision_on_pip_that_did_not_fail_returns_409(
    client: TestClient, db: Session, pip_decision_setup: dict[str, Any]
):
    """T7. A decision on a PIP that did not fail returns 409."""
    mgr_h = _auth_headers(pip_decision_setup["mgr_user"])
    hr1_h = _auth_headers(pip_decision_setup["hr1_user"])
    target_emp = pip_decision_setup["target_emp"]
    pip_id = _create_active_pip(client, mgr_h, str(target_emp.id))

    # Try decision while PIP is active
    r_act = client.post(
        f"/api/v1/performance/pips/{pip_id}/separation-decision",
        headers=hr1_h,
        json={"decision": "retain", "reason": "Active PIP"},
    )
    assert r_act.status_code == 409

    # Evaluate as passed
    r_pass = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=mgr_h,
        json={"outcome": "passed", "outcome_notes": "Passed"},
    )
    assert r_pass.status_code == 200

    # Try decision after passed
    r_pass_dec = client.post(
        f"/api/v1/performance/pips/{pip_id}/separation-decision",
        headers=hr1_h,
        json={"decision": "retain", "reason": "Passed PIP"},
    )
    assert r_pass_dec.status_code == 409


def test_t8_rate_limit_separation_decision_30_per_minute(
    client: TestClient, pip_decision_setup: dict[str, Any], limits_on: None
):
    """T8. Rate limit the new route at 30/minute with a 429 test using the shared limits_on fixture."""
    hr1_h = _auth_headers(pip_decision_setup["hr1_user"])
    fake_pip_id = str(uuid.uuid4())
    hit_429 = False
    for _ in range(40):
        res = client.post(
            f"/api/v1/performance/pips/{fake_pip_id}/separation-decision",
            headers=hr1_h,
            json={"decision": "retain", "reason": "Test rate limit"},
        )
        if res.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "POST /pips/{pip_id}/separation-decision must trigger 429 when exceeding rate limit"
