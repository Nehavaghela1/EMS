from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.modules.identity.schemas import (
    CompanyRegisterRequest,
    CompanyResponse,
    LoginRequest,
    TokenResponse,
)
from app.modules.identity.service import AuthService

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


@router.post("/register", response_model=CompanyResponse, status_code=201)
def register_company(data: CompanyRegisterRequest, db: Session = Depends(get_db)):
    return AuthService(db).register_company(data)


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
