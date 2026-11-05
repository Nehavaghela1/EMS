"""esi daily wage exemption and payroll item salary segments

Revision ID: 5c2a0001a002
Revises: 5c2a0001a001
Create Date: 2026-11-05 10:00:00.000000

5.2: `statutory_rates.employee_exempt_daily_wage` (ESI only): an employee whose average daily
wage is at or below it pays no employee share. Existing rows get NULL (no exemption); the seed
sets 176.00 on the ESI row with its source note.

5.3 / 5.4: `payroll_items.salary_segments_json`, the salary rows a payroll month was paid at
(row id, from, to, days, ctc), so a payslip for a month with a mid-month raise shows both
parts. Items created before this migration have NULL (they were paid at one salary).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5c2a0001a002'
down_revision: Union[str, Sequence[str], None] = '5c2a0001a001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "statutory_rates",
        sa.Column("employee_exempt_daily_wage", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "payroll_items",
        sa.Column("salary_segments_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payroll_items", "salary_segments_json")
    op.drop_column("statutory_rates", "employee_exempt_daily_wage")
