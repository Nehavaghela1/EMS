"""statutory rates table official source columns remove company rate columns

Revision ID: 5c2a0001a001
Revises: 11355755ef14
Create Date: 2026-11-04 17:00:00.000000

5.2. PF and ESI rates and ceilings move from every company's `statutory_configs` row to the
platform table `statutory_rates` (effective-dated, no overlap, each row with its official
source). `pt_slabs` and `tax_slabs` get the same source columns.

Data: the four placeholder Gujarat professional-tax rows (start date 2000-01-01, end
2022-03-31) are DELETED. No official page supports them: the start date was an unverified
placeholder and the figures were quoted from a tax-law publisher, not a government page. The
downgrade does not bring them back. The Gujarat rows from 2022-04-01 and the income-tax rows of
2025-2026 and 2026-2027 get their official source from the table below; any other pt_slabs or
tax_slabs row has no known source, so the migration stops and names it. Nothing is guessed.

The downgrade re-adds the six company rate columns with the old defaults (12.000, 12.000,
15000.00, 0.750, 3.250, 21000.00) and drops `statutory_rates`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c2a0001a001'
down_revision: Union[str, Sequence[str], None] = '11355755ef14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VERIFIED_ON = "2026-11-04"

_GUJARAT_PT = {
    "url": "https://commercialtax.gujarat.gov.in/vatwebsite/download/schedule/Rate_of_Profession_Tax.pdf",
    "title": "Gujarat Commercial Tax Department - Rate of Profession Tax (Entry 1, effective 01/04/2022)",
    "note": (
        "Gujarat Commercial Tax Department schedule of professional tax rates, Entry 1, "
        "effective 01/04/2022 (page updated 14/02/2024): monthly salary up to and including "
        "12000.00 pays 0.00; more than 12000.00 pays 200.00."
    ),
}

_TAX_YEARS = {
    "2025-2026": {
        "url": "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2098406&reg=3&lang=2",
        "title": "PIB - Union Budget 2025: new regime slabs, standard deduction 75,000, no tax up to 12 lakh",
        "note": (
            "Also: https://www.incometaxindia.gov.in/w/tax-rates%E2%80%8B (slabs by assessment "
            "year, old regime, surcharge, cess, 87A rebate old regime 12,500). The old-regime "
            "standard deduction of 50,000 was not re-verified against an official page on "
            "2026-11-04."
        ),
    },
    "2026-2027": {
        "url": "https://www.indiabudget.gov.in/doc/memo.pdf",
        "title": "Finance Bill 2026 explanatory memo - no change proposed in tax rates",
        "note": (
            "Also: https://static.pib.gov.in/WriteReadData/specificdocs/documents/2026/feb/"
            "doc202621776101.pdf (Union Budget 2026-27 summary: no slab change listed). "
            "'Unchanged for FY 2026-27' is taken from those two documents and needs a human "
            "check against the Finance Act 2026 text. The old-regime standard deduction of "
            "50,000 was not re-verified against an official page on 2026-11-04."
        ),
    },
}

_OLD_DEFAULTS = {
    "pf_employee_rate": ("0.000", sa.Numeric(6, 3), "12.000"),
    "pf_employer_rate": ("0.000", sa.Numeric(6, 3), "12.000"),
    "pf_wage_ceiling": ("0.00", sa.Numeric(14, 2), "15000.00"),
    "esi_employee_rate": ("0.000", sa.Numeric(6, 3), "0.750"),
    "esi_employer_rate": ("0.000", sa.Numeric(6, 3), "3.250"),
    "esi_wage_ceiling": ("0.00", sa.Numeric(14, 2), "21000.00"),
}


def _add_source_columns(table: str) -> None:
    op.add_column(table, sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column(table, sa.Column("source_title", sa.String(length=200), nullable=True))
    op.add_column(table, sa.Column("verified_on", sa.Date(), nullable=True))
    op.alter_column(table, "source_note", existing_type=sa.Text(), nullable=True)


def _require_sources(conn, table: str, label_sql: str) -> None:
    unknown = conn.execute(
        sa.text(f"SELECT {label_sql} FROM {table} WHERE source_url IS NULL ORDER BY 1")
    ).fetchall()
    if unknown:
        listed = "; ".join(r[0] for r in unknown)
        raise RuntimeError(
            f"Cannot add the official source columns to {table}: these rows have no known "
            f"official source: {listed}. Delete them or give each an official source first. "
            "Nothing is guessed."
        )


def upgrade() -> None:
    conn = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "statutory_rates",
        sa.Column("scheme", sa.String(length=10), nullable=False),
        sa.Column("employee_rate", sa.Numeric(6, 3), nullable=False),
        sa.Column("employer_rate", sa.Numeric(6, 3), nullable=False),
        sa.Column("wage_ceiling", sa.Numeric(14, 2), nullable=False),
        sa.Column("employer_epf_rate", sa.Numeric(6, 3), nullable=True),
        sa.Column("employer_eps_rate", sa.Numeric(6, 3), nullable=True),
        sa.Column("edli_rate", sa.Numeric(6, 3), nullable=True),
        sa.Column("admin_charge_rate", sa.Numeric(6, 3), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_title", sa.String(length=200), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("verified_on", sa.Date(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scheme IN ('epf', 'esi')", name="ck_statutory_rates_scheme"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "ALTER TABLE statutory_rates ADD CONSTRAINT ex_statutory_rates_no_overlap "
        "EXCLUDE USING gist (scheme WITH =, "
        "(daterange(effective_from, coalesce(effective_to, 'infinity'::date), '[]')) WITH &&) "
        "WHERE (deleted_at IS NULL)"
    )

    # The placeholder Gujarat rows: no official source, never verified. Deleted (see docstring).
    conn.execute(
        sa.text(
            "DELETE FROM pt_slabs WHERE state = 'Gujarat' "
            "AND effective_from = DATE '2000-01-01' AND effective_to = DATE '2022-03-31'"
        )
    )

    _add_source_columns("pt_slabs")
    conn.execute(
        sa.text(
            "UPDATE pt_slabs SET source_url = :url, source_title = :title, source_note = :note, "
            "verified_on = :verified WHERE state = 'Gujarat' AND effective_from = DATE '2022-04-01'"
        ),
        {
            "url": _GUJARAT_PT["url"],
            "title": _GUJARAT_PT["title"],
            "note": _GUJARAT_PT["note"],
            "verified": _VERIFIED_ON,
        },
    )
    _require_sources(conn, "pt_slabs", "state || ' from ' || effective_from::text || ' (no source)'")

    _add_source_columns("tax_slabs")
    for fy, source in _TAX_YEARS.items():
        conn.execute(
            sa.text(
                "UPDATE tax_slabs SET source_url = :url, source_title = :title, "
                "source_note = :note, verified_on = :verified "
                "WHERE country = 'IN' AND financial_year = :fy"
            ),
            {
                "url": source["url"],
                "title": source["title"],
                "note": source["note"],
                "verified": _VERIFIED_ON,
                "fy": fy,
            },
        )
    _require_sources(
        conn,
        "tax_slabs",
        "country || ' ' || financial_year || ' ' || regime::text || ' (no source)'",
    )

    for table in ("pt_slabs", "tax_slabs"):
        for column, kind in (("source_url", sa.Text()), ("source_title", sa.String(200)), ("verified_on", sa.Date())):
            op.alter_column(table, column, existing_type=kind, nullable=False)

    for column in _OLD_DEFAULTS:
        op.drop_column("statutory_configs", column)


def downgrade() -> None:
    conn = op.get_bind()
    for column, (_, kind, default) in _OLD_DEFAULTS.items():
        op.add_column(
            "statutory_configs",
            sa.Column(column, kind, nullable=False, server_default=sa.text(default)),
        )
        op.alter_column("statutory_configs", column, existing_type=kind, server_default=None)

    for table in ("tax_slabs", "pt_slabs"):
        conn.execute(sa.text(f"UPDATE {table} SET source_note = '' WHERE source_note IS NULL"))
        op.alter_column(table, "source_note", existing_type=sa.Text(), nullable=False)
        op.drop_column(table, "verified_on")
        op.drop_column(table, "source_title")
        op.drop_column(table, "source_url")

    op.drop_table("statutory_rates")
