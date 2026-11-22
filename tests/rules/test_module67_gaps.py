"""Comprehensive tests for Module 6 & 7 gaps:
- PART A: Project cost calculation (A1-A5)
- PART B: Local date / timezone checks (B3)
- PART C: Notifications for Module 6 & 7 & budget threshold alerts (C1-C4)
- PART D: PIP gaps (D1-D4)
"""

import time
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.payroll.models import EmployeeSalary, SalaryStructure
from app.modules.platform.models import Notification


def _auth_headers(user: User) -> dict[str, str]:
    user_id = user.__dict__.get("id") or user.id
    company_id = user.__dict__.get("company_id") or user.company_id
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(
        sub=str(user_id),
        company_id=str(company_id) if company_id else None,
        role=role_val,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def gap_setup(db: Session) -> dict[str, Any]:
    db.expire_on_commit = False

    cid = uuid.uuid4()
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    company = Company(
        id=cid,
        name=f"GapTest_{uuid.uuid4().hex[:6]}",
        code=f"GT{uuid.uuid4().hex[:6].upper()}",
        email=f"gap_{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
    )
    db.add(company)
    db.flush()

    def make_user_and_emp(
        prefix: str, role: UserRole, reporting_manager_id: uuid.UUID | None = None
    ) -> tuple[User, Employee]:
        u = User(
            id=uuid.uuid4(),
            company_id=cid,
            email=f"{prefix}_{uuid.uuid4().hex[:4]}@example.com",
            hashed_password=hash_password("Pass1234!"),
            role=role,
            is_active=True,
        )
        db.add(u)
        db.flush()

        e = Employee(
            id=uuid.uuid4(),
            company_id=cid,
            user_id=u.id,
            first_name=prefix.capitalize(),
            last_name="Tester",
            email=u.email,
            employee_code=f"E-{uuid.uuid4().hex[:6].upper()}",
            employment_type=EmploymentType.full_time,
            hire_date=utcnow().date() - timedelta(days=200),
            invitation_status=InvitationStatus.activated,
            reporting_manager_id=reporting_manager_id,
            is_active=True,
        )
        db.add(e)
        db.flush()
        return u, e

    owner_u, owner_e = make_user_and_emp("owner", UserRole.owner)
    hr_u, hr_e = make_user_and_emp("hr", UserRole.hr_admin)
    pm_u, pm_e = make_user_and_emp("pm", UserRole.manager)
    emp_u, emp_e = make_user_and_emp("emp", UserRole.employee, reporting_manager_id=pm_e.id)
    emp2_u, emp2_e = make_user_and_emp("emp2", UserRole.employee, reporting_manager_id=pm_e.id)
    mentor_u, mentor_e = make_user_and_emp("mentor", UserRole.employee)
    other_emp_u, other_emp_e = make_user_and_emp("other", UserRole.employee)

    # Salary Structure
    struct = SalaryStructure(
        id=uuid.uuid4(),
        company_id=cid,
        name="Gap Standard Structure",
        country="IN",
        is_active=True,
    )
    db.add(struct)
    db.flush()

    db.commit()

    return {
        "cid": cid,
        "company": company,
        "owner_u": owner_u,
        "owner_e": owner_e,
        "hr_u": hr_u,
        "hr_e": hr_e,
        "pm_u": pm_u,
        "pm_e": pm_e,
        "emp_u": emp_u,
        "emp_e": emp_e,
        "emp2_u": emp2_u,
        "emp2_e": emp2_e,
        "mentor_u": mentor_u,
        "mentor_e": mentor_e,
        "other_emp_u": other_emp_u,
        "other_emp_e": other_emp_e,
        "struct": struct,
    }


def _create_project_and_task(
    client: TestClient,
    gap_setup: dict[str, Any],
    budget: str | None = "100000.00",
) -> tuple[str, str]:
    pm_h = _auth_headers(gap_setup["pm_u"])
    r_p = client.post(
        "/api/v1/projects",
        json={
            "name": f"Proj_{uuid.uuid4().hex[:6]}",
            "code": f"P{uuid.uuid4().hex[:4].upper()}",
            "budget": budget,
            "manager_id": str(gap_setup["pm_e"].id),
            "start_date": (utcnow().date() - timedelta(days=60)).isoformat(),
        },
        headers=pm_h,
    )
    assert r_p.status_code == 201, r_p.text
    proj_id = r_p.json()["id"]

    # Add member emp_e
    client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(gap_setup["emp_e"].id), "role": "member"},
        headers=pm_h,
    )
    # Add member emp2_e
    client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"employee_id": str(gap_setup["emp2_e"].id), "role": "member"},
        headers=pm_h,
    )

    r_t = client.post(
        f"/api/v1/projects/{proj_id}/tasks",
        json={
            "title": "Task 1",
            "assigned_to": str(gap_setup["emp_e"].id),
            "status": "todo",
        },
        headers=pm_h,
    )
    assert r_t.status_code == 201, r_t.text
    task_id = r_t.json()["id"]

    return proj_id, task_id


# ==============================================================================
# PART A: Project Cost Calculation (A1 - A5)
# ==============================================================================


