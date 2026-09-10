import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.pagination import Page, PageParams, page_params
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole
from app.modules.performance.models import CycleStatus, GoalStatus
from app.modules.performance.schemas import (
    GoalsCreateRequest,
    GoalUpdateRequest,
    ManagerReviewRequest,
    PerformanceCycleCreateRequest,
    PerformanceCycleResponse,
    PerformanceCycleUpdateRequest,
    PerformanceGoalResponse,
    PerformanceReportResponse,
    PerformanceReviewResponse,
    PerformanceSummaryResponse,
    SelfReviewRequest,
    SummaryFinalizeRequest,
)
from app.modules.performance.service import PerformanceGoalRepository, PerformanceService

performance_router = APIRouter(prefix="/performance", tags=["Performance Management"])


# --- Routes 67-69: Cycles --------------------------------------------------

@performance_router.get("/cycles", response_model=Page[PerformanceCycleResponse])
def list_performance_cycles(
    status_filter: CycleStatus | None = Query(default=None, alias="status_filter"),
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = PerformanceService(db)
    cycles, total, pages = service.list_cycles(user.company_id, params, status_filter)
    items = [PerformanceCycleResponse.model_validate(c) for c in cycles]
    return Page(
        items=items,
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@performance_router.post("/cycles", response_model=PerformanceCycleResponse, status_code=201)
def create_performance_cycle(
    data: PerformanceCycleCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    service = PerformanceService(db)
    cycle = service.create_cycle(user.company_id, data, user)
    return PerformanceCycleResponse.model_validate(cycle)


@performance_router.put("/cycles/{id}", response_model=PerformanceCycleResponse)
def update_performance_cycle(
    id: uuid.UUID,
    data: PerformanceCycleUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    service = PerformanceService(db)
    cycle = service.update_cycle(user.company_id, id, data, user)
    return PerformanceCycleResponse.model_validate(cycle)


# --- Route 77: Report (before {employee_id} wildcard) ----------------------

@performance_router.get("/report", response_model=PerformanceReportResponse)
def get_performance_report(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    service = PerformanceService(db)
    return service.get_report(user.company_id)


# --- Routes 70-74: Goals & Reviews -----------------------------------------

@performance_router.post("/goals", response_model=list[PerformanceGoalResponse], status_code=201)
def set_performance_goals(
    data: GoalsCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = PerformanceService(db)
    goals = service.create_goals(user.company_id, data, user)
    return [PerformanceGoalResponse.model_validate(g) for g in goals]


@performance_router.get("/goals/{employee_id}", response_model=list[PerformanceGoalResponse])
def list_performance_goals(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager, UserRole.employee)),
):
    service = PerformanceService(db)

    # Scoping check: employees can only view their own goals
    target_emp_id = employee_id
    if user.role == UserRole.employee:
        emp = EmployeeRepository(db).get_by_user_id(user.company_id, user.id)
        if not emp or (emp.id != employee_id and user.id != employee_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Employees can only view their own performance goals.",
            )
        target_emp_id = emp.id
    else:
        # If employee_id passed was actually user.id, resolve to employee record if matching
        emp_by_user = EmployeeRepository(db).get_by_user_id(user.company_id, employee_id)
        if emp_by_user:
            target_emp_id = emp_by_user.id

    goals = service.list_goals(user.company_id, target_emp_id, user)
    return [PerformanceGoalResponse.model_validate(g) for g in goals]



@performance_router.put("/goals/{id}", response_model=PerformanceGoalResponse)
def update_performance_goal(
    id: uuid.UUID,
    data: GoalUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    repo = PerformanceGoalRepository(db)
    goal = repo.get_by_id(id, user.company_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Performance goal not found.")

    emp = EmployeeRepository(db).get_by_user_id(user.company_id, user.id)
    if not emp or goal.employee_id != emp.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employees can only update their own performance goals.",
        )

    updated = repo.update(
        goal,
        title=data.title if data.title is not None else goal.title,
        description=data.description if data.description is not None else goal.description,
        weightage=data.weightage if data.weightage is not None else goal.weightage,
        target_value=data.target_value if data.target_value is not None else goal.target_value,
        status=data.status if data.status is not None else goal.status,
    )
    db.commit()
    return PerformanceGoalResponse.model_validate(updated)


@performance_router.post("/goals/{goal_id}/self-review", response_model=PerformanceReviewResponse)
def submit_self_review(
    goal_id: uuid.UUID,
    data: SelfReviewRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = PerformanceService(db)
    review = service.submit_self_review(user.company_id, goal_id, data, user)
    return PerformanceReviewResponse.model_validate(review)


@performance_router.post("/goals/{goal_id}/manager-review", response_model=PerformanceReviewResponse)
def submit_manager_review(
    goal_id: uuid.UUID,
    data: ManagerReviewRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.manager)),
):
    service = PerformanceService(db)
    review = service.submit_manager_review(user.company_id, goal_id, data, user)
    return PerformanceReviewResponse.model_validate(review)


# --- Routes 75-76: Summaries -----------------------------------------------

@performance_router.get("/summary/{employee_id}", response_model=PerformanceSummaryResponse | None)
def get_performance_summary(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.manager, UserRole.employee)),
):
    service = PerformanceService(db)

    if user.role == UserRole.employee:
        emp = EmployeeRepository(db).get_by_user_id(user.company_id, user.id)
        if not emp or emp.id != employee_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Employees can only view their own performance summary.",
            )

    summary = service.get_summary(user.company_id, employee_id)
    if summary is None:
        return None
    return PerformanceSummaryResponse.model_validate(summary)


@performance_router.post("/summary/{employee_id}", response_model=PerformanceSummaryResponse)
def finalize_performance_summary(
    employee_id: uuid.UUID,
    data: SummaryFinalizeRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    service = PerformanceService(db)
    summary = service.finalize_summary(user.company_id, employee_id, data, user)
    return PerformanceSummaryResponse.model_validate(summary)
