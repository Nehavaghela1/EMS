"""add announcement department_id

Revision ID: a1b2c3d4e5f6
Revises: 9e0f1a2b3c4d
Create Date: 2026-10-30 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9e0f1a2b3c4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "announcements",
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_announcements_department_id",
        "announcements",
        ["department_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_announcements_department_id", table_name="announcements")
    op.drop_column("announcements", "department_id")
