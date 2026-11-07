"""employee bank accounts and payroll run payments

Revision ID: 44b1a0e02746
Revises: 5c2a0001a002
Create Date: 2026-11-05 17:56:56.601187

5.8. `employee_bank_accounts`: one ACTIVE row per employee (partial unique index); a change adds
a new row and deactivates the old one, so old rows stay as history. The account number is an
AES-256-GCM blob (column name `bank_account_number` in the associated data) with the last four
digits beside it.

`payroll_run_payments`: the payment lines of a run, written in the same save as its approval.
A line holds the holder, bank, encrypted number (column name `payment_account_number`), IFSC
and the amount; an employee who is left out has no bank fields and an `excluded_reason`.

Both are tenant tables: company_id, FORCE row level security and the tenant_isolation policy.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.rls import enable_rls


# revision identifiers, used by Alembic.
revision: str = '44b1a0e02746'
down_revision: Union[str, Sequence[str], None] = '5c2a0001a002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "employee_bank_accounts",
        *_base_columns(),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("account_holder", sa.String(length=100), nullable=False),
        sa.Column("bank_name", sa.String(length=100), nullable=False),
        sa.Column("account_number_enc", sa.LargeBinary(), nullable=False),
        sa.Column("account_last4", sa.String(length=4), nullable=False),
        sa.Column("ifsc_code", sa.String(length=11), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_employee_bank_accounts_company_id", "employee_bank_accounts", ["company_id"])
    op.create_index(
        "ix_employee_bank_accounts_employee_id", "employee_bank_accounts", ["employee_id"]
    )
    op.create_index(
        "uq_employee_bank_accounts_one_active",
        "employee_bank_accounts",
        ["employee_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    enable_rls("employee_bank_accounts")

    op.create_table(
        "payroll_run_payments",
        *_base_columns(),
        sa.Column("payroll_run_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("employee_code", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("account_holder", sa.String(length=100), nullable=True),
        sa.Column("bank_name", sa.String(length=100), nullable=True),
        sa.Column("account_number_enc", sa.LargeBinary(), nullable=True),
        sa.Column("account_last4", sa.String(length=4), nullable=True),
        sa.Column("ifsc_code", sa.String(length=11), nullable=True),
        sa.Column("excluded_reason", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payroll_run_id"], ["payroll_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payroll_run_id", "employee_id", name="uq_payroll_run_payments_run_employee"),
    )
    op.create_index("ix_payroll_run_payments_company_id", "payroll_run_payments", ["company_id"])
    enable_rls("payroll_run_payments")


def downgrade() -> None:
    op.drop_table("payroll_run_payments")
    op.drop_table("employee_bank_accounts")
