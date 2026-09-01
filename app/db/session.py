from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    echo=settings.DB_ECHO,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # A failed statement (e.g. an IntegrityError a handler converts to a
        # clean 409) leaves the transaction "aborted" in Postgres — no
        # further statement can run on it until rolled back. In production
        # each request gets a fresh session, so db.close() alone would mask
        # this; it matters the moment anything reuses a session across
        # requests, which the test suite's shared-session client fixture
        # does deliberately (15.2). Roll back before closing either way.
        db.rollback()
        raise
    finally:
        db.close()
