"""add password_changed_at to users

Revision ID: 4a5b6c7d8e9f
Revises: 3f9a1c7e5b20
Create Date: 2026-10-21 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4a5b6c7d8e9f"
down_revision: Union[str, Sequence[str], None] = "3f9a1c7e5b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users is an application-scoped table owned by ems_owner;
    # ems_app already inherits grants via default privileges, and users has no RLS (Spec 7.2).
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
