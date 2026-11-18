"""change default payroll_working_days_basis to calendar_days and migrate existing rows

Revision ID: 5c60ecccd8c9
Revises: 1ea71db045fc
Create Date: 2026-11-19 00:21:59.332594

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c60ecccd8c9'
down_revision: Union[str, Sequence[str], None] = '1ea71db045fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""change default payroll_working_days_basis to calendar_days and migrate existing rows

Revision ID: 5c60ecccd8c9
Revises: 1ea71db045fc
Create Date: 2026-11-19 00:21:59.000000

This migration changes the default value of payroll_working_days_basis on company_settings
from 'working_days' to 'calendar_days' and updates existing rows. This preserves current behaviour
because the payroll calculation engine has always paid on calendar days and ignored this column until now.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c60ecccd8c9'
down_revision: Union[str, Sequence[str], None] = '1ea71db045fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema and update existing rows."""
    op.execute(
        "UPDATE company_settings SET payroll_working_days_basis = 'calendar_days' "
        "WHERE payroll_working_days_basis = 'working_days'"
    )
    op.alter_column(
        "company_settings",
        "payroll_working_days_basis",
        server_default="calendar_days",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "company_settings",
        "payroll_working_days_basis",
        server_default="working_days",
    )
