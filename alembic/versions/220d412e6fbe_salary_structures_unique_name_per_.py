"""salary structures unique name per company

Revision ID: 220d412e6fbe
Revises: 34c17612b66d
Create Date: 2026-11-03 19:24:50.098648

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "220d412e6fbe"
down_revision: Union[str, Sequence[str], None] = "34c17612b66d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Under FORCE ROW LEVEL SECURITY alembic runs as ems_owner without tenant context; set the
    # platform-admin context for this transaction so the duplicate check sees every company.
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))

    dupes = conn.execute(
        sa.text(
            "SELECT company_id, lower(name), count(*) "
            "FROM salary_structures "
            "WHERE deleted_at IS NULL "
            "GROUP BY company_id, lower(name) "
            "HAVING count(*) > 1"
        )
    ).fetchall()
    if dupes:
        dupe_list = ", ".join(f"company {r[0]}: '{r[1]}' (x{r[2]})" for r in dupes)
        raise RuntimeError(
            "Cannot create unique index uq_salary_structures_company_lower_name: "
            f"live salary structures share a name: {dupe_list}. Rename or delete them first."
        )

    op.create_index(
        "uq_salary_structures_company_lower_name",
        "salary_structures",
        ["company_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_salary_structures_company_lower_name",
        table_name="salary_structures",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
