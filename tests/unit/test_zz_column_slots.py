"""The shared test database must not lose column slots to the tests.

PostgreSQL gives a table at most 1,600 column slots and a dropped column keeps its slot. The
migration round-trip tests used to add and drop real columns of `statutory_configs` on the shared
database on every run, so a local database broke after about a dozen full runs. They now run on a
scratch database. This file is named so that it runs last: the number read here, from the system
catalog, must be the one the session started with. The session prints both numbers at the end
(`statutory_configs column slots: start N, end N`), so two runs in a row can be compared.
"""

import pytest
from pytest import FixtureRequest
from sqlalchemy import text
from sqlalchemy.orm import Session


def _slots(db: Session) -> dict[str, int]:
    rows = db.execute(
        text(
            "SELECT c.relname, max(a.attnum) FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "WHERE c.relname = ANY(:names) AND c.relkind = 'r' AND a.attnum > 0 "
            "GROUP BY c.relname"
        ),
        {"names": ["statutory_configs", "reimbursements", "payroll_items", "statutory_rates"]},
    ).fetchall()
    return {name: int(top) for name, top in rows}


def test_the_shared_database_keeps_the_same_column_slots_for_the_whole_session(
    request: FixtureRequest, db: Session
) -> None:
    try:
        baseline = request.getfixturevalue("column_slot_baseline")
    except pytest.FixtureLookupError:
        pytest.fail("conftest has no column_slot_baseline fixture yet")
    now = _slots(db)
    assert now == baseline, (
        "a test used up column slots of the shared database (run the migration round trips "
        f"on the scratch database): at the start {baseline}, now {now}"
    )
    assert now["statutory_configs"] < 1500, "statutory_configs is close to PostgreSQL's limit"
