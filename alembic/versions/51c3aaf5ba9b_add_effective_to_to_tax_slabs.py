"""add effective_to to tax_slabs

Revision ID: 51c3aaf5ba9b
Revises: d8c9e0111213
Create Date: 2026-11-18 23:22:34.505214

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '51c3aaf5ba9b'
down_revision: Union[str, Sequence[str], None] = 'd8c9e0111213'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tax_slabs", sa.Column("effective_to", sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tax_slabs", "effective_to")
