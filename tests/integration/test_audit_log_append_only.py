"""Spec 7.8: `audit_logs` is append-only at the database level, not merely by
convention. Proved with a real, separate connection authenticated as
`ems_app` (the runtime role) — the savepoint-scoped `db` fixture shares one
connection and would never actually exercise the REVOKE this migration
issued, the same reasoning `test_employee_code_concurrency.py` documents for
real row-locking.
"""

import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import settings


def test_ems_app_can_insert_but_not_update_or_delete_audit_logs():
    engine = create_engine(settings.TEST_DATABASE_URL)
    log_id = uuid.uuid4()
    try:
        with Session(engine) as session:
            session.execute(
                text(
                    "INSERT INTO audit_logs (id, company_id, action, created_at, updated_at) "
                    "VALUES (:id, NULL, 'TEST_APPEND_ONLY', now(), now())"
                ),
                {"id": str(log_id)},
            )
            session.commit()

        with Session(engine) as session:
            try:
                session.execute(
                    text("UPDATE audit_logs SET action = 'TAMPERED' WHERE id = :id"),
                    {"id": str(log_id)},
                )
                session.commit()
                update_raised = False
            except ProgrammingError:
                session.rollback()
                update_raised = True
        assert update_raised, "ems_app must not be able to UPDATE audit_logs"

        with Session(engine) as session:
            try:
                session.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": str(log_id)})
                session.commit()
                delete_raised = False
            except ProgrammingError:
                session.rollback()
                delete_raised = True
        assert delete_raised, "ems_app must not be able to DELETE audit_logs"
    finally:
        # Cleanup connects as ems_owner (TEST_MIGRATION_URL) — ems_app itself
        # can never delete this row, by design; that's exactly what was proved.
        owner_engine = create_engine(settings.TEST_MIGRATION_URL)
        try:
            with Session(owner_engine) as cleanup:
                cleanup.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": str(log_id)})
                cleanup.commit()
        finally:
            owner_engine.dispose()
        engine.dispose()
