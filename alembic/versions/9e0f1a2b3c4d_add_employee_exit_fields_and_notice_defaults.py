"""add employee exit fields and company notice defaults

Revision ID: 9e0f1a2b3c4d
Revises: 8d9e0f1a2b3c
Create Date: 2026-10-29 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9e0f1a2b3c4d"
down_revision: Union[str, Sequence[str], None] = "8d9e0f1a2b3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add exit columns to employees
    op.add_column(
        "employees",
        sa.Column("resignation_reason", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column("termination_notes", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column("fnf_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column("clearance_signoffs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # 2. Add notice_period_defaults to companies
    op.add_column(
        "companies",
        sa.Column("notice_period_defaults", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("companies", "notice_period_defaults")
    op.drop_column("employees", "clearance_signoffs")
    op.drop_column("employees", "fnf_snapshot")
    op.drop_column("employees", "termination_notes")
    op.drop_column("employees", "resignation_reason")
