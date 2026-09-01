import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantBase, TimeStampedBase


class IndustryPreset(TimeStampedBase):
    """RLS: No — global seed data (Spec 7.8). Applied automatically when a
    company is approved (WP-05)."""

    __tablename__ = "industry_presets"
    __table_args__ = (Index("uq_industry_presets_industry_name", "industry_name", unique=True),)

    industry_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # [{"name": "Engineering", "description": "..."}, ...] — applied to
    # `departments` on approval (WP-05/WP-06).
    departments_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    # [{"name": "Annual Leave", "code": "annual", "annual_allowance": 18, ...}, ...]
    # — applied to `leave_types` once that table exists (WP-10).
    leave_types_json: Mapped[list] = mapped_column(JSONB, nullable=False)


class AuditLog(TimeStampedBase):
    """RLS: No — append-only (Spec 7.8). Does NOT inherit TenantBase:
    `company_id` here is nullable (platform-level events, e.g. a super-admin
    approving a company, genuinely have no tenant), and TenantBase's
    `company_id` is NOT NULL. Scoping is therefore enforced in
    AuditRepository, not by a policy — see the spec's own "why no RLS here"
    note (7.8) for the full reasoning: the standard policy's WITH CHECK
    would evaluate to NULL for a NULL company_id and make those rows
    impossible to insert at all.

    Append-only is enforced at the database level in the same migration
    that creates this table (`REVOKE UPDATE, DELETE ... FROM ems_app`), not
    merely by convention — see tests/integration/test_audit_log_append_only.py.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_company_id_created_at", "company_id", "created_at"),
        Index("ix_audit_logs_action", "action"),
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Denormalized so the log survives user deletion (Spec 7.8).
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # Never contains a secret or full PII (Spec 7.8) — see AuditService.record's
    # docstring for how callers are expected to whitelist fields.
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class Notification(TenantBase):
    """RLS: Yes (Spec 7.8)."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_id_is_read", "user_id", "is_read"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
