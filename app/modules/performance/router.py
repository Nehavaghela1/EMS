import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.pagination import Page, PageParams, page_params
from app.core.rate_limit import get_user_or_ip_key, limiter
from app.core.roles import HR_LEVEL_ROLES
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole
from app.modules.performance.models import CycleStatus
from app.modules.performance.schemas import (
    GoalProgressHistoryResponse,
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
    PerformanceReviewResponse,
    PerformanceSummaryResponse,
    PIPCreateRequest,
    PIPEvaluateRequest,
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
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def create_performance_cycle(
    request: Request,
    data: PerformanceCycleCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.owner)),
):
    service = PerformanceService(db)
    cycle = service.create_cycle(user.company_id, data, user)
    return PerformanceCycleResponse.model_validate(cycle)


@performance_router.put("/cycles/{id}", response_model=PerformanceCycleResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def update_performance_cycle(
    request: Request,
    id: uuid.UUID,
    data: PerformanceCycleUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.owner)),
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
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def set_performance_goals(
    request: Request,
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
    user: User = Depends(
        require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager, UserRole.employee)
    ),
):
    service = PerformanceService(db)

    # Scoping check: employees can only view their own goals;
    # managers can view their own goals or goals of employees in their reporting chain.
    target_emp_id = employee_id
    if user.role == UserRole.employee:
        emp = EmployeeRepository(db).get_by_user_id(user.company_id, user.id)
        if not emp or (emp.id != employee_id and user.id != employee_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Employees can only view their own performance goals.",
            )
        target_emp_id = emp.id
    elif user.role == UserRole.manager:
        emp_repo = EmployeeRepository(db)
        # If employee_id passed was user.id, resolve to employee record
        target_emp = emp_repo.get_by_user_id(user.company_id, employee_id)
        if not target_emp:
            target_emp = emp_repo.get_by_id(employee_id, user.company_id)
        if target_emp is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found.",
            )
        target_emp_id = target_emp.id
        if target_emp.user_id != user.id:
            from app.core.approval_authority import can_approve_for

            can_approve_for(db, user, target_emp)
    else:
        # If employee_id passed was actually user.id, resolve to employee record if matching
        emp_by_user = EmployeeRepository(db).get_by_user_id(user.company_id, employee_id)
        if emp_by_user:
            target_emp_id = emp_by_user.id

    goals = service.list_goals(user.company_id, target_emp_id, user)
    return [PerformanceGoalResponse.model_validate(g) for g in goals]


@performance_router.put("/goals/{id}", response_model=PerformanceGoalResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def update_performance_goal(
    request: Request,
    id: uuid.UUID,
    data: GoalUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = PerformanceService(db)
    updated = service.update_goal(user.company_id, id, data, user)
    return PerformanceGoalResponse.model_validate(updated)


@performance_router.put("/goals/{id}/progress", response_model=PerformanceGoalResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def update_goal_progress(
    request: Request,
    id: uuid.UUID,
    data: GoalProgressUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = PerformanceService(db)
    updated = service.update_goal_progress(user.company_id, id, data, user)
    return PerformanceGoalResponse.model_validate(updated)


@performance_router.get(
    "/goals/{id}/history", response_model=list[GoalProgressHistoryResponse]
)
def get_goal_progress_history(
    id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = PerformanceService(db)
    history = service.get_goal_progress_history(user.company_id, id, user)
    return [GoalProgressHistoryResponse.model_validate(h) for h in history]


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


@performance_router.post(
    "/goals/{goal_id}/manager-review", response_model=PerformanceReviewResponse
)
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


# --- Performance Improvement Plan (PIP) Endpoints ---


@performance_router.post("/pips", response_model=PerformancePIPResponse, status_code=201)
def initiate_pip(
    data: PIPCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.super_admin, UserRole.manager)),
):
    service = PerformanceService(db)
    pip = service.create_pip(user.company_id, data, user)
    return service.get_active_pip(
        user.company_id, pip.employee_id
    ) or PerformancePIPResponse.model_validate(pip)


@performance_router.get("/pips", response_model=list[PerformancePIPResponse])
def list_pips(
    employee_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = PerformanceService(db)
    target_emp_id = employee_id

    # If employee, can only see their own PIPs
    if user.role == UserRole.employee:
        emp = EmployeeRepository(db).get_by_user_id(user.company_id, user.id)
        if not emp:
            return []
        target_emp_id = emp.id

    return service.list_pips(user.company_id, target_emp_id, status_filter)


@performance_router.get("/pips/active/{employee_id}", response_model=PerformancePIPResponse | None)
def get_active_pip(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = PerformanceService(db)
    # Check scoping
    if user.role == UserRole.employee:
        emp = EmployeeRepository(db).get_by_user_id(user.company_id, user.id)
        if not emp or (emp.id != employee_id and user.id != employee_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Employees can only view their own active PIP.",
            )
        employee_id = emp.id

    return service.get_active_pip(user.company_id, employee_id)


@performance_router.post("/pips/{pip_id}/evaluate", response_model=PerformancePIPResponse)
def evaluate_pip(
    pip_id: uuid.UUID,
    data: PIPEvaluateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.super_admin, UserRole.manager)),
):
    service = PerformanceService(db)
    return service.evaluate_pip(user.company_id, pip_id, data, user)
