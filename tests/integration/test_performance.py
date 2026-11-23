import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import User, UserRole
from tests.conftest import TenantContext


def _create_employee_with_user(
    db: Session, company_id: uuid.UUID, role: UserRole = UserRole.employee
) -> tuple[Employee, dict[str, str]]:
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    user = User(
        company_id=company_id,
        email=f"perf-{uuid.uuid4().hex[:6]}@example.test",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    employee = Employee(
        company_id=company_id,
        user_id=user.id,
        employee_code=f"EMP{uuid.uuid4().hex[:6].upper()}",
        first_name="Perf",
        last_name="Test",
        email=user.email,
        employment_type=EmploymentType.full_time,
        hire_date=utcnow().date(),
        is_active=True,
        invitation_status=InvitationStatus.activated,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return employee, {"Authorization": f"Bearer {token}"}


def test_performance_cycle_lifecycle(client: TestClient, company_a: TenantContext):
    # 1. HR creates performance cycle (draft)
    create_res = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": "FY 2026-27 Annual Review",
            "cycle_type": "annual",
            "start_date": "2026-04-01",
            "end_date": "2027-03-31",
            "self_review_deadline": "2027-03-15",
            "manager_review_deadline": "2027-03-25",
        },
        headers=company_a.hr_headers,
    )
    assert create_res.status_code == 201
    cycle = create_res.json()
    assert cycle["status"] == "draft"
    cycle_id = cycle["id"]

    # 2. HR activates cycle
    act_res = client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=company_a.hr_headers,
    )
    assert act_res.status_code == 200
    assert act_res.json()["status"] == "active"


def test_goals_weightage_sum_gate_and_review_workflow(
    client: TestClient, company_a: TenantContext, db: Session
):
    emp, emp_headers = _create_employee_with_user(db, company_a.company_id)

    # 1. Create and Activate Cycle
    cycle_res = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": "Q3 2026 Review",
            "cycle_type": "quarterly",
            "start_date": "2026-07-01",
            "end_date": "2026-09-30",
        },
        headers=company_a.hr_headers,
    )
    cycle_id = cycle_res.json()["id"]
    client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=company_a.hr_headers,
    )

    # 2. Employee sets 2 goals with weightages summing to 80 (invalid: must sum to 100)
    goals_res = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": cycle_id,
            "goals": [
                {
                    "title": "Deliver WP-22 Backend",
                    "description": "Build performance endpoints",
                    "weightage": "50.00",
                    "target_value": "100% tests passing",
                },
                {
                    "title": "Optimize Queries",
                    "description": "Improve database speed",
                    "weightage": "30.00",
                    "target_value": "< 50ms latency",
                },
            ],
        },
        headers=emp_headers,
    )
    assert goals_res.status_code == 201
    created_goals = goals_res.json()
    goal1_id = created_goals[0]["id"]
    goal2_id = created_goals[1]["id"]

    # 3. GATE ASSERTION: Self-review MUST fail because weightages sum to 80, not 100
    fail_self_res = client.post(
        f"/api/v1/performance/goals/{goal1_id}/self-review",
        json={"rating": "4.5", "comments": "Completed task"},
        headers=emp_headers,
    )
    assert fail_self_res.status_code == 400
    assert fail_self_res.json()["error"]["code"] == "invalid_weightage_sum"

    # 4. Employee updates Goal 2 weightage to 50.00 so total == 100.00
    client.put(
        f"/api/v1/performance/goals/{goal2_id}",
        json={"weightage": "50.00"},
        headers=emp_headers,
    )

    # 5. Now Self-review succeeds!
    self_res = client.post(
        f"/api/v1/performance/goals/{goal1_id}/self-review",
        json={"rating": "4.5", "comments": "Completed on time"},
        headers=emp_headers,
    )
    assert self_res.status_code == 200
    assert self_res.json()["rating"] == "4.5"

    # 6. Manager submits rating
    mgr_res = client.post(
        f"/api/v1/performance/goals/{goal1_id}/manager-review",
        json={"rating": "5.0", "comments": "Exceeded expectations"},
        headers=company_a.hr_headers,
    )
    assert mgr_res.status_code == 200
    assert mgr_res.json()["rating"] == "5.0"

    # 6b. A summary cannot be finalized while goal 2 has no manager rating:
    # a missing rating is never filled in with a default.
    early_summary = client.post(
        f"/api/v1/performance/summary/{emp.id}",
        json={"cycle_id": cycle_id, "overall_comments": "Too early"},
        headers=company_a.hr_headers,
    )
    assert early_summary.status_code == 409, early_summary.text

    # 6c. Goal 2 is reviewed too, so every goal carries a real rating.
    assert (
        client.post(
            f"/api/v1/performance/goals/{goal2_id}/self-review",
            json={"rating": "3.0", "comments": "Partly met"},
            headers=emp_headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/performance/goals/{goal2_id}/manager-review",
            json={"rating": "3.0", "comments": "Room to improve"},
            headers=company_a.hr_headers,
        ).status_code
        == 200
    )

    # 7. Finalize summary
    summary_res = client.post(
        f"/api/v1/performance/summary/{emp.id}",
        json={
            "cycle_id": cycle_id,
            "overall_comments": "Outstanding performance this quarter",
            "salary_revision_recommended": True,
            "recommended_increment_percent": "12.50",
        },
        headers=company_a.hr_headers,
    )
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["employee_id"] == str(emp.id)
    assert summary["salary_revision_recommended"] is True


