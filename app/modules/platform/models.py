import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
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


class Announcement(TenantBase):
    """RLS: Yes (Spec 7.8)."""

    __tablename__ = "announcements"
    __table_args__ = (
        Index("ix_announcements_company_id_expires_at", "company_id", "expires_at"),
        Index("ix_announcements_department_id", "department_id"),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    target_role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="all"
    )  # all, employee, manager, hr_admin
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )


class FileObject(TenantBase):
    """RLS: Yes (Spec 7.8, 9.9)."""

    __tablename__ = "file_objects"
    __table_args__ = (Index("ix_file_objects_company_id", "company_id"),)

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


RATE_SCHEME_GROUPS = ("epf_esi", "professional_tax", "income_tax", "social_security", "other")
RATE_CHECK_RESULTS = ("never", "baseline", "unchanged", "changed", "fetch_failed")
RATE_DRAFT_KINDS = ("statutory_rate", "pt_slabs", "tax_slabs", "no_numbers")
RATE_DRAFT_STATUSES = ("pending", "verified", "approved", "rejected")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class RateSource(TimeStampedBase):
    """RLS: No — platform data (5.9), like `statutory_rates`. A government page the daily
    check reads: when it changed, a draft is made. Scoped by the super_admin-only routes."""

    __tablename__ = "rate_sources"
    __table_args__ = (
        CheckConstraint(_in_list("scheme_group", RATE_SCHEME_GROUPS), name="ck_rate_sources_group"),
        CheckConstraint(_in_list("last_result", RATE_CHECK_RESULTS), name="ck_rate_sources_result"),
        CheckConstraint("interval_months BETWEEN 1 AND 24", name="ck_rate_sources_interval_months"),
        Index(
            "uq_rate_sources_country_state_group_url",
            "country",
            text("coalesce(state, '')"),
            "scheme_group",
            "source_url",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    country: Mapped[str] = mapped_column(String(2), nullable=False)
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scheme_group: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    interval_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    next_check_on: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_checked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_result: Mapped[str] = mapped_column(String(20), nullable=False, default="never")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RateChangeDraft(TimeStampedBase):
    """RLS: No — platform data (5.9). A proposed change to live rates: pending -> verified ->
    approved (or rejected). Only approval changes a rate row."""

    __tablename__ = "rate_change_drafts"
    __table_args__ = (
        CheckConstraint(_in_list("kind", RATE_DRAFT_KINDS), name="ck_rate_change_drafts_kind"),
        CheckConstraint(
            _in_list("status", RATE_DRAFT_STATUSES), name="ck_rate_change_drafts_status"
        ),
        Index("ix_rate_change_drafts_status", "status"),
    )

    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rate_sources.id"), nullable=True, index=True
    )
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    proposed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"url": ..., "fetched_at": ..., "hash": ...}] — what the page check read.
    fetched_sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sources_checked: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class RateReminderLog(TimeStampedBase):
    """RLS: No — platform data (5.9). One row per stale rate row and reminder, so the same
    row is reminded at most once per 30 days."""

    __tablename__ = "rate_reminder_log"
    __table_args__ = (Index("ix_rate_reminder_log_row", "row_kind", "row_id"),)

    row_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    row_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reminded_on: Mapped[date] = mapped_column(Date, nullable=False)


class EmployeeDocument(TenantBase):
    """RLS: Yes (Spec 7.8)."""

    __tablename__ = "employee_documents"
    __table_args__ = (Index("ix_employee_documents_employee_id", "employee_id"),)

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    file_object_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("file_objects.id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # kyc, offer_letter, passport, certificate, contract
    name: Mapped[str] = mapped_column(String(255), nullable=False)
