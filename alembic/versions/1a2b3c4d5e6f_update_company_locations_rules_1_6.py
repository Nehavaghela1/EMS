"""update_company_locations_rules_1_6

Revision ID: 1a2b3c4d5e6f
Revises: 06b3d2190d0c
Create Date: 2026-10-22 19:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = '06b3d2190d0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COUNTRY_MAP = {
    "india": "IN",
    "in": "IN",
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "us": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "gb": "GB",
    "canada": "CA",
    "ca": "CA",
    "australia": "AU",
    "au": "AU",
    "germany": "DE",
    "de": "DE",
    "france": "FR",
    "fr": "FR",
    "singapore": "SG",
    "sg": "SG",
    "united arab emirates": "AE",
    "uae": "AE",
    "ae": "AE",
}


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Normalise existing country values to 2-letter ISO
    rows = conn.execute(sa.text("SELECT id, country FROM company_locations")).fetchall()
    for row in rows:
        loc_id, raw_country = row[0], row[1]
        cleaned = raw_country.strip().lower() if raw_country else ""
        if cleaned in COUNTRY_MAP:
            iso_code = COUNTRY_MAP[cleaned]
            conn.execute(
                sa.text("UPDATE company_locations SET country = :iso WHERE id = :id"),
                {"iso": iso_code, "id": loc_id},
            )
        elif len(cleaned) == 2 and cleaned.isalpha():
            conn.execute(
                sa.text("UPDATE company_locations SET country = :iso WHERE id = :id"),
                {"iso": cleaned.upper(), "id": loc_id},
            )
        else:
            raise RuntimeError(
                f"Cannot normalise country value '{raw_country}' for location {loc_id}. Unknown country format."
            )

    # 2. Check for duplicate names inside each company (case-insensitively)
    name_dupes = conn.execute(
        sa.text(
            "SELECT company_id, lower(name), count(*) "
            "FROM company_locations "
            "GROUP BY company_id, lower(name) "
            "HAVING count(*) > 1"
        )
    ).fetchall()
    if name_dupes:
        dupe_list = ", ".join(f"company {r[0]}: '{r[1]}' (x{r[2]})" for r in name_dupes)
        raise RuntimeError(
            f"Cannot create unique index uq_company_locations_lower_name: existing duplicates found: {dupe_list}"
        )

    # 3. Check for duplicate codes inside each company (case-insensitively)
    code_dupes = conn.execute(
        sa.text(
            "SELECT company_id, lower(code), count(*) "
            "FROM company_locations "
            "GROUP BY company_id, lower(code) "
            "HAVING count(*) > 1"
        )
    ).fetchall()
    if code_dupes:
        dupe_list = ", ".join(f"company {r[0]}: '{r[1]}' (x{r[2]})" for r in code_dupes)
        raise RuntimeError(
            f"Cannot create unique index uq_company_locations_lower_code: existing duplicates found: {dupe_list}"
        )

    # 4. Check for multiple head offices inside any company
    hq_dupes = conn.execute(
        sa.text(
            "SELECT company_id, count(*) "
            "FROM company_locations "
            "WHERE is_primary = true "
            "GROUP BY company_id "
            "HAVING count(*) > 1"
        )
    ).fetchall()
    if hq_dupes:
        dupe_list = ", ".join(f"company {r[0]} has {r[1]} head offices" for r in hq_dupes)
        raise RuntimeError(
            f"Cannot create partial unique index uq_company_locations_primary_head_office: multiple head offices found: {dupe_list}"
        )

    # 5. Add is_active column with server default true
    op.add_column(
        'company_locations',
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )

    # 6. Drop old case-sensitive indexes
    op.drop_index('uq_company_locations_company_id_name', table_name='company_locations')
    op.drop_index('uq_company_locations_company_id_code', table_name='company_locations')

    # 7. Create partial unique head-office index
    op.create_index(
        'uq_company_locations_primary_head_office',
        'company_locations',
        ['company_id'],
        unique=True,
        postgresql_where=sa.text('is_primary = true'),
    )

    # 8. Create lower() unique indexes for name and code
    op.create_index(
        'uq_company_locations_lower_name',
        'company_locations',
        ['company_id', sa.literal_column('lower(name)')],
        unique=True,
    )
    op.create_index(
        'uq_company_locations_lower_code',
        'company_locations',
        ['company_id', sa.literal_column('lower(code)')],
        unique=True,
    )


def downgrade() -> None:
    # 1. Drop lower and head office indexes
    op.drop_index('uq_company_locations_lower_code', table_name='company_locations')
    op.drop_index('uq_company_locations_lower_name', table_name='company_locations')
    op.drop_index('uq_company_locations_primary_head_office', table_name='company_locations')

    # 2. Re-create original case-sensitive unique indexes
    op.create_index('uq_company_locations_company_id_code', 'company_locations', ['company_id', 'code'], unique=True)
    op.create_index('uq_company_locations_company_id_name', 'company_locations', ['company_id', 'name'], unique=True)

    # 3. Drop is_active column
    op.drop_column('company_locations', 'is_active')
