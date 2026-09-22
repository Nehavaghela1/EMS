"""Add attachment_url and admin_notes to regularizations

Revision ID: f9b8c7d6e5a4
Revises: ab4df060ab27
Create Date: 2026-09-22 09:27:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9b8c7d6e5a4'
down_revision: Union[str, Sequence[str], None] = 'ab4df060ab27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('attendance_regularizations', sa.Column('attachment_url', sa.String(length=500), nullable=True))
    op.add_column('attendance_regularizations', sa.Column('admin_notes', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('attendance_regularizations', 'admin_notes')
    op.drop_column('attendance_regularizations', 'attachment_url')
