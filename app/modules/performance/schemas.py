import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field

from app.modules.performance.models import (
    CycleStatus,
    CycleType,
    GoalStatus,
    ReviewerRole,
)


class PerformanceCycleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    cycle_type: CycleType = CycleType.annual
    start_date: date
    end_date: date
    self_review_deadline: date | None = None
    manager_review_deadline: date | None = None


class PerformanceCycleUpdateRequest(BaseModel):
    status: CycleStatus


class PerformanceCycleResponse(BaseModel):
    id: uuid.UUID
    name: str
    cycle_type: CycleType
    start_date: date
    end_date: date
    status: CycleStatus
    self_review_deadline: date | None
    manager_review_deadline: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GoalCreateItem(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    weightage: Decimal = Field(gt=0, le=100)
    target_value: str | None = None


class GoalsCreateRequest(BaseModel):
    cycle_id: uuid.UUID
    goals: list[GoalCreateItem] = Field(min_length=1)


class GoalUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    weightage: Decimal | None = None
    target_value: str | None = None
    status: GoalStatus | None = None


class PerformanceGoalResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    cycle_id: uuid.UUID
    title: str
    description: str | None
    weightage: Decimal
    target_value: str | None
    status: GoalStatus
    self_rating: Decimal | None
    self_comments: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SelfReviewRequest(BaseModel):
    rating: Decimal = Field(ge=1.0, le=5.0)
    comments: str | None = None


class ManagerReviewRequest(BaseModel):
    rating: Decimal = Field(ge=1.0, le=5.0)
    comments: str | None = None


class PerformanceReviewResponse(BaseModel):
    id: uuid.UUID
    goal_id: uuid.UUID
    reviewer_id: uuid.UUID
    reviewer_role: ReviewerRole
    rating: Decimal
    comments: str | None
    submitted_at: datetime

    model_config = {"from_attributes": True}


class SummaryFinalizeRequest(BaseModel):
    cycle_id: uuid.UUID
    overall_comments: str | None = None
    salary_revision_recommended: bool = False
    recommended_increment_percent: Decimal | None = None


class PerformanceSummaryResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    cycle_id: uuid.UUID
    final_rating: Decimal
    overall_comments: str | None
    salary_revision_recommended: bool
    recommended_increment_percent: Decimal | None
    reviewed_by: uuid.UUID
    finalized_at: datetime

    model_config = {"from_attributes": True}


class PerformanceReportResponse(BaseModel):
    active_cycle: PerformanceCycleResponse | None
    total_employees: int
    completed_reviews: int
    completion_rate_percent: Decimal
    rating_distribution: dict[str, int]
