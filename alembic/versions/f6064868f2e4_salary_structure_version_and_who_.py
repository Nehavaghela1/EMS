"""Salary structures: a version counter and who created or last changed one.

A salary structure is the one payroll record edited in place rather than
appended to (employee_salaries adds a row for every revision and the database
refuses overlapping ranges), so two people editing it at once could overwrite
each other with nobody told. `version` carries the row's edition: an update
states the version it read and is refused if the row has moved on since.

`created_by` and `updated_by` answer "who changed this", which until now lived
only in the audit log. Both are nullable because rows already in the database
pre-date the columns and their author is not knowable here.

Revision ID: f6064868f2e4
Revises: a7c3e9d1f2b4
Create Date: 2026-11-22 09:00:18.534197
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6064868f2e4"
down_revision: str | Sequence[str] | None = "a7c3e9d1f2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "salary_structures",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("salary_structures", sa.Column("created_by", sa.UUID(), nullable=True))
    op.add_column("salary_structures", sa.Column("updated_by", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_salary_structures_created_by_users",
        "salary_structures",
        "users",
        ["created_by"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_salary_structures_updated_by_users",
        "salary_structures",
        "users",
        ["updated_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_salary_structures_updated_by_users", "salary_structures", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_salary_structures_created_by_users", "salary_structures", type_="foreignkey"
    )
    op.drop_column("salary_structures", "updated_by")
    op.drop_column("salary_structures", "created_by")
    op.drop_column("salary_structures", "version")
