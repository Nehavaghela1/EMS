"""rate sources, rate change drafts and reminder log

Revision ID: 2add83c6cc86
Revises: 615c8f1fd828
Create Date: 2026-11-05 20:10:00.000000

5.9. Three PLATFORM tables (no company_id, no row level security: like `statutory_rates`
they are scoped by the super_admin-only routes):

- `rate_sources`: a government page the daily check reads (country, optional state, scheme
  group, title, link, interval, next check date, last result and the SHA-256 of its text).
- `rate_change_drafts`: a proposed change of live rates, pending -> verified -> approved (or
  rejected). Only approval changes a rate row.
- `rate_reminder_log`: one row per stale rate row and reminder, so a row is reminded at most
  once per 30 days.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '2add83c6cc86'
down_revision: Union[str, Sequence[str], None] = '615c8f1fd828'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "rate_sources",
        *_base_columns(),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=True),
        sa.Column("scheme_group", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("interval_months", sa.SmallInteger(), nullable=False),
        sa.Column("next_check_on", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_checked_on", sa.Date(), nullable=True),
        sa.Column("last_result", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "scheme_group IN ('epf_esi', 'professional_tax', 'income_tax', 'social_security', 'other')",
            name="ck_rate_sources_group",
        ),
        sa.CheckConstraint(
            "last_result IN ('never', 'baseline', 'unchanged', 'changed', 'fetch_failed')",
            name="ck_rate_sources_result",
        ),
        sa.CheckConstraint("interval_months BETWEEN 1 AND 24", name="ck_rate_sources_interval_months"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_rate_sources_country_state_group_url",
        "rate_sources",
        ["country", sa.text("coalesce(state, '')"), "scheme_group", "source_url"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "rate_change_drafts",
        *_base_columns(),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("proposed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("fetched_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("verified_by", sa.UUID(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sources_checked", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('statutory_rate', 'pt_slabs', 'tax_slabs', 'no_numbers')",
            name="ck_rate_change_drafts_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'approved', 'rejected')",
            name="ck_rate_change_drafts_status",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["rate_sources.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rate_change_drafts_source_id", "rate_change_drafts", ["source_id"])
    op.create_index("ix_rate_change_drafts_status", "rate_change_drafts", ["status"])

    op.create_table(
        "rate_reminder_log",
        *_base_columns(),
        sa.Column("row_kind", sa.String(length=20), nullable=False),
        sa.Column("row_id", sa.UUID(), nullable=False),
        sa.Column("reminded_on", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rate_reminder_log_row", "rate_reminder_log", ["row_kind", "row_id"])


def downgrade() -> None:
    op.drop_table("rate_reminder_log")
    op.drop_table("rate_change_drafts")
    op.drop_table("rate_sources")