def test_a1_a2_work_date_before_any_salary_row_gives_zero_cost_and_no_salary_data_true(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """A1, A2, A5: Work date before any salary row gives 0.00 cost and no_salary_data=True,
    and returns hours_without_salary_data.
    """
    proj_id, task_id = _create_project_and_task(client, gap_setup)
    emp_h = _auth_headers(gap_setup["emp_u"])
    pm_h = _auth_headers(gap_setup["pm_u"])

    # Salary effective starting tomorrow
    salary = EmployeeSalary(
        id=uuid.uuid4(),
        company_id=gap_setup["cid"],
        employee_id=gap_setup["emp_e"].id,
        structure_id=gap_setup["struct"].id,
        ctc=Decimal("1200000.00"),
        hourly_rate=Decimal("1000.00"),
        effective_from=utcnow().date() + timedelta(days=1),
        effective_to=None,
        created_by=gap_setup["hr_u"].id,
    )
    db.add(salary)
    db.commit()

    # Log time on today's date (before salary row)
    work_date = (utcnow().date() - timedelta(days=2)).isoformat()
    r = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id,
            "task_id": task_id,
            "date": work_date,
            "hours": "8.00",
            "description": "Dev work before salary starts",
        },
        headers=emp_h,
    )
    assert r.status_code == 201, r.text
    entry_id = r.json()["id"]

    # Approve entry
    client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=pm_h,
    )

    # Check project summary
    s = client.get(f"/api/v1/projects/{proj_id}/summary", headers=pm_h).json()
    assert Decimal(s["budget_spent"]) == Decimal("0.00")
    assert s["no_salary_data"] is True
    assert Decimal(str(s["hours_without_salary_data"])) == Decimal("8.00")


def test_a1_a5_later_salary_is_never_used_for_earlier_date(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """A1, A5: A later salary row is never used for an earlier work date."""
    proj_id, task_id = _create_project_and_task(client, gap_setup)
    emp_h = _auth_headers(gap_setup["emp_u"])
    pm_h = _auth_headers(gap_setup["pm_u"])

    # Salary effective from 10 days in the future
    salary = EmployeeSalary(
        id=uuid.uuid4(),
        company_id=gap_setup["cid"],
        employee_id=gap_setup["emp_e"].id,
        structure_id=gap_setup["struct"].id,
        ctc=Decimal("2112000.00"),
        effective_from=utcnow().date() + timedelta(days=10),
        effective_to=None,
        created_by=gap_setup["hr_u"].id,
    )
    db.add(salary)
    db.commit()

    # Time entry logged 5 days ago
    work_date = (utcnow().date() - timedelta(days=5)).isoformat()
    r = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id,
            "task_id": task_id,
            "date": work_date,
            "hours": "5.00",
            "description": "Earlier work",
        },
        headers=emp_h,
    )
    assert r.status_code == 201
    entry_id = r.json()["id"]

    client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=pm_h,
    )

    s = client.get(f"/api/v1/projects/{proj_id}/summary", headers=pm_h).json()
    # Cost must be 0.00 because later salary is never used
    assert Decimal(s["budget_spent"]) == Decimal("0.00")
    assert s["no_salary_data"] is True
    assert Decimal(str(s["hours_without_salary_data"])) == Decimal("5.00")


def test_a3_a5_176_divisor_asserted_on_known_ctc(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """A3, A5: STANDARD_MONTHLY_HOURS = 176 divisor:
    ctc = 2,112,000 -> monthly = 176,000 -> hourly = 176,000 / 176 = 1,000.00.
    10 hours -> 10,000.00 cost.
    """
    proj_id, task_id = _create_project_and_task(client, gap_setup)
    emp_h = _auth_headers(gap_setup["emp_u"])
    pm_h = _auth_headers(gap_setup["pm_u"])

    salary = EmployeeSalary(
        id=uuid.uuid4(),
        company_id=gap_setup["cid"],
        employee_id=gap_setup["emp_e"].id,
        structure_id=gap_setup["struct"].id,
        ctc=Decimal("2112000.00"),
        effective_from=utcnow().date() - timedelta(days=30),
        effective_to=None,
        created_by=gap_setup["hr_u"].id,
    )
    db.add(salary)
    db.commit()

    work_date = (utcnow().date() - timedelta(days=1)).isoformat()
    r = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id,
            "task_id": task_id,
            "date": work_date,
            "hours": "10.00",
            "description": "Standard work hours",
        },
        headers=emp_h,
    )
    assert r.status_code == 201
    entry_id = r.json()["id"]

    client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=pm_h,
    )

    s = client.get(f"/api/v1/projects/{proj_id}/summary", headers=pm_h).json()
    assert Decimal(s["budget_spent"]) == Decimal("10000.00")
    assert s["no_salary_data"] is False
    assert Decimal(str(s["hours_without_salary_data"])) == Decimal("0.00")


