"""add_hourly_rate_to_employee_salaries

Revision ID: 0a75858bf298
Revises: b776f6d76f3f
Create Date: 2026-09-17 17:14:22.948561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a75858bf298'
down_revision: Union[str, Sequence[str], None] = 'b776f6d76f3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('employee_salaries', sa.Column('hourly_rate', sa.Numeric(precision=14, scale=2), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('employee_salaries', 'hourly_rate')
