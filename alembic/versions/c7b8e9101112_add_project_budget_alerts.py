"""add_project_budget_alerts

Revision ID: c7b8e9101112
Revises: a6c37f34c63c
Create Date: 2026-11-18 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7b8e9101112"
down_revision: str | Sequence[str] | None = "a6c37f34c63c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "projects",
        sa.Column("budget_alert_80_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("budget_alert_100_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("projects", "budget_alert_100_sent_at")
    op.drop_column("projects", "budget_alert_80_sent_at")
