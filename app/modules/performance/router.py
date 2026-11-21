import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_tenant_db, require_company_role
from app.core.pagination import Page, PageParams, page_params
from app.core.rate_limit import get_user_or_ip_key, limiter
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
    PerformanceSummaryDetailResponse,
    PerformanceSummaryResponse,
    PIPCheckInCreateRequest,
    PIPCheckInResponse,
    PIPCreateRequest,
    PIPEvaluateRequest,
    PIPExtendRequest,
    ReviewReopenRequest,
    SelfReviewRequest,
    SummaryFinalizeRequest,
)
from app.modules.performance.service import PerformanceService

performance_router = APIRouter(prefix="/performance", tags=["Performance Management"])


# --- Routes 67-69: Cycles --------------------------------------------------


@performance_router.get("/cycles", response_model=Page[PerformanceCycleResponse])
def list_performance_cycles(
    status_filter: CycleStatus | None = Query(default=None, alias="status_filter"),
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role()),
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
    user: User = Depends(require_company_role(UserRole.hr_admin, UserRole.owner)),
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
    user: User = Depends(require_company_role(UserRole.hr_admin, UserRole.owner)),
):
    service = PerformanceService(db)
    cycle = service.update_cycle(user.company_id, id, data, user)
    return PerformanceCycleResponse.model_validate(cycle)


# --- Route 77: Report (before {employee_id} wildcard) ----------------------


@performance_router.get("/report", response_model=PerformanceReportResponse)
def get_performance_report(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role(UserRole.hr_admin)),
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
    user: User = Depends(require_company_role()),
):
    service = PerformanceService(db)
    goals = service.create_goals(user.company_id, data, user)
    return [PerformanceGoalResponse.model_validate(g) for g in goals]


@performance_router.get("/goals/{employee_id}", response_model=list[PerformanceGoalResponse])
def list_performance_goals(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(
        require_company_role(UserRole.hr_admin, UserRole.manager, UserRole.employee)
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
        # HR/Admin: verify employee exists in this company
        emp = EmployeeRepository(db).get_by_id(employee_id, user.company_id)
        if emp is None:
            emp_by_user = EmployeeRepository(db).get_by_user_id(user.company_id, employee_id)
            if not emp_by_user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Employee not found.",
                )
            target_emp_id = emp_by_user.id
        else:
            target_emp_id = emp.id

    goals = service.list_goals(user.company_id, target_emp_id, user)
    return [PerformanceGoalResponse.model_validate(g) for g in goals]


@performance_router.put("/goals/{id}", response_model=PerformanceGoalResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def update_performance_goal(
    request: Request,
    id: uuid.UUID,
    data: GoalUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role()),
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
    user: User = Depends(require_company_role()),
):
    service = PerformanceService(db)
    updated = service.update_goal_progress(user.company_id, id, data, user)
    return PerformanceGoalResponse.model_validate(updated)


@performance_router.get("/goals/{id}/history", response_model=list[GoalProgressHistoryResponse])
def get_goal_progress_history(
    id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role()),
):
    service = PerformanceService(db)
    history = service.get_goal_progress_history(user.company_id, id, user)
    return [GoalProgressHistoryResponse.model_validate(h) for h in history]


@performance_router.post("/goals/{goal_id}/self-review", response_model=PerformanceReviewResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def submit_self_review(
    request: Request,
    goal_id: uuid.UUID,
    data: SelfReviewRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role()),
):
    service = PerformanceService(db)
    review = service.submit_self_review(user.company_id, goal_id, data, user)
    return PerformanceReviewResponse.model_validate(review)


@performance_router.post(
    "/goals/{goal_id}/manager-review", response_model=PerformanceReviewResponse
)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def submit_manager_review(
    request: Request,
    goal_id: uuid.UUID,
    data: ManagerReviewRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role(UserRole.hr_admin, UserRole.manager)),
):
    service = PerformanceService(db)
    review = service.submit_manager_review(user.company_id, goal_id, data, user)
    return PerformanceReviewResponse.model_validate(review)


@performance_router.get("/goals/{goal_id}/reviews", response_model=list[PerformanceReviewResponse])
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def list_goal_reviews(
    request: Request,
    goal_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role()),
):
    service = PerformanceService(db)
    reviews = service.list_goal_reviews(user.company_id, goal_id, user)
    return [PerformanceReviewResponse.model_validate(r) for r in reviews]


@performance_router.get("/reviews/{id}", response_model=PerformanceReviewResponse)
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def get_performance_review(
    request: Request,
    id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role()),
):
    service = PerformanceService(db)
    review = service.get_review_by_id(user.company_id, id, user)
    return PerformanceReviewResponse.model_validate(review)


