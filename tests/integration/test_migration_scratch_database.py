"""The test database helpers (tests/db_tools.py): a scratch database for the migration
round-trip tests, and the role grants applied whenever a test database is created.

The migration tests downgrade and upgrade through real migrations. Run on the shared test
database they use up PostgreSQL column slots (dropped columns still count towards the 1,600
limit), so they run on a scratch database that the test session creates and drops instead.
"""

import importlib
import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings


def _tools() -> Any:
    try:
        return importlib.import_module("tests.db_tools")
    except ModuleNotFoundError:
        pytest.fail("tests/db_tools.py does not exist yet")


def _database_name(url: str | None) -> str:
    assert url is not None
    return make_url(url).database or ""


def _exists(name: str) -> bool:
    assert settings.TEST_MIGRATION_URL is not None
    admin = create_engine(
        make_url(settings.TEST_MIGRATION_URL).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as conn:
            return bool(
                conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
                ).scalar()
            )
    finally:
        admin.dispose()


def test_a_migration_round_trip_test_runs_on_its_own_scratch_database() -> None:
    """The conftest finds tests that call the alembic downgrade command and gives them a
    scratch database: the marker string below is what it looks for ("command.downgrade(")."""
    marker = "command.downgrade("
    assert marker
    name = _database_name(settings.TEST_MIGRATION_URL)
    assert name.startswith("ems_scratch_") and name.endswith("_test"), (
        f"a round-trip test must run on a scratch database, not the shared one: {name}"
    )
    assert _database_name(settings.TEST_DATABASE_URL) == name, "the app URL must follow it"
    assert _exists(name), "the scratch database must exist while its test runs"


def test_a_scratch_database_is_dropped_even_when_the_block_fails() -> None:
    tools = _tools()
    seen: list[str] = []
    with pytest.raises(RuntimeError):
        with tools.scratch_database() as scratch:
            seen.append(scratch.name)
            assert _exists(scratch.name), "it must exist inside the block"
            raise RuntimeError("a test failed")
    assert seen and not _exists(seen[0]), "the scratch database must be dropped after a failure"


def test_a_scratch_database_is_dropped_after_a_clean_block_too() -> None:
    tools = _tools()
    with tools.scratch_database() as scratch:
        name = scratch.name
    assert not _exists(name)


def test_a_scratch_database_never_has_the_name_of_the_shared_one() -> None:
    tools = _tools()
    with tools.scratch_database() as scratch:
        assert scratch.name != _database_name(settings.TEST_MIGRATION_URL)
        assert scratch.name != _database_name(settings.DATABASE_URL)
        assert scratch.name.startswith("ems_scratch_") and scratch.name.endswith("_test")


def _probe_access(owner_url: str, app_url: str) -> int:
    """ems_owner creates a table; ems_app must be able to use it with no manual grant."""
    owner = create_engine(owner_url)
    app = create_engine(app_url)
    try:
        with owner.begin() as conn:
            conn.execute(text("CREATE TABLE grant_probe (id integer)"))
            conn.execute(text("INSERT INTO grant_probe VALUES (1)"))
        with app.begin() as conn:
            conn.execute(text("INSERT INTO grant_probe VALUES (2)"))
            return conn.execute(text("SELECT count(*) FROM grant_probe")).scalar_one()
    finally:
        owner.dispose()
        app.dispose()


def test_a_scratch_database_gives_ems_app_the_grants_with_no_manual_step() -> None:
    tools = _tools()
    with tools.scratch_database() as scratch:
        assert _probe_access(scratch.owner_url, scratch.app_url) == 2, (
            "ems_app must read and write tables that ems_owner creates"
        )


def test_a_created_test_database_gets_the_role_grants_in_the_same_step() -> None:
    """What conftest does when ems_pro_test is missing (fresh machine, or just dropped)."""
    tools = _tools()
    name = f"ems_grants_{uuid.uuid4().hex[:8]}_test"
    tools.create_database(name)
    try:
        owner_url = (
            make_url(str(settings.TEST_MIGRATION_URL))
            .set(database=name)
            .render_as_string(hide_password=False)
        )
        app_url = (
            make_url(str(settings.TEST_DATABASE_URL))
            .set(database=name)
            .render_as_string(hide_password=False)
        )
        assert _probe_access(owner_url, app_url) == 2, (
            "a freshly created test database must not need a manual grant step"
        )
    finally:
        tools.drop_database(name)
    assert not _exists(name)


def test_creating_a_database_that_exists_is_left_alone() -> None:
    tools = _tools()
    name = _database_name(settings.TEST_MIGRATION_URL)
    assert tools.database_exists(name) is True
    assert tools.database_exists(f"ems_missing_{uuid.uuid4().hex[:8]}_test") is False
