from datetime import date, timedelta

import pytest

from tests.date_helpers import next_working_day, past_working_day

# 2026-11-02 is a Monday, so the seven days below cover every weekday as "today".
_WEEK = [date(2026, 11, 2) + timedelta(days=i) for i in range(7)]


@pytest.mark.parametrize("today", _WEEK, ids=lambda d: d.strftime("%A"))
def test_past_working_day_is_a_weekday_at_least_five_days_back(today: date) -> None:
    day = past_working_day(today)
    assert day.isoweekday() <= 5
    assert day <= today - timedelta(days=5)
    # nearest: nothing closer to today (but still 5+ days back) is a working day
    closer = [
        d
        for d in (today - timedelta(days=n) for n in range(5, (today - day).days))
        if d.isoweekday() <= 5
    ]
    assert closer == []


@pytest.mark.parametrize("today", _WEEK, ids=lambda d: d.strftime("%A"))
def test_next_working_day_is_a_weekday_after_today(today: date) -> None:
    day = next_working_day(today)
    assert day.isoweekday() <= 5
    assert day > today
    assert (day - today).days <= 3