@performance_router.post("/reviews/{id}/reopen", response_model=PerformanceReviewResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def reopen_performance_review(
    request: Request,
    id: uuid.UUID,
    data: ReviewReopenRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role(UserRole.hr_admin)),
):
    service = PerformanceService(db)
    review = service.reopen_review(user.company_id, id, data.reason, user)
    return PerformanceReviewResponse.model_validate(review)


# --- Routes 75-76: Summaries -----------------------------------------------


@performance_router.get(
    "/summary/{employee_id}", response_model=PerformanceSummaryDetailResponse | None
)
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def get_performance_summary(
    request: Request,
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(
        require_company_role(UserRole.hr_admin, UserRole.manager, UserRole.employee)
    ),
):
    service = PerformanceService(db)
    summary = service.get_summary(user.company_id, employee_id, actor=user)
    if summary is None:
        return None
    return PerformanceSummaryDetailResponse(**summary)


@performance_router.get("/summaries", response_model=Page[PerformanceSummaryResponse])
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def list_performance_summaries(
    request: Request,
    cycle_id: uuid.UUID = Query(...),
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role(UserRole.hr_admin, UserRole.manager)),
):
    service = PerformanceService(db)
    summaries, total, pages = service.list_summaries(user.company_id, cycle_id, params, actor=user)
    items = [PerformanceSummaryResponse.model_validate(s) for s in summaries]
    return Page(
        items=items,
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@performance_router.post("/summary/{employee_id}", response_model=PerformanceSummaryResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def finalize_performance_summary(
    request: Request,
    employee_id: uuid.UUID,
    data: SummaryFinalizeRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role(UserRole.hr_admin)),
):
    service = PerformanceService(db)
    summary = service.finalize_summary(user.company_id, employee_id, data, user)
    return PerformanceSummaryResponse.model_validate(summary)


# --- Performance Improvement Plan (PIP) Endpoints ---


@performance_router.post("/pips", response_model=PerformancePIPResponse, status_code=201)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def initiate_pip(
    request: Request,
    data: PIPCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role(UserRole.hr_admin, UserRole.manager)),
):
    service = PerformanceService(db)
    return service.create_pip(user.company_id, data, user)


@performance_router.post("/pips/{pip_id}/activate", response_model=PerformancePIPResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def activate_pip(
    request: Request,
    pip_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role(UserRole.hr_admin, UserRole.manager)),
):
    service = PerformanceService(db)
    return service.activate_pip(user.company_id, pip_id, user)


@performance_router.post("/pips/{pip_id}/extend", response_model=PerformancePIPResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def extend_pip(
    request: Request,
    pip_id: uuid.UUID,
    data: PIPExtendRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role(UserRole.hr_admin, UserRole.manager)),
):
    service = PerformanceService(db)
    return service.extend_pip(user.company_id, pip_id, data, user)


@performance_router.post(
    "/pips/{pip_id}/check-ins", response_model=PIPCheckInResponse, status_code=201
)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def add_pip_checkin(
    request: Request,
    pip_id: uuid.UUID,
    data: PIPCheckInCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role()),
):
    service = PerformanceService(db)
    checkin = service.add_pip_checkin(user.company_id, pip_id, data, user)
    return PIPCheckInResponse.model_validate(checkin)


@performance_router.get("/pips/{pip_id}/check-ins", response_model=list[PIPCheckInResponse])
def list_pip_checkins(
    pip_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role()),
):
    service = PerformanceService(db)
    checkins = service.list_pip_checkins(user.company_id, pip_id, user)
    return [PIPCheckInResponse.model_validate(c) for c in checkins]


@performance_router.get("/pips", response_model=list[PerformancePIPResponse])
def list_pips(
    employee_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role()),
):
    # Employees see their own, managers their reporting chain, HR level everyone.
    return PerformanceService(db).list_pips_for(user.company_id, user, employee_id, status_filter)


@performance_router.get("/pips/active/{employee_id}", response_model=PerformancePIPResponse | None)
def get_active_pip(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role()),
):
    return PerformanceService(db).get_active_pip_for(user.company_id, user, employee_id)


@performance_router.post("/pips/{pip_id}/evaluate", response_model=PerformancePIPResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def evaluate_pip(
    request: Request,
    pip_id: uuid.UUID,
    data: PIPEvaluateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_company_role(UserRole.hr_admin, UserRole.manager)),
):
    service = PerformanceService(db)
    return service.evaluate_pip(user.company_id, pip_id, data, user)
    service = PerformanceService(db)
    return service.evaluate_pip(user.company_id, pip_id, data, user)
