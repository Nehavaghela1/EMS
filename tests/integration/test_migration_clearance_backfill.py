import uuid

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from tests.conftest import REPO_ROOT, TenantContext


def test_clearance_function_migration_backfill_as_ems_owner(
    db: Session, company_a: TenantContext, monkeypatch: pytest.MonkeyPatch
):
    """Verifies that running the real migration (downgrade to parent revision 7a8b9c0d1e2f
    and upgrade to cbf5cc7429a8) backfills clearance_function on departments under forced RLS
    when alembic runs as ems_owner with no tenant or platform-admin context set.
    """
    # Override settings.ALEMBIC_DATABASE_URL to point to TEST_MIGRATION_URL (the test database)
    monkeypatch.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)

    owner_engine = create_engine(settings.TEST_MIGRATION_URL)
    comp_id = uuid.uuid4()
    comp_code = f"MIG{comp_id.hex[:5].upper()}"
    fin_id = uuid.uuid4()
    it_id = uuid.uuid4()

    try:
        # Step 1: Create company and departments with clearance_function NULL via owner connection
        with owner_engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO companies (
                            id, name, code, email, status, country,
                            currency, last_employee_seq, created_at, updated_at
                        )
                        VALUES (
                            :comp_id, 'Migration Test Corp', :comp_code, :email,
                            'active', 'IN', 'INR', 0, NOW(), NOW()
                        )
                        """
                    ),
                    {
                        "comp_id": comp_id,
                        "comp_code": comp_code,
                        "email": f"{comp_code.lower()}@test.test",
                    },
                )
                # Temporarily disable FORCE RLS during test setup insert only
                conn.execute(sa.text("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY;"))
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO departments (
                            id, company_id, name, clearance_function, created_at, updated_at
                        )
                        VALUES (:fin_id, :comp_id, 'Finance', NULL, NOW(), NOW()),
                               (:it_id, :comp_id, 'Information Technology', NULL, NOW(), NOW())
                        """
                    ),
                    {"fin_id": fin_id, "it_id": it_id, "comp_id": comp_id},
                )
                conn.execute(sa.text("ALTER TABLE departments FORCE ROW LEVEL SECURITY;"))

        # Step 2: Ensure NO tenant or platform-admin context is set, and run the REAL migration:
        # Downgrade to parent revision 7a8b9c0d1e2f, then upgrade to cbf5cc7429a8 using alembic's command API
        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        command.downgrade(cfg, "7a8b9c0d1e2f")
        command.upgrade(cfg, "cbf5cc7429a8")

        # Step 3: Assert clearance_function is 'finance' and 'it'
        with owner_engine.connect() as conn:
            with conn.begin():
                conn.execute(sa.text("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY;"))
                fin_fn = conn.execute(
                    sa.text("SELECT clearance_function FROM departments WHERE id = :id"),
                    {"id": fin_id},
                ).scalar_one()
                it_fn = conn.execute(
                    sa.text("SELECT clearance_function FROM departments WHERE id = :id"),
                    {"id": it_id},
                ).scalar_one()

                assert fin_fn == "finance"
                assert it_fn == "it"

    finally:
        # Cleanup
        with owner_engine.connect() as conn:
            with conn.begin():
                conn.execute(sa.text("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY;"))
                conn.execute(
                    sa.text("DELETE FROM departments WHERE id IN (:fin_id, :it_id)"),
                    {"fin_id": fin_id, "it_id": it_id},
                )
                conn.execute(
                    sa.text("DELETE FROM companies WHERE id = :comp_id"),
                    {"comp_id": comp_id},
                )
                conn.execute(sa.text("ALTER TABLE departments FORCE ROW LEVEL SECURITY;"))
        owner_engine.dispose()
