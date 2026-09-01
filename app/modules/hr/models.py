import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantBase


class Department(TenantBase):
    """RLS: Yes (Spec 7.3)."""

    __tablename__ = "departments"
    __table_args__ = (Index("uq_departments_company_id_name", "company_id", "name", unique=True),)

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `employees` doesn't exist yet (WP-07). Plain nullable UUID, no FK, for
    # now — added via a follow-up migration once that table exists, the same
    # pattern the companies/users FK cycle uses (7.2), generalized to "the
    # target table doesn't exist yet" rather than a true cycle.
    head_employee_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
