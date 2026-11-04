"""encrypt payout account number

Revision ID: 685f8636a5ca
Revises: 6966b6687e96
Create Date: 2026-11-04 14:26:04.231939

The company payout account number moves from a plain text column to an AES-256-GCM blob
(`payout_account_number_enc`) with the last four digits beside it (`payout_account_last4`).
Existing plain numbers are encrypted in this migration, so it needs ENCRYPTION_KEY whenever a
row holds a number; with no number stored it needs no key. The downgrade decrypts them back.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.encryption import (
    DecryptionFailedError,
    EncryptionUnavailableError,
    decrypt_field,
    encrypt_field,
)


# revision identifiers, used by Alembic.
revision: str = '685f8636a5ca'
down_revision: Union[str, Sequence[str], None] = '6966b6687e96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMN = "payout_account_number"


def _platform_admin(conn) -> None:
    # Under FORCE ROW LEVEL SECURITY alembic runs as ems_owner without a tenant context; set
    # the platform-admin context for this transaction so every company's row is visible.
    conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))


def _require_key(action: str) -> None:
    """Fail before anything is changed when rows need a key and there is none."""
    try:
        encrypt_field("0", company_id=uuid.UUID(int=0), column=_COLUMN)
    except EncryptionUnavailableError as exc:
        raise RuntimeError(
            f"Cannot {action} the payout account numbers: rows hold a number and ENCRYPTION_KEY "
            f"is not usable ({exc.message}) Set ENCRYPTION_KEY and run the migration again."
        ) from None


def upgrade() -> None:
    conn = op.get_bind()
    _platform_admin(conn)
    rows = conn.execute(
        sa.text(
            "SELECT id, company_id, payout_account_number FROM statutory_configs "
            "WHERE payout_account_number IS NOT NULL AND payout_account_number <> ''"
        )
    ).fetchall()
    if rows:
        _require_key("encrypt")

    op.add_column(
        "statutory_configs", sa.Column("payout_account_number_enc", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "statutory_configs", sa.Column("payout_account_last4", sa.String(length=4), nullable=True)
    )
    for row_id, company_id, plain in rows:
        conn.execute(
            sa.text(
                "UPDATE statutory_configs SET payout_account_number_enc = :enc, "
                "payout_account_last4 = :last4 WHERE id = :id"
            ),
            {
                "enc": encrypt_field(plain, company_id=company_id, column=_COLUMN),
                "last4": plain[-4:],
                "id": row_id,
            },
        )
    op.drop_column("statutory_configs", "payout_account_number")


def downgrade() -> None:
    conn = op.get_bind()
    _platform_admin(conn)
    rows = conn.execute(
        sa.text(
            "SELECT id, company_id, payout_account_number_enc FROM statutory_configs "
            "WHERE payout_account_number_enc IS NOT NULL"
        )
    ).fetchall()
    if rows:
        _require_key("decrypt")

    op.add_column(
        "statutory_configs", sa.Column("payout_account_number", sa.String(length=50), nullable=True)
    )
    for row_id, company_id, blob in rows:
        try:
            plain = decrypt_field(bytes(blob), company_id=company_id, column=_COLUMN)
        except DecryptionFailedError as exc:
            raise RuntimeError(
                f"Cannot decrypt the payout account number of statutory_configs row {row_id}: "
                f"{exc.message}"
            ) from None
        conn.execute(
            sa.text("UPDATE statutory_configs SET payout_account_number = :plain WHERE id = :id"),
            {"plain": plain, "id": row_id},
        )
    op.drop_column("statutory_configs", "payout_account_last4")
    op.drop_column("statutory_configs", "payout_account_number_enc")
