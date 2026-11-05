"""regions: country on statutory_rates and pt_slabs

Revision ID: 615c8f1fd828
Revises: 44b1a0e02746
Create Date: 2026-11-05 18:40:00.000000

5.2 (regions). `statutory_rates` and `pt_slabs` get a `country` column (2 letters, NOT NULL,
default IN). Every existing row is backfilled IN. The overlap rule of `statutory_rates` (the
exclusion constraint) now also compares the country, and the PT slab index starts with it.

The existing `pt_slabs.state` and `statutory_configs.pt_state` values are rewritten to the
canonical spelling of the shared list (app/core/regions.py), matched ignoring case and spaces:
the slabs against India, a company's state against its company's country. If any value matches
no state of the list the migration STOPS before changing anything and names the distinct values;
nothing is guessed.

The downgrade removes the country columns and restores the old constraint and index. Rows of
another country (written after this migration) would overlap the Indian ones without it, so the
downgrade deletes them. The spelling rewrite is not undone.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.regions import COUNTRY_REGIONS_MAP


# revision identifiers, used by Alembic.
revision: str = '615c8f1fd828'
down_revision: Union[str, Sequence[str], None] = '44b1a0e02746'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _canonical_lookup(country: str) -> dict[str, str]:
    entry = COUNTRY_REGIONS_MAP.get(country)
    return {s.lower(): s for s in entry["states"]} if entry else {}


def _plan_state_rewrites(
    conn,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """(slab rewrites as (country, old, new), config rewrites as (country, old, new)) and the
    unmatched values; raises when any value matches no state."""
    unmatched: set[str] = set()
    slab_rewrites: list[tuple[str, str, str]] = []
    india = _canonical_lookup("IN")
    for (state,) in conn.execute(sa.text("SELECT DISTINCT state FROM pt_slabs")).fetchall():
        canonical = india.get(state.strip().lower())
        if canonical is None:
            unmatched.add(state)
        elif canonical != state:
            slab_rewrites.append(("IN", state, canonical))

    config_rewrites: list[tuple[str, str, str]] = []
    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT c.country, sc.pt_state FROM statutory_configs sc "
            "JOIN companies c ON c.id = sc.company_id WHERE sc.pt_state IS NOT NULL"
        )
    ).fetchall()
    for country, state in rows:
        canonical = _canonical_lookup(country).get(state.strip().lower())
        if canonical is None:
            unmatched.add(state)
        elif canonical != state:
            config_rewrites.append((country, state, canonical))

    if unmatched:
        listed = ", ".join(sorted(unmatched))
        raise RuntimeError(
            "Cannot add the country column: these state values match no state in the shared "
            f"country and state list: {listed}. Correct or remove them first. Nothing was "
            "changed and nothing is guessed."
        )
    return slab_rewrites, config_rewrites


def upgrade() -> None:
    conn = op.get_bind()
    # Under FORCE ROW LEVEL SECURITY alembic runs as ems_owner without a tenant context; set
    # the platform-admin context for this transaction so every company's row is visible.
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))

    slab_rewrites, config_rewrites = _plan_state_rewrites(conn)

    op.add_column(
        "statutory_rates",
        sa.Column("country", sa.String(length=2), server_default="IN", nullable=False),
    )
    op.add_column(
        "pt_slabs",
        sa.Column("country", sa.String(length=2), server_default="IN", nullable=False),
    )

    op.execute("ALTER TABLE statutory_rates DROP CONSTRAINT ex_statutory_rates_no_overlap")
    op.execute(
        "ALTER TABLE statutory_rates ADD CONSTRAINT ex_statutory_rates_no_overlap "
        "EXCLUDE USING gist (country WITH =, scheme WITH =, "
        "(daterange(effective_from, coalesce(effective_to, 'infinity'::date), '[]')) WITH &&) "
        "WHERE (deleted_at IS NULL)"
    )

    op.drop_index("ix_pt_slabs_state_effective_from", table_name="pt_slabs")
    op.create_index(
        "ix_pt_slabs_country_state_effective_from",
        "pt_slabs",
        ["country", "state", "effective_from"],
    )

    for country, old, new in slab_rewrites:
        conn.execute(
            sa.text("UPDATE pt_slabs SET state = :new WHERE country = :c AND state = :old"),
            {"new": new, "c": country, "old": old},
        )
    for country, old, new in config_rewrites:
        conn.execute(
            sa.text(
                "UPDATE statutory_configs SET pt_state = :new WHERE pt_state = :old "
                "AND company_id IN (SELECT id FROM companies WHERE country = :c)"
            ),
            {"new": new, "c": country, "old": old},
        )


def downgrade() -> None:
    op.execute("DELETE FROM statutory_rates WHERE country <> 'IN'")
    op.execute("DELETE FROM pt_slabs WHERE country <> 'IN'")

    op.drop_index("ix_pt_slabs_country_state_effective_from", table_name="pt_slabs")
    op.create_index("ix_pt_slabs_state_effective_from", "pt_slabs", ["state", "effective_from"])

    op.execute("ALTER TABLE statutory_rates DROP CONSTRAINT ex_statutory_rates_no_overlap")
    op.execute(
        "ALTER TABLE statutory_rates ADD CONSTRAINT ex_statutory_rates_no_overlap "
        "EXCLUDE USING gist (scheme WITH =, "
        "(daterange(effective_from, coalesce(effective_to, 'infinity'::date), '[]')) WITH &&) "
        "WHERE (deleted_at IS NULL)"
    )
    op.drop_column("pt_slabs", "country")
    op.drop_column("statutory_rates", "country")
