import redis
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware, SecurityHeadersMiddleware
from app.core.rate_limit import limiter
from app.db.session import SessionLocal
from app.modules.hr.router import departments_router, employees_router
from app.modules.identity.router import companies_router
from app.modules.identity.router import router as auth_router
from app.modules.platform.router import audit_logs_router, dashboard_router, notifications_router
from app.modules.platform.router import router as jobs_router
from app.modules.time_leave.router import (
    attendance_router,
    holidays_router,
    leave_types_router,
    leaves_router,
    shifts_router,
)

configure_logging()

app = FastAPI(
    title=settings.APP_NAME,
    description="HRMS + Payroll + Projects — Multi-Tenant SaaS Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter

# Middleware order matters: add_middleware stacks LIFO, so the LAST one added
# is OUTERMOST — it sees the request first and the response last. This
# mirrors the request lifecycle in Spec 5.1: CORS outermost (so a preflight
# OPTIONS is handled before anything else runs) -> rate limit -> request-id.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # explicit list from config — never "*" (9.7)
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-Request-ID",
        "X-Requested-With",
    ],
)

register_exception_handlers(app)

# Every route lives under /api/v1 (Spec 6.9) — set once, here, not per-router.
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(companies_router, prefix=settings.API_V1_PREFIX)
app.include_router(departments_router, prefix=settings.API_V1_PREFIX)
app.include_router(employees_router, prefix=settings.API_V1_PREFIX)
app.include_router(attendance_router, prefix=settings.API_V1_PREFIX)
app.include_router(shifts_router, prefix=settings.API_V1_PREFIX)
app.include_router(holidays_router, prefix=settings.API_V1_PREFIX)
app.include_router(leave_types_router, prefix=settings.API_V1_PREFIX)
app.include_router(leaves_router, prefix=settings.API_V1_PREFIX)
app.include_router(jobs_router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboard_router, prefix=settings.API_V1_PREFIX)
app.include_router(audit_logs_router, prefix=settings.API_V1_PREFIX)
app.include_router(notifications_router, prefix=settings.API_V1_PREFIX)

# One client, reused across requests (redis-py pools connections internally).
# Short timeouts so a dead Redis makes /health fail fast, not hang.
_redis_client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)


@app.get("/health")
def health_check(response: Response) -> dict:
    """200 only when the app, PostgreSQL and Redis are all reachable, with a
    per-dependency breakdown and the app version (16.4). Hosting platforms
    use this for restarts, so it must be honest — never a hardcoded "ok".
    """
    checks: dict[str, str] = {}

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 — a health check must not crash on a dead dependency
        checks["database"] = f"error: {exc}"

    try:
        _redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc}"

    healthy = all(value == "ok" for value in checks.values())
    response.status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if healthy else "unavailable",
        "version": app.version,
        "environment": settings.ENVIRONMENT,
        "checks": checks,
    }
