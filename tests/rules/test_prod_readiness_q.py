"""Tests for PART Q: Probation confirmation workflow and background notifications.

Q1: On or after probation end date, hr_admin or owner records outcome:
    confirmed, extended with new end date, or not confirmed.
Q2: Confirming sets probation_status = 'confirmed'.
    Extending moves probation_end_date forward and requires a reason.
    Not confirmed leaves employee active with no last_working_date.
Q3: Audited with employee id, outcome, and dates.
    Celery job picks employees whose probation ends within next 14 days and notifies HR.
Q4: Tests:
    - confirming before the end date is refused (409);
    - extending requires a reason and a later date (422/400);
    - not-confirmed leaves employee active with no last_working_date;
    - a manager and an employee each get 403;
    - another tenant's employee returns 404;
    - the audit row exists;
    - employee with no probation_end_date returns 409 and is skipped by Celery job;
    - due-soon job picks up only employees inside the window.
"""

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, ProbationDecision
from app.modules.platform.models import AuditLog, Notification
from app.workers.tasks.hr import notify_probations_due_soon_task
from tests.conftest import TenantContext


def _create_employee_with_probation(
    db: Session,
    company_id: uuid.UUID,
    probation_end_date: date | None,
    probation_status: str = "pending",
) -> Employee:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    emp = Employee(
        id=uuid.uuid4(),
        company_id=company_id,
        employee_code=f"PRB-{uuid.uuid4().hex[:5]}",
        first_name="Probation",
        last_name="Tester",
        email=f"prb-{uuid.uuid4().hex[:6]}@example.com",
        employment_type=EmploymentType.full_time,
        hire_date=date(2026, 1, 1),
        probation_end_date=probation_end_date,
        probation_status=probation_status,
        notice_period_days=30,
        is_active=True,
    )
    db.add(emp)
    db.commit()
    return emp


def test_q4_confirm_before_end_date_refused(
    client: TestClient, company_a: TenantContext, db: Session
) -> None:
    today = utcnow().date()
    # End date is in the future
    emp = _create_employee_with_probation(db, company_a.company_id, today + timedelta(days=5))

    res = client.post(
        f"/api/v1/employees/{emp.id}/probation-decision",
        json={"outcome": "confirmed"},
        headers=company_a.hr_headers,
    )
    assert res.status_code == 409
    assert "before the probation end date" in res.json()["error"]["message"]


def test_q4_extending_requires_reason_and_later_date(
    client: TestClient, company_a: TenantContext, db: Session
) -> None:
    today = utcnow().date()
    # End date is past or today
    past_end = today - timedelta(days=2)
    emp = _create_employee_with_probation(db, company_a.company_id, past_end)

    # Missing reason
    res_no_reason = client.post(
        f"/api/v1/employees/{emp.id}/probation-decision",
        json={"outcome": "extended", "new_end_date": str(today + timedelta(days=30))},
        headers=company_a.hr_headers,
    )
    assert res_no_reason.status_code in (400, 422)

    # Date not later than current
    res_bad_date = client.post(
        f"/api/v1/employees/{emp.id}/probation-decision",
        json={
            "outcome": "extended",
            "new_end_date": str(past_end - timedelta(days=1)),
            "reason": "Performance evaluation",
        },
        headers=company_a.hr_headers,
    )
    assert res_bad_date.status_code in (400, 422)

    # Valid extension
    new_end = today + timedelta(days=60)
    res_valid = client.post(
        f"/api/v1/employees/{emp.id}/probation-decision",
        json={
            "outcome": "extended",
            "new_end_date": str(new_end),
            "reason": "Extended by 60 days to complete project review",
        },
        headers=company_a.hr_headers,
    )
    assert res_valid.status_code == 200
    data = res_valid.json()
    assert data["outcome"] == "extended"
    assert data["new_end_date"] == str(new_end)

    # Verify employee model updated
    db.expire_all()
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    updated_emp = db.query(Employee).filter(Employee.id == emp.id).one()
    assert updated_emp.probation_end_date == new_end
    assert updated_emp.probation_status == "extended"


def test_q4_not_confirmed_leaves_employee_active_no_lwd(
    client: TestClient, company_a: TenantContext, db: Session
) -> None:
    today = utcnow().date()
    emp = _create_employee_with_probation(db, company_a.company_id, today)

    res = client.post(
        f"/api/v1/employees/{emp.id}/probation-decision",
        json={"outcome": "not_confirmed", "reason": "Did not meet bar"},
        headers=company_a.hr_headers,
    )
    assert res.status_code == 200

    db.expire_all()
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    updated_emp = db.query(Employee).filter(Employee.id == emp.id).one()
    assert updated_emp.probation_status == "not_confirmed"
    assert updated_emp.is_active is True
    assert updated_emp.last_working_date is None


