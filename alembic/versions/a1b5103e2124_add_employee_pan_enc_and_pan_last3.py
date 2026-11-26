"""add_employee_pan_enc_and_pan_last3

Revision ID: a1b5103e2124
Revises: 11f39252e8ac
Create Date: 2026-11-26 23:35:10.133368

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b5103e2124'
down_revision: Union[str, Sequence[str], None] = '11f39252e8ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("employees")]
    if "pan_enc" not in columns:
        op.add_column("employees", sa.Column("pan_enc", sa.LargeBinary(), nullable=True))
    if "pan_last3" not in columns:
        op.add_column("employees", sa.Column("pan_last3", sa.String(length=3), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("employees")]
    if "pan_last3" in columns:
        op.drop_column("employees", "pan_last3")
    if "pan_enc" in columns:
        op.drop_column("employees", "pan_enc")
