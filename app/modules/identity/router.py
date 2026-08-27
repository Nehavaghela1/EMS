from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.identity.schemas import (
    CompanyRegisterRequest,
    CompanyResponse,
    LoginRequest,
    TokenResponse,
    RefreshRequest,
)
from app.modules.identity.service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=CompanyResponse, status_code=201)
def register_company(data: CompanyRegisterRequest, db: Session = Depends(get_db)):
    return AuthService(db).register_company(data)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    return AuthService(db).login(data)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(data: RefreshRequest, db: Session = Depends(get_db)):
    return AuthService(db).refresh(data.refresh_token)