def test_a4_a5_two_entries_each_round_up_gives_sum_equal_to_lines(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """A4, A5: Round half-up to 2 places per entry BEFORE adding to running total.
    Rate = 10.05.
    Entry 1: 1.5 hrs * 10.05 = 15.075 -> rounded to 15.08.
    Entry 2: 1.5 hrs * 10.05 = 15.075 -> rounded to 15.08.
    Running total = 15.08 + 15.08 = 30.16.
    (If unrounded sum 3.0 * 10.05 were taken, it would be 30.15).
    """
    proj_id, task_id = _create_project_and_task(client, gap_setup)
    emp_h = _auth_headers(gap_setup["emp_u"])
    pm_h = _auth_headers(gap_setup["pm_u"])

    salary = EmployeeSalary(
        id=uuid.uuid4(),
        company_id=gap_setup["cid"],
        employee_id=gap_setup["emp_e"].id,
        structure_id=gap_setup["struct"].id,
        ctc=Decimal("1200000.00"),
        hourly_rate=Decimal("10.05"),
        effective_from=utcnow().date() - timedelta(days=30),
        effective_to=None,
        created_by=gap_setup["hr_u"].id,
    )
    db.add(salary)
    db.commit()

    date1 = (utcnow().date() - timedelta(days=2)).isoformat()
    date2 = (utcnow().date() - timedelta(days=1)).isoformat()

    r1 = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id,
            "task_id": task_id,
            "date": date1,
            "hours": "1.50",
            "description": "Entry 1",
        },
        headers=emp_h,
    )
    r2 = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id,
            "task_id": task_id,
            "date": date2,
            "hours": "1.50",
            "description": "Entry 2",
        },
        headers=emp_h,
    )
    assert r1.status_code == 201 and r2.status_code == 201
    e1_id, e2_id = r1.json()["id"], r2.json()["id"]

    client.post(
        f"/api/v1/projects/time-entries/{e1_id}/approve?status_action=approved",
        headers=pm_h,
    )
    client.post(
        f"/api/v1/projects/time-entries/{e2_id}/approve?status_action=approved",
        headers=pm_h,
    )

    s = client.get(f"/api/v1/projects/{proj_id}/summary", headers=pm_h).json()
    assert Decimal(s["budget_spent"]) == Decimal("30.16")


# ==============================================================================
# PART B: Local Date and Timezone (B3)
# ==============================================================================


def test_b3_tz_asia_kolkata_today_utc_accepted_and_daily_cap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, gap_setup: dict[str, Any]
):
    """B3: With TZ=Asia/Kolkata set, a time entry dated 'today in UTC' is accepted
    and the daily 24-hour cap counts the correct day.
    """
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    if hasattr(time, "tzset"):
        time.tzset()

    proj_id, task_id = _create_project_and_task(client, gap_setup)
    emp_h = _auth_headers(gap_setup["emp_u"])

    today_utc = utcnow().date().isoformat()

    # 1. First entry of 14 hours dated today in UTC is accepted
    r1 = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id,
            "task_id": task_id,
            "date": today_utc,
            "hours": "14.00",
            "description": "First chunk",
        },
        headers=emp_h,
    )
    assert r1.status_code == 201, r1.text

    # 2. Second entry of 10 hours on same day reaches 24h cap
    r2 = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id,
            "task_id": task_id,
            "date": today_utc,
            "hours": "10.00",
            "description": "Second chunk",
        },
        headers=emp_h,
    )
    assert r2.status_code == 201, r2.text

    # 3. Third entry of 1 hour on same day exceeds 24h cap -> 422
    r3 = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id,
            "task_id": task_id,
            "date": today_utc,
            "hours": "1.00",
            "description": "Exceeding cap",
        },
        headers=emp_h,
    )
    assert r3.status_code in (422, 400)


# ==============================================================================
# PART C: Notifications (C1, C2, C3, C4)
# ==============================================================================


def test_c1_cycle_activated_notifies_active_employees(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """C1: Cycle activated -> active company employees are notified."""
    hr_h = _auth_headers(gap_setup["hr_u"])

    # Create cycle
    r_c = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": f"Cycle_{uuid.uuid4().hex[:6]}",
            "start_date": "2030-01-01",
            "end_date": "2030-12-31",
        },
        headers=hr_h,
    )
    assert r_c.status_code == 201
    cycle_id = r_c.json()["id"]

    # Clear notifications for clean count
    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    db.query(Notification).filter(Notification.company_id == gap_setup["cid"]).delete()
    db.commit()

    # Activate cycle
    r_act = client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=hr_h,
    )
    assert r_act.status_code == 200

    notifs = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "performance_cycle_activated",
        )
        .all()
    )
    recipients = {n.user_id for n in notifs}
    assert gap_setup["emp_u"].id in recipients, (
        "Active employee must be notified on cycle activation"
    )


def test_c1_goal_created_or_edited_by_other_notifies_employee_and_manager(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """C1: Someone other than the employee creates or edits that employee's goals
    -> the employee and their reporting manager.
    """
    hr_h = _auth_headers(gap_setup["hr_u"])
    emp_h = _auth_headers(gap_setup["emp_u"])

    # Create and activate a cycle
    r_c = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": f"GoalCycle_{uuid.uuid4().hex[:6]}",
            "start_date": "2031-01-01",
            "end_date": "2031-12-31",
        },
        headers=hr_h,
    )
    cycle_id = r_c.json()["id"]
    client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=hr_h,
    )

    # 1. Employee creates own goal -> no "other" notification
    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    db.query(Notification).filter(Notification.company_id == gap_setup["cid"]).delete()
    db.commit()

    r_own = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": cycle_id,
            "goals": [
                {
                    "title": "Own Goal",
                    "weightage": "50.00",
                }
            ],
        },
        headers=emp_h,
    )
    assert r_own.status_code == 201

    notifs = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "employee_goals_updated",
        )
        .all()
    )
    assert len(notifs) == 0, "No notification when employee creates own goal"

    # 2. HR creates goal for employee -> notifies employee AND manager
    r_hr = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": cycle_id,
            "employee_id": str(gap_setup["emp_e"].id),
            "goals": [
                {
                    "title": "HR Assigned Goal",
                    "weightage": "50.00",
                }
            ],
        },
        headers=hr_h,
    )
    assert r_hr.status_code == 201

    notifs_hr = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "employee_goals_updated",
        )
        .all()
    )
    recipients = {n.user_id for n in notifs_hr}
    assert gap_setup["emp_u"].id in recipients, "Employee must be notified"
    assert gap_setup["pm_u"].id in recipients, "Reporting manager must be notified"


