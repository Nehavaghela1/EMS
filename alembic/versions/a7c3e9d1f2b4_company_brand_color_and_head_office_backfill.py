"""company brand colour column and head office backfill

Adds companies.brand_color (the accent colour picked in Settings > Company
Branding, previously kept only in one browser's localStorage) and gives every
company that still has no head office one, the same way approval does
(rule 1.6-3). Companies approved before locations existed had none.

Revision ID: a7c3e9d1f2b4
Revises: 39a987d23e60
Create Date: 2026-11-21 13:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e9d1f2b4"
down_revision: Union[str, Sequence[str], None] = "39a987d23e60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# One head office per company that has no primary location at all. The code
# keeps only A-Z, 0-9 and hyphens from the company code (old codes could hold
# other characters) and never collides: a company with no locations has no
# codes yet, and a company with locations but no head office gets the name
# and code only when they are still free.
BACKFILL_HEAD_OFFICE_SQL = """
INSERT INTO company_locations (
    id, company_id, name, code, address_line1, city, state, country, postal_code,
    is_primary, is_active, geofence_radius_meters, is_remote_exempt, created_at, updated_at
)
SELECT
    gen_random_uuid(), c.id, 'Head Office', sub.hq_code, c.address, c.city, c.state,
    CASE WHEN c.country ~ '^[A-Z]{2}$' THEN c.country ELSE 'IN' END,
    c.pincode, true, true, 150, false, now(), now()
FROM companies c
CROSS JOIN LATERAL (
    SELECT COALESCE(
        NULLIF(left(regexp_replace(upper(c.code), '[^A-Z0-9-]', '', 'g'), 17), ''), 'CO'
    ) || '-HQ' AS hq_code
) sub
WHERE c.deleted_at IS NULL
  AND c.status::text = 'active'
  AND NOT EXISTS (
      SELECT 1 FROM company_locations l
      WHERE l.company_id = c.id AND l.is_primary = true AND l.deleted_at IS NULL
  )
  AND NOT EXISTS (
      SELECT 1 FROM company_locations l
      WHERE l.company_id = c.id
        AND (lower(l.name) = 'head office' OR lower(l.code) = lower(sub.hq_code))
  );
"""


def upgrade() -> None:
    op.add_column("companies", sa.Column("brand_color", sa.String(length=7), nullable=True))
    conn = op.get_bind()
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))
    conn.execute(sa.text(BACKFILL_HEAD_OFFICE_SQL))


def downgrade() -> None:
    # The head office backfill is data and is kept; only the column is dropped.
    op.drop_column("companies", "brand_color")
