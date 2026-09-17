"""add_rejection_reason_to_time_entries

Revision ID: f7fd13e886c4
Revises: 0a75858bf298
Create Date: 2026-09-17 19:09:22.742841

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7fd13e886c4'
down_revision: Union[str, Sequence[str], None] = '0a75858bf298'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('time_entries', sa.Column('rejection_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('time_entries', 'rejection_reason')
