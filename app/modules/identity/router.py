import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.pagination import Page, PageParams, page_params
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.modules.identity.models import CompanyStatus, User, UserRole
from app.modules.identity.schemas import (
    CompanyApproveResponse,
    CompanyDetailResponse,
    CompanyProfileUpdateRequest,
    CompanyRegisterRequest,
    CompanyRejectRequest,
    CompanyResponse,
    LoginRequest,
    TokenResponse,
)
from app.modules.identity.service import AuthService, CompanyService

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


# --- Companies (10.2 routes 12-18) -----------------------------------------

companies_router = APIRouter(prefix="/companies", tags=["Companies"])


@companies_router.post("/register", response_model=CompanyResponse, status_code=201)
def register_company(data: CompanyRegisterRequest, db: Session = Depends(get_db)):
    return CompanyService(db).register_company(data)


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


@companies_router.get("/{company_id}", response_model=CompanyDetailResponse)
def get_company_detail(
    company_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _admin: User = Depends(require_role(UserRole.super_admin)),
):
    company, counts = CompanyService(db).get_company_detail(company_id)
    return CompanyDetailResponse(
        **CompanyResponse.model_validate(company).model_dump(),
        phone=company.phone,
        rejection_reason=company.rejection_reason,
        approved_at=company.approved_at,
        counts=counts,
    )


@companies_router.post("/{company_id}/approve", response_model=CompanyApproveResponse)
def approve_company(
    company_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    admin: User = Depends(require_role(UserRole.super_admin)),
):
    company, hr_admin_email, temporary_password = CompanyService(db).approve_company(
        company_id, admin.id
    )
    return CompanyApproveResponse(
        company=CompanyResponse.model_validate(company),
        hr_admin_email=hr_admin_email,
        temporary_password=temporary_password,
    )


@companies_router.post("/{company_id}/reject", response_model=CompanyResponse)
def reject_company(
    company_id: uuid.UUID,
    data: CompanyRejectRequest,
    db: Session = Depends(get_tenant_db),
    _admin: User = Depends(require_role(UserRole.super_admin)),
):
    return CompanyService(db).reject_company(company_id, data.reason)
