"""add probation_decisions and status

Revision ID: 460ca24e1326
Revises: eae57e59e8b8
Create Date: 2026-11-23 16:59:39.123456

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = "460ca24e1326"
down_revision: str | Sequence[str] | None = "eae57e59e8b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "employees",
        sa.Column(
            "probation_status",
            sa.String(30),
            nullable=False,
            server_default="pending",
        ),
    )

    op.create_table(
        "probation_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("previous_end_date", sa.Date(), nullable=False),
        sa.Column("new_end_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
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
        "ix_probation_decisions_company_id",
        "probation_decisions",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_probation_decisions_employee_id",
        "probation_decisions",
        ["employee_id"],
        unique=False,
    )

    enable_rls("probation_decisions")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_probation_decisions_employee_id", table_name="probation_decisions")
    op.drop_index("ix_probation_decisions_company_id", table_name="probation_decisions")
    op.drop_table("probation_decisions")
    op.drop_column("employees", "probation_status")
