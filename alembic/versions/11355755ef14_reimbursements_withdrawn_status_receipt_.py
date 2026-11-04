"""reimbursements withdrawn status receipt key and open claim indexes

Revision ID: 11355755ef14
Revises: 685f8636a5ca
Create Date: 2026-11-04 14:26:21.870218

5.6: a claim can be withdrawn (new enum value), its receipt is a real file (foreign key),
one receipt backs one open claim, and an employee cannot have two open claims for the same
date, type and amount (two partial unique indexes). Existing data that would break these
rules makes the migration stop with a message that says which rows; nothing is changed or
deleted silently.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11355755ef14'
down_revision: Union[str, Sequence[str], None] = '685f8636a5ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OPEN = "status IN ('pending', 'approved', 'paid')"


def _check_existing_rows(conn) -> None:
    # Under FORCE ROW LEVEL SECURITY alembic runs as ems_owner without a tenant context; set
    # the platform-admin context for this transaction so every company's rows are checked.
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))

    shared_receipts = conn.execute(
        sa.text(
            "SELECT company_id, file_object_id, count(*) FROM reimbursements "
            f"WHERE file_object_id IS NOT NULL AND {_OPEN} "
            "GROUP BY company_id, file_object_id HAVING count(*) > 1"
        )
    ).fetchall()
    if shared_receipts:
        listed = ", ".join(f"receipt {r[1]} used by {r[2]} open claims" for r in shared_receipts)
        raise RuntimeError(
            "Cannot create uq_reimbursements_open_receipt: duplicate receipts on open claims: "
            f"{listed}. Reject or correct all but one claim per receipt first."
        )

    duplicate_claims = conn.execute(
        sa.text(
            "SELECT employee_id, expense_date, type::text, amount, count(*) FROM reimbursements "
            f"WHERE {_OPEN} "
            "GROUP BY company_id, employee_id, expense_date, type, amount HAVING count(*) > 1"
        )
    ).fetchall()
    if duplicate_claims:
        listed = ", ".join(
            f"employee {r[0]} on {r[1]} ({r[2]}, {r[3]}) has {r[4]} open claims"
            for r in duplicate_claims
        )
        raise RuntimeError(
            "Cannot create uq_reimbursements_open_claim: duplicate open claims: "
            f"{listed}. Reject all but one of each first."
        )

    orphans = conn.execute(
        sa.text(
            "SELECT r.id, r.file_object_id FROM reimbursements r "
            "LEFT JOIN file_objects f ON f.id = r.file_object_id "
            "WHERE r.file_object_id IS NOT NULL AND f.id IS NULL"
        )
    ).fetchall()
    if orphans:
        listed = ", ".join(f"claim {r[0]} points at missing file {r[1]}" for r in orphans)
        raise RuntimeError(
            "Cannot add the receipt foreign key: these claims have a receipt that is not an "
            f"uploaded file: {listed}. Fix or clear the receipt on those claims first."
        )


def upgrade() -> None:
    _check_existing_rows(op.get_bind())

    # A new enum value cannot be used in the transaction that adds it, and cannot be added
    # inside a transaction block at all on older servers: run it in autocommit.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE reimbursement_status ADD VALUE IF NOT EXISTS 'withdrawn'")

    op.create_foreign_key(
        None, "reimbursements", "file_objects", ["file_object_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index(
        "uq_reimbursements_open_receipt",
        "reimbursements",
        ["company_id", "file_object_id"],
        unique=True,
        postgresql_where=sa.text(f"file_object_id IS NOT NULL AND {_OPEN}"),
    )
    op.create_index(
        "uq_reimbursements_open_claim",
        "reimbursements",
        ["company_id", "employee_id", "expense_date", "type", "amount"],
        unique=True,
        postgresql_where=sa.text(_OPEN),
    )


def downgrade() -> None:
    op.drop_index("uq_reimbursements_open_claim", table_name="reimbursements")
    op.drop_index("uq_reimbursements_open_receipt", table_name="reimbursements")
    op.drop_constraint("reimbursements_file_object_id_fkey", "reimbursements", type_="foreignkey")

    # PostgreSQL cannot drop one value from an enum: build the old type, move the column over
    # (a withdrawn claim becomes rejected, which also frees its receipt), drop the new type.
    op.execute("ALTER TYPE reimbursement_status RENAME TO reimbursement_status_with_withdrawn")
    op.execute("CREATE TYPE reimbursement_status AS ENUM ('pending', 'approved', 'rejected', 'paid')")
    op.execute(
        "ALTER TABLE reimbursements ALTER COLUMN status TYPE reimbursement_status USING "
        "(CASE WHEN status::text = 'withdrawn' THEN 'rejected' ELSE status::text END)"
        "::reimbursement_status"
    )
    op.execute("DROP TYPE reimbursement_status_with_withdrawn")
