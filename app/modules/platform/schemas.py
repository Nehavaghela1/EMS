import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel


class JobStatusResponse(BaseModel):
    """Route 136: polls a Celery task's own result-backend state directly —
    no dedicated `jobs` table exists in the spec's schema (Section 7), and
    Celery's result backend (Redis) already persists exactly this."""

    job_id: str
    status: Literal["queued", "started", "success", "failure"]
    result: Any = None
    error: str | None = None


class JobQueuedResponse(BaseModel):
    """Route 129's 202 body — same tiny shape as time_leave's, kept local so
    this module doesn't reach across another module's schema file for one
    two-field response."""

    job_id: str
    status: Literal["queued"] = "queued"


# ── Audit logs (routes 128-129) ──────────────────────────────────
class AuditLogResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    actor_email: str | None
    action: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    details: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogExportRequest(BaseModel):
    action: str | None = None
    actor_email: str | None = None
    entity_type: str | None = None
    date_from: date | None = None
    date_to: date | None = None


# ── Dashboard (route 121) ────────────────────────────────────────
class DashboardResponse(BaseModel):
    """One wrapper for all four role shapes (Spec 11.10) rather than four
    parallel strict response models — `data`'s keys differ by `role`,
    documented on DashboardService.get_dashboard rather than enforced by
    distinct Pydantic classes (FastAPI Union responses add complexity this
    single-endpoint, four-shape payload doesn't need)."""

    role: str
    generated_at: datetime
    data: dict[str, Any]


# ── Notifications (routes 125-127) ───────────────────────────────
class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    message: str
    is_read: bool
    read_at: datetime | None
    action_url: str | None
    entity_type: str | None
    entity_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    """Wraps the standard Page envelope with the unread count the spec's
    deliverable asks for but doesn't assign its own route to — cheaper to
    compute alongside the list query than to add a fifth notifications
    route the spec's own route table (10.8) doesn't have room for."""

    items: list[NotificationResponse]
    page: int
    limit: int
    total: int
    pages: int
    has_next: bool
    unread_count: int


class MarkAllReadResponse(BaseModel):
    marked_read: int
