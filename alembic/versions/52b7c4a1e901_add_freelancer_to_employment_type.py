"""add freelancer to employment_type enum

Revision ID: 52b7c4a1e901
Revises: 460ca24e1326
Create Date: 2026-11-24 06:33:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "52b7c4a1e901"
down_revision: str | Sequence[str] | None = "460ca24e1326"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add 'freelancer' value to native Postgres employment_type enum if in Postgres."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE employment_type ADD VALUE IF NOT EXISTS 'freelancer'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres ENUM values cannot be cleanly removed without recreating the type
    pass
