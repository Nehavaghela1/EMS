"""backfill_company_owner_user_id

Revision ID: b3a17e0892c1
Revises: 564032fe6a10
Create Date: 2026-10-23 13:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3a17e0892c1"
down_revision: Union[str, Sequence[str], None] = "564032fe6a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BACKFILL_SQL = """
UPDATE companies c
SET owner_user_id = sub.id
FROM (
    SELECT DISTINCT ON (company_id) id, company_id
    FROM users
    WHERE role::text = 'owner' AND deleted_at IS NULL
    ORDER BY company_id, created_at ASC, id ASC
) sub
WHERE c.id = sub.company_id AND c.owner_user_id IS NULL;
"""


def upgrade() -> None:
    # Data-only migration: backfill owner_user_id on companies where NULL with earliest owner
    conn = op.get_bind()
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))
    conn.execute(sa.text(BACKFILL_SQL))


def downgrade() -> None:
    # Documented no-op: data backfill is irreversible and non-destructive.
    pass