def test_c1_self_and_manager_reviews_notifications(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """C1: Self-review submitted -> employee's reporting manager.
    Manager review submitted -> employee.
    """
    hr_h = _auth_headers(gap_setup["hr_u"])
    emp_h = _auth_headers(gap_setup["emp_u"])
    pm_h = _auth_headers(gap_setup["pm_u"])

    r_c = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": f"RevCycle_{uuid.uuid4().hex[:6]}",
            "start_date": "2032-01-01",
            "end_date": "2032-12-31",
        },
        headers=hr_h,
    )
    cycle_id = r_c.json()["id"]
    client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=hr_h,
    )

    r_g = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": cycle_id,
            "goals": [
                {
                    "title": "Goal for Review",
                    "weightage": "100.00",
                }
            ],
        },
        headers=emp_h,
    )
    assert r_g.status_code == 201
    goal_id = r_g.json()[0]["id"]

    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    db.query(Notification).filter(Notification.company_id == gap_setup["cid"]).delete()
    db.commit()

    # Self-review submitted -> manager notified
    r_self = client.post(
        f"/api/v1/performance/goals/{goal_id}/self-review",
        json={"rating": "4.5", "comments": "Good progress"},
        headers=emp_h,
    )
    assert r_self.status_code == 200

    self_notifs = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "self_review_submitted",
        )
        .all()
    )
    assert any(n.user_id == gap_setup["pm_u"].id for n in self_notifs)

    # Manager review submitted -> employee notified
    r_mgr = client.post(
        f"/api/v1/performance/goals/{goal_id}/manager-review",
        json={"rating": "4.0", "comments": "Agreed"},
        headers=pm_h,
    )
    assert r_mgr.status_code == 200

    mgr_notifs = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "manager_review_submitted",
        )
        .all()
    )
    assert any(n.user_id == gap_setup["emp_u"].id for n in mgr_notifs)


def test_c1_pip_created_and_evaluated_notifications(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """C1: PIP created -> employee and mentor.
    PIP evaluated -> employee.
    """
    pm_h = _auth_headers(gap_setup["pm_u"])

    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    db.query(Notification).filter(Notification.company_id == gap_setup["cid"]).delete()
    db.commit()

    today = utcnow().date()
    r_pip = client.post(
        "/api/v1/performance/pips",
        json={
            "employee_id": str(gap_setup["emp_e"].id),
            "mentor_id": str(gap_setup["mentor_e"].id),
            "title": "Notif PIP",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=30)).isoformat(),
        },
        headers=pm_h,
    )
    assert r_pip.status_code == 201
    pip_id = r_pip.json()["id"]

    # Verify PIP created notifications
    pip_notifs = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "pip_created",
        )
        .all()
    )
    recipients = {n.user_id for n in pip_notifs}
    assert gap_setup["emp_u"].id in recipients, "Employee must be notified of PIP creation"
    assert gap_setup["mentor_u"].id in recipients, "Mentor must be notified of PIP creation"

    # Activate PIP before evaluating
    r_act = client.post(f"/api/v1/performance/pips/{pip_id}/activate", headers=pm_h)
    assert r_act.status_code == 200

    # Evaluate PIP
    db.query(Notification).filter(Notification.company_id == gap_setup["cid"]).delete()
    db.commit()

    r_eval = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        json={"outcome": "passed", "outcome_notes": "Well done"},
        headers=pm_h,
    )
    assert r_eval.status_code == 200

    eval_notifs = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "pip_evaluated",
        )
        .all()
    )
    assert any(n.user_id == gap_setup["emp_u"].id for n in eval_notifs)


def test_c2_task_assignee_changed_notifies_new_assignee(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """C2: Task assignee changed -> new assignee."""
    proj_id, task_id = _create_project_and_task(client, gap_setup)
    pm_h = _auth_headers(gap_setup["pm_u"])

    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    db.query(Notification).filter(Notification.company_id == gap_setup["cid"]).delete()
    db.commit()

    # Reassign task from emp_e to emp2_e
    r = client.put(
        f"/api/v1/projects/tasks/{task_id}",
        json={"assigned_to": str(gap_setup["emp2_e"].id)},
        headers=pm_h,
    )
    assert r.status_code == 200

    notifs = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "task_assigned",
        )
        .all()
    )
    assert any(n.user_id == gap_setup["emp2_u"].id for n in notifs)


