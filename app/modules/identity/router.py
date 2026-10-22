import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.exceptions import NotFoundError
from app.core.otp import check_and_increment_account_limit
from app.core.pagination import Page, PageParams, page_params
from app.core.rate_limit import get_user_or_ip_key, limiter
from app.db.session import get_db
from app.modules.identity.models import CompanyStatus, User, UserRole
from app.modules.identity.schemas import (
    ActivateAccountRequest,
    ActivationPreviewResponse,
    AdminCompanyUpdateRequest,
    AdminUserResponse,
    ChangePasswordRequest,
    CompanyApproveResponse,
    CompanyDeactivateRequest,
    CompanyDetailResponse,
    CompanyLocationCreate,
    CompanyLocationResponse,
    CompanyLocationUpdate,
    CompanyProfileUpdateRequest,
    CompanyRegisterRequest,
    CompanyRejectRequest,
    CompanyResponse,
    CreateWorkspaceRequest,
    CreateWorkspaceResponse,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    ResetPasswordRequest,
    SwitchWorkspaceRequest,
    TokenResponse,
    UsernameAvailabilityResponse,
    UserRoleUpdateRequest,
    UserWorkspaceResponse,
)
from app.modules.identity.service import AuthService, CompanyService, LocationService
from app.workers.tasks.identity import process_password_reset_request

router = APIRouter(prefix="/auth", tags=["Authentication"])

REFRESH_COOKIE_NAME = "refresh_token"
# Matches this router's own mount point (Spec 9.2's exact example path) — the
# cookie is never sent to any other endpoint.
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, raw_refresh: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh,
        httponly=True,
        # Secure is omitted only on local development (9.2).
        secure=settings.ENVIRONMENT != "development",
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")  # Spec 9.5 — blocks credential-stuffing
def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    result, raw_refresh = AuthService(db).login(data, device_info=request.headers.get("user-agent"))
    _set_refresh_cookie(response, raw_refresh)  # httpOnly cookie — never in the JSON body (9.2)
    return result


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")  # Spec 9.5
def refresh_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    # An empty/missing cookie fails the same lookup a forged one would (no
    # matching token_hash), so the service's usual "invalid or expired" path
    # handles it — no separate branch needed here.
    raw_refresh = request.cookies.get(REFRESH_COOKIE_NAME, "")
    result, new_raw_refresh = AuthService(db).refresh(raw_refresh)
    _set_refresh_cookie(response, new_raw_refresh)
    return result


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    raw_refresh = request.cookies.get(REFRESH_COOKIE_NAME, "")
    AuthService(db).logout(raw_refresh)
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


