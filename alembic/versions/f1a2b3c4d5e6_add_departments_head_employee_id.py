"""add departments head_employee_id fk

Revision ID: f1a2b3c4d5e6
Revises: b0a30daaecff
Create Date: 2026-09-01 18:50:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'b0a30daaecff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # departments.head_employee_id -> employees.id (Spec 7.3). Same shape as
    # the companies.approved_by / users cycle (7.2): departments was created
    # in WP-06 before employees existed, so this FK is added now, in a
    # follow-up migration, rather than in departments' own CREATE TABLE.
    op.create_foreign_key(
        'fk_departments_head_employee_id_employees',
        'departments',
        'employees',
        ['head_employee_id'],
        ['id'],
        use_alter=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_departments_head_employee_id_employees', 'departments', type_='foreignkey')
