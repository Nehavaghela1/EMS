"""Add owner and attendance exempt fields

Revision ID: 7a8b9c0d1e2f
Revises: f9b8c7d6e5a4
Create Date: 2026-09-22 16:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7a8b9c0d1e2f'
down_revision: Union[str, Sequence[str], None] = 'f9b8c7d6e5a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update user_role postgres enum if exists
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'owner';")

    # 2. Add columns to companies
    op.add_column('companies', sa.Column('owner_user_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('companies', sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('companies', sa.Column('deactivation_reason', sa.Text(), nullable=True))
    op.create_foreign_key(
        'fk_companies_owner_user_id_users',
        'companies',
        'users',
        ['owner_user_id'],
        ['id'],
        use_alter=True,
    )

    # 3. Add column to employees
    op.add_column('employees', sa.Column('is_attendance_exempt', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('employees', 'is_attendance_exempt')
    op.drop_constraint('fk_companies_owner_user_id_users', 'companies', type_='foreignkey')
    op.drop_column('companies', 'deactivation_reason')
    op.drop_column('companies', 'is_active')
    op.drop_column('companies', 'owner_user_id')
