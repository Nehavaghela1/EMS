from datetime import UTC, datetime

from app.core.time import utcnow


def test_utcnow_returns_timezone_aware_utc_datetime():
    now = utcnow()

    assert isinstance(now, datetime)
    assert now.tzinfo is not None
    assert now.utcoffset() == UTC.utcoffset(now)
