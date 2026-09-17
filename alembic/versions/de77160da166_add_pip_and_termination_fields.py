"""add_pip_and_termination_fields

Revision ID: de77160da166
Revises: f7fd13e886c4
Create Date: 2026-09-17 19:26:31.979272

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de77160da166'
down_revision: Union[str, Sequence[str], None] = 'f7fd13e886c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add separation & settlement fields to employees
    op.add_column('employees', sa.Column('separation_type', sa.String(length=50), nullable=True))
    op.add_column('employees', sa.Column('termination_reason', sa.String(length=255), nullable=True))
    op.add_column('employees', sa.Column('severance_pay', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('employees', sa.Column('pending_reimbursements', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('employees', sa.Column('gratuity_bonus', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('employees', sa.Column('asset_deductions', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('employees', sa.Column('it_clearance', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('employees', sa.Column('hr_clearance', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('employees', sa.Column('finance_clearance', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('employees', sa.Column('fnf_settled_at', sa.DateTime(timezone=True), nullable=True))

    # 2. Create performance_pips table
    op.create_table(
        'performance_pips',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('employee_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('mentor_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('milestones_kpis', sa.Text(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='active'),
        sa.Column('outcome_notes', sa.Text(), nullable=True),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('evaluated_by', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_performance_pips_company_employee', 'performance_pips', ['company_id', 'employee_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_performance_pips_company_employee', table_name='performance_pips')
    op.drop_table('performance_pips')
    op.drop_column('employees', 'fnf_settled_at')
    op.drop_column('employees', 'finance_clearance')
    op.drop_column('employees', 'hr_clearance')
    op.drop_column('employees', 'it_clearance')
    op.drop_column('employees', 'asset_deductions')
    op.drop_column('employees', 'gratuity_bonus')
    op.drop_column('employees', 'pending_reimbursements')
    op.drop_column('employees', 'severance_pay')
    op.drop_column('employees', 'termination_reason')
    op.drop_column('employees', 'separation_type')