def test_c2_time_entry_submitted_and_approved_rejected_notifications(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """C2: Time entry submitted -> approver; approved or rejected -> employee."""
    proj_id, task_id = _create_project_and_task(client, gap_setup)
    emp_h = _auth_headers(gap_setup["emp_u"])
    pm_h = _auth_headers(gap_setup["pm_u"])

    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    db.query(Notification).filter(Notification.company_id == gap_setup["cid"]).delete()
    db.commit()

    work_date = (utcnow().date() - timedelta(days=1)).isoformat()
    r = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id,
            "task_id": task_id,
            "date": work_date,
            "hours": "4.00",
            "description": "Submitted work",
            "status": "submitted",
        },
        headers=emp_h,
    )
    assert r.status_code == 201
    entry_id = r.json()["id"]

    # Approver (PM) received time_entry_submitted notification
    sub_notifs = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "time_entry_submitted",
        )
        .all()
    )
    assert any(n.user_id == gap_setup["pm_u"].id for n in sub_notifs)

    # Approve entry -> employee notified
    db.query(Notification).filter(Notification.company_id == gap_setup["cid"]).delete()
    db.commit()

    client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=pm_h,
    )

    app_notifs = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "time_entry_approved",
        )
        .all()
    )
    assert any(n.user_id == gap_setup["emp_u"].id for n in app_notifs)


def test_c3_c4_w4_budget_threshold_alerts_moved_to_celery_task(
    client: TestClient,
    db: Session,
    gap_setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    limits_off: None,
):
    """C3, C4, W4: Budget threshold alerts must not live in a GET.
    - 65 GET requests to /summary against a project that crossed the threshold
      write nothing to the database, leave the sent_at columns NULL, and send no notifications.
    - Running the scheduled task directly sends the 80% notification to the PM and company
      HR admins, and sets budget_alert_80_sent_at.
    - Running it a second time sends nothing.
    - Running it after spend crosses 100% sends 100% alert and sets budget_alert_100_sent_at.
    """
    from app.modules.projects.models import Project
    from app.workers.tasks.projects import check_project_budget_alerts_task

    monkeypatch.setattr("app.workers.tasks.projects.get_task_db_session", lambda: db)

    # Project budget = 10,000.00
    proj_id_str, task_id_str = _create_project_and_task(client, gap_setup, budget="10000.00")
    proj_id = uuid.UUID(proj_id_str)
    emp_h = _auth_headers(gap_setup["emp_u"])
    pm_h = _auth_headers(gap_setup["pm_u"])

    # Hourly rate = 1,000.00
    salary = EmployeeSalary(
        id=uuid.uuid4(),
        company_id=gap_setup["cid"],
        employee_id=gap_setup["emp_e"].id,
        structure_id=gap_setup["struct"].id,
        ctc=Decimal("1200000.00"),
        hourly_rate=Decimal("1000.00"),
        effective_from=utcnow().date() - timedelta(days=30),
        effective_to=None,
        created_by=gap_setup["hr_u"].id,
    )
    db.add(salary)
    db.commit()

    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    db.query(Notification).filter(Notification.company_id == gap_setup["cid"]).delete()
    db.commit()

    # Entry 1: 8 hours = 8,000.00 (exactly 80%)
    r1 = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id_str,
            "task_id": task_id_str,
            "date": (utcnow().date() - timedelta(days=2)).isoformat(),
            "hours": "8.00",
            "description": "80% threshold work",
        },
        headers=emp_h,
    )
    assert r1.status_code == 201
    client.post(
        f"/api/v1/projects/time-entries/{r1.json()['id']}/approve?status_action=approved",
        headers=pm_h,
    )

    # Read summary 65 times (W4)
    for _ in range(65):
        resp = client.get(f"/api/v1/projects/{proj_id_str}/summary", headers=pm_h)
        assert resp.status_code == 200

    # Assert 65 GET requests wrote nothing to DB, left sent_at NULL, and sent no notifications
    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    proj = db.get(Project, proj_id)
    assert proj.budget_alert_80_sent_at is None
    assert proj.budget_alert_100_sent_at is None

    notifs_before = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "budget_threshold_alert",
        )
        .all()
    )
    assert len(notifs_before) == 0, "GET /summary must send no notifications"

    # Now run scheduled task directly
    alerts_run_1 = check_project_budget_alerts_task()
    assert alerts_run_1 >= 1

    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    proj = db.get(Project, proj_id)
    assert proj.budget_alert_80_sent_at is not None
    assert proj.budget_alert_100_sent_at is None

    notifs_80 = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "budget_threshold_alert",
            Notification.title.ilike("%80%%"),
        )
        .all()
    )
    pm_80 = [n for n in notifs_80 if n.user_id == gap_setup["pm_u"].id]
    hr_80 = [n for n in notifs_80 if n.user_id == gap_setup["hr_u"].id]
    assert len(pm_80) == 1, f"PM must receive exactly 1 alert for 80%, got {len(pm_80)}"
    assert len(hr_80) == 1, f"HR Admin must receive exactly 1 alert for 80%, got {len(hr_80)}"

    # Running it a second time sends nothing
    alerts_run_2 = check_project_budget_alerts_task()
    assert alerts_run_2 == 0

    notifs_80_again = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "budget_threshold_alert",
            Notification.title.ilike("%80%%"),
        )
        .all()
    )
    assert len(notifs_80_again) == len(notifs_80), "Second run must send no duplicate 80% alerts"

    # Entry 2: 2 hours = 2,000.00 -> total 10,000.00 (100%)
    r2 = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id_str,
            "task_id": task_id_str,
            "date": (utcnow().date() - timedelta(days=1)).isoformat(),
            "hours": "2.00",
            "description": "Crossing 100% threshold",
        },
        headers=emp_h,
    )
    assert r2.status_code == 201
    client.post(
        f"/api/v1/projects/time-entries/{r2.json()['id']}/approve?status_action=approved",
        headers=pm_h,
    )

    # Read summary again - still no side-effects
    client.get(f"/api/v1/projects/{proj_id_str}/summary", headers=pm_h)
    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    proj = db.get(Project, proj_id)
    assert proj.budget_alert_100_sent_at is None

    # Running scheduled task after spend crosses 100% sends 100% alert
    alerts_run_3 = check_project_budget_alerts_task()
    assert alerts_run_3 >= 1

    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    proj = db.get(Project, proj_id)
    assert proj.budget_alert_100_sent_at is not None

    notifs_100 = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "budget_threshold_alert",
            Notification.title.ilike("%100%%"),
        )
        .all()
    )
    pm_100 = [n for n in notifs_100 if n.user_id == gap_setup["pm_u"].id]
    hr_100 = [n for n in notifs_100 if n.user_id == gap_setup["hr_u"].id]
    assert len(pm_100) == 1, f"PM must receive exactly 1 alert for 100%, got {len(pm_100)}"
    assert len(hr_100) == 1, f"HR Admin must receive exactly 1 alert for 100%, got {len(hr_100)}"


