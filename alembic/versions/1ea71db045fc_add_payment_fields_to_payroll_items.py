"""add payment fields to payroll_items

Revision ID: 1ea71db045fc
Revises: 51c3aaf5ba9b
Create Date: 2026-11-18 23:24:26.945649

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1ea71db045fc'
down_revision: Union[str, Sequence[str], None] = '51c3aaf5ba9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "payroll_items",
        sa.Column(
            "payment_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column("payroll_items", sa.Column("paid_on", sa.Date(), nullable=True))
    op.add_column(
        "payroll_items",
        sa.Column("bank_reference", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("payroll_items", "bank_reference")
    op.drop_column("payroll_items", "paid_on")
    op.drop_column("payroll_items", "payment_status")
