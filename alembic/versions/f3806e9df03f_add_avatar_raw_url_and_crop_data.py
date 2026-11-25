"""add avatar_raw_url and avatar_crop_data to employees

Revision ID: f3806e9df03f
Revises: 8f1e2d3c4b5a
Create Date: 2026-11-25 16:20:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f3806e9df03f"
down_revision: str | None = "8f1e2d3c4b5a"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("avatar_raw_url", sa.Text(), nullable=True))
    op.add_column("employees", sa.Column("avatar_crop_data", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "avatar_crop_data")
    op.drop_column("employees", "avatar_raw_url")
