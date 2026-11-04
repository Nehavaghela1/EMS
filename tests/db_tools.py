"""Creating, bootstrapping and dropping test databases.

Two uses (tests/conftest.py):

* the shared test database (`ems_pro_test`) is created here when it does not exist, with the
  ems_owner / ems_app role grants applied before any migration runs, so a new machine or a
  teammate needs no manual step;
* the migration round-trip tests (downgrade, then upgrade) run on a scratch database that the
  session creates and drops, so they never touch the shared one.

The grants come from app/db/seed/bootstrap_roles.sql, the same script scripts/setup.sh runs. It
needs a superuser (it creates roles if they are missing and reassigns ownership), so it runs as
the bootstrap user that setup.sh uses: `PG_BOOTSTRAP_USER` (default: your OS username, the local
superuser of Homebrew and Postgres.app) and `PG_BOOTSTRAP_PASSWORD` (default: none). In CI
`PG_BOOTSTRAP_USER` is ems_owner, which is a superuser there. The script is run through the
Python driver (psql's `\\set` lines are dropped), so the `psql` program is not needed here.
"""

import getpass
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from app.core.config import settings

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_SQL = REPO_ROOT / "app" / "db" / "seed" / "bootstrap_roles.sql"
SCRATCH_PREFIX = "ems_scratch"


@dataclass(frozen=True)
class ScratchDatabase:
    name: str
    owner_url: str  # ems_owner: migrations
    app_url: str  # ems_app: the runtime role


def _migration_url() -> URL:
    assert settings.TEST_MIGRATION_URL is not None
    return make_url(settings.TEST_MIGRATION_URL)


def _app_url() -> URL:
    assert settings.TEST_DATABASE_URL is not None
    return make_url(settings.TEST_DATABASE_URL)


def url_for(base: URL, name: str) -> str:
    return base.set(database=name).render_as_string(hide_password=False)


def _admin_engine():
    return create_engine(_migration_url().set(database="postgres"), isolation_level="AUTOCOMMIT")


def database_exists(name: str) -> bool:
    admin = _admin_engine()
    try:
        with admin.connect() as conn:
            return bool(
                conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
                ).scalar()
            )
    finally:
        admin.dispose()


def apply_bootstrap_roles(name: str) -> None:
    """Run bootstrap_roles.sql against database `name` as the bootstrap superuser."""
    url = _migration_url()
    user = os.environ.get("PG_BOOTSTRAP_USER") or getpass.getuser()
    password = os.environ.get("PG_BOOTSTRAP_PASSWORD") or None
    script = "\n".join(
        line
        for line in BOOTSTRAP_SQL.read_text().splitlines()
        if not line.lstrip().startswith("\\")
    )
    try:
        conn = psycopg2.connect(
            dbname=name,
            host=url.host or "localhost",
            port=url.port or 5432,
            user=user,
            password=password,
        )
    except psycopg2.Error as exc:
        raise RuntimeError(_bootstrap_hint(name, user, exc)) from None
    try:
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute(script)
    except psycopg2.Error as exc:
        raise RuntimeError(_bootstrap_hint(name, user, exc)) from None
    finally:
        conn.close()


def _bootstrap_hint(name: str, user: str, exc: Exception) -> str:
    return (
        f"Could not apply app/db/seed/bootstrap_roles.sql to database '{name}' as '{user}': "
        f"{str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__}. "
        "The script needs a PostgreSQL superuser: set PG_BOOTSTRAP_USER (and "
        "PG_BOOTSTRAP_PASSWORD), the same variables scripts/setup.sh uses."
    )


def create_database(name: str) -> None:
    """CREATE DATABASE, then the role grants, before anything else uses it. A database whose
    grants fail is dropped again, so the next run retries instead of finding a half-made one."""
    admin = _admin_engine()
    try:
        with admin.connect() as conn:
            # `name` comes from our own settings or a generated token, never from input.
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()
    try:
        apply_bootstrap_roles(name)
    except Exception:
        drop_database(name)
        raise


def drop_database(name: str) -> None:
    admin = _admin_engine()
    try:
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        admin.dispose()


@contextmanager
def scratch_database() -> Iterator[ScratchDatabase]:
    """A throw-away database (roles and grants applied, no tables yet) that is dropped when
    the block ends, also when it raises. The name ends in `_test` like every test database."""
    name = f"{SCRATCH_PREFIX}_{uuid.uuid4().hex[:8]}_test"
    create_database(name)
    try:
        yield ScratchDatabase(
            name=name,
            owner_url=url_for(_migration_url(), name),
            app_url=url_for(_app_url(), name),
        )
    finally:
        drop_database(name)
