# ruff: noqa: F401, F811  (pytest fixtures imported from sibling test modules)
"""Module 6 fixes for problems found by the end-to-end test plan (21-Nov-2026).

BUG-062  the reviewed employee cannot read a draft manager review by its id
BUG-064  recommended increment must be 0-100 percent
BUG-066  an employee cannot be their own PIP mentor
BUG-067  a PIP must end after it starts
BUG-069  a manager lists and looks up PIPs only for their reporting chain; another
         company's employee is 404
"""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.core.time import utcnow
from tests.rules.test_6_3_6_5_reviews_and_summary import (
    _auth_headers as rev_headers,
)
from tests.rules.test_6_3_6_5_reviews_and_summary import (
    p2_setup,
    setup_active_cycle_with_goals,
)
from tests.rules.test_6_4_pips import _auth_headers, p3_setup

PIPS = "/api/v1/performance/pips"


def _pip(client, headers, employee_id, **over):
    today = utcnow().date()
    body = {
        "employee_id": str(employee_id),
        "title": "Improve delivery",
        "start_date": str(today),
        "end_date": str(today + timedelta(days=60)),
    }
    body.update(over)
    return client.post(PIPS, headers=headers, json=body)


def test_pip_end_must_be_after_start(client: TestClient, p3_setup: dict[str, Any]) -> None:
    hr = _auth_headers(p3_setup["hr_a"])
    today = utcnow().date()
    resp = _pip(
        client,
        hr,
        p3_setup["emp_a"].id,
        start_date=str(today + timedelta(days=30)),
        end_date=str(today),
    )
    assert resp.status_code == 422, resp.text


def test_employee_cannot_mentor_own_pip(client: TestClient, p3_setup: dict[str, Any]) -> None:
    hr = _auth_headers(p3_setup["hr_a"])
    emp_id = p3_setup["emp_a"].id
    resp = _pip(client, hr, emp_id, mentor_id=str(emp_id))
    assert resp.status_code == 422, resp.text


def test_manager_sees_only_pips_of_own_chain(client: TestClient, p3_setup: dict[str, Any]) -> None:
    hr = _auth_headers(p3_setup["hr_a"])
    assert _pip(client, hr, p3_setup["emp_a"].id).status_code == 201
    other = _pip(client, hr, p3_setup["other_emp_a"].id)
    assert other.status_code == 201, other.text

    mgr = _auth_headers(p3_setup["mgr_user_a"])
    listed = client.get(PIPS, headers=mgr)
    assert listed.status_code == 200
    ids = {p["employee_id"] for p in listed.json()}
    assert str(p3_setup["emp_a"].id) in ids
    assert str(p3_setup["other_emp_a"].id) not in ids

    outside = client.get(f"{PIPS}/active/{p3_setup['other_emp_a'].id}", headers=mgr)
    assert outside.status_code == 403
    hr_list = client.get(PIPS, headers=hr).json()
    assert len({p["employee_id"] for p in hr_list}) >= 2


def test_other_company_active_pip_lookup_is_404(
    client: TestClient, p3_setup: dict[str, Any]
) -> None:
    hr_b = _auth_headers(p3_setup["hr_b"])
    resp = client.get(f"{PIPS}/active/{p3_setup['emp_a'].id}", headers=hr_b)
    assert resp.status_code == 404


def test_recommended_increment_must_be_0_to_100(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
) -> None:
    hr = rev_headers(p2_setup["hr_a"])
    emp_id = p2_setup["emp_a"].id
    for bad in [-5, 1000]:
        resp = client.post(
            f"/api/v1/performance/summary/{emp_id}",
            headers=hr,
            json={
                "cycle_id": setup_active_cycle_with_goals["cycle_id"],
                "salary_revision_recommended": True,
                "recommended_increment_percent": bad,
            },
        )
        assert resp.status_code == 422, (bad, resp.text)


def test_employee_cannot_read_draft_manager_review_by_id(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
) -> None:
    emp_h = rev_headers(p2_setup["emp_user_a"])
    mgr_h = rev_headers(p2_setup["mgr_user_a"])
    hr_h = rev_headers(p2_setup["hr_a"])
    g1 = setup_active_cycle_with_goals["goal_1_id"]
    assert client.post(
        f"/api/v1/performance/goals/{g1}/self-review",
        json={"rating": 4.0, "comments": "Self"},
        headers=emp_h,
    ).status_code in (200, 201)
    mgr = client.post(
        f"/api/v1/performance/goals/{g1}/manager-review",
        json={"rating": 4.5, "comments": "Good"},
        headers=mgr_h,
    )
    assert mgr.status_code in (200, 201), mgr.text
    rev_id = mgr.json()["id"]
    assert client.get(f"/api/v1/performance/reviews/{rev_id}", headers=emp_h).status_code == 200

    reopened = client.post(
        f"/api/v1/performance/reviews/{rev_id}/reopen", json={"reason": "Recheck"}, headers=hr_h
    )
    assert reopened.status_code == 200, reopened.text
    assert client.get(f"/api/v1/performance/reviews/{rev_id}", headers=emp_h).status_code == 404
    # The manager who wrote it still sees the draft.
    assert client.get(f"/api/v1/performance/reviews/{rev_id}", headers=mgr_h).status_code == 200


