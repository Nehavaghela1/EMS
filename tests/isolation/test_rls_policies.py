"""The mandatory parametrized sweep (Spec 8.6): every table whose model
inherits TenantBase must have RLS enabled, FORCED, and at least one policy.
Discovered dynamically from the class hierarchy (app/db/base.py), so a table
added later with TenantBase but no enable_rls() call fails this suite
automatically — nothing here needs updating by hand.
"""

import pytest
from sqlalchemy import text

import app.main  # noqa: F401 — imports every wired module's models.py
from app.db.base import tenant_table_names

TENANT_TABLES = tenant_table_names()


def test_at_least_one_tenant_table_is_registered():
    # If this fails, either no tenant table exists yet (fine, early on) or
    # something broke the discovery — either way, worth seeing explicitly
    # rather than the parametrized test below silently collecting zero cases.
    assert TENANT_TABLES, "No tenant tables discovered — expected at least company_settings"


@pytest.mark.parametrize("table_name", TENANT_TABLES)
def test_tenant_table_has_rls_enabled_and_forced(db, table_name):
    row = db.execute(
        text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :name"),
        {"name": table_name},
    ).one_or_none()

    assert row is not None, f"{table_name} does not exist in the database"
    row_security_enabled, force_enabled = row
    assert row_security_enabled, f"{table_name} has TenantBase but RLS is not ENABLEd"
    assert force_enabled, (
        f"{table_name} has RLS ENABLEd but not FORCEd — the table owner would bypass it"
    )


@pytest.mark.parametrize("table_name", TENANT_TABLES)
def test_tenant_table_has_a_policy(db, table_name):
    policy_count = db.execute(
        text("SELECT count(*) FROM pg_policies WHERE tablename = :name"),
        {"name": table_name},
    ).scalar()
    assert policy_count and policy_count > 0, f"{table_name} has RLS enabled but no policy"
