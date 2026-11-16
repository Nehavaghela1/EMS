"""add_performance_goal_progress_history

Revision ID: ba7f5a947ea9
Revises: 2add83c6cc86
Create Date: 2026-11-16 13:20:58.882904

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.rls import enable_rls


# revision identifiers, used by Alembic.
revision: str = 'ba7f5a947ea9'
down_revision: Union[str, Sequence[str], None] = '2add83c6cc86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add progress column to performance_goals if not present
    op.add_column(
        'performance_goals',
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
    )

    # Create performance_goal_progress_history table
    op.create_table(
        'performance_goal_progress_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('goal_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('performance_goals.id', ondelete='CASCADE'), nullable=False),
        sa.Column('updated_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('old_progress', sa.Integer(), nullable=False),
        sa.Column('new_progress', sa.Integer(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
    )
    op.create_index(
        'ix_performance_goal_progress_history_company_id',
        'performance_goal_progress_history',
        ['company_id'],
        unique=False,
    )
    op.create_index(
        'ix_performance_goal_progress_history_goal_id',
        'performance_goal_progress_history',
        ['goal_id'],
        unique=False,
    )

    enable_rls('performance_goal_progress_history')


def downgrade() -> None:
    op.drop_index('ix_performance_goal_progress_history_goal_id', table_name='performance_goal_progress_history')
    op.drop_index('ix_performance_goal_progress_history_company_id', table_name='performance_goal_progress_history')
    op.drop_table('performance_goal_progress_history')
    op.drop_column('performance_goals', 'progress')
