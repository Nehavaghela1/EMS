"""Date helpers for tests whose date must be a working day (Mon-Fri, the default
company weekend is Saturday and Sunday, isoweekday 6 and 7)."""

from datetime import date, timedelta

DEFAULT_WEEKEND_DAYS = frozenset({6, 7})


def past_working_day(today: date, min_days_back: int = 5) -> date:
    """The nearest working day that is at least `min_days_back` days before `today`."""
    day = today - timedelta(days=min_days_back)
    while day.isoweekday() in DEFAULT_WEEKEND_DAYS:
        day -= timedelta(days=1)
    return day


def next_working_day(today: date) -> date:
    """The nearest working day strictly after `today`."""
    day = today + timedelta(days=1)
    while day.isoweekday() in DEFAULT_WEEKEND_DAYS:
        day += timedelta(days=1)
    return day
