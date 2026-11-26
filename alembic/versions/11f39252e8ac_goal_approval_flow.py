"""goal approval flow

Add approval_status to performance_goals with server_default 'approved' so every
existing goal stays exactly as it behaves today.

Revision ID: 11f39252e8ac
Revises: 360eb8182e97
Create Date: 2026-11-26 18:47:51.340452

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11f39252e8ac'
down_revision: Union[str, Sequence[str], None] = '360eb8182e97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    sa.Enum('pending_approval', 'approved', 'rejected', name='goal_approval_status').create(op.get_bind(), checkfirst=True)
    op.add_column('performance_goals', sa.Column('approval_status', sa.Enum('pending_approval', 'approved', 'rejected', name='goal_approval_status'), server_default=sa.text("'approved'"), nullable=False))
    op.add_column('performance_goals', sa.Column('rejection_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('performance_goals', 'rejection_reason')
    op.drop_column('performance_goals', 'approval_status')
    sa.Enum(name='goal_approval_status').drop(op.get_bind(), checkfirst=True)
