import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.identity.models import Company, CompanySettings, CompanyStatus, User, UserRole

REPO_ROOT = Path(__file__).resolve().parent.parent


def _database_name(url: str) -> str:
    return make_url(url).database or ""


for _name in ("TEST_DATABASE_URL", "TEST_MIGRATION_URL"):
    if not getattr(settings, _name):
        raise RuntimeError(
            f"{_name} is not set. Tests need a dedicated test database — see .env.example."
        )

# Never run tests against the development database (Spec 15.2).
if _database_name(settings.TEST_DATABASE_URL) == _database_name(settings.DATABASE_URL):
    raise RuntimeError(
        "TEST_DATABASE_URL points at the same database as DATABASE_URL. Tests must run "
        "against a separate database (e.g. ems_pro_test), never the development one."
    )


def _ensure_test_database_exists() -> None:
    migration_url = make_url(settings.TEST_MIGRATION_URL)
    db_name = migration_url.database
    admin_engine = create_engine(
        migration_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
            ).scalar()
            if not exists:
                # CREATE DATABASE can't take a bind parameter for the name;
                # db_name comes from our own settings, not user input.
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin_engine.dispose()


def _migrate_test_database() -> None:
    """Migrations run as ems_owner, via a real `alembic upgrade head` — a
    subprocess with ALEMBIC_DATABASE_URL overridden to TEST_MIGRATION_URL, so
    alembic/env.py (which reads settings.ALEMBIC_DATABASE_URL) resolves to
    the test database without touching this process's own settings object.
    """
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = settings.TEST_MIGRATION_URL
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to migrate the test database:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


@pytest.fixture(scope="session", autouse=True)
def _test_database_ready() -> None:
    _ensure_test_database_exists()
    _migrate_test_database()


@pytest.fixture(scope="session")
def engine(_test_database_ready):
    # Tests connect as ems_app (TEST_DATABASE_URL), never ems_owner — ems_owner
    # bypasses any policy that got ENABLE but not FORCE, which would make the
    # isolation suite pass on tables that are not actually protected (15.2).
    eng = create_engine(settings.TEST_DATABASE_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def connection(engine):
    conn = engine.connect()
    yield conn
    conn.close()


@pytest.fixture
def db(connection):
    """Test isolation uses a savepoint, not a plain transaction (Spec 15.2).
    Services commit (6.7) — a service commit would end a simple outer
    transaction, leaving nothing for a plain rollback to undo and letting
    data leak between tests. join_transaction_mode="create_savepoint" makes
    the session's commits land on savepoints inside the outer transaction;
    the after_begin listener (8.4) re-applies the tenant context on each of
    those, so RLS keeps working through the test's own commits.
    """
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    outer.rollback()


@pytest.fixture
def client(db):
    def _override_get_db():
        yield db

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()


@dataclass
class TenantContext:
    company_id: uuid.UUID
    hr_headers: dict[str, str]
    manager_headers: dict[str, str]
    employee_headers: dict[str, str]


TEST_PASSWORD = "Test1234pass!"


def _make_user_headers(db: Session, company_id: uuid.UUID, role: UserRole) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}@{company_id}.test",
        hashed_password=hash_password(TEST_PASSWORD),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


def _make_tenant(db: Session, *, name: str, code: str) -> TenantContext:
    from app.db.rls import bind_tenant_to_session

    # companies has no RLS (platform-level table, 7.2) — no context needed yet.
    company = Company(
        name=name, code=code, email=f"{code.lower()}@example.test", status=CompanyStatus.active
    )
    db.add(company)
    db.flush()

    # company_settings IS RLS-protected — WITH CHECK requires the context to
    # already match company.id before this insert.
    bind_tenant_to_session(db, company_id=company.id, is_platform_admin=False)
    db.add(CompanySettings(company_id=company.id))
    db.flush()

    hr_headers = _make_user_headers(db, company.id, UserRole.hr_admin)
    manager_headers = _make_user_headers(db, company.id, UserRole.manager)
    employee_headers = _make_user_headers(db, company.id, UserRole.employee)
    db.commit()

    return TenantContext(
        company_id=company.id,
        hr_headers=hr_headers,
        manager_headers=manager_headers,
        employee_headers=employee_headers,
    )


@pytest.fixture
def company_a(db) -> TenantContext:
    return _make_tenant(db, name="Company A", code=f"COA{uuid.uuid4().hex[:5].upper()}")


@pytest.fixture
def company_b(db) -> TenantContext:
    return _make_tenant(db, name="Company B", code=f"COB{uuid.uuid4().hex[:5].upper()}")