def test_c3_no_budget_never_alerts(
    client: TestClient, db: Session, gap_setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    """C3: A project with no budget never alerts."""
    from app.workers.tasks.projects import check_project_budget_alerts_task

    monkeypatch.setattr("app.workers.tasks.projects.get_task_db_session", lambda: db)

    proj_id, task_id = _create_project_and_task(client, gap_setup, budget=None)
    emp_h = _auth_headers(gap_setup["emp_u"])
    pm_h = _auth_headers(gap_setup["pm_u"])

    salary = EmployeeSalary(
        id=uuid.uuid4(),
        company_id=gap_setup["cid"],
        employee_id=gap_setup["emp_e"].id,
        structure_id=gap_setup["struct"].id,
        ctc=Decimal("1200000.00"),
        hourly_rate=Decimal("1000.00"),
        effective_from=utcnow().date() - timedelta(days=30),
        effective_to=None,
        created_by=gap_setup["hr_u"].id,
    )
    db.add(salary)
    db.commit()

    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    db.query(Notification).filter(Notification.company_id == gap_setup["cid"]).delete()
    db.commit()

    r = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": proj_id,
            "task_id": task_id,
            "date": (utcnow().date() - timedelta(days=1)).isoformat(),
            "hours": "10.00",
            "description": "Unbudgeted work",
        },
        headers=emp_h,
    )
    assert r.status_code == 201
    client.post(
        f"/api/v1/projects/time-entries/{r.json()['id']}/approve?status_action=approved",
        headers=pm_h,
    )

    client.get(f"/api/v1/projects/{proj_id}/summary", headers=pm_h)
    check_project_budget_alerts_task()

    alerts = (
        db.query(Notification)
        .filter(
            Notification.company_id == gap_setup["cid"],
            Notification.type == "budget_threshold_alert",
        )
        .all()
    )
    assert len(alerts) == 0, "No budget project must never alert"


# ==============================================================================
# PART D: PIP Gaps (D1 - D4)
# ==============================================================================


def test_d4_draft_pip_cannot_be_evaluated(client: TestClient, gap_setup: dict[str, Any]):
    """D4: A draft PIP cannot be evaluated (409 Conflict)."""
    pm_h = _auth_headers(gap_setup["pm_u"])
    today = utcnow().date()

    r_pip = client.post(
        "/api/v1/performance/pips",
        json={
            "employee_id": str(gap_setup["emp_e"].id),
            "title": "Draft Evaluate Test",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=30)).isoformat(),
        },
        headers=pm_h,
    )
    assert r_pip.status_code == 201
    pip_id = r_pip.json()["id"]

    # Attempt evaluate while draft -> 409
    r_eval = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        json={"outcome": "passed", "outcome_notes": "Premature eval"},
        headers=pm_h,
    )
    assert r_eval.status_code == 409, r_eval.text


def test_d4_extend_pip_validation(client: TestClient, gap_setup: dict[str, Any]):
    """D4: Extend with an earlier date is 422; extend with no reason is 422."""
    pm_h = _auth_headers(gap_setup["pm_u"])
    today = utcnow().date()
    end_date = today + timedelta(days=30)

    r_pip = client.post(
        "/api/v1/performance/pips",
        json={
            "employee_id": str(gap_setup["emp_e"].id),
            "title": "Extend Validation PIP",
            "start_date": today.isoformat(),
            "end_date": end_date.isoformat(),
        },
        headers=pm_h,
    )
    assert r_pip.status_code == 201
    pip_id = r_pip.json()["id"]

    # Activate PIP
    r_act = client.post(f"/api/v1/performance/pips/{pip_id}/activate", headers=pm_h)
    assert r_act.status_code == 200

    # 1. Extend with earlier date -> 422
    r_earlier = client.post(
        f"/api/v1/performance/pips/{pip_id}/extend",
        json={
            "new_end_date": (end_date - timedelta(days=5)).isoformat(),
            "reason": "Trying to shorten",
        },
        headers=pm_h,
    )
    assert r_earlier.status_code == 422

    # 2. Extend with same date -> 422
    r_same = client.post(
        f"/api/v1/performance/pips/{pip_id}/extend",
        json={
            "new_end_date": end_date.isoformat(),
            "reason": "Same date extension",
        },
        headers=pm_h,
    )
    assert r_same.status_code == 422

    # 3. Extend with no reason / empty reason -> 422
    r_no_reason = client.post(
        f"/api/v1/performance/pips/{pip_id}/extend",
        json={
            "new_end_date": (end_date + timedelta(days=15)).isoformat(),
            "reason": "   ",
        },
        headers=pm_h,
    )
    assert r_no_reason.status_code == 422


