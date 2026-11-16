"""add_project_member_rates_and_projects_status

Revision ID: 7a1b2c3d4e5f
Revises: 484c890ff971
Create Date: 2026-11-16 19:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7a1b2c3d4e5f'
down_revision: Union[str, Sequence[str], None] = '484c890ff971'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add end_date to projects table
    op.add_column('projects', sa.Column('end_date', sa.Date(), nullable=True))

    # 2. Add hourly_rate to project_members table
    op.add_column(
        'project_members',
        sa.Column('hourly_rate', sa.Numeric(precision=12, scale=2), nullable=True),
    )

    # 3. Create project_member_rates table for effective-dated hourly billing rates history
    op.create_table(
        'project_member_rates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('employee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('rate', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index(
        'idx_project_member_rates_lookup',
        'project_member_rates',
        ['company_id', 'project_id', 'employee_id', 'effective_from'],
    )

    from app.db.rls import enable_rls
    enable_rls('project_member_rates')


def downgrade() -> None:
    op.drop_table('project_member_rates')
    op.drop_column('project_members', 'hourly_rate')
    op.drop_column('projects', 'end_date')