@router.post("/logout-all", status_code=204)
def logout_all(
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    AuthService(db).logout_all(user.id)
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


@router.get("/me", response_model=MeResponse)
def get_me(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return AuthService(db).get_me(user)


@router.get("/workspaces", response_model=list[UserWorkspaceResponse])
def get_user_workspaces(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return AuthService(db).get_user_workspaces(user.email)


@router.post("/switch-workspace", response_model=TokenResponse)
@limiter.limit("20/minute", key_func=get_user_or_ip_key)
def switch_workspace(
    data: SwitchWorkspaceRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result, raw_refresh = AuthService(db).switch_workspace(
        user.email,
        data.company_id,
        device_info=request.headers.get("user-agent"),
        caller=user,
    )
    _set_refresh_cookie(response, raw_refresh)
    return result


@router.post("/change-password", status_code=204)
@limiter.limit("5/minute")
def change_password(
    data: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    AuthService(db).change_password(user, data)


@router.post("/forgot-password", status_code=200)
@limiter.limit("3/hour")  # Spec 9.5 — per-IP limit on sending real email/OTPs
def forgot_password(data: ForgotPasswordRequest, request: Request):
    """F1 & F2: Constant handler work and per-account rate limit.
    Redis counter key sha256(lower(email)), atomic counter + expiry via pipeline, limit 3.
    Counts every request, including unknown emails.
    Over the limit: same reply, no email, no new code, no lockout.
    Under limit: enqueues process_password_reset_request.
    If enqueue raises or Redis raises: catch it, log password_reset_enqueue_failed
    on app.security at ERROR with type(exc).__name__, return same reply.
    """
    sec_logger = logging.getLogger("app.security")
    email_hash_val = hashlib.sha256(data.email.lower().strip().encode()).hexdigest()[:12]
    req_id = getattr(request.state, "request_id", None) if hasattr(request, "state") else None

    # Increment per-account counter; handle Redis errors gracefully
    try:
        count = check_and_increment_account_limit(data.email, limit=3, window_seconds=3600)
    except Exception as exc:
        sec_logger.error(
            "Failed to increment account rate limit counter",
            extra={
                "event": "password_reset_enqueue_failed",
                "email_hash": email_hash_val,
                "request_id": req_id,
                "error": type(exc).__name__,
            },
        )
        return {"message": "If that email exists, a password reset code has been sent."}

    if count > 3:
        # F7: password_reset_rate_limited
        sec_logger.warning(
            "Password reset request rate-limited per-account",
            extra={
                "event": "password_reset_rate_limited",
                "email_hash": email_hash_val,
                "request_id": req_id,
            },
        )
        return {"message": "If that email exists, a password reset code has been sent."}

    # Enqueue task
    try:
        process_password_reset_request.delay(email=data.email, company_code=data.company_code)
    except Exception as exc:
        sec_logger.error(
            "Failed to enqueue password reset task",
            extra={
                "event": "password_reset_enqueue_failed",
                "email_hash": email_hash_val,
                "request_id": req_id,
                "error": type(exc).__name__,
            },
        )

    return {"message": "If that email exists, a password reset code has been sent."}


@router.post("/reset-password", status_code=204)
@limiter.limit("10/minute")
def reset_password(data: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    AuthService(db).reset_password(data)


@router.get("/check-username/{username}", response_model=UsernameAvailabilityResponse)
@limiter.limit("20/minute")  # Spec 9.5
def check_username(username: str, request: Request, token: str, db: Session = Depends(get_db)):
    available = AuthService(db).check_username_available(username, raw_token=token)
    return UsernameAvailabilityResponse(available=available)


@router.get("/activate/{token}", response_model=ActivationPreviewResponse)
@limiter.limit("20/minute")
def preview_activation(token: str, request: Request, db: Session = Depends(get_db)):
    employee, company = AuthService(db).preview_activation(token)
    # AuthService.preview_activation already raises when this is None/expired.
    assert employee.activation_expires_at is not None
    return ActivationPreviewResponse(
        first_name=employee.first_name,
        last_name=employee.last_name,
        company_name=company.name,
        expires_at=employee.activation_expires_at,
    )


@router.post("/activate", response_model=TokenResponse)
@limiter.limit("10/minute")
def activate(
    data: ActivateAccountRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    result, raw_refresh = AuthService(db).activate_employee(data)
    _set_refresh_cookie(response, raw_refresh)
    return result


# --- Companies (10.2 routes 12-18) -----------------------------------------

companies_router = APIRouter(prefix="/companies", tags=["Companies"])


@companies_router.post("/register", response_model=CompanyResponse, status_code=201)
@limiter.limit("5/hour")
def register_company(
    data: CompanyRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    return CompanyService(db).register_company(data)


@companies_router.post("/workspaces", response_model=CreateWorkspaceResponse, status_code=201)
@limiter.limit("5/hour", key_func=get_user_or_ip_key)
def create_workspace(
    data: CreateWorkspaceRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.owner, UserRole.hr_admin)),
):
    company, token_response, raw_refresh = CompanyService(db).create_workspace(
        user, data, device_info=request.headers.get("user-agent")
    )
    _set_refresh_cookie(response, raw_refresh)
    return CreateWorkspaceResponse(
        company=CompanyResponse.model_validate(company),
        access_token=token_response.access_token,
        token_type=token_response.token_type,
    )


@companies_router.get("", response_model=Page[CompanyResponse])
def list_companies(
    status: CompanyStatus | None = None,
    q: str | None = None,
    country: str | None = None,
    sort: str | None = None,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    _admin: User = Depends(require_role(UserRole.super_admin)),
):
    items, total, pages = CompanyService(db).list_companies(
        status=status, q=q, country=country, sort=sort, page_params=params
    )
    return Page(
        items=items,
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@companies_router.get("/me", response_model=CompanyResponse)
def get_my_company(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return CompanyService(db).get_my_company(user.company_id)


@companies_router.put("/me", response_model=CompanyResponse)
def update_my_company(
    data: CompanyProfileUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    return CompanyService(db).update_my_company(user.company_id, data)


# --- Locations (defined before /{company_id} routes to prevent path capture) ---
@companies_router.get("/locations", response_model=list[CompanyLocationResponse])
def list_locations(
    is_active: bool | None = None,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return LocationService(db).list_locations(user.company_id, is_active=is_active)


@companies_router.post("/locations", response_model=CompanyLocationResponse, status_code=201)
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def create_location(
    request: Request,
    data: CompanyLocationCreate,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.owner, UserRole.hr_admin)),
):
    return LocationService(db).create_location(user.company_id, data, actor=user)


@companies_router.put("/locations/{location_id}", response_model=CompanyLocationResponse)
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def update_location(
    request: Request,
    location_id: uuid.UUID,
    data: CompanyLocationUpdate,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.owner, UserRole.hr_admin)),
):
    return LocationService(db).update_location(user.company_id, location_id, data, actor=user)


@companies_router.delete("/locations/{location_id}", response_model=CompanyLocationResponse)
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def deactivate_location(
    request: Request,
    location_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.owner, UserRole.hr_admin)),
):
    return LocationService(db).deactivate_location(user.company_id, location_id, actor=user)


@companies_router.post("/locations/{location_id}/set-head-office", response_model=CompanyLocationResponse)
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def set_head_office(
    request: Request,
    location_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.owner, UserRole.hr_admin)),
):
    return LocationService(db).set_head_office(user.company_id, location_id, actor=user)


@companies_router.get("/{company_id}", response_model=CompanyDetailResponse)
def get_company_detail(
    company_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _admin: User = Depends(require_role(UserRole.super_admin)),
):
    company, counts = CompanyService(db).get_company_detail(company_id)
    base_data = CompanyResponse.model_validate(company).model_dump()
    return CompanyDetailResponse(
        **base_data,
        rejection_reason=company.rejection_reason,
        approved_at=company.approved_at,
        counts=counts,
    )


@companies_router.put("/{company_id}", response_model=CompanyResponse)
def update_company(
    company_id: uuid.UUID,
    data: AdminCompanyUpdateRequest,
    db: Session = Depends(get_tenant_db),
    _admin: User = Depends(require_role(UserRole.super_admin)),
):
    return CompanyService(db).update_company_by_admin(company_id, data)


@companies_router.post("/{company_id}/approve", response_model=CompanyApproveResponse)
def approve_company(
    company_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    admin: User = Depends(require_role(UserRole.super_admin)),
):
    company, hr_admin_email = CompanyService(db).approve_company(company_id, admin.id)
    return CompanyApproveResponse(
        company=CompanyResponse.model_validate(company),
        hr_admin_email=hr_admin_email,
    )


@companies_router.post("/{company_id}/reject", response_model=CompanyResponse)
def reject_company(
    company_id: uuid.UUID,
    data: CompanyRejectRequest,
    db: Session = Depends(get_tenant_db),
    admin: User = Depends(require_role(UserRole.super_admin)),
):
    return CompanyService(db).reject_company(company_id, data.reason, admin_user=admin)


@companies_router.post("/{company_id}/deactivate")
def deactivate_company(
    company_id: uuid.UUID,
    data: CompanyDeactivateRequest,
    current_user: User = Depends(require_role(UserRole.owner, UserRole.super_admin)),
    db: Session = Depends(get_tenant_db),
):
    return CompanyService(db).deactivate_company(
        company_id=company_id,
        reason=data.reason,
        actor=current_user,
        password=data.password,
    )


@companies_router.post("/{company_id}/reactivate", response_model=CompanyResponse)
def reactivate_company(
    company_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    admin: User = Depends(require_role(UserRole.super_admin)),
):
    company = CompanyService(db).reactivate_company(company_id=company_id, actor=admin)
    return CompanyResponse.model_validate(company)


# --- Users ---
users_router = APIRouter(prefix="/users", tags=["Users"])


@users_router.patch("/{user_id}/role")
def update_user_role(
    user_id: uuid.UUID,
    data: UserRoleUpdateRequest,
    current_user: User = Depends(require_role(UserRole.owner)),
    db: Session = Depends(get_tenant_db),
):
    if user_id == current_user.id:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Cannot change your own role.")

    if data.role not in [UserRole.employee, UserRole.hr_admin]:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400, detail="Can only promote to hr_admin or demote to employee."
        )

    user = (
        db.query(User)
        .filter(User.id == user_id, User.company_id == current_user.company_id)
        .first()
    )
    if not user:
        raise NotFoundError("User not found.")

    user.role = data.role
    db.commit()
    return {"message": f"User role updated to {data.role.value}"}


@users_router.get("/administrators", response_model=list[AdminUserResponse])
def list_administrators(
    current_user: User = Depends(require_role(UserRole.owner, UserRole.hr_admin)),
    db: Session = Depends(get_tenant_db),
):
    """Return all users in the tenant who hold an administrative role (owner or hr_admin).
    Used by the Settings > Manage Admins card. Accessible to owner and hr_admin.
    """

    from app.modules.hr.models import Employee as EmployeeModel

    # Fetch all admin users in the tenant
    admin_users = (
        db.query(User)
        .filter(
            User.company_id == current_user.company_id,
            User.role.in_([UserRole.owner, UserRole.hr_admin]),
        )
        .all()
    )

    # Build response — join employee names where available
    result: list[AdminUserResponse] = []
    for u in admin_users:
        emp = None
        if u.id:
            emp = (
                db.query(EmployeeModel)
                .filter(
                    EmployeeModel.user_id == u.id,
                    EmployeeModel.company_id == current_user.company_id,
                    EmployeeModel.deleted_at.is_(None),
                )
                .first()
            )
        result.append(
            AdminUserResponse(
                id=u.id,
                email=u.email,
                role=u.role,
                first_name=emp.first_name if emp else None,
                last_name=emp.last_name if emp else None,
                employee_id=emp.id if emp else None,
                position=emp.position if emp else None,
                hire_date=str(emp.hire_date) if emp and emp.hire_date else None,
            )
        )
    return result
