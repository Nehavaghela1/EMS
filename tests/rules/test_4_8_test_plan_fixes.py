# ruff: noqa: F401, F811  (pytest fixtures imported from a sibling test module)
"""Module 4 fixes for problems found by the end-to-end test plan (21-Nov-2026).

BUG-026/027/028  HR attendance correction refuses check-out before check-in, future
                 times, other dates and spans over 24 hours (never a server error)
BUG-030          a half day leave must say which half
BUG-031          the calendar shows a punched day as worked, not as a pending leave
BUG-033          a second check-out says "already checked out"
"""

from datetime import date, timedelta

from app.core.time import utcnow
from app.modules.identity.models import UserRole
from tests.integration.test_leaves import _create_leave_type
from tests.rules.test_4_2_punch import CHECK_IN, CHECK_OUT, _create_employee, _link_user_to_employee
from tests.rules.test_4_3_regularization import ATT, _at, _day, _record, org


def _hr_edit(client, ctx, att_id, **body):
    body.setdefault("reason", "HR correction")
    return client.put(f"{ATT}/{att_id}", headers=ctx.hr_headers, json=body)


def test_hr_edit_refuses_check_out_before_check_in(client, db, org) -> None:
    ctx = org["ctx"]
    att = _record(db, ctx, org["emp"]["id"], days_ago=3)
    day = _day(3)
    resp = _hr_edit(
        client, ctx, att, check_in=_at(day, 12).isoformat(), check_out=_at(day, 10).isoformat()
    )
    assert resp.status_code == 422, resp.text


def test_hr_edit_refuses_far_future_and_other_dates(client, db, org) -> None:
    ctx = org["ctx"]
    att = _record(db, ctx, org["emp"]["id"], days_ago=3)
    day = _day(3)
    for out in [
        "2027-01-01T10:00:00+00:00",
        "2100-01-01T10:00:00+00:00",
        (utcnow() + timedelta(hours=2)).isoformat(),
        _at(day + timedelta(days=2), 10).isoformat(),
    ]:
        resp = _hr_edit(client, ctx, att, check_out=out)
        assert resp.status_code == 422, (out, resp.text)


def test_hr_edit_refuses_more_than_24_hours(client, db, org) -> None:
    ctx = org["ctx"]
    att = _record(db, ctx, org["emp"]["id"], days_ago=3)
    day = _day(3)
    resp = _hr_edit(
        client,
        ctx,
        att,
        check_in=_at(day, 1).isoformat(),
        check_out=_at(day + timedelta(days=1), 4).isoformat(),
    )
    assert resp.status_code == 422, resp.text


def test_hr_edit_valid_correction_still_works(client, db, org) -> None:
    ctx = org["ctx"]
    att = _record(db, ctx, org["emp"]["id"], days_ago=3)
    day = _day(3)
    resp = _hr_edit(client, ctx, att, check_out=_at(day, 18).isoformat())
    assert resp.status_code == 200, resp.text
    assert float(resp.json()["hours_worked"]) == 9.0


def test_second_check_out_says_already_checked_out(client, db, company_a) -> None:
    emp = _create_employee(client, company_a.hr_headers)
    h, _ = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)
    assert client.post(CHECK_IN, headers=h).status_code == 201
    assert client.post(CHECK_OUT, headers=h).status_code == 200
    again = client.post(CHECK_OUT, headers=h)
    assert again.status_code == 400
    assert again.json()["error"]["message"] == "You have already checked out today."


def _leave_type(client, hr):
    return _create_leave_type(client, hr, annual_allowance="12")["id"]


def _next_weekday(days: int = 7):
    d = utcnow().date() + timedelta(days=days)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def test_half_day_leave_needs_a_session(client, db, org) -> None:
    lt = _leave_type(client, org["ctx"].hr_headers)
    day = _next_weekday().isoformat()
    base = {
        "leave_type_id": lt,
        "start_date": day,
        "end_date": day,
        "reason": "Doctor",
        "is_half_day": True,
    }
    missing = client.post("/api/v1/leaves", headers=org["emp"]["h"], json=base)
    assert missing.status_code == 422, missing.text
    ok = client.post(
        "/api/v1/leaves", headers=org["emp"]["h"], json={**base, "half_day_session": "second_half"}
    )
    assert ok.status_code == 201, ok.text


def test_calendar_shows_punch_not_pending_leave(client, db, org) -> None:
    h = org["emp"]["h"]
    lt = _leave_type(client, org["ctx"].hr_headers)
    assert client.post(CHECK_IN, headers=h).status_code == 201
    today = utcnow().date()
    client.post(
        "/api/v1/leaves",
        headers=h,
        json={
            "leave_type_id": lt,
            "start_date": today.isoformat(),
            "end_date": today.isoformat(),
            "reason": "x",
        },
    )
    cal = client.get(
        f"/api/v1/attendance/calendar?month={today.month}&year={today.year}", headers=h
    )
    assert cal.status_code == 200, cal.text
    day = {d["date"]: d for d in cal.json()["days"]}[today.isoformat()]
    assert day["status"] != "pending_leave", day


# --- BUG-029 / BUG-035: one leave year at a time -----------------------------------------


def test_leave_in_a_future_leave_year_is_refused(client, db, org) -> None:
    """Balances are per leave year, so next year's leave had nothing to deduct
    from and was approved against no balance at all (BUG-029)."""
    h = org["emp"]["h"]
    lt = _leave_type(client, org["ctx"].hr_headers)
    today = utcnow().date()
    next_year = date(today.year + 1, 5, 11)
    while next_year.weekday() >= 5:
        next_year += timedelta(days=1)

    resp = client.post(
        "/api/v1/leaves",
        headers=h,
        json={
            "leave_type_id": lt,
            "start_date": next_year.isoformat(),
            "end_date": (next_year + timedelta(days=2)).isoformat(),
            "reason": "Holiday planned for next year",
        },
    )
    # A leave business rule is a 400 by this module's convention, not a 422.
    assert resp.status_code == 400, resp.text
    assert str(today.year + 1) in resp.json()["error"]["message"]


def test_leave_crossing_the_leave_year_end_is_refused(client, db, org) -> None:
    """A leave belongs to one leave year; 30 Dec to 2 Jan is two (BUG-035)."""
    h = org["ctx"].hr_headers  # HR may back-date, so the dates themselves decide
    lt = _leave_type(client, org["ctx"].hr_headers)
    emp_id = str(org["emp"]["id"])
    today = utcnow().date()

    # The default leave year runs April to March, so the boundary to straddle
    # is 31 March. Compute it from today rather than typing a fixed year in.
    fy_start_year = today.year if today.month >= 4 else today.year - 1
    last_day = date(fy_start_year + 1, 3, 31)

    resp = client.post(
        "/api/v1/leaves",
        headers=h,
        json={
            "employee_id": emp_id,
            "leave_type_id": lt,
            "start_date": (last_day - timedelta(days=1)).isoformat(),
            "end_date": (last_day + timedelta(days=2)).isoformat(),
            "reason": "Year end break",
        },
    )
    assert resp.status_code == 422, resp.text
    assert "leave year" in resp.json()["error"]["message"].lower()
