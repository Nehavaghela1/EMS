import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

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

    @model_validator(mode="after")
    def validate_dates(self) -> "PerformanceCycleCreateRequest":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date.")
        if self.self_review_deadline is not None:
            if not (self.start_date <= self.self_review_deadline <= self.end_date):
                raise ValueError("self_review_deadline must be between start_date and end_date.")
        if self.manager_review_deadline is not None:
            if self.self_review_deadline is not None:
                if not (self.self_review_deadline <= self.manager_review_deadline <= self.end_date):
                    raise ValueError(
                        "manager_review_deadline must be between self_review_deadline and end_date."
                    )
            elif not (self.start_date <= self.manager_review_deadline <= self.end_date):
                raise ValueError("manager_review_deadline must be between start_date and end_date.")
        return self


class PerformanceCycleUpdateRequest(BaseModel):
    status: CycleStatus | None = None
    self_review_deadline: date | None = None
    manager_review_deadline: date | None = None


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
    weightage: Decimal = Field(gt=Decimal("0"), le=Decimal("100"))
    target_value: str | None = None


class GoalsCreateRequest(BaseModel):
    cycle_id: uuid.UUID
    employee_id: uuid.UUID | None = None
    goals: list[GoalCreateItem] = Field(min_length=1)


class GoalProgressUpdateRequest(BaseModel):
    progress: int = Field(ge=0, le=100)
    notes: str | None = None


class GoalProgressHistoryResponse(BaseModel):
    id: uuid.UUID
    goal_id: uuid.UUID
    updated_by_id: uuid.UUID
    old_progress: int
    new_progress: int
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GoalUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    weightage: Decimal | None = Field(default=None, gt=Decimal("0"), le=Decimal("100"))
    target_value: str | None = None
    status: GoalStatus | None = None
    reason: str | None = None


class PerformanceGoalResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    cycle_id: uuid.UUID
    title: str
    description: str | None
    weightage: Decimal
    target_value: str | None
    status: GoalStatus
    progress: int = 0
    self_rating: Decimal | None
    self_comments: str | None
    self_review_status: str | None = None
    self_review_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SelfReviewRequest(BaseModel):
    rating: Decimal = Field(ge=Decimal("1.0"), le=Decimal("5.0"))
    comments: str | None = Field(default=None, max_length=2000)


class ManagerReviewRequest(BaseModel):
    rating: Decimal = Field(ge=Decimal("1.0"), le=Decimal("5.0"))
    comments: str | None = Field(default=None, max_length=2000)


class ReviewReopenRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class PerformanceReviewResponse(BaseModel):
    id: uuid.UUID
    goal_id: uuid.UUID
    reviewer_id: uuid.UUID
    reviewer_role: ReviewerRole
    rating: Decimal
    comments: str | None
    submitted_at: datetime
    status: str = "submitted"
    reopened_at: datetime | None = None
    reopen_reason: str | None = None

    model_config = {"from_attributes": True}


class SummaryFinalizeRequest(BaseModel):
    cycle_id: uuid.UUID
    overall_comments: str | None = None
    salary_revision_recommended: bool = False
    # An increment recommendation is a raise: 0 to 100 percent, 2 decimals (BUG-064).
    recommended_increment_percent: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2
    )


class PerformanceSummaryDetailResponse(BaseModel):
    employee_id: uuid.UUID
    cycle_id: uuid.UUID
    goals: list[PerformanceGoalResponse]
    weighted_progress: Decimal
    weighted_manager_rating: Decimal | None = None
    manager_review_status: str
    completed_reviews_count: int
    on_pip: bool
    final_rating: Decimal | None = None
    overall_comments: str | None = None
    finalized_at: datetime | None = None


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


# --- Performance Improvement Plan (PIP) Schemas ---
class PIPCreateRequest(BaseModel):
    employee_id: uuid.UUID
    mentor_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    milestones_kpis: str | None = None
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _check_dates_and_mentor(self) -> "PIPCreateRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date.")  # BUG-067
        if self.mentor_id is not None and self.mentor_id == self.employee_id:
            raise ValueError("An employee cannot be their own PIP mentor.")  # BUG-066
        return self


class PIPEvaluateRequest(BaseModel):
    outcome: str = Field(pattern="^(passed|failed|cancelled)$")  # passed, failed, cancelled
    outcome_notes: str | None = None


class PIPExtendRequest(BaseModel):
    new_end_date: date
    reason: str = Field(min_length=1, max_length=500)


class PIPCheckInCreateRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class PIPCheckInResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    pip_id: uuid.UUID
    note: str
    created_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class PerformancePIPResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str | None = None
    employee_code: str | None = None
    mentor_id: uuid.UUID | None = None
    mentor_name: str | None = None
    title: str
    description: str | None
    milestones_kpis: str | None
    start_date: date
    end_date: date
    previous_end_date: date | None = None
    extension_reason: str | None = None
    status: str
    outcome_notes: str | None
    evaluated_at: datetime | None
    evaluated_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PIPSeparationDecisionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    decision: str  # separate, extend, retain
    last_working_date: date | None = None
    notice_choice: str | None = None  # served, waived, pay_in_lieu
    new_end_date: date | None = None
    reason: str | None = None


class PIPSeparationDecisionResponse(BaseModel):
    id: uuid.UUID
    pip_id: uuid.UUID
    decision: str
    decided_by: uuid.UUID
    decided_at: datetime
    last_working_date: date | None = None
    notice_choice: str | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}
