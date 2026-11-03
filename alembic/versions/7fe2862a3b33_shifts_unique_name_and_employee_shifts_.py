"""shifts unique active name and employee shifts date check constraint

Revision ID: 7fe2862a3b33
Revises: c4d5e6f7a8b9
Create Date: 2026-11-03 11:19:38.212210

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7fe2862a3b33"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _platform_context(conn) -> None:
    # Under FORCE ROW LEVEL SECURITY alembic (ems_owner) sees no tenant rows unless the
    # platform-admin context is set, transaction-locally, before duplicate/constraint checks.
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))


def upgrade() -> None:
    conn = op.get_bind()
    _platform_context(conn)

    # Check existing duplicates on shifts lower(name) where deleted_at IS NULL
    dupes = conn.execute(
        sa.text(
            "SELECT company_id, lower(name), count(*) FROM shifts "
            "WHERE deleted_at IS NULL GROUP BY company_id, lower(name) "
            "HAVING count(*) > 1"
        )
    ).fetchall()
    if dupes:
        listing = ", ".join(f"company {r[0]}: '{r[1]}' (x{r[2]})" for r in dupes)
        raise RuntimeError(
            f"Cannot create unique index uq_shifts_company_lower_name: "
            f"duplicate active shift names exist: {listing}"
        )

    # Check existing violations of effective_to >= effective_from
    invalid_dates = conn.execute(
        sa.text(
            "SELECT id, company_id, employee_id, effective_from, effective_to "
            "FROM employee_shifts "
            "WHERE effective_to IS NOT NULL AND effective_to < effective_from"
        )
    ).fetchall()
    if invalid_dates:
        listing = ", ".join(
            f"id {r[0]} (company {r[1]}, employee {r[2]}: {r[3]} > {r[4]})"
            for r in invalid_dates
        )
        raise RuntimeError(
            f"Cannot add constraint ck_employee_shifts_effective_dates: "
            f"invalid date ranges exist: {listing}"
        )

    op.create_index(
        "uq_shifts_company_lower_name",
        "shifts",
        ["company_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_check_constraint(
        "ck_employee_shifts_effective_dates",
        "employee_shifts",
        sa.text("effective_to IS NULL OR effective_to >= effective_from"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    _platform_context(conn)

    op.drop_constraint(
        "ck_employee_shifts_effective_dates",
        "employee_shifts",
        type_="check",
    )
    op.drop_index("uq_shifts_company_lower_name", table_name="shifts")
