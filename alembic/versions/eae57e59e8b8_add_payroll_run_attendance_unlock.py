"""add_payroll_run_attendance_unlock

Revision ID: eae57e59e8b8
Revises: a98805137c72
Create Date: 2026-11-23 16:53:08.613295

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eae57e59e8b8"
down_revision: str | Sequence[str] | None = "a98805137c72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "payroll_runs",
        sa.Column(
            "is_attendance_unlocked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "payroll_runs",
        sa.Column(
            "attendance_unlocked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "payroll_runs",
        sa.Column(
            "attendance_unlocked_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "payroll_runs",
        sa.Column(
            "attendance_unlock_reason",
            sa.String(500),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("payroll_runs", "attendance_unlock_reason")
    op.drop_column("payroll_runs", "attendance_unlocked_by")
    op.drop_column("payroll_runs", "attendance_unlocked_at")
    op.drop_column("payroll_runs", "is_attendance_unlocked")
