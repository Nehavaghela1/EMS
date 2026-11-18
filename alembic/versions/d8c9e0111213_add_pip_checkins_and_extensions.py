"""add_pip_checkins_and_extensions

Revision ID: d8c9e0111213
Revises: c7b8e9101112
Create Date: 2026-11-18 16:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = "d8c9e0111213"
down_revision: str | Sequence[str] | None = "c7b8e9101112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "performance_pips",
        sa.Column("previous_end_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "performance_pips",
        sa.Column("extension_reason", sa.String(500), nullable=True),
    )

    op.create_table(
        "performance_pip_checkins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "pip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("performance_pips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("note", sa.String(2000), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_performance_pip_checkins_company_id",
        "performance_pip_checkins",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_performance_pip_checkins_pip_id",
        "performance_pip_checkins",
        ["pip_id"],
        unique=False,
    )

    enable_rls("performance_pip_checkins")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_performance_pip_checkins_pip_id",
        table_name="performance_pip_checkins",
    )
    op.drop_index(
        "ix_performance_pip_checkins_company_id",
        table_name="performance_pip_checkins",
    )
    op.drop_table("performance_pip_checkins")
    op.drop_column("performance_pips", "extension_reason")
    op.drop_column("performance_pips", "previous_end_date")
