import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimeStampedBase(Base):
    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class TenantBase(TimeStampedBase):
    """Everything TimeStampedBase has, plus company_id. Tenant-scoped tables inherit this.

    If a model inherits TenantBase, it must also have an RLS policy in the same
    migration (Section 8) — the two go together, always.
    """

    __abstract__ = True

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


def tenant_table_names() -> list[str]:
    """Every table whose model inherits TenantBase, discovered from the class
    hierarchy rather than a maintained list — so the isolation suite's
    parametrized sweep (Spec 8.6) automatically covers a table added later
    with TenantBase but no RLS policy, with nothing to remember to update.
    Requires every module's models.py to have been imported first (main.py
    does this transitively via each module's router).
    """
    names: set[str] = set()

    def _walk(cls: type) -> None:
        for sub in cls.__subclasses__():
            if "__tablename__" in sub.__dict__:
                names.add(sub.__tablename__)  # type: ignore[attr-defined]
            _walk(sub)

    _walk(TenantBase)
    return sorted(names)
