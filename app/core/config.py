from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every configuration value comes from here — no `os.getenv` anywhere else
    in the codebase (Spec 17.1). A required field with no default means the
    application fails to start if it's missing; that is deliberate.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Application ─────────────────────────────────────────────
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    APP_NAME: str = "EMS Pro"
    API_V1_PREFIX: str = "/api/v1"

    # ── Database ────────────────────────────────────────────────
    # Runtime role: NOT the table owner, NOT superuser, NOBYPASSRLS (Spec 8.2)
    DATABASE_URL: str
    # Migration role: owns the schema, used only by Alembic
    ALEMBIC_DATABASE_URL: str
    # Tests connect as the APPLICATION role, so RLS and grants are actually
    # exercised (15.2). Optional here — only conftest.py needs them.
    TEST_DATABASE_URL: str | None = None
    TEST_MIGRATION_URL: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    # ── Redis ───────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # ── Security ────────────────────────────────────────────────
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ENCRYPTION_KEY: str | None = None
    ENCRYPTION_KEY_VERSION: int = 1
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15
    # Employee invite/activation tokens (Spec 7.3 `activation_expires_at`) —
    # no TTL is named in the spec, so this follows the same
    # settings-not-a-literal convention as the other token lifetimes above.
    INVITE_TOKEN_EXPIRE_DAYS: int = 7
    # Password-reset OTPs (Spec 7.9): 10-minute TTL, 5-attempt cap, both
    # spec-literal numbers, kept as settings rather than inline for the same
    # reason MAX_LOGIN_ATTEMPTS/LOCKOUT_MINUTES are.
    OTP_TTL_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    # Password policy (Spec 9.1): minimum length, enforced in the Pydantic
    # schema layer so it fails at the edge with a clear message.
    PASSWORD_MIN_LENGTH: int = 10

    # ── CORS ────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # ── Email ───────────────────────────────────────────────────
    EMAIL_BACKEND: Literal["console", "sendgrid"] = "console"
    SENDGRID_API_KEY: str | None = None
    EMAIL_FROM: str = "noreply@example.com"
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # ── File storage ────────────────────────────────────────────
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    S3_BUCKET: str | None = None
    S3_REGION: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    MAX_UPLOAD_MB: int = 10

    # ── Observability ───────────────────────────────────────────
    SENTRY_DSN: str | None = None
    LOG_LEVEL: str = "INFO"

    # ── Background jobs (Spec 13) ────────────────────────────────
    # Where a Celery export task writes its output file, local-storage mode
    # (STORAGE_BACKEND=local). A real object-store path is a WP-08+/S3
    # concern; this is the interim, explicit, settings-driven location.
    EXPORT_DIR: str = "var/exports"

    # ── Dashboard cache (Spec 11.10) ─────────────────────────────
    DASHBOARD_CACHE_TTL_SECONDS: int = 60

    # ── Platform defaults for NEW companies ─────────────────────
    # Seed a company's company_settings row at approval time and are never
    # read again afterwards. Per-tenant policy lives in company_settings
    # (7.2), not here.
    DEFAULT_COUNTRY: str = "IN"
    DEFAULT_CURRENCY: str = "INR"
    DEFAULT_WORKING_WEEK_DAYS: int = 5
    DEFAULT_HALF_DAY_HOURS_THRESHOLD: float = 4


# mypy doesn't know pydantic-settings populates required fields from the
# environment, so it sees a no-arg call to a class with required fields.
settings = Settings()  # type: ignore[call-arg]
