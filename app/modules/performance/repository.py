import uuid
from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate
from app.modules.performance.models import (
    CycleStatus,
    GoalStatus,
    PerformanceCycle,
    PerformanceGoal,
    PerformanceReview,
    PerformanceSummary,
    ReviewerRole,
)


class PerformanceCycleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, cycle_id: uuid.UUID, company_id: uuid.UUID) -> PerformanceCycle | None:
        return self.db.scalar(
            select(PerformanceCycle).where(
                PerformanceCycle.id == cycle_id,
                PerformanceCycle.company_id == company_id,
                PerformanceCycle.deleted_at.is_(None),
            )
        )

    def get_active_cycle(self, company_id: uuid.UUID) -> PerformanceCycle | None:
        return self.db.scalar(
            select(PerformanceCycle).where(
                PerformanceCycle.company_id == company_id,
                PerformanceCycle.status == CycleStatus.active,
                PerformanceCycle.deleted_at.is_(None),
            )
        )

    def list_cycles(
        self, company_id: uuid.UUID, page_params: PageParams, status: CycleStatus | None = None
    ) -> tuple[list[PerformanceCycle], int, int]:
        stmt = select(PerformanceCycle).where(
            PerformanceCycle.company_id == company_id,
            PerformanceCycle.deleted_at.is_(None),
        ).order_by(PerformanceCycle.created_at.desc())

        if status is not None:
            stmt = stmt.where(PerformanceCycle.status == status)

        return paginate(self.db, stmt, page_params)

    def create(self, **kwargs) -> PerformanceCycle:
        cycle = PerformanceCycle(**kwargs)
        self.db.add(cycle)
        self.db.flush()
        return cycle

    def update(self, cycle: PerformanceCycle, **kwargs) -> PerformanceCycle:
        for key, value in kwargs.items():
            setattr(cycle, key, value)
        self.db.flush()
        return cycle


class PerformanceGoalRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, goal_id: uuid.UUID, company_id: uuid.UUID) -> PerformanceGoal | None:
        return self.db.scalar(
            select(PerformanceGoal).where(
                PerformanceGoal.id == goal_id,
                PerformanceGoal.company_id == company_id,
                PerformanceGoal.deleted_at.is_(None),
            )
        )

    def list_by_employee_and_cycle(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, cycle_id: uuid.UUID
    ) -> list[PerformanceGoal]:
        return list(
            self.db.scalars(
                select(PerformanceGoal).where(
                    PerformanceGoal.company_id == company_id,
                    PerformanceGoal.employee_id == employee_id,
                    PerformanceGoal.cycle_id == cycle_id,
                    PerformanceGoal.deleted_at.is_(None),
                )
            ).all()
        )

    def create(self, **kwargs) -> PerformanceGoal:
        goal = PerformanceGoal(**kwargs)
        self.db.add(goal)
        self.db.flush()
        return goal

    def update(self, goal: PerformanceGoal, **kwargs) -> PerformanceGoal:
        for key, value in kwargs.items():
            setattr(goal, key, value)
        self.db.flush()
        return goal


class PerformanceReviewRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_goal_and_role(
        self, company_id: uuid.UUID, goal_id: uuid.UUID, reviewer_role: ReviewerRole
    ) -> PerformanceReview | None:
        return self.db.scalar(
            select(PerformanceReview).where(
                PerformanceReview.company_id == company_id,
                PerformanceReview.goal_id == goal_id,
                PerformanceReview.reviewer_role == reviewer_role,
                PerformanceReview.deleted_at.is_(None),
            )
        )

    def create(self, **kwargs) -> PerformanceReview:
        review = PerformanceReview(**kwargs)
        self.db.add(review)
        self.db.flush()
        return review


class PerformanceSummaryRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_employee_and_cycle(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, cycle_id: uuid.UUID
    ) -> PerformanceSummary | None:
        return self.db.scalar(
            select(PerformanceSummary).where(
                PerformanceSummary.company_id == company_id,
                PerformanceSummary.employee_id == employee_id,
                PerformanceSummary.cycle_id == cycle_id,
                PerformanceSummary.deleted_at.is_(None),
            )
        )

    def create(self, **kwargs) -> PerformanceSummary:
        summary = PerformanceSummary(**kwargs)
        self.db.add(summary)
        self.db.flush()
        return summary
