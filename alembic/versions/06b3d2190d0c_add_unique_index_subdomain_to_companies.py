"""add_unique_index_subdomain_to_companies

Revision ID: 06b3d2190d0c
Revises: 4a5b6c7d8e9f
Create Date: 2026-10-22 17:54:00.006850

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '06b3d2190d0c'
down_revision: Union[str, Sequence[str], None] = '4a5b6c7d8e9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Check for existing duplicates on lower(subdomain) where subdomain is not null
    conn = op.get_bind()
    dupes = conn.execute(
        sa.text(
            "SELECT lower(subdomain), count(*) "
            "FROM companies "
            "WHERE subdomain IS NOT NULL "
            "GROUP BY lower(subdomain) "
            "HAVING count(*) > 1"
        )
    ).fetchall()
    if dupes:
        dupe_list = ", ".join(f"'{row[0]}' (x{row[1]})" for row in dupes)
        raise RuntimeError(
            f"Cannot create unique index uq_companies_lower_subdomain: existing duplicates found: {dupe_list}"
        )

    # 2. Create partial unique index on lower(subdomain)
    op.create_index(
        "uq_companies_lower_subdomain",
        "companies",
        [sa.literal_column("lower(subdomain)")],
        unique=True,
        postgresql_where=sa.text("subdomain IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_companies_lower_subdomain", table_name="companies")
