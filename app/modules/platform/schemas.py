import unicodedata
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


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
    action: str | None = Field(default=None, max_length=100)
    actor_email: str | None = Field(default=None, max_length=255)
    entity_type: str | None = Field(default=None, max_length=50)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot be after date_to.")
        return self


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
    department_id: uuid.UUID | None = None
    expires_at: datetime | None = None

    model_config = {"extra": "forbid"}

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Title must be a string.")
        s = v.strip()
        if not s or len(s) > 255:
            raise ValueError("Title must be between 1 and 255 characters after trimming.")
        return s

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Content must be a string.")
        s = v.strip()
        if not s or len(s) > 5000:
            raise ValueError("Content must be between 1 and 5000 characters after trimming.")
        for ch in s:
            if unicodedata.category(ch).startswith("C") and ch not in ("\n", "\r", "\t"):
                raise ValueError("Content cannot contain control characters.")
        return s

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware.")
        if v <= datetime.now(UTC):
            raise ValueError("expires_at must be in the future.")
        return v

    @model_validator(mode="after")
    def validate_department_target_role(self) -> Self:
        if self.department_id is not None and self.target_role != "all":
            raise ValueError("A department announcement must have target_role 'all'.")
        return self


class AnnouncementResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    content: str
    target_role: str
    department_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    expires_at: datetime | None = None
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
VALID_DOCUMENT_TYPES = {
    "id_proof",
    "address_proof",
    "kyc",
    "offer_letter",
    "contract",
    "certificate",
    "passport",
    "other",
}


class EmployeeDocumentResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    employee_id: uuid.UUID
    file_object_id: uuid.UUID
    document_type: str
    name: str
    created_at: datetime
    download_url: str | None = None

    model_config = {"from_attributes": True}


# ── Global Tenant Search (route 134) ────────────────────────────
class SearchResultItem(BaseModel):
    id: uuid.UUID
    type: Literal["employee", "project", "task"]
    title: str
    subtitle: str | None = None
    url: str | None = None


class GlobalSearchResponse(BaseModel):
    query: str
    total_results: int
    results: list[SearchResultItem]
