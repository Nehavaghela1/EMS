from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field

# --- Projects ---

class ProjectBase(BaseModel):
    name: str = Field(..., max_length=255)
    code: str = Field(..., max_length=50)
    description: Optional[str] = None
    status: str = Field("planning", pattern="^(planning|active|on_hold|completed|cancelled)$")
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    budget: Optional[Decimal] = Field(None, ge=0)
    manager_id: Optional[UUID] = None
    client_name: Optional[str] = None

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(planning|active|on_hold|completed|cancelled)$")
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    budget: Optional[Decimal] = Field(None, ge=0)
    manager_id: Optional[UUID] = None
    client_name: Optional[str] = None

class ProjectResponse(ProjectBase):
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Project Members ---

class ProjectMemberCreate(BaseModel):
    employee_id: UUID
    role: str = Field("member", pattern="^(lead|member)$")
    joined_at: Optional[date] = None

class ProjectMemberResponse(BaseModel):
    id: UUID
    company_id: UUID
    project_id: UUID
    employee_id: UUID
    role: str
    joined_at: date
    left_at: Optional[date] = None
    created_at: datetime

    class Config:
        from_attributes = True

# --- Tasks ---

class TaskBase(BaseModel):
    title: str = Field(..., max_length=255)
    description: Optional[str] = None
    assigned_to: Optional[UUID] = None
    priority: str = Field("medium", pattern="^(critical|high|medium|low)$")
    status: str = Field("todo", pattern="^(todo|in_progress|review|done)$")
    due_date: Optional[date] = None
    estimated_hours: Optional[Decimal] = Field(None, ge=0)

class TaskCreate(TaskBase):
    pass

class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    assigned_to: Optional[UUID] = None
    priority: Optional[str] = Field(None, pattern="^(critical|high|medium|low)$")
    status: Optional[str] = Field(None, pattern="^(todo|in_progress|review|done)$")
    due_date: Optional[date] = None
    estimated_hours: Optional[Decimal] = Field(None, ge=0)

class TaskResponse(TaskBase):
    id: UUID
    company_id: UUID
    project_id: UUID
    completed_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

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
    task_id: Optional[UUID] = None
    date: date
    hours: Decimal = Field(..., gt=0, le=24)
    description: Optional[str] = None
    is_billable: bool = True

class TimeEntryUpdate(BaseModel):
    task_id: Optional[UUID] = None
    date: Optional[date] = None
    hours: Optional[Decimal] = Field(None, gt=0, le=24)
    description: Optional[str] = None
    is_billable: Optional[bool] = None
    status: Optional[str] = Field(None, pattern="^(draft|submitted|approved|rejected)$")

class TimeEntryResponse(BaseModel):
    id: UUID
    company_id: UUID
    project_id: UUID
    task_id: Optional[UUID] = None
    employee_id: UUID
    date: date
    hours: Decimal
    description: Optional[str] = None
    is_billable: bool
    status: str
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Milestones ---

class MilestoneBase(BaseModel):
    title: str = Field(..., max_length=255)
    description: Optional[str] = None
    due_date: Optional[date] = None
    status: str = Field("pending", pattern="^(pending|in_progress|completed|missed)$")
    completion_percentage: Decimal = Field(Decimal("0.00"), ge=0, le=100)

class MilestoneCreate(MilestoneBase):
    pass

class MilestoneUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    due_date: Optional[date] = None
    status: Optional[str] = Field(None, pattern="^(pending|in_progress|completed|missed)$")
    completion_percentage: Optional[Decimal] = Field(None, ge=0, le=100)

class MilestoneResponse(MilestoneBase):
    id: UUID
    company_id: UUID
    project_id: UUID
    completed_at: Optional[datetime] = None
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
