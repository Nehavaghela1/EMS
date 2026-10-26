"""replace uq_departments_company_id_name with uq_departments_company_lower_name

Revision ID: 7c8d9e0f1a2b
Revises: b3a17e0892c1
Create Date: 2026-10-26 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c8d9e0f1a2b"
down_revision: Union[str, Sequence[str], None] = "b3a17e0892c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Fail clearly if duplicate active department names exist inside any company (case-insensitively)
    dupes = conn.execute(
        sa.text(
            "SELECT company_id, lower(name), count(*) "
            "FROM departments "
            "WHERE deleted_at IS NULL "
            "GROUP BY company_id, lower(name) "
            "HAVING count(*) > 1"
        )
    ).fetchall()
    if dupes:
        dupe_list = ", ".join(f"company {r[0]}: '{r[1]}' (x{r[2]})" for r in dupes)
        raise RuntimeError(
            f"Cannot create unique index uq_departments_company_lower_name: existing duplicates found: {dupe_list}"
        )

    # 2. Drop the old index
    op.drop_index("uq_departments_company_id_name", table_name="departments")

    # 3. Create the new unique index on (company_id, lower(name)) WHERE deleted_at IS NULL
    op.create_index(
        "uq_departments_company_lower_name",
        "departments",
        ["company_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # 1. Drop the lower() partial unique index
    op.drop_index("uq_departments_company_lower_name", table_name="departments")

    # 2. Restore the original unique index
    op.create_index(
        "uq_departments_company_id_name",
        "departments",
        ["company_id", "name"],
        unique=True,
    )