def test_d4_checkin_notes_permissions_and_immutability(
    client: TestClient, gap_setup: dict[str, Any]
):
    """D4: Mentor can add check-in note, random employee gets 403;
    employee can read own check-ins;
    check-in note cannot be edited or deleted (no such route).
    """
    pm_h = _auth_headers(gap_setup["pm_u"])
    emp_h = _auth_headers(gap_setup["emp_u"])
    mentor_h = _auth_headers(gap_setup["mentor_u"])
    other_h = _auth_headers(gap_setup["other_emp_u"])
    today = utcnow().date()

    r_pip = client.post(
        "/api/v1/performance/pips",
        json={
            "employee_id": str(gap_setup["emp_e"].id),
            "mentor_id": str(gap_setup["mentor_e"].id),
            "title": "Check-in PIP",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=30)).isoformat(),
        },
        headers=pm_h,
    )
    assert r_pip.status_code == 201
    pip_id = r_pip.json()["id"]

    # 1. Random employee tries to add check-in note -> 403
    r_other = client.post(
        f"/api/v1/performance/pips/{pip_id}/check-ins",
        json={"note": "Unrelated employee note"},
        headers=other_h,
    )
    assert r_other.status_code == 403

    # 2. Mentor adds check-in note -> 201
    r_mentor = client.post(
        f"/api/v1/performance/pips/{pip_id}/check-ins",
        json={"note": "Week 1 check-in: Good progress on milestones."},
        headers=mentor_h,
    )
    assert r_mentor.status_code == 201
    note_id = r_mentor.json()["id"]

    # 3. Employee reads own PIP's check-in notes -> 200
    r_read_emp = client.get(
        f"/api/v1/performance/pips/{pip_id}/check-ins",
        headers=emp_h,
    )
    assert r_read_emp.status_code == 200
    notes = r_read_emp.json()
    assert len(notes) == 1
    assert notes[0]["note"] == "Week 1 check-in: Good progress on milestones."

    # 4. Other employee tries to read check-ins -> 403
    r_read_other = client.get(
        f"/api/v1/performance/pips/{pip_id}/check-ins",
        headers=other_h,
    )
    assert r_read_other.status_code == 403

    # 5. Check-in cannot be edited or deleted (no such route -> 404/405)
    r_put = client.put(
        f"/api/v1/performance/pips/{pip_id}/check-ins/{note_id}",
        json={"note": "Tampered note"},
        headers=mentor_h,
    )
    assert r_put.status_code in (404, 405)

    r_del = client.delete(
        f"/api/v1/performance/pips/{pip_id}/check-ins/{note_id}",
        headers=mentor_h,
    )
    assert r_del.status_code in (404, 405)


def test_d4_extended_pip_can_fail_with_atomic_termination(
    client: TestClient, db: Session, gap_setup: dict[str, Any]
):
    """D4: An extended PIP can later be failed and the termination still happens
    in one commit.
    """
    pm_h = _auth_headers(gap_setup["pm_u"])
    today = utcnow().date()
    end_date = today + timedelta(days=30)

    r_pip = client.post(
        "/api/v1/performance/pips",
        json={
            "employee_id": str(gap_setup["emp_e"].id),
            "title": "Extend-Fail PIP",
            "start_date": today.isoformat(),
            "end_date": end_date.isoformat(),
        },
        headers=pm_h,
    )
    assert r_pip.status_code == 201
    pip_id = r_pip.json()["id"]

    # Activate
    client.post(f"/api/v1/performance/pips/{pip_id}/activate", headers=pm_h)

    # Extend PIP
    new_end_date = end_date + timedelta(days=15)
    r_ext = client.post(
        f"/api/v1/performance/pips/{pip_id}/extend",
        json={
            "new_end_date": new_end_date.isoformat(),
            "reason": "Need two more weeks to evaluate performance metrics.",
        },
        headers=pm_h,
    )
    assert r_ext.status_code == 200
    assert r_ext.json()["status"] == "extended"

    # Evaluate as failed
    r_fail = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        json={
            "outcome": "failed",
            "outcome_notes": "Did not meet extended expectations.",
        },
        headers=pm_h,
    )
    assert r_fail.status_code == 200
    assert r_fail.json()["status"] == "failed"

    # Separation decision confirmed by HR
    hr_h = _auth_headers(gap_setup["hr_u"])
    r_decide = client.post(
        f"/api/v1/performance/pips/{pip_id}/separation-decision",
        headers=hr_h,
        json={
            "decision": "separate",
            "last_working_date": str(utcnow().date()),
            "notice_choice": "waived",
        },
    )
    assert r_decide.status_code == 200

    # Verify employee record is terminated atomically
    bind_tenant_to_session(db, company_id=gap_setup["cid"], is_platform_admin=True)
    emp_db = db.get(Employee, gap_setup["emp_e"].id)
    assert emp_db is not None
    assert emp_db.is_active is False or emp_db.resignation_status is not None
    assert emp_db.separation_type == "pip_failed"


