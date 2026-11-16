import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.pagination import PageParams
from app.core.time import utcnow
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole
from app.modules.performance.models import (
    CycleStatus,
    GoalStatus,
    PerformanceCycle,
    PerformanceGoal,
    PerformancePIP,
    PerformanceReview,
    PerformanceSummary,
    ReviewerRole,
)
from app.modules.performance.repository import (
    PerformanceCycleRepository,
    PerformanceGoalRepository,
    PerformancePIPRepository,
    PerformanceReviewRepository,
    PerformanceSummaryRepository,
)
from app.modules.performance.schemas import (
    GoalProgressUpdateRequest,
    GoalsCreateRequest,
    GoalUpdateRequest,
    ManagerReviewRequest,
    PerformanceCycleCreateRequest,
    PerformanceCycleResponse,
    PerformanceCycleUpdateRequest,
    PerformanceGoalResponse,
    PerformancePIPResponse,
    PerformanceReportResponse,
    PIPCreateRequest,
    PIPEvaluateRequest,
    SelfReviewRequest,
    SummaryFinalizeRequest,
)
from app.modules.platform.service import AuditService


class WeightageSumError(AppError):
    status_code = 400
    code = "invalid_weightage_sum"


class PerformanceService:
    def __init__(self, db: Session):
        self.db = db
        self.cycle_repo = PerformanceCycleRepository(db)
        self.goal_repo = PerformanceGoalRepository(db)
        self.review_repo = PerformanceReviewRepository(db)
        self.summary_repo = PerformanceSummaryRepository(db)
        self.pip_repo = PerformancePIPRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.audit = AuditService(db)

    # 1. Cycles
    def create_cycle(
        self, company_id: uuid.UUID, data: PerformanceCycleCreateRequest, actor: User
    ) -> PerformanceCycle:
        # Check date overlap
        clash = self.cycle_repo.get_overlapping_cycle(
            company_id=company_id, start_date=data.start_date, end_date=data.end_date
        )
        if clash is not None:
            raise ConflictError(f"Cycle dates clash with existing cycle '{clash.name}'.")

        cycle = self.cycle_repo.create(
            company_id=company_id,
            name=data.name,
            cycle_type=data.cycle_type,
            start_date=data.start_date,
            end_date=data.end_date,
            status=CycleStatus.draft,
            self_review_deadline=data.self_review_deadline,
            manager_review_deadline=data.manager_review_deadline,
        )
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PERFORMANCE_CYCLE_CREATED",
            entity_type="performance_cycle",
            entity_id=cycle.id,
            details={"name": cycle.name, "type": cycle.cycle_type.value},
        )
        self.db.commit()
        return cycle

    def update_cycle(
        self,
        company_id: uuid.UUID,
        cycle_id: uuid.UUID,
        data: PerformanceCycleUpdateRequest,
        actor: User,
    ) -> PerformanceCycle:
        cycle = self.cycle_repo.get_by_id(cycle_id, company_id)
        if cycle is None:
            raise NotFoundError("Performance cycle not found.")

        # Status transition checks
        if cycle.status == CycleStatus.closed:
            raise ConflictError("A closed performance cycle cannot be reopened or edited.")

        if cycle.status == CycleStatus.draft:
            if data.status == CycleStatus.closed:
                raise ConflictError(
                    "A draft cycle cannot be closed directly; it must be activated first."
                )
            if data.status == CycleStatus.draft:
                pass  # no-op
            elif data.status == CycleStatus.active:
                # Enforce single active cycle
                existing_active = self.cycle_repo.get_active_cycle(company_id)
                if existing_active is not None and existing_active.id != cycle.id:
                    raise ConflictError(
                        f"Cannot activate cycle: '{existing_active.name}' is already active."
                    )
        elif cycle.status == CycleStatus.active:
            if data.status == CycleStatus.draft:
                raise ConflictError("An active performance cycle cannot be reverted to draft.")

        self.cycle_repo.update(cycle, status=data.status)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action=f"PERFORMANCE_CYCLE_{data.status.value.upper()}",
            entity_type="performance_cycle",
            entity_id=cycle.id,
            details={"status": data.status.value},
        )
        self.db.commit()

        # Notification after commit on activation
        if data.status == CycleStatus.active:
            from sqlalchemy import select

            from app.modules.hr.models import Employee
            from app.modules.platform.models import Notification

            employees = list(
                self.db.scalars(
                    select(Employee).where(
                        Employee.company_id == company_id,
                        Employee.is_active.is_(True),
                        Employee.deleted_at.is_(None),
                    )
                ).all()
            )
            for emp in employees:
                if emp.user_id:
                    notif = Notification(
                        company_id=company_id,
                        user_id=emp.user_id,
                        type="performance_cycle_activated",
                        title=f"Performance Cycle Activated: {cycle.name}",
                        message=(
                            f"Performance cycle '{cycle.name}' is now active. "
                            "Please set your goals."
                        ),
                    )
                    self.db.add(notif)
            self.db.commit()

        return cycle

    def list_cycles(
        self, company_id: uuid.UUID, page_params: PageParams, status: CycleStatus | None = None
    ) -> tuple[list[PerformanceCycle], int, int]:
        return self.cycle_repo.list_cycles(company_id, page_params, status=status)

    # 2. Goals
    def create_goals(
        self, company_id: uuid.UUID, data: GoalsCreateRequest, actor: User
    ) -> list[PerformanceGoal]:
        cycle = self.cycle_repo.get_by_id(data.cycle_id, company_id)
        if cycle is None:
            raise NotFoundError("Performance cycle not found.")
        if cycle.status != CycleStatus.active:
            raise ConflictError("Goals can only be submitted for active performance cycles.")

        emp = None
        if data.employee_id:
            emp = self.employee_repo.get_by_id(data.employee_id, company_id)
            if emp is None:
                raise NotFoundError("Specified employee profile not found.")
        else:
            emp = self.employee_repo.get_by_user_id(company_id, actor.id)
            if emp is None:
                raise NotFoundError(
                    "Employee profile not found for current user. Admin or manager "
                    "accounts must select an employee profile when creating goals."
                )

        # Scoping permission check
        # Employee sets own; manager sets for people in reporting chain; HR any; others 403
        current_emp = self.employee_repo.get_by_user_id(company_id, actor.id)
        is_hr = actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin)
        if not is_hr:
            if current_emp is None:
                raise ForbiddenError("You do not have permission to set goals.")
            if current_emp.id == emp.id:
                pass  # Employee setting own goals
            elif actor.role == UserRole.manager:
                from app.core.approval_authority import can_approve_for

                try:
                    can_approve_for(self.db, actor, emp)
                except Exception as err:
                    raise ForbiddenError(
                        "Managers can only set goals for employees in their reporting chain."
                    ) from err
            else:
                raise ForbiddenError("Employees can only set goals for themselves.")

        # Check total weightages sum <= 100
        existing_goals = self.goal_repo.list_by_employee_and_cycle(company_id, emp.id, cycle.id)
        current_sum = sum((g.weightage for g in existing_goals), Decimal("0.00"))
        new_items_sum = sum((item.weightage for item in data.goals), Decimal("0.00"))
        if current_sum + new_items_sum > Decimal("100.00"):
            raise WeightageSumError(
                f"Total goal weightage cannot exceed 100.00%. "
                f"Current sum: {current_sum}%, attempting to add: {new_items_sum}%"
            )

        created = []
        for item in data.goals:
            goal = self.goal_repo.create(
                company_id=company_id,
                employee_id=emp.id,
                cycle_id=cycle.id,
                title=item.title,
                description=item.description,
                weightage=item.weightage,
                target_value=item.target_value,
                status=GoalStatus.in_progress,
                progress=0,
            )
            created.append(goal)
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="PERFORMANCE_GOAL_CREATED",
                entity_type="performance_goal",
                entity_id=goal.id,
                details={"title": goal.title, "weightage": str(goal.weightage)},
            )

        self.db.commit()

        # If someone else created/modified goals for the employee, notify the manager
        if current_emp is None or current_emp.id != emp.id:
            if emp.reporting_manager_id:
                mgr = self.employee_repo.get_by_id(emp.reporting_manager_id, company_id)
                if mgr and mgr.user_id:
                    from app.modules.platform.models import Notification

                    notif = Notification(
                        company_id=company_id,
                        user_id=mgr.user_id,
                        type="employee_goals_updated",
                        title="Employee Goals Updated",
                        message=(
                            f"Goals for employee {emp.first_name} {emp.last_name} "
                            f"were updated by {actor.email}."
                        ),
                    )
                    self.db.add(notif)
                    self.db.commit()

        return created

    def update_goal(
        self,
        company_id: uuid.UUID,
        goal_id: uuid.UUID,
        data: GoalUpdateRequest,
        actor: User,
    ) -> PerformanceGoal:
        goal = self.goal_repo.get_by_id(goal_id, company_id)
        if goal is None:
            raise NotFoundError("Performance goal not found.")

        # Cycle lock check
        cycle = self.cycle_repo.get_by_id(goal.cycle_id, company_id)
        if cycle is None or cycle.status != CycleStatus.active:
            raise ConflictError(
                "Goals cannot be modified when the performance cycle is not active."
            )

        # Self-review submission freeze check
        existing_self_rev = self.review_repo.get_by_goal_and_role(
            company_id, goal.id, ReviewerRole.self
        )
        if existing_self_rev is not None:
            raise ConflictError("Goals are locked after self-review has been submitted.")

        emp = self.employee_repo.get_by_user_id(company_id, actor.id)
        is_owner = emp and goal.employee_id == emp.id
        is_hr = actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin)

        if not (is_owner or is_hr):
            raise ForbiddenError("You do not have permission to update this performance goal.")

        # Status rules: completed goal changed only by HR with reason
        if goal.status == GoalStatus.completed and not is_hr:
            raise ConflictError("Completed goals can only be modified by HR.")

        if goal.status == GoalStatus.completed and is_hr and not data.reason:
            raise ConflictError("A reason is required to modify a completed goal.")

        # If weightage is updated, check sum
        if data.weightage is not None and data.weightage != goal.weightage:
            emp_goals = self.goal_repo.list_by_employee_and_cycle(
                company_id, goal.employee_id, goal.cycle_id
            )
            other_sum = sum((g.weightage for g in emp_goals if g.id != goal.id), Decimal("0.00"))
            if other_sum + data.weightage > Decimal("100.00"):
                raise WeightageSumError("Total goal weightage cannot exceed 100.00%.")

        updated = self.goal_repo.update(
            goal,
            title=data.title if data.title is not None else goal.title,
            description=data.description if data.description is not None else goal.description,
            weightage=data.weightage if data.weightage is not None else goal.weightage,
            target_value=data.target_value if data.target_value is not None else goal.target_value,
            status=data.status if data.status is not None else goal.status,
        )

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PERFORMANCE_GOAL_UPDATED",
            entity_type="performance_goal",
            entity_id=goal.id,
            details={"title": updated.title, "status": updated.status.value},
        )
        self.db.commit()

        # If someone else updated the goal, notify manager
        if not is_owner:
            target_emp = self.employee_repo.get_by_id(goal.employee_id, company_id)
            if target_emp and target_emp.reporting_manager_id:
                mgr = self.employee_repo.get_by_id(target_emp.reporting_manager_id, company_id)
                if mgr and mgr.user_id:
                    from app.modules.platform.models import Notification

                    notif = Notification(
                        company_id=company_id,
                        user_id=mgr.user_id,
                        type="employee_goals_updated",
                        title="Employee Goals Updated",
                        message=(
                            f"Goals for employee {target_emp.first_name} {target_emp.last_name} "
                            f"were updated by {actor.email}."
                        ),
                    )
                    self.db.add(notif)
                    self.db.commit()

        return updated

    def update_goal_progress(
        self,
        company_id: uuid.UUID,
        goal_id: uuid.UUID,
        data: GoalProgressUpdateRequest,
        actor: User,
    ) -> PerformanceGoal:
        goal = self.goal_repo.get_by_id(goal_id, company_id)
        if goal is None:
            raise NotFoundError("Performance goal not found.")

        # Cycle lock check
        cycle = self.cycle_repo.get_by_id(goal.cycle_id, company_id)
        if cycle is None or cycle.status != CycleStatus.active:
            raise ConflictError(
                "Goals cannot be modified when the performance cycle is not active."
            )

        emp = self.employee_repo.get_by_user_id(company_id, actor.id)
        is_owner = emp and goal.employee_id == emp.id
        is_hr = actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin)

        if not (is_owner or is_hr):
            raise ForbiddenError("Employees can only update progress on their own goals.")

        old_progress = goal.progress
        self.goal_repo.update(goal, progress=data.progress)
        self.goal_repo.add_progress_history(
            company_id=company_id,
            goal_id=goal.id,
            updated_by_id=actor.id,
            old_progress=old_progress,
            new_progress=data.progress,
            notes=data.notes,
        )

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PERFORMANCE_GOAL_PROGRESS_UPDATED",
            entity_type="performance_goal",
            entity_id=goal.id,
            details={"old_progress": str(old_progress), "new_progress": str(data.progress)},
        )
        self.db.commit()
        return goal

    def get_goal_progress_history(
        self, company_id: uuid.UUID, goal_id: uuid.UUID, actor: User
    ) -> list[Any]:
        goal = self.goal_repo.get_by_id(goal_id, company_id)
        if goal is None:
            raise NotFoundError("Performance goal not found.")
        return self.goal_repo.get_progress_history(company_id, goal.id)

    def list_goals(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, actor: User
    ) -> list[PerformanceGoal]:
        active_cycle = self.cycle_repo.get_active_cycle(company_id)
        if active_cycle is None:
            return []
        return self.goal_repo.list_by_employee_and_cycle(company_id, employee_id, active_cycle.id)

    # 3. Reviews & Invariants
    def submit_self_review(
        self, company_id: uuid.UUID, goal_id: uuid.UUID, data: SelfReviewRequest, actor: User
    ) -> PerformanceReview:
        goal = self.goal_repo.get_by_id(goal_id, company_id)
        if goal is None:
            raise NotFoundError("Performance goal not found.")

        # Cycle active check
        cycle = self.cycle_repo.get_by_id(goal.cycle_id, company_id)
        if cycle is None or cycle.status != CycleStatus.active:
            raise ConflictError(
                "Reviews can only be submitted while the performance cycle is active."
            )

        emp = self.employee_repo.get_by_user_id(company_id, actor.id)
        if emp is None or goal.employee_id != emp.id:
            raise ForbiddenError("Employees can only submit self-reviews for their own goals.")

        # Check total weightages sum for this employee in this cycle == 100
        emp_goals = self.goal_repo.list_by_employee_and_cycle(
            company_id, goal.employee_id, goal.cycle_id
        )
        total_weightage = sum((g.weightage for g in emp_goals), Decimal("0.00"))
        if total_weightage != Decimal("100.00"):
            raise WeightageSumError(
                f"Goal weightages for this cycle sum to {total_weightage}%, "
                "but must equal exactly 100.00% before self-review can be submitted."
            )

        existing = self.review_repo.get_by_goal_and_role(company_id, goal.id, ReviewerRole.self)
        if existing is not None:
            if existing.status == "draft":
                # Re-submitting an HR-reopened review
                self.review_repo.update(
                    existing,
                    rating=data.rating,
                    comments=data.comments,
                    status="submitted",
                    submitted_at=utcnow(),
                )
                self.goal_repo.update(goal, self_rating=data.rating, self_comments=data.comments)
                self.audit.record(
                    company_id=company_id,
                    actor=actor,
                    action="PERFORMANCE_REVIEW_SELF_SUBMITTED",
                    entity_type="performance_review",
                    entity_id=existing.id,
                    details={"goal_id": str(goal.id)},
                )
                self.db.commit()
                return existing
            raise ConflictError("Self-review for this goal has already been submitted.")

        review = self.review_repo.create(
            company_id=company_id,
            goal_id=goal.id,
            reviewer_id=actor.id,
            reviewer_role=ReviewerRole.self,
            rating=data.rating,
            comments=data.comments,
            status="submitted",
            submitted_at=utcnow(),
        )

        self.goal_repo.update(goal, self_rating=data.rating, self_comments=data.comments)

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PERFORMANCE_REVIEW_SELF_SUBMITTED",
            entity_type="performance_review",
            entity_id=review.id,
            details={"goal_id": str(goal.id)},
        )

        # Notify reporting manager if present
        if emp.reporting_manager_id:
            mgr = self.employee_repo.get_by_id(emp.reporting_manager_id, company_id)
            if mgr and mgr.user_id:
                from app.modules.platform.models import Notification

                emp_full_name = f"{emp.first_name} {emp.last_name or ''}".strip()
                notif = Notification(
                    company_id=company_id,
                    user_id=mgr.user_id,
                    type="self_review_submitted",
                    title="Self-Review Submitted",
                    message=f"Employee {emp_full_name} submitted a self-review.",
                )
                self.db.add(notif)

        self.db.commit()
        return review

    def submit_manager_review(
        self, company_id: uuid.UUID, goal_id: uuid.UUID, data: ManagerReviewRequest, actor: User
    ) -> PerformanceReview:
        goal = self.goal_repo.get_by_id(goal_id, company_id)
        if goal is None:
            raise NotFoundError("Performance goal not found.")

        # Cycle active check
        cycle = self.cycle_repo.get_by_id(goal.cycle_id, company_id)
        if cycle is None or cycle.status != CycleStatus.active:
            raise ConflictError(
                "Reviews can only be submitted while the performance cycle is active."
            )

        # Prerequisite: employee must have submitted self-review for this goal
        self_rev = self.review_repo.get_by_goal_and_role(company_id, goal.id, ReviewerRole.self)
        if self_rev is None or self_rev.status != "submitted":
            raise ConflictError(
                "Employee must submit their self-review before manager review can be submitted."
            )

        # Only reporting manager can review. HR cannot submit review if employee has a manager.
        target_emp = self.employee_repo.get_by_id(goal.employee_id, company_id)
        if not target_emp:
            raise NotFoundError("Employee profile not found.")

        if actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin):
            # Check if actor is also the reporting manager
            mgr_emp = self.employee_repo.get_by_user_id(company_id, actor.id)
            if target_emp.reporting_manager_id is not None:
                if not mgr_emp or target_emp.reporting_manager_id != mgr_emp.id:
                    raise ForbiddenError(
                        "HR administrators cannot submit manager reviews on behalf of managers."
                    )
            # If employee has no manager assigned, HR admin / Owner acts as fallback reviewer
        elif actor.role == UserRole.manager:
            mgr_emp = self.employee_repo.get_by_user_id(company_id, actor.id)
            if not mgr_emp:
                raise ForbiddenError("Manager profile not found.")
            if target_emp.reporting_manager_id != mgr_emp.id:
                raise ForbiddenError("Managers can only review goals for their direct reports.")
        else:
            raise ForbiddenError("Only reporting managers can submit manager reviews.")

        existing = self.review_repo.get_by_goal_and_role(company_id, goal.id, ReviewerRole.manager)
        if existing is not None:
            if existing.status == "draft":
                self.review_repo.update(
                    existing,
                    rating=data.rating,
                    comments=data.comments,
                    status="submitted",
                    submitted_at=utcnow(),
                )
                self.audit.record(
                    company_id=company_id,
                    actor=actor,
                    action="PERFORMANCE_REVIEW_MANAGER_SUBMITTED",
                    entity_type="performance_review",
                    entity_id=existing.id,
                    details={"goal_id": str(goal.id)},
                )
                self.db.commit()
                return existing
            raise ConflictError("Manager review for this goal has already been submitted.")

        review = self.review_repo.create(
            company_id=company_id,
            goal_id=goal.id,
            reviewer_id=actor.id,
            reviewer_role=ReviewerRole.manager,
            rating=data.rating,
            comments=data.comments,
            status="submitted",
            submitted_at=utcnow(),
        )

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PERFORMANCE_REVIEW_MANAGER_SUBMITTED",
            entity_type="performance_review",
            entity_id=review.id,
            details={"goal_id": str(goal.id)},
        )

        # Notify employee
        target_emp = self.employee_repo.get_by_id(goal.employee_id, company_id)
        if target_emp and target_emp.user_id:
            from app.modules.platform.models import Notification

            notif = Notification(
                company_id=company_id,
                user_id=target_emp.user_id,
                type="manager_review_submitted",
                title="Manager Review Submitted",
                message="Your manager has submitted a review for your goal.",
            )
            self.db.add(notif)

        self.db.commit()
        return review

    def reopen_review(
        self,
        company_id: uuid.UUID,
        review_id: uuid.UUID,
        reason: str,
        actor: User,
    ) -> PerformanceReview:
        if actor.role not in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin):
            raise ForbiddenError("Only HR administrators and company owners can reopen reviews.")

        if not reason or not reason.strip():
            raise ValidationError("Reopening a review requires a non-empty reason.")

        review = self.review_repo.get_by_id(review_id, company_id)
        if review is None:
            raise NotFoundError("Performance review not found.")

        self.review_repo.update(
            review,
            status="draft",
            reopened_at=utcnow(),
            reopened_by_id=actor.id,
            reopen_reason=reason.strip(),
        )

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PERFORMANCE_REVIEW_REOPENED",
            entity_type="performance_review",
            entity_id=review.id,
            details={"reason": reason.strip(), "review_id": str(review.id)},
        )
        self.db.commit()
        return review

    def get_review_by_id(
        self, company_id: uuid.UUID, review_id: uuid.UUID, actor: User
    ) -> PerformanceReview:
        review = self.review_repo.get_by_id(review_id, company_id)
        if review is None:
            raise NotFoundError("Performance review not found.")
        return review

    def list_goal_reviews(
        self, company_id: uuid.UUID, goal_id: uuid.UUID, actor: User
    ) -> list[PerformanceReview]:
        goal = self.goal_repo.get_by_id(goal_id, company_id)
        if goal is None:
            raise NotFoundError("Performance goal not found.")

        reviews = self.review_repo.list_by_goal(company_id, goal_id)
        emp = self.employee_repo.get_by_user_id(company_id, actor.id)
        is_goal_owner = emp and goal.employee_id == emp.id

        # Blind review gating: Employee cannot see manager review if unsubmitted
        if is_goal_owner:
            reviews = [
                r
                for r in reviews
                if not (r.reviewer_role == ReviewerRole.manager and r.status != "submitted")
            ]

        return reviews

    def get_summary(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, actor: User | None = None
    ) -> dict[str, Any] | None:
        target_emp = self.employee_repo.get_by_id(employee_id, company_id)
        if target_emp is None:
            # Check if employee_id belongs to another company or doesn't exist
            raise NotFoundError("Employee profile not found.")

        # Scoping permission check
        if actor is not None:
            current_emp = self.employee_repo.get_by_user_id(company_id, actor.id)
            is_hr_or_owner = actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin)
            if not is_hr_or_owner:
                if current_emp is None:
                    raise ForbiddenError("Not authorized to view performance summary.")
                if current_emp.id == target_emp.id:
                    pass  # Employee viewing own summary
                elif actor.role == UserRole.manager:
                    # Direct reports only or reporting chain
                    team_ids = self.employee_repo.list_direct_report_ids(company_id, current_emp.id)
                    if target_emp.id not in team_ids:
                        raise ForbiddenError(
                            "Managers can only view summaries for their direct reports."
                        )
                else:
                    raise ForbiddenError("Employees can only view their own performance summary.")

        active_cycle = self.cycle_repo.get_active_cycle(company_id)
        if active_cycle is None:
            return None

        # Gather goals for active cycle
        goals = self.goal_repo.list_by_employee_and_cycle(company_id, employee_id, active_cycle.id)

        # Active PIP status
        active_pip = self.pip_repo.get_active_pip_for_employee(company_id, employee_id)
        on_pip = active_pip is not None

        # Existing finalized summary if any
        finalized_summ = self.summary_repo.get_by_employee_and_cycle(
            company_id, employee_id, active_cycle.id
        )

        # Calculate weighted progress: sum(progress * weightage / 100)
        weighted_progress = Decimal("0.00")
        for g in goals:
            weighted_progress += Decimal(str(g.progress)) * (g.weightage / Decimal("100.00"))
        weighted_progress = weighted_progress.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Check reviews
        completed_reviews_count = 0
        weighted_manager_rating: Decimal | None = None
        has_pending_mgr_review = False
        manager_ratings_sum = Decimal("0.00")
        total_mgr_weightage = Decimal("0.00")

        for g in goals:
            mgr_rev = self.review_repo.get_by_goal_and_role(company_id, g.id, ReviewerRole.manager)
            if mgr_rev and mgr_rev.status == "submitted":
                completed_reviews_count += 1
                manager_ratings_sum += mgr_rev.rating * (g.weightage / Decimal("100.00"))
                total_mgr_weightage += g.weightage
            else:
                has_pending_mgr_review = True

        if (
            completed_reviews_count > 0
            and not has_pending_mgr_review
            and total_mgr_weightage > Decimal("0.00")
        ):
            weighted_manager_rating = manager_ratings_sum.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        elif completed_reviews_count > 0 and actor and actor.role != UserRole.employee:
            # Managers and HR can see partial weighted manager rating if any
            if total_mgr_weightage == Decimal("100.00"):
                weighted_manager_rating = manager_ratings_sum.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

        mgr_review_status = (
            "completed" if (completed_reviews_count == len(goals) and len(goals) > 0) else "pending"
        )

        # Blind review gating for employee viewing:
        emp_actor = self.employee_repo.get_by_user_id(company_id, actor.id) if actor else None
        if (
            actor
            and actor.role == UserRole.employee
            and emp_actor
            and emp_actor.id == target_emp.id
        ):
            # If not all reviews submitted, manager rating is hidden
            if has_pending_mgr_review:
                weighted_manager_rating = None

        goal_responses = [PerformanceGoalResponse.model_validate(g) for g in goals]

        return {
            "employee_id": employee_id,
            "cycle_id": active_cycle.id,
            "goals": goal_responses,
            "weighted_progress": weighted_progress,
            "weighted_manager_rating": weighted_manager_rating,
            "manager_review_status": mgr_review_status,
            "completed_reviews_count": completed_reviews_count,
            "on_pip": on_pip,
            "final_rating": finalized_summ.final_rating if finalized_summ else None,
            "overall_comments": finalized_summ.overall_comments if finalized_summ else None,
            "finalized_at": finalized_summ.finalized_at if finalized_summ else None,
        }

    def list_summaries(
        self, company_id: uuid.UUID, cycle_id: uuid.UUID, page_params: PageParams, actor: User
    ) -> tuple[list[PerformanceSummary], int, int]:
        if actor.role not in (
            UserRole.hr_admin,
            UserRole.owner,
            UserRole.super_admin,
            UserRole.manager,
        ):
            raise ForbiddenError("Not authorized to list performance summaries.")
        return self.summary_repo.list_summaries(company_id, cycle_id, page_params)

    def finalize_summary(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        data: SummaryFinalizeRequest,
        actor: User,
    ) -> PerformanceSummary:
        cycle = self.cycle_repo.get_by_id(data.cycle_id, company_id)
        if cycle is None:
            raise NotFoundError("Performance cycle not found.")

        existing = self.summary_repo.get_by_employee_and_cycle(company_id, employee_id, cycle.id)
        if existing is not None:
            return existing

        goals = self.goal_repo.list_by_employee_and_cycle(company_id, employee_id, cycle.id)
        if not goals:
            raise ConflictError("Cannot finalize summary for employee with no goals.")

        # Calculate weighted average from manager reviews
        weighted_sum = Decimal("0.00")
        for g in goals:
            mgr_rev = self.review_repo.get_by_goal_and_role(company_id, g.id, ReviewerRole.manager)
            rating = mgr_rev.rating if mgr_rev else g.self_rating or Decimal("3.0")
            weighted_sum += rating * (g.weightage / Decimal("100.00"))

        final_rating = weighted_sum.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

        summary = self.summary_repo.create(
            company_id=company_id,
            employee_id=employee_id,
            cycle_id=cycle.id,
            final_rating=final_rating,
            overall_comments=data.overall_comments,
            salary_revision_recommended=data.salary_revision_recommended,
            recommended_increment_percent=data.recommended_increment_percent,
            reviewed_by=actor.id,
            finalized_at=utcnow(),
        )

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PERFORMANCE_SUMMARY_FINALIZED",
            entity_type="performance_summary",
            entity_id=summary.id,
            details={"final_rating": str(summary.final_rating)},
        )
        self.db.commit()
        return summary

    def get_report(self, company_id: uuid.UUID) -> PerformanceReportResponse:
        active_cycle = self.cycle_repo.get_active_cycle(company_id)
        if active_cycle is None:
            return PerformanceReportResponse(
                active_cycle=None,
                total_employees=0,
                completed_reviews=0,
                completion_rate_percent=Decimal("0.00"),
                rating_distribution={},
            )

        employees, total_emp, _ = self.employee_repo.list_employees(
            company_id=company_id,
            q=None,
            department_id=None,
            is_active=True,
            level=None,
            employment_type=None,
            reporting_manager_id=None,
            sort=None,
            page_params=PageParams(page=1, limit=1000),
        )

        completed_count = 0
        distribution: dict[str, int] = {"1-2": 0, "2-3": 0, "3-4": 0, "4-5": 0}

        for emp in employees:
            summ = self.summary_repo.get_by_employee_and_cycle(company_id, emp.id, active_cycle.id)
            if summ is not None:
                completed_count += 1
                r = float(summ.final_rating)
                if r < 2.0:
                    distribution["1-2"] += 1
                elif r < 3.0:
                    distribution["2-3"] += 1
                elif r < 4.0:
                    distribution["3-4"] += 1
                else:
                    distribution["4-5"] += 1

        rate = (
            Decimal(completed_count * 100 / total_emp).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if total_emp > 0
            else Decimal("0.00")
        )

        return PerformanceReportResponse(
            active_cycle=PerformanceCycleResponse.model_validate(active_cycle),
            total_employees=total_emp,
            completed_reviews=completed_count,
            completion_rate_percent=rate,
            rating_distribution=distribution,
        )

    # 6. Performance Improvement Plans (PIP)
    def create_pip(
        self, company_id: uuid.UUID, data: PIPCreateRequest, actor: User
    ) -> PerformancePIP:
        emp = self.employee_repo.get_by_id(data.employee_id, company_id)
        if emp is None:
            raise NotFoundError("Employee not found.")

        # Authority check before checking active PIP state
        from app.core.approval_authority import can_approve_for

        can_approve_for(self.db, actor, emp)

        # Validate mentor if provided: must exist in same company and be active
        if data.mentor_id is not None:
            mentor = self.employee_repo.get_by_id_any_status(data.mentor_id, company_id)
            if mentor is None:
                raise NotFoundError("Mentor employee not found.")
            if not mentor.is_active:
                raise ConflictError("Mentor employee is inactive.")

        # Check if already has an active PIP
        existing = self.pip_repo.get_active_pip_for_employee(company_id, data.employee_id)
        if existing is not None:
            raise ConflictError(
                "Employee already has an active Performance Improvement Plan (PIP)."
            )

        pip = self.pip_repo.create(
            company_id=company_id,
            employee_id=data.employee_id,
            mentor_id=data.mentor_id,
            title=data.title,
            description=data.description,
            milestones_kpis=data.milestones_kpis,
            start_date=data.start_date,
            end_date=data.end_date,
            status="active",
        )

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PIP_INITIATED",
            entity_type="performance_pip",
            entity_id=pip.id,
            details={"employee_id": str(data.employee_id), "end_date": str(data.end_date)},
        )
        self.db.commit()
        return pip

    def list_pips(
        self, company_id: uuid.UUID, employee_id: uuid.UUID | None = None, status: str | None = None
    ) -> list[PerformancePIPResponse]:
        pips = self.pip_repo.list_pips(company_id, employee_id, status)
        res = []
        for p in pips:
            emp = self.employee_repo.get_by_id(company_id, p.employee_id)
            mentor = self.employee_repo.get_by_id(company_id, p.mentor_id) if p.mentor_id else None
            res.append(
                PerformancePIPResponse(
                    id=p.id,
                    employee_id=p.employee_id,
                    employee_name=f"{emp.first_name} {emp.last_name or ''}".strip()
                    if emp
                    else None,
                    employee_code=emp.employee_code if emp else None,
                    mentor_id=p.mentor_id,
                    mentor_name=f"{mentor.first_name} {mentor.last_name or ''}".strip()
                    if mentor
                    else None,
                    title=p.title,
                    description=p.description,
                    milestones_kpis=p.milestones_kpis,
                    start_date=p.start_date,
                    end_date=p.end_date,
                    status=p.status,
                    outcome_notes=p.outcome_notes,
                    evaluated_at=p.evaluated_at,
                    evaluated_by=p.evaluated_by,
                    created_at=p.created_at,
                )
            )
        return res

    def get_active_pip(
        self, company_id: uuid.UUID, employee_id: uuid.UUID
    ) -> PerformancePIPResponse | None:
        p = self.pip_repo.get_active_pip_for_employee(company_id, employee_id)
        if p is None:
            return None
        emp = self.employee_repo.get_by_id(company_id, p.employee_id)
        mentor = self.employee_repo.get_by_id(company_id, p.mentor_id) if p.mentor_id else None
        return PerformancePIPResponse(
            id=p.id,
            employee_id=p.employee_id,
            employee_name=f"{emp.first_name} {emp.last_name or ''}".strip() if emp else None,
            employee_code=emp.employee_code if emp else None,
            mentor_id=p.mentor_id,
            mentor_name=f"{mentor.first_name} {mentor.last_name or ''}".strip() if mentor else None,
            title=p.title,
            description=p.description,
            milestones_kpis=p.milestones_kpis,
            start_date=p.start_date,
            end_date=p.end_date,
            status=p.status,
            outcome_notes=p.outcome_notes,
            evaluated_at=p.evaluated_at,
            evaluated_by=p.evaluated_by,
            created_at=p.created_at,
        )

    def evaluate_pip(
        self, company_id: uuid.UUID, pip_id: uuid.UUID, data: PIPEvaluateRequest, actor: User
    ) -> PerformancePIPResponse:
        pip = self.pip_repo.get_by_id(pip_id, company_id)
        if pip is None:
            raise NotFoundError("PIP record not found.")

        from app.core.approval_authority import can_approve_for

        emp = self.employee_repo.get_by_id_any_status(pip.employee_id, company_id)
        if not emp or not can_approve_for(self.db, actor, emp):
            raise ForbiddenError("Not authorized to approve this request.")

        if pip.status in ("passed", "failed", "cancelled"):
            raise ConflictError(f"PIP has already been evaluated (current status: {pip.status}).")

        self.pip_repo.update(
            pip,
            status=data.outcome,
            outcome_notes=data.outcome_notes,
            evaluated_at=utcnow(),
            evaluated_by=actor.id,
        )

        # Track C rule: "If marked Failed, automatically triggers separation/termination"
        if data.outcome == "failed" and emp:
            from app.modules.hr.models import ResignationStatus
            from app.modules.hr.service import EmployeeService

            self.employee_repo.update(
                emp,
                resignation_status=ResignationStatus.approved,
                separation_type="pip_failed",
                termination_reason=f"Failed Performance Improvement Plan: {pip.title}",
                last_working_date=utcnow().date(),
                notice_waived=True,
                notice_recovery_days=0,
            )
            EmployeeService(self.db).apply_exit(company_id, emp.id, actor=actor, commit=False)

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action=f"PIP_{data.outcome.upper()}",
            entity_type="performance_pip",
            entity_id=pip.id,
            details={"outcome": data.outcome, "notes": data.outcome_notes},
        )
        self.db.commit()
        return self.get_active_pip(
            company_id, pip.employee_id
        ) or PerformancePIPResponse.model_validate(pip)
