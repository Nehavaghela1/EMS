"""add_company_locations_check_constraints

Revision ID: 564032fe6a10
Revises: 1a2b3c4d5e6f
Create Date: 2026-10-23 10:25:58.177894

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '564032fe6a10'
down_revision: Union[str, Sequence[str], None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Pre-checks for check constraints with loud error messages listing offending rows
    # Country regex check: country ~ '^[A-Z]{2}$'
    bad_countries = conn.execute(
        sa.text("SELECT id, country FROM company_locations WHERE country !~ '^[A-Z]{2}$'")
    ).fetchall()
    if bad_countries:
        bad_list = ", ".join(f"location {r[0]}: '{r[1]}'" for r in bad_countries)
        raise RuntimeError(
            f"Cannot create check constraint ck_company_locations_country: invalid rows found: {bad_list}"
        )

    # Coordinates pair check: (latitude IS NULL) = (longitude IS NULL)
    bad_pairs = conn.execute(
        sa.text(
            "SELECT id, latitude, longitude FROM company_locations "
            "WHERE (latitude IS NULL) != (longitude IS NULL)"
        )
    ).fetchall()
    if bad_pairs:
        bad_list = ", ".join(f"location {r[0]}: lat={r[1]}, lon={r[2]}" for r in bad_pairs)
        raise RuntimeError(
            f"Cannot create check constraint ck_company_locations_coordinates_pair: invalid rows found: {bad_list}"
        )

    # Latitude range check: latitude between -90 and 90
    bad_lats = conn.execute(
        sa.text(
            "SELECT id, latitude FROM company_locations "
            "WHERE latitude IS NOT NULL AND (latitude < -90 OR latitude > 90)"
        )
    ).fetchall()
    if bad_lats:
        bad_list = ", ".join(f"location {r[0]}: lat={r[1]}" for r in bad_lats)
        raise RuntimeError(
            f"Cannot create check constraint ck_company_locations_latitude_range: invalid rows found: {bad_list}"
        )

    # Longitude range check: longitude between -180 and 180
    bad_lons = conn.execute(
        sa.text(
            "SELECT id, longitude FROM company_locations "
            "WHERE longitude IS NOT NULL AND (longitude < -180 OR longitude > 180)"
        )
    ).fetchall()
    if bad_lons:
        bad_list = ", ".join(f"location {r[0]}: lon={r[1]}" for r in bad_lons)
        raise RuntimeError(
            f"Cannot create check constraint ck_company_locations_longitude_range: invalid rows found: {bad_list}"
        )

    # Geofence radius range check: geofence_radius_meters between 10 and 5000
    bad_radii = conn.execute(
        sa.text(
            "SELECT id, geofence_radius_meters FROM company_locations "
            "WHERE geofence_radius_meters < 10 OR geofence_radius_meters > 5000"
        )
    ).fetchall()
    if bad_radii:
        bad_list = ", ".join(f"location {r[0]}: radius={r[1]}" for r in bad_radii)
        raise RuntimeError(
            f"Cannot create check constraint ck_company_locations_radius_range: invalid rows found: {bad_list}"
        )

    # 2. Add check constraints
    op.create_check_constraint(
        "ck_company_locations_country",
        "company_locations",
        "country ~ '^[A-Z]{2}$'",
    )
    op.create_check_constraint(
        "ck_company_locations_coordinates_pair",
        "company_locations",
        "(latitude IS NULL) = (longitude IS NULL)",
    )
    op.create_check_constraint(
        "ck_company_locations_latitude_range",
        "company_locations",
        "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
    )
    op.create_check_constraint(
        "ck_company_locations_longitude_range",
        "company_locations",
        "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
    )
    op.create_check_constraint(
        "ck_company_locations_radius_range",
        "company_locations",
        "geofence_radius_meters >= 10 AND geofence_radius_meters <= 5000",
    )


def downgrade() -> None:
    op.drop_constraint("ck_company_locations_radius_range", "company_locations", type_="check")
    op.drop_constraint("ck_company_locations_longitude_range", "company_locations", type_="check")
    op.drop_constraint("ck_company_locations_latitude_range", "company_locations", type_="check")
    op.drop_constraint("ck_company_locations_coordinates_pair", "company_locations", type_="check")
    op.drop_constraint("ck_company_locations_country", "company_locations", type_="check")
