"""add pending_separation and separation_decisions

Revision ID: a98805137c72
Revises: f6064868f2e4
Create Date: 2026-11-23 01:04:42.095860

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = "a98805137c72"
down_revision: str | Sequence[str] | None = "f6064868f2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "employees",
        sa.Column("pending_separation", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "separation_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "pip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("performance_pips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_working_date", sa.Date(), nullable=True),
        sa.Column("notice_choice", sa.String(50), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
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
        "ix_separation_decisions_company_id",
        "separation_decisions",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_separation_decisions_pip_id",
        "separation_decisions",
        ["pip_id"],
        unique=False,
    )

    enable_rls("separation_decisions")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_separation_decisions_pip_id",
        table_name="separation_decisions",
    )
    op.drop_index(
        "ix_separation_decisions_company_id",
        table_name="separation_decisions",
    )
    op.drop_table("separation_decisions")
    op.drop_column("employees", "pending_separation")
