from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.modules.identity.router import router as auth_router

app = FastAPI(
    title="EMS Pro",
    description="HRMS + Payroll + Projects — Multi-Tenant SaaS Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every route lives under /api/v1 (Spec 6.9) — set once, here, not per-router.
API_V1_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=API_V1_PREFIX)


@app.get("/health")
def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}