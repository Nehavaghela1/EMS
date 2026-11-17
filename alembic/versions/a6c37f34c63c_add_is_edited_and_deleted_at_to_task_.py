"""add_is_edited_and_deleted_at_to_task_comments_and_project_documents

Revision ID: a6c37f34c63c
Revises: 7b5eae988b1c
Create Date: 2026-11-17 10:34:15.837641

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6c37f34c63c'
down_revision: Union[str, Sequence[str], None] = '7b5eae988b1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "task_comments",
        sa.Column("is_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "task_comments",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "task_comments",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_task_comments_deleted_at", "task_comments", ["deleted_at"])

    op.add_column(
        "project_documents",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_project_documents_deleted_at", "project_documents", ["deleted_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_project_documents_deleted_at", table_name="project_documents")
    op.drop_column("project_documents", "deleted_at")

    op.drop_index("ix_task_comments_deleted_at", table_name="task_comments")
    op.drop_column("task_comments", "deleted_at")
    op.drop_column("task_comments", "updated_at")
    op.drop_column("task_comments", "is_edited")
