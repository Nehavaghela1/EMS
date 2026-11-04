"""employee salaries no overlap exclusion constraint

Revision ID: 6966b6687e96
Revises: 220d412e6fbe
Create Date: 2026-11-03 19:52:10.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6966b6687e96"
down_revision: Union[str, Sequence[str], None] = "220d412e6fbe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RANGE = "daterange(effective_from, coalesce(effective_to, 'infinity'::date), '[]')"


def upgrade() -> None:
    conn = op.get_bind()

    # Under FORCE ROW LEVEL SECURITY alembic runs as ems_owner without tenant context; set the
    # platform-admin context for this transaction so the overlap check sees every company.
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))

    overlaps = conn.execute(
        sa.text(
            "SELECT a.employee_id, a.id, b.id "
            "FROM employee_salaries a JOIN employee_salaries b "
            "  ON a.employee_id = b.employee_id AND a.id < b.id "
            " AND a.deleted_at IS NULL AND b.deleted_at IS NULL "
            "WHERE daterange(a.effective_from, coalesce(a.effective_to, 'infinity'::date), '[]') "
            "   && daterange(b.effective_from, coalesce(b.effective_to, 'infinity'::date), '[]')"
        )
    ).fetchall()
    if overlaps:
        listed = ", ".join(f"employee {r[0]}: rows {r[1]} and {r[2]}" for r in overlaps)
        raise RuntimeError(
            "Cannot create ex_employee_salaries_no_overlap: these employees have salary rows "
            f"with overlapping dates: {listed}. Fix the dates (or soft-delete the wrong row) first."
        )

    # btree_gist lets a gist index compare the employee id with "=" next to the date range.
    # If this statement is refused the migration stops here, loudly; the extension is not
    # worked around.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        "ALTER TABLE employee_salaries "
        "ADD CONSTRAINT ex_employee_salaries_no_overlap "
        f"EXCLUDE USING gist (employee_id WITH =, ({_RANGE}) WITH &&) "
        "WHERE (deleted_at IS NULL)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE employee_salaries DROP CONSTRAINT ex_employee_salaries_no_overlap")
    # The btree_gist extension is left installed: other objects may use it.
