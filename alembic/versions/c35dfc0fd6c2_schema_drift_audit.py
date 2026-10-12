"""add missing companies and statutory_configs columns

Revision ID: c35dfc0fd6c2
Revises: cbf5cc7429a8
Create Date: 2026-10-12 14:58:27.724531

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c35dfc0fd6c2'
down_revision: Union[str, Sequence[str], None] = 'cbf5cc7429a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS subdomain VARCHAR(100)")
    op.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS company_size VARCHAR(50)")
    op.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS admin_password_hash TEXT")
    op.execute("ALTER TABLE statutory_configs ADD COLUMN IF NOT EXISTS payout_bank_name VARCHAR(100)")
    op.execute("ALTER TABLE statutory_configs ADD COLUMN IF NOT EXISTS payout_account_number VARCHAR(50)")
    op.execute("ALTER TABLE statutory_configs ADD COLUMN IF NOT EXISTS payout_ifsc_code VARCHAR(20)")
    op.execute(
        "ALTER TABLE statutory_configs "
        "ADD COLUMN IF NOT EXISTS payout_enabled BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE statutory_configs DROP COLUMN IF EXISTS payout_enabled")
    op.execute("ALTER TABLE statutory_configs DROP COLUMN IF EXISTS payout_ifsc_code")
    op.execute("ALTER TABLE statutory_configs DROP COLUMN IF EXISTS payout_account_number")
    op.execute("ALTER TABLE statutory_configs DROP COLUMN IF EXISTS payout_bank_name")
    op.execute("ALTER TABLE companies DROP COLUMN IF EXISTS admin_password_hash")
    op.execute("ALTER TABLE companies DROP COLUMN IF EXISTS company_size")
    op.execute("ALTER TABLE companies DROP COLUMN IF EXISTS subdomain")
