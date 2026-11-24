"""Widen statutory_rates scheme constraint and length for global jurisdictions

Revision ID: 7e2f1a9b3c4d
Revises: 52b7c4a1e901
Create Date: 2026-11-24 16:45:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision: str = "7e2f1a9b3c4d"
down_revision: str | None = "52b7c4a1e901"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 1. Drop the check constraint that restricted schemes strictly to 'epf' and 'esi'
    op.drop_constraint("ck_statutory_rates_scheme", "statutory_rates", type_="check")

    # 2. Widen scheme column from VARCHAR(10) to VARCHAR(30) to support global scheme codes
    op.alter_column(
        "statutory_rates",
        "scheme",
        existing_type=sa.String(10),
        type_=sa.String(30),
        nullable=False,
    )

    # 3. Add updated check constraint ensuring scheme is a non-empty alphanumeric/underscore slug
    op.create_check_constraint(
        "ck_statutory_rates_scheme",
        "statutory_rates",
        "length(scheme) >= 2 AND scheme = lower(scheme)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_statutory_rates_scheme", "statutory_rates", type_="check")
    op.alter_column(
        "statutory_rates",
        "scheme",
        existing_type=sa.String(30),
        type_=sa.String(10),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_statutory_rates_scheme",
        "statutory_rates",
        "scheme IN ('epf', 'esi')",
    )
