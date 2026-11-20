"""add_half_day_session_to_leaves

Revision ID: 39a987d23e60
Revises: 5c60ecccd8c9
Create Date: 2026-11-19 19:26:08.449836

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39a987d23e60'
down_revision: Union[str, Sequence[str], None] = '5c60ecccd8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('leaves', sa.Column('half_day_session', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('leaves', 'half_day_session')
