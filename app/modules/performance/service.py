import uuid
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams
from app.core.time import utcnow
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole
from app.modules.performance.models import (
    CycleStatus,
    CycleType,
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
    GoalsCreateRequest,
    ManagerReviewRequest,
    PerformanceCycleCreateRequest,
    PerformanceCycleUpdateRequest,
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
            emp = self.employee_repo.get_by_id(company_id, data.employee_id)
            if emp is None:
                raise NotFoundError("Specified employee profile not found.")
        else:
            emp = self.employee_repo.get_by_user_id(company_id, actor.id)
            if emp is None:
                raise NotFoundError(
                    "Employee profile not found for current user. Admin or manager accounts must select an employee profile when creating goals."
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
            )
            created.append(goal)

        self.db.commit()
        return created

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
                f"Goal weightages for this cycle sum to {total_weightage}%, but must equal exactly 100.00% before self-review can be submitted."
            )

        existing = self.review_repo.get_by_goal_and_role(company_id, goal.id, ReviewerRole.self)
        if existing is not None:
            raise ConflictError("Self-review for this goal has already been submitted.")

        review = self.review_repo.create(
            company_id=company_id,
            goal_id=goal.id,
            reviewer_id=actor.id,
            reviewer_role=ReviewerRole.self,
            rating=data.rating,
            comments=data.comments,
            submitted_at=utcnow(),
        )

        self.goal_repo.update(goal, self_rating=data.rating, self_comments=data.comments)
        self.db.commit()
        return review

    def submit_manager_review(
        self, company_id: uuid.UUID, goal_id: uuid.UUID, data: ManagerReviewRequest, actor: User
    ) -> PerformanceReview:
        goal = self.goal_repo.get_by_id(goal_id, company_id)
        if goal is None:
            raise NotFoundError("Performance goal not found.")

        if actor.role == UserRole.manager:
            mgr_emp = self.employee_repo.get_by_user_id(company_id, actor.id)
            if not mgr_emp:
                raise ForbiddenError("Manager profile not found.")
            team_ids = self.employee_repo.list_direct_report_ids(company_id, mgr_emp.id)
            if goal.employee_id not in team_ids:
                raise ForbiddenError("Managers can only review goals for their direct reports.")

        existing = self.review_repo.get_by_goal_and_role(company_id, goal.id, ReviewerRole.manager)
        if existing is not None:
            raise ConflictError("Manager review for this goal has already been submitted.")

        review = self.review_repo.create(
            company_id=company_id,
            goal_id=goal.id,
            reviewer_id=actor.id,
            reviewer_role=ReviewerRole.manager,
            rating=data.rating,
            comments=data.comments,
            submitted_at=utcnow(),
        )
        self.db.commit()
        return review

    def get_summary(
        self, company_id: uuid.UUID, employee_id: uuid.UUID
    ) -> PerformanceSummary | None:
        active_cycle = self.cycle_repo.get_active_cycle(company_id)
        if active_cycle is None:
            return None
        return self.summary_repo.get_by_employee_and_cycle(company_id, employee_id, active_cycle.id)

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
            Decimal(completed_count * 100 / total_emp).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if total_emp > 0
            else Decimal("0.00")
        )

        return PerformanceReportResponse(
            active_cycle=active_cycle,
            total_employees=total_emp,
            completed_reviews=completed_count,
            completion_rate_percent=rate,
            rating_distribution=distribution,
        )

    # 6. Performance Improvement Plans (PIP)
    def create_pip(self, company_id: uuid.UUID, data: PIPCreateRequest, actor: User) -> PerformancePIP:
        emp = self.employee_repo.get_by_id(company_id, data.employee_id)
        if emp is None:
            raise NotFoundError("Employee not found.")

        # Check if already has an active PIP
        existing = self.pip_repo.get_active_pip_for_employee(company_id, data.employee_id)
        if existing is not None:
            raise ConflictError("Employee already has an active Performance Improvement Plan (PIP).")

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
            )
        return res

    def get_active_pip(self, company_id: uuid.UUID, employee_id: uuid.UUID) -> PerformancePIPResponse | None:
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

        self.pip_repo.update(
            pip,
            status=data.outcome,
            outcome_notes=data.outcome_notes,
            evaluated_at=utcnow(),
            evaluated_by=actor.id,
        )

        # Track C rule: "If marked Failed, automatically triggers separation/termination"
        if data.outcome == "failed":
            emp = self.employee_repo.get_by_id(company_id, pip.employee_id)
            if emp:
                from app.modules.hr.models import ResignationStatus
                self.employee_repo.update(
                    emp,
                    is_active=False,
                    resignation_status=ResignationStatus.approved,
                    separation_type="pip_failed",
                    termination_reason=f"Failed Performance Improvement Plan: {pip.title}",
                    last_working_date=utcnow().date(),
                    notice_waived=True,
                    notice_recovery_days=0,
                )
                if emp.user_id:
                    user = self.db.scalar(select(User).where(User.id == emp.user_id))
                    if user:
                        user.is_active = False

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action=f"PIP_{data.outcome.upper()}",
            entity_type="performance_pip",
            entity_id=pip.id,
            details={"outcome": data.outcome, "notes": data.outcome_notes},
        )
        self.db.commit()
        return self.get_active_pip(company_id, pip.employee_id) or PerformancePIPResponse.model_validate(pip)
