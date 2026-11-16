"""add_milestone_id_and_position_to_tasks

Revision ID: 7b5eae988b1c
Revises: 7a1b2c3d4e5f
Create Date: 2026-11-16 22:49:22.698367

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7b5eae988b1c"
down_revision: str | Sequence[str] | None = "7a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "milestone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("milestones.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tasks_milestone_id", "tasks", ["milestone_id"])
    op.add_column(
        "tasks",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "position")
    op.drop_index("ix_tasks_milestone_id", table_name="tasks")
    op.drop_column("tasks", "milestone_id")