def test_q4_confirm_succeeds_and_creates_audit_and_decision_row(
    client: TestClient, company_a: TenantContext, db: Session
) -> None:
    today = utcnow().date()
    past_end = today - timedelta(days=1)
    emp = _create_employee_with_probation(db, company_a.company_id, past_end)

    res = client.post(
        f"/api/v1/employees/{emp.id}/probation-decision",
        json={"outcome": "confirmed", "reason": "Exceptional delivery"},
        headers=company_a.hr_headers,
    )
    assert res.status_code == 200
    assert res.json()["outcome"] == "confirmed"

    db.expire_all()
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    updated_emp = db.query(Employee).filter(Employee.id == emp.id).one()
    assert updated_emp.probation_status == "confirmed"

    # Verify decision table row
    decision_row = (
        db.query(ProbationDecision)
        .filter(
            ProbationDecision.company_id == company_a.company_id,
            ProbationDecision.employee_id == emp.id,
        )
        .first()
    )
    assert decision_row is not None
    assert decision_row.outcome == "confirmed"
    assert decision_row.previous_end_date == past_end

    # Verify audit row
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == company_a.company_id,
            AuditLog.action == "PROBATION_DECIDED",
            AuditLog.entity_id == emp.id,
        )
        .first()
    )
    assert audit is not None
    assert audit.details["outcome"] == "confirmed"


def test_q4_roles_and_cross_tenant_and_no_probation(
    client: TestClient, company_a: TenantContext, company_b: TenantContext, db: Session
) -> None:
    today = utcnow().date()
    emp = _create_employee_with_probation(db, company_a.company_id, today)

    # Employee gets 403
    res_emp = client.post(
        f"/api/v1/employees/{emp.id}/probation-decision",
        json={"outcome": "confirmed"},
        headers=company_a.employee_headers,
    )
    assert res_emp.status_code == 403

    # Manager gets 403
    res_mgr = client.post(
        f"/api/v1/employees/{emp.id}/probation-decision",
        json={"outcome": "confirmed"},
        headers=company_a.manager_headers,
    )
    assert res_mgr.status_code == 403

    # Other tenant returns 404, never 403
    res_other = client.post(
        f"/api/v1/employees/{emp.id}/probation-decision",
        json={"outcome": "confirmed"},
        headers=company_b.hr_headers,
    )
    assert res_other.status_code == 404

    # Employee with no probation_end_date set returns 409
    emp_no_prob = _create_employee_with_probation(db, company_a.company_id, None)
    res_no_prob = client.post(
        f"/api/v1/employees/{emp_no_prob.id}/probation-decision",
        json={"outcome": "confirmed"},
        headers=company_a.hr_headers,
    )
    assert res_no_prob.status_code == 409
    assert "does not have a probation period configured" in res_no_prob.json()["error"]["message"]


def test_q4_due_soon_celery_task_picks_only_window(
    client: TestClient, company_a: TenantContext, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.workers.tasks.hr as hr_tasks

    monkeypatch.setattr(hr_tasks, "get_task_db_session", lambda: db)
    today = utcnow().date()
    # 1. Candidate within 14 days (due in 7 days) -> included
    emp_in = _create_employee_with_probation(db, company_a.company_id, today + timedelta(days=7))
    emp_in_id = emp_in.id
    # 2. Candidate due in 25 days (outside 14-day window) -> excluded
    emp_far = _create_employee_with_probation(db, company_a.company_id, today + timedelta(days=25))
    emp_far_id = emp_far.id
    # 3. Candidate already past (due 3 days ago) -> excluded (past window)
    emp_past = _create_employee_with_probation(db, company_a.company_id, today - timedelta(days=3))
    emp_past_id = emp_past.id
    # 4. Candidate with no probation end date -> excluded
    emp_none = _create_employee_with_probation(db, company_a.company_id, None)
    emp_none_id = emp_none.id
    # 5. Candidate within window but already confirmed -> excluded
    emp_confirmed = _create_employee_with_probation(
        db, company_a.company_id, today + timedelta(days=5), probation_status="confirmed"
    )
    emp_confirmed_id = emp_confirmed.id

    result = notify_probations_due_soon_task()
    assert result["notified_count"] >= 1

    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    notifs = (
        db.query(Notification)
        .filter(
            Notification.company_id == company_a.company_id,
            Notification.type == "probation_due_soon",
        )
        .all()
    )

    notified_emp_ids = {n.entity_id for n in notifs}
    assert emp_in_id in notified_emp_ids
    assert emp_far_id not in notified_emp_ids
    assert emp_past_id not in notified_emp_ids
    assert emp_none_id not in notified_emp_ids
    assert emp_confirmed_id not in notified_emp_ids

    # Check notification payload and action_url
    sample = [n for n in notifs if n.entity_id == emp_in_id][0]
    assert sample.action_url == f"/employees/{emp_in_id}"
    assert "ends on" in sample.message
