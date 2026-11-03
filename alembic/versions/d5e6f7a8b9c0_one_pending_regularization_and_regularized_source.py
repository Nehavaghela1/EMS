"""one pending regularization per attendance record; attendance source 'regularized'

Revision ID: d5e6f7a8b9c0
Revises: 7fe2862a3b33
Create Date: 2026-11-03 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "7fe2862a3b33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _platform_context(conn) -> None:
    # Under FORCE ROW LEVEL SECURITY alembic (ems_owner) sees no tenant rows unless the
    # platform-admin context is set, transaction-locally.
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))


def upgrade() -> None:
    conn = op.get_bind()
    _platform_context(conn)

    dupes = conn.execute(
        sa.text(
            "SELECT company_id, attendance_id, count(*) FROM attendance_regularizations "
            "WHERE status = 'pending' GROUP BY company_id, attendance_id HAVING count(*) > 1"
        )
    ).fetchall()
    if dupes:
        listing = ", ".join(f"company {r[0]}: attendance {r[1]} (x{r[2]})" for r in dupes)
        raise RuntimeError(
            "Cannot create unique index uq_attendance_regularizations_pending: duplicate "
            f"pending regularization requests exist: {listing}"
        )

    op.create_index(
        "uq_attendance_regularizations_pending",
        "attendance_regularizations",
        ["company_id", "attendance_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.execute("ALTER TYPE attendance_source ADD VALUE IF NOT EXISTS 'regularized'")


def downgrade() -> None:
    conn = op.get_bind()
    _platform_context(conn)

    op.drop_index("uq_attendance_regularizations_pending", table_name="attendance_regularizations")

    # A Postgres enum value cannot be dropped: rows that used it go back to 'system', then the
    # type is rebuilt without it.
    conn.execute(sa.text("UPDATE attendance SET source = 'system' WHERE source = 'regularized'"))
    op.execute("ALTER TYPE attendance_source RENAME TO attendance_source_old")
    op.execute("CREATE TYPE attendance_source AS ENUM ('web', 'mobile', 'system', 'import')")
    op.execute(
        "ALTER TABLE attendance ALTER COLUMN source TYPE attendance_source "
        "USING source::text::attendance_source"
    )
    op.execute("DROP TYPE attendance_source_old")
