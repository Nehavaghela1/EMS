"""Helpers that hide most of a sensitive value before it is shown or logged."""


def mask_tail(value: str | None, visible: int = 4) -> str | None:
    """Return value with everything except the last `visible` characters
    replaced by '*'.
    """
    if visible < 1:
        raise ValueError("visible must be >= 1")
    if value is None:
        return None
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]
