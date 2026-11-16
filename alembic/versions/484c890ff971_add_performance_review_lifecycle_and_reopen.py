"""add_performance_review_lifecycle_and_reopen

Revision ID: 484c890ff971
Revises: ba7f5a947ea9
Create Date: 2026-11-16 15:19:31.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '484c890ff971'
down_revision: Union[str, Sequence[str], None] = 'ba7f5a947ea9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add status and reopened tracking columns to performance_reviews
    op.add_column(
        'performance_reviews',
        sa.Column('status', sa.String(length=30), nullable=False, server_default='submitted'),
    )
    op.add_column(
        'performance_reviews',
        sa.Column('reopened_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'performance_reviews',
        sa.Column('reopened_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
    )
    op.add_column(
        'performance_reviews',
        sa.Column('reopen_reason', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('performance_reviews', 'reopen_reason')
    op.drop_column('performance_reviews', 'reopened_by_id')
    op.drop_column('performance_reviews', 'reopened_at')
    op.drop_column('performance_reviews', 'status')