# --- BUG-061 ---------------------------------------------------------------------------


def test_manager_can_rate_a_goal_once_the_self_review_is_in(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """The 409 seen on the demo data was the data, not the rule (BUG-061).

    A goal only carries a self rating because submit_self_review wrote both the
    rating and the review row in the same commit, so a goal that shows a self
    rating can always be reviewed by its manager.
    """
    emp_headers = rev_headers(p2_setup["emp_user_a"])
    mgr_headers = rev_headers(p2_setup["mgr_user_a"])
    goal_id = setup_active_cycle_with_goals["goal_1_id"]

    # No self-review yet: the manager is refused, and the goal shows no rating.
    early = client.post(
        f"/api/v1/performance/goals/{goal_id}/manager-review",
        json={"rating": 4.0, "comments": "Strong quarter overall."},
        headers=mgr_headers,
    )
    assert early.status_code == 409, early.text

    # The employee submits the self-review; the goal now shows a self rating.
    self_review = client.post(
        f"/api/v1/performance/goals/{goal_id}/self-review",
        json={"rating": 3.5, "comments": "Met the delivery targets."},
        headers=emp_headers,
    )
    assert self_review.status_code == 200, self_review.text

    # The manager can now rate that same goal.
    mgr = client.post(
        f"/api/v1/performance/goals/{goal_id}/manager-review",
        json={"rating": 4.0, "comments": "Strong quarter overall."},
        headers=mgr_headers,
    )
    assert mgr.status_code == 200, mgr.text


# --- BUG-071 ---------------------------------------------------------------------------


def test_summary_refuses_to_finalize_while_a_manager_review_is_missing(
    client: TestClient, p2_setup: dict[str, Any], setup_active_cycle_with_goals: dict[str, Any]
):
    """No invented ratings: every goal needs a real manager rating (BUG-071)."""
    emp_headers = rev_headers(p2_setup["emp_user_a"])
    mgr_headers = rev_headers(p2_setup["mgr_user_a"])
    hr_headers = rev_headers(p2_setup["hr_a"])
    employee_id = str(p2_setup["emp_a"].id)
    cycle_id = setup_active_cycle_with_goals["cycle_id"]
    goal_1 = setup_active_cycle_with_goals["goal_1_id"]
    goal_2 = setup_active_cycle_with_goals["goal_2_id"]

    for goal_id in (goal_1, goal_2):
        assert (
            client.post(
                f"/api/v1/performance/goals/{goal_id}/self-review",
                json={"rating": 3.0, "comments": "Self assessment for the cycle."},
                headers=emp_headers,
            ).status_code
            == 200
        )

    # Only the first goal is rated by the manager.
    assert (
        client.post(
            f"/api/v1/performance/goals/{goal_1}/manager-review",
            json={"rating": 5.0, "comments": "Exceeded the target."},
            headers=mgr_headers,
        ).status_code
        == 200
    )

    early = client.post(
        f"/api/v1/performance/summary/{employee_id}",
        json={"cycle_id": cycle_id, "overall_comments": "Finalising early."},
        headers=hr_headers,
    )
    assert early.status_code == 409, early.text
    assert "manager review" in early.json()["error"]["message"].lower()

    # Once the second goal is rated, the summary finalizes on the real numbers:
    # 5.0 at 60% + 2.0 at 40% = 3.8, never the old 3.0 fallback.
    assert (
        client.post(
            f"/api/v1/performance/goals/{goal_2}/manager-review",
            json={"rating": 2.0, "comments": "Below the target."},
            headers=mgr_headers,
        ).status_code
        == 200
    )
    ok = client.post(
        f"/api/v1/performance/summary/{employee_id}",
        json={"cycle_id": cycle_id, "overall_comments": "Cycle closed."},
        headers=hr_headers,
    )
    assert ok.status_code in (200, 201), ok.text
    assert float(ok.json()["final_rating"]) == 3.8
