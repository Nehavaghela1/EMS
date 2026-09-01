from datetime import UTC, datetime


def utcnow() -> datetime:
    """The single time source (Spec 6.3). Use this everywhere instead of
    datetime.now(timezone.utc) directly, so the whole system can be
    time-mocked in tests.
    """
    return datetime.now(UTC)
