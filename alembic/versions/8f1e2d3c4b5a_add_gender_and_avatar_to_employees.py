"""add gender avatar_url and avatar_visibility to employees

Revision ID: 8f1e2d3c4b5a
Revises: 7e2f1a9b3c4d
Create Date: 2026-11-25 15:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision: str = "8f1e2d3c4b5a"
down_revision: str | None = "7e2f1a9b3c4d"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("gender", sa.String(length=50), nullable=True))
    op.add_column("employees", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column(
        "employees",
        sa.Column(
            "avatar_visibility",
            sa.String(length=20),
            nullable=False,
            server_default="company",
        ),
    )


def downgrade() -> None:
    op.drop_column("employees", "avatar_visibility")
    op.drop_column("employees", "avatar_url")
    op.drop_column("employees", "gender")
