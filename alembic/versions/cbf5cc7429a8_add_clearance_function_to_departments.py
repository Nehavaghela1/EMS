"""add clearance_function to departments

Revision ID: cbf5cc7429a8
Revises: 7a8b9c0d1e2f
Create Date: 2026-10-11 16:28:10.858181

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cbf5cc7429a8"
down_revision: str | Sequence[str] | None = "7a8b9c0d1e2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add column with check constraint
    op.add_column(
        "departments",
        sa.Column("clearance_function", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_departments_clearance_function",
        "departments",
        "clearance_function IN ('it', 'finance', 'hr')",
    )

    # 2. Backfill exact case-insensitive matches:
    # IT, Information Technology -> it
    # Finance -> finance
    # Human Resources, HR -> hr
    conn = op.get_bind()
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))
    it_names = ("it", "information technology")
    fin_names = ("finance",)
    hr_names = ("human resources", "hr")

    # Fetch rows to backfill and print
    rows = conn.execute(
        sa.text(
            """
            SELECT d.id, d.name, c.name AS company_name, lower(trim(d.name)) AS norm_name
            FROM departments d
            JOIN companies c ON d.company_id = c.id
            WHERE d.deleted_at IS NULL
            """
        )
    ).fetchall()

    for row in rows:
        fn = None
        if row.norm_name in it_names:
            fn = "it"
        elif row.norm_name in fin_names:
            fn = "finance"
        elif row.norm_name in hr_names:
            fn = "hr"

        if fn:
            conn.execute(
                sa.text("UPDATE departments SET clearance_function = :fn WHERE id = :dept_id"),
                {"fn": fn, "dept_id": row.id},
            )
            print(
                f"[Migration Backfill] Company: {row.company_name!r}, "
                f"Department: {row.name!r} -> clearance_function={fn!r}"
            )


def downgrade() -> None:
    op.drop_constraint("ck_departments_clearance_function", "departments", type_="check")
    op.drop_column("departments", "clearance_function")
