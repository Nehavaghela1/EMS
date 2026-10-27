import pytest

from app.core.masking import mask_tail


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("", ""),
        ("123", "***"),
        ("1234", "****"),
        ("1234567890", "******7890"),
    ],
)
def test_mask_tail_default_visible(value, expected):
    assert mask_tail(value) == expected


def test_mask_tail_rejects_visible_below_one():
    with pytest.raises(ValueError):
        mask_tail("1234567890", visible=0)
