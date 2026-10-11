from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# --- Projects ---

class ProjectBase(BaseModel):
    name: str = Field(..., max_length=255)
    code: str = Field(..., max_length=50)
    description: str | None = None
    status: str = Field("planning", pattern="^(planning|active|on_hold|completed|cancelled)$")
    start_date: date | None = None
    deadline: date | None = None
    budget: Decimal | None = Field(None, ge=0)
    manager_id: UUID | None = None
    client_name: str | None = None

class ProjectCreate(ProjectBase):
    company_id: UUID | None = None

class ProjectUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    code: str | None = Field(None, max_length=50)
    description: str | None = None
    status: str | None = Field(None, pattern="^(planning|active|on_hold|completed|cancelled)$")
    start_date: date | None = None
    deadline: date | None = None
    budget: Decimal | None = Field(None, ge=0)
    manager_id: UUID | None = None
    client_name: str | None = None

class ProjectResponse(ProjectBase):
    id: UUID
    company_id: UUID
    company_name: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Project Members ---

class ProjectMemberCreate(BaseModel):
    employee_id: UUID
    role: str = Field("member", pattern="^(lead|member)$")
    joined_at: date | None = None

class ProjectMemberResponse(BaseModel):
    id: UUID
    company_id: UUID
    project_id: UUID
    employee_id: UUID
    role: str
    joined_at: date
    left_at: date | None = None
    created_at: datetime
    employee_name: str | None = None
    employee_email: str | None = None
    employee_code: str | None = None
    designation: str | None = None
    department_name: str | None = None

    class Config:
        from_attributes = True

# --- Tasks ---

class TaskBase(BaseModel):
    title: str = Field(..., max_length=255)
    description: str | None = None
    assigned_to: UUID | None = None
    priority: str = Field("medium", pattern="^(critical|high|medium|low)$")
    status: str = Field("todo", pattern="^(todo|in_progress|review|done)$")
    due_date: date | None = None
    estimated_hours: Decimal | None = Field(None, ge=0)

class TaskCreate(TaskBase):
    pass

class TaskUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    assigned_to: UUID | None = None
    priority: str | None = Field(None, pattern="^(critical|high|medium|low)$")
    status: str | None = Field(None, pattern="^(todo|in_progress|review|done)$")
    due_date: date | None = None
    estimated_hours: Decimal | None = Field(None, ge=0)

class TaskResponse(TaskBase):
    id: UUID
    company_id: UUID
    project_id: UUID
    completed_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    assigned_to_name: str | None = None
    assigned_to_email: str | None = None
    assigned_to_code: str | None = None
    assigned_to_designation: str | None = None

    class Config:
        from_attributes = True

# --- Task Comments ---

class TaskCommentCreate(BaseModel):
    comment: str = Field(..., min_length=1)

class TaskCommentResponse(BaseModel):
    id: UUID
    company_id: UUID
    task_id: UUID
    user_id: UUID
    comment: str
    created_at: datetime

    class Config:
        from_attributes = True

# --- Time Entries ---

class TimeEntryCreate(BaseModel):
    project_id: UUID
    task_id: UUID | None = None
    employee_id: UUID | None = None
    date: date
    hours: Decimal = Field(..., gt=0, le=24)
    description: str | None = None
    is_billable: bool = True
    is_overtime: bool = False
    overtime_multiplier: Decimal | None = None

class TimeEntryUpdate(BaseModel):
    task_id: UUID | None = None
    date: date | None = None
    hours: Decimal | None = Field(None, gt=0, le=24)
    description: str | None = None
    is_billable: bool | None = None
    status: str | None = Field(None, pattern="^(draft|submitted|approved|rejected)$")
    is_overtime: bool | None = None
    overtime_multiplier: Decimal | None = None

class TimeEntryResponse(BaseModel):
    id: UUID
    company_id: UUID
    project_id: UUID
    task_id: UUID | None = None
    employee_id: UUID
    date: date
    hours: Decimal
    description: str | None = None
    is_billable: bool
    status: str
    is_overtime: bool
    overtime_multiplier: Decimal | None = None
    overtime_amount: Decimal | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    employee_name: str | None = None
    employee_email: str | None = None
    employee_code: str | None = None
    task_title: str | None = None
    project_name: str | None = None
    project_code: str | None = None
    rejection_reason: str | None = None

    class Config:
        from_attributes = True

# --- Project Documents ---

class ProjectDocumentCreate(BaseModel):
    file_id: UUID | None = None
    file_object_id: UUID | None = None
    name: str | None = Field(None, max_length=255)
    file_name: str | None = Field(None, max_length=255)
    file_size: int = 0
    file_type: str = "application/octet-stream"
    description: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, values):
        if isinstance(values, dict):
            fid = values.get("file_id") or values.get("file_object_id")
            if not fid:
                raise ValueError("file_id or file_object_id is required")
            values["file_id"] = fid
            nm = values.get("name") or values.get("file_name")
            if not nm:
                raise ValueError("name or file_name is required")
            values["name"] = nm
        return values

class ProjectDocumentResponse(BaseModel):
    id: UUID
    company_id: UUID
    project_id: UUID
    file_id: UUID
    name: str
    file_size: int
    file_type: str
    description: str | None = None
    uploaded_by: UUID | None = None
    uploaded_by_name: str | None = None
    created_at: datetime
    download_url: str | None = None

    class Config:
        from_attributes = True

# --- Milestones ---

class MilestoneBase(BaseModel):
    title: str = Field(..., max_length=255)
    description: str | None = None
    due_date: date | None = None
    status: str = Field("pending", pattern="^(pending|in_progress|completed|missed)$")
    completion_percentage: Decimal = Field(Decimal("0.00"), ge=0, le=100)

class MilestoneCreate(MilestoneBase):
    pass

class MilestoneUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    due_date: date | None = None
    status: str | None = Field(None, pattern="^(pending|in_progress|completed|missed)$")
    completion_percentage: Decimal | None = Field(None, ge=0, le=100)

class MilestoneResponse(MilestoneBase):
    id: UUID
    company_id: UUID
    project_id: UUID
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Analytics / Summaries ---

class ProjectSummaryResponse(BaseModel):
    project: ProjectResponse
    total_tasks: int
    completed_tasks: int
    overdue_tasks: int
    completion_percentage: Decimal
    total_logged_hours: Decimal
    total_billable_hours: Decimal
    members_count: int
    milestones_count: int
    completed_milestones_count: int
    budget_spent: Decimal = Decimal("0.00")
    budget_remaining: Decimal | None = None
    delivery_health: str = "Not Started"
    approved_billable_hours: Decimal = Decimal("0.00")
    approved_logged_hours: Decimal = Decimal("0.00")

