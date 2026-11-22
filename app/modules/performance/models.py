import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy import (
    Numeric as SANumeric,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import TenantBase


class CycleType(str, enum.Enum):
    annual = "annual"
    half_yearly = "half_yearly"
    quarterly = "quarterly"


class CycleStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    closed = "closed"


class GoalStatus(str, enum.Enum):
    draft = "draft"
    in_progress = "in_progress"
    completed = "completed"


class ReviewerRole(str, enum.Enum):
    self = "self"
    manager = "manager"
    peer = "peer"


class PerformanceCycle(TenantBase):
    """RLS: Yes (Spec 7.5)."""

    __tablename__ = "performance_cycles"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    cycle_type: Mapped[CycleType] = mapped_column(
        SAEnum(CycleType, name="cycle_type"), nullable=False, default=CycleType.annual
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[CycleStatus] = mapped_column(
        SAEnum(CycleStatus, name="cycle_status"), nullable=False, default=CycleStatus.draft
    )
    self_review_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    manager_review_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)

    goals: Mapped[list["PerformanceGoal"]] = relationship(
        "PerformanceGoal", cascade="all, delete-orphan", passive_deletes=True
    )


class PerformanceGoal(TenantBase):
    """RLS: Yes (Spec 7.5)."""

    __tablename__ = "performance_goals"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("performance_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weightage: Mapped[Decimal] = mapped_column(SANumeric(5, 2), nullable=False)
    target_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[GoalStatus] = mapped_column(
        SAEnum(GoalStatus, name="goal_status"), nullable=False, default=GoalStatus.draft
    )
    progress: Mapped[int] = mapped_column(nullable=False, default=0)
    self_rating: Mapped[Decimal | None] = mapped_column(SANumeric(3, 1), nullable=True)
    self_comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    reviews: Mapped[list["PerformanceReview"]] = relationship(
        "PerformanceReview", cascade="all, delete-orphan", passive_deletes=True
    )
    progress_history: Mapped[list["PerformanceGoalProgressHistory"]] = relationship(
        "PerformanceGoalProgressHistory", cascade="all, delete-orphan", passive_deletes=True
    )


class PerformanceGoalProgressHistory(TenantBase):
    """RLS: Yes."""

    __tablename__ = "performance_goal_progress_history"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("performance_goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    updated_by_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    old_progress: Mapped[int] = mapped_column(nullable=False)
    new_progress: Mapped[int] = mapped_column(nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PerformanceReview(TenantBase):
    """RLS: Yes (Spec 7.5)."""

    __tablename__ = "performance_reviews"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "goal_id",
            "reviewer_role",
            name="uq_performance_reviews_goal_reviewer_role",
        ),
    )

    goal_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("performance_goals.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    reviewer_role: Mapped[ReviewerRole] = mapped_column(
        SAEnum(ReviewerRole, name="reviewer_role"), nullable=False
    )
    rating: Mapped[Decimal] = mapped_column(SANumeric(3, 1), nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=SANumeric() if False else None
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted")
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class PerformanceSummary(TenantBase):
    """RLS: Yes (Spec 7.5)."""

    __tablename__ = "performance_summaries"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "employee_id", "cycle_id", name="uq_performance_summaries_employee_cycle"
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("performance_cycles.id"), nullable=False
    )
    final_rating: Mapped[Decimal] = mapped_column(SANumeric(3, 1), nullable=False)
    overall_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    salary_revision_recommended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    recommended_increment_percent: Mapped[Decimal | None] = mapped_column(
        SANumeric(5, 2), nullable=True
    )
    reviewed_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PIPStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    passed = "passed"
    failed = "failed"
    cancelled = "cancelled"
    extended = "extended"


class PerformancePIP(TenantBase):
    """Performance Improvement Plan (PIP)."""

    __tablename__ = "performance_pips"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    mentor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    milestones_kpis: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    previous_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    extension_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    outcome_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PerformancePIPCheckIn(TenantBase):
    """Performance Improvement Plan Check-in Notes. RLS: Yes (Spec 7.5)."""

    __tablename__ = "performance_pip_checkins"

    pip_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("performance_pips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    note: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class SeparationDecision(TenantBase):
    """HR Decision on Failed PIP. RLS: Yes."""

    __tablename__ = "separation_decisions"

    pip_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("performance_pips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    decided_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_working_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_choice: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
