import uuid
from datetime import date, datetime
from typing import Any, Literal, List, Optional
from pydantic import BaseModel, Field

# --- Existing Jobs / Audit / Dashboard / Notifications ---
class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "started", "success", "failure"]
    result: Any = None
    error: str | None = None

class JobQueuedResponse(BaseModel):
    job_id: str
    status: Literal["queued"] = "queued"

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

class DashboardResponse(BaseModel):
    role: str
    generated_at: datetime
    data: dict[str, Any]

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
    items: list[NotificationResponse]
    page: int
    limit: int
    total: int
    pages: int
    has_next: bool
    unread_count: int

class MarkAllReadResponse(BaseModel):
    marked_read: int


# ── Announcements (routes 122-124) ──────────────────────────────
class AnnouncementCreate(BaseModel):
    title: str = Field(..., max_length=255)
    content: str = Field(..., min_length=1)
    target_role: str = Field("all", pattern="^(all|employee|manager|hr_admin)$")
    expires_at: Optional[datetime] = None

class AnnouncementResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    content: str
    target_role: str
    created_by: Optional[uuid.UUID] = None
    expires_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── File Uploads & Signed URLs (routes 130-131) ─────────────────
class FileUploadResponse(BaseModel):
    file_object_id: uuid.UUID
    file_name: str
    file_type: str
    file_size: int

    model_config = {"from_attributes": True}

class SignedUrlResponse(BaseModel):
    file_object_id: uuid.UUID
    file_name: str
    url: str
    expires_in_seconds: int = 3600


# ── Employee Documents (routes 132-133) ─────────────────────────
class EmployeeDocumentCreate(BaseModel):
    employee_id: uuid.UUID
    file_object_id: uuid.UUID
    document_type: str = Field(..., max_length=100)
    name: str = Field(..., max_length=255)

class EmployeeDocumentResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    employee_id: uuid.UUID
    file_object_id: uuid.UUID
    document_type: str
    name: str
    created_at: datetime
    download_url: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Global Tenant Search (route 134) ────────────────────────────
class SearchResultItem(BaseModel):
    id: uuid.UUID
    type: Literal["employee", "project", "task"]
    title: str
    subtitle: Optional[str] = None
    url: str

class GlobalSearchResponse(BaseModel):
    query: str
    total_results: int
    results: List[SearchResultItem]
