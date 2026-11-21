# ruff: noqa: F401, F811  (pytest fixtures imported from a sibling test module)
"""Module 4 fixes for problems found by the end-to-end test plan (21-Nov-2026).

BUG-026/027/028  HR attendance correction refuses check-out before check-in, future
                 times, other dates and spans over 24 hours (never a server error)
BUG-030          a half day leave must say which half
BUG-031          the calendar shows a punched day as worked, not as a pending leave
BUG-033          a second check-out says "already checked out"
"""

from datetime import timedelta

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
