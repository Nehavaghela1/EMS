import pytest

from app.core.csv_safety import csv_safe_cell


@pytest.mark.parametrize(
    "input_val,expected",
    [
        (None, ""),
        ("", ""),
        ("hello", "hello"),
        ("=1+1", "'=1+1"),
        ("+cmd", "'+cmd"),
        ("-calc", "'-calc"),
        ("@SUM(A1:A10)", "'@SUM(A1:A10)"),
        ("\tTabbed", "'\tTabbed"),
        ("\rReturn", "'\rReturn"),
        ("a=b", "a=b"),
        (5, "5"),
        (-5, "-5"),
        (-1.5, "-1.5"),
        (True, "True"),
        (False, "False"),
    ],
)
def test_csv_safe_cell(input_val, expected):
    assert csv_safe_cell(input_val) == expected

