"""enable RLS on attendance_regularizations, company_locations, performance_pips

Revision ID: 3f9a1c7e5b20
Revises: c35dfc0fd6c2
Create Date: 2026-10-12 16:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

from app.db.rls import enable_rls

revision: str = "3f9a1c7e5b20"
down_revision: Union[str, Sequence[str], None] = "c35dfc0fd6c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("attendance_regularizations", "company_locations", "performance_pips")


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        enable_rls(table)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