def test_tier_1_performance_module_invariants(
    client: TestClient, company_a: TenantContext, db: Session
):
    """Tests for Tier 1:
    A. self_review_status (null before review, submitted after submission, draft after reopen)
    B. update_goal_progress refuses (409) after self-review has been submitted and progress unchanged
    C. review deadlines enforced (reject late submission with 409 Conflict)
    D. status and progress synchronization (completed sets progress=100; progress=100 sets completed)
    """
    from datetime import timedelta

    today = utcnow().date()
    # 1. Create an active cycle with future deadlines
    cycle_res = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": f"Tier1 Cycle {uuid.uuid4().hex[:6]}",
            "cycle_type": "annual",
            "start_date": str(today - timedelta(days=10)),
            "end_date": str(today + timedelta(days=90)),
            "self_review_deadline": str(today + timedelta(days=30)),
            "manager_review_deadline": str(today + timedelta(days=60)),
        },
        headers=company_a.hr_headers,
    )
    assert cycle_res.status_code == 201
    cycle_id = cycle_res.json()["id"]

    # Activate cycle
    act_res = client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=company_a.hr_headers,
    )
    assert act_res.status_code == 200

    emp, emp_headers = _create_employee_with_user(db, company_a.company_id)

    # Create goals summing to 100%
    goals_res = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": cycle_id,
            "employee_id": str(emp.id),
            "goals": [
                {"title": "Goal A", "weightage": 60, "target_value": "100%"},
                {"title": "Goal B", "weightage": 40, "target_value": "100%"},
            ],
        },
        headers=emp_headers,
    )
    assert goals_res.status_code == 201
    goal_a_id = goals_res.json()[0]["id"]
    goal_b_id = goals_res.json()[1]["id"]

    # Part A Test: self_review_status is null before any review
    listed = client.get(f"/api/v1/performance/goals/{emp.id}", headers=emp_headers).json()
    assert listed[0]["self_review_status"] is None

    # Part D Test 1: Updating progress to 50 does not mark completed; updating progress to 100 sets status to completed
    prg_res1 = client.put(
        f"/api/v1/performance/goals/{goal_a_id}/progress",
        json={"progress": 50, "notes": "Halfway"},
        headers=emp_headers,
    )
    assert prg_res1.status_code == 200
    assert prg_res1.json()["progress"] == 50
    assert prg_res1.json()["status"] == "in_progress"

    # Part D Test 2: Marking status completed forces progress to 100
    stat_res = client.put(
        f"/api/v1/performance/goals/{goal_b_id}",
        json={"status": "completed"},
        headers=emp_headers,
    )
    assert stat_res.status_code == 200
    assert stat_res.json()["status"] == "completed"
    assert stat_res.json()["progress"] == 100

    # Part D Test 3: Updating progress to 100 sets status to completed
    prg_res2 = client.put(
        f"/api/v1/performance/goals/{goal_a_id}/progress",
        json={"progress": 100, "notes": "Done"},
        headers=emp_headers,
    )
    assert prg_res2.status_code == 200
    assert prg_res2.json()["progress"] == 100
    assert prg_res2.json()["status"] == "completed"

    # Part A & C Test: On-time submission succeeds
    sub_res = client.post(
        f"/api/v1/performance/goals/{goal_a_id}/self-review",
        json={"rating": "4.5", "comments": "Great progress"},
        headers=emp_headers,
    )
    assert sub_res.status_code == 200
    rev_id = sub_res.json()["id"]

    # Part A Test: self_review_status is submitted after submission
    listed_after_sub = client.get(f"/api/v1/performance/goals/{emp.id}", headers=emp_headers).json()
    goal_map = {g["id"]: g for g in listed_after_sub}
    assert goal_map[goal_a_id]["self_review_status"] == "submitted"

    # Part B Test: PUT to /goals/{id}/progress on reviewed goal returns 409 and stored value is unchanged
    fail_prg = client.put(
        f"/api/v1/performance/goals/{goal_a_id}/progress",
        json={"progress": 80, "notes": "Trying to modify reviewed goal"},
        headers=emp_headers,
    )
    assert fail_prg.status_code == 409
    unchanged_goal = client.get(f"/api/v1/performance/goals/{emp.id}", headers=emp_headers).json()
    unchanged_map = {g["id"]: g for g in unchanged_goal}
    assert unchanged_map[goal_a_id]["progress"] == 100

    # Part A Test: Reopen review -> self_review_status becomes draft
    reopen_res = client.post(
        f"/api/v1/performance/reviews/{rev_id}/reopen",
        json={"reason": "Need adjustments to comments"},
        headers=company_a.hr_headers,
    )
    assert reopen_res.status_code == 200
    assert reopen_res.json()["status"] == "draft"

    listed_after_reopen = client.get(
        f"/api/v1/performance/goals/{emp.id}", headers=emp_headers
    ).json()
    reopen_map = {g["id"]: g for g in listed_after_reopen}
    assert reopen_map[goal_a_id]["self_review_status"] == "draft"

    # Part C Test: Test late submission rejection
    # Close current cycle
    client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "closed"},
        headers=company_a.hr_headers,
    )

    from tests.conftest import _make_tenant
    company_late = _make_tenant(db, name="Late Review Co", code="LATE")
    emp_late, emp_late_headers = _create_employee_with_user(db, company_late.company_id)

    late_cycle_res = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": f"Past Deadline Cycle {uuid.uuid4().hex[:6]}",
            "cycle_type": "quarterly",
            "start_date": str(today - timedelta(days=60)),
            "end_date": str(today - timedelta(days=1)),
            "self_review_deadline": str(today - timedelta(days=15)),
            "manager_review_deadline": str(today - timedelta(days=5)),
        },
        headers=company_late.hr_headers,
    )
    assert late_cycle_res.status_code == 201
    late_cycle_id = late_cycle_res.json()["id"]

    client.put(
        f"/api/v1/performance/cycles/{late_cycle_id}",
        json={"status": "active"},
        headers=company_late.hr_headers,
    )

    late_goals = client.post(
        "/api/v1/performance/goals",
        json={
            "cycle_id": late_cycle_id,
            "employee_id": str(emp_late.id),
            "goals": [{"title": "Late Goal", "weightage": 100}],
        },
        headers=emp_late_headers,
    ).json()
    late_goal_id = late_goals[0]["id"]

    # Late self-review attempt -> 409 Conflict
    late_sub = client.post(
        f"/api/v1/performance/goals/{late_goal_id}/self-review",
        json={"rating": "4.0", "comments": "Late review"},
        headers=emp_late_headers,
    )
    assert late_sub.status_code == 409
    assert "Self-review deadline" in late_sub.json()["error"]["message"]
    assert "has passed" in late_sub.json()["error"]["message"]
    assert late_sub.status_code == 409
    assert "deadline" in late_sub.json()["error"]["message"].lower()
