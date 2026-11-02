"""holiday date unique only while active; leave type name and code unique ignoring case

Revision ID: c4d5e6f7a8b9
Revises: a1b2c3d4e5f6
Create Date: 2026-11-02 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _platform_context(conn) -> None:
    # Under FORCE ROW LEVEL SECURITY alembic (ems_owner) sees no tenant rows unless the
    # platform-admin context is set, transaction-locally, before the duplicate checks.
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))


def upgrade() -> None:
    conn = op.get_bind()
    _platform_context(conn)

    for column in ("name", "code"):
        dupes = conn.execute(
            sa.text(
                f"SELECT company_id, lower({column}), count(*) FROM leave_types "
                f"WHERE deleted_at IS NULL GROUP BY company_id, lower({column}) "
                "HAVING count(*) > 1"
            )
        ).fetchall()
        if dupes:
            listing = ", ".join(f"company {r[0]}: '{r[1]}' (x{r[2]})" for r in dupes)
            raise RuntimeError(
                f"Cannot create unique index uq_leave_types_company_lower_{column}: "
                f"duplicate leave type {column}s exist: {listing}"
            )

    # Holidays: the old constraint also counted soft-deleted rows, so a deleted holiday
    # blocked its date forever. The new index only covers active rows.
    op.drop_constraint("uq_holidays_company_id_date_department_id", "holidays", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_holidays_company_date_department ON holidays "
        "(company_id, date, applies_to_department_id) NULLS NOT DISTINCT "
        "WHERE deleted_at IS NULL"
    )

    op.drop_constraint("uq_leave_types_company_id_code", "leave_types", type_="unique")
    op.create_index(
        "uq_leave_types_company_lower_code",
        "leave_types",
        ["company_id", sa.literal_column("lower(code)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_leave_types_company_lower_name",
        "leave_types",
        ["company_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    _platform_context(conn)

    holiday_dupes = conn.execute(
        sa.text(
            "SELECT company_id, date, count(*) FROM holidays "
            "GROUP BY company_id, date, applies_to_department_id "
            "HAVING count(*) > 1"
        )
    ).fetchall()
    if holiday_dupes:
        listing = ", ".join(f"company {r[0]}: {r[1]} (x{r[2]})" for r in holiday_dupes)
        raise RuntimeError(
            "Cannot restore uq_holidays_company_id_date_department_id: duplicate holidays "
            f"(including soft-deleted ones) exist: {listing}"
        )
    type_dupes = conn.execute(
        sa.text(
            "SELECT company_id, code, count(*) FROM leave_types "
            "GROUP BY company_id, code HAVING count(*) > 1"
        )
    ).fetchall()
    if type_dupes:
        listing = ", ".join(f"company {r[0]}: '{r[1]}' (x{r[2]})" for r in type_dupes)
        raise RuntimeError(
            "Cannot restore uq_leave_types_company_id_code: duplicate leave type codes "
            f"(including soft-deleted ones) exist: {listing}"
        )

    op.drop_index("uq_leave_types_company_lower_name", table_name="leave_types")
    op.drop_index("uq_leave_types_company_lower_code", table_name="leave_types")
    op.create_unique_constraint(
        "uq_leave_types_company_id_code", "leave_types", ["company_id", "code"]
    )

    op.execute("DROP INDEX uq_holidays_company_date_department")
    op.execute(
        "ALTER TABLE holidays ADD CONSTRAINT uq_holidays_company_id_date_department_id "
        "UNIQUE NULLS NOT DISTINCT (company_id, date, applies_to_department_id)"
    )