# ---------------------------------------------------------------------------
# PART Z4: Two-step rollback tests
# ---------------------------------------------------------------------------


def test_z4_create_project_rollback_when_add_member_fails(
    db: Session, gap_setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    """Z4 Action 1: create project then auto-add manager as member.
    Force the second step (add_member) to raise and assert NOTHING from the
    first step (project row) remains in the database.
    """
    from app.modules.projects.models import Project
    from app.modules.projects.schemas import ProjectCreate
    from app.modules.projects.service import ProjectService

    cid = gap_setup["cid"]
    pm_u = gap_setup["pm_u"]
    pm_e = gap_setup["pm_e"]
    service = ProjectService(db)

    # Force second step to raise
    def fail_add_member(*args, **kwargs):
        raise RuntimeError("Simulated failure in add_member")

    monkeypatch.setattr(service.repo, "add_member", fail_add_member)

    code = f"Z4P{uuid.uuid4().hex[:4].upper()}"
    proj_in = ProjectCreate(
        name=f"Z4_Proj_{uuid.uuid4().hex[:6]}",
        code=code,
        budget=Decimal("50000.00"),
        manager_id=pm_e.id,
    )

    with pytest.raises(RuntimeError, match="Simulated failure in add_member"):
        service.create_project(cid, proj_in, actor=pm_u)

    db.rollback()

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    proj = db.query(Project).filter(Project.company_id == cid, Project.code == code).first()
    assert proj is None, "Project from first step must NOT be in the database after rollback"


def test_z4_remove_member_rollback_when_repo_remove_fails(
    client: TestClient, db: Session, gap_setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    """Z4 Action 2: remove member then unassign their open tasks.
    Force the second step (remove_member in repo) to raise and assert
    NOTHING from the first step (task unassignment) remains in the database.
    """
    from app.modules.projects.models import ProjectMember, Task
    from app.modules.projects.service import ProjectService

    proj_id_str, task_id_str = _create_project_and_task(client, gap_setup)
    proj_id = uuid.UUID(proj_id_str)
    task_id = uuid.UUID(task_id_str)
    emp_id = gap_setup["emp_e"].id
    cid = gap_setup["cid"]
    hr_u = gap_setup["hr_u"]

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    task_before = db.get(Task, task_id)
    assert task_before.assigned_to == emp_id

    service = ProjectService(db)

    # Force second step to raise
    def fail_remove_member(*args, **kwargs):
        raise RuntimeError("Simulated failure in remove_member")

    monkeypatch.setattr(service.repo, "remove_member", fail_remove_member)

    with pytest.raises(RuntimeError, match="Simulated failure in remove_member"):
        service.remove_member(cid, proj_id, emp_id, actor=hr_u)

    db.rollback()

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    task_after = db.get(Task, task_id)
    assert task_after.assigned_to == emp_id, "Open task must still be assigned to member"
    member = (
        db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == proj_id,
            ProjectMember.employee_id == emp_id,
        )
        .first()
    )
    assert member is not None, "Member must still exist in the database"


def test_z4_approve_time_entry_rollback_when_audit_fails(
    client: TestClient, db: Session, gap_setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    """Z4 Action 3: approve a time entry.
    Force the second step (audit record) to raise and assert
    NOTHING from the first step (status change to approved) remains in the database.
    """
    from app.modules.projects.models import TimeEntry
    from app.modules.projects.service import ProjectService

    proj_id, task_id = _create_project_and_task(client, gap_setup)
    emp_h = _auth_headers(gap_setup["emp_u"])

    # Submit a time entry
    today = utcnow().date()
    r_sub = client.post(
        "/api/v1/projects/time-entries",
        json={
            "project_id": str(proj_id),
            "task_id": str(task_id),
            "date": today.isoformat(),
            "hours": "4.00",
            "description": "Working on task 1",
            "billable": True,
            "status": "submitted",
        },
        headers=emp_h,
    )
    assert r_sub.status_code == 201
    entry_id = uuid.UUID(r_sub.json()["id"])
    cid = gap_setup["cid"]
    pm_u = gap_setup["pm_u"]

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    entry_before = db.get(TimeEntry, entry_id)
    assert entry_before.status == "submitted"

    service = ProjectService(db)

    # Force second step (audit) to raise
    def fail_audit(*args, **kwargs):
        raise RuntimeError("Simulated failure in audit.record")

    monkeypatch.setattr(service.audit, "record", fail_audit)

    with pytest.raises(RuntimeError, match="Simulated failure in audit.record"):
        service.approve_reject_time_entry(
            company_id=cid,
            entry_id=entry_id,
            status="approved",
            approver_user_id=pm_u.id,
            actor=pm_u,
        )

    db.rollback()

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    entry_after = db.get(TimeEntry, entry_id)
    assert entry_after.status == "submitted", "Time entry must remain submitted after rollback"
    assert entry_after.approved_at is None
