"""WP-11 route 129: `export_audit_logs_csv_task`'s own business logic — same
pattern as test_attendance_export.py (a real, separate test-database
session, not the savepoint-scoped `db` fixture, since the task opens its
own session exactly as production does).
"""

import csv
import os
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.rls import bind_tenant_to_session
from app.modules.identity.models import Company, CompanyStatus
from app.modules.platform.models import AuditLog


def test_export_audit_logs_csv_task_writes_a_real_csv_file(tmp_path, monkeypatch):
    engine = create_engine(settings.TEST_DATABASE_URL)
    monkeypatch.setattr("app.workers.tasks.platform.SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))

    company_id: uuid.UUID | None = None
    try:
        with Session(engine) as setup:
            company = Company(
                name="Audit Export Co",
                code=f"AEXP{uuid.uuid4().hex[:5].upper()}",
                email=f"auditexport-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
            )
            setup.add(company)
            setup.flush()
            bind_tenant_to_session(setup, company_id=company.id, is_platform_admin=False)
            setup.add(
                AuditLog(
                    company_id=company.id,
                    actor_email="hr@auditexport.com",
                    action="EMPLOYEE_CREATED",
                    entity_type="employee",
                )
            )
            setup.commit()
            company_id = company.id

        from app.workers.tasks.platform import export_audit_logs_csv_task

        result = export_audit_logs_csv_task(company_id=str(company_id))

        assert result["row_count"] == 1
        assert os.path.exists(result["file_path"])
        with open(result["file_path"]) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["actor_email"] == "hr@auditexport.com"
        assert rows[0]["action"] == "EMPLOYEE_CREATED"
    finally:
        # ems_app has no DELETE grant on audit_logs (append-only, Spec 7.8) —
        # cleanup connects as ems_owner instead, same as
        # test_audit_log_append_only.py's cleanup.
        if company_id is not None:
            owner_engine = create_engine(settings.TEST_MIGRATION_URL)
            try:
                with Session(owner_engine) as cleanup:
                    cleanup.query(AuditLog).filter(AuditLog.company_id == company_id).delete()
                    cleanup.query(Company).filter(Company.id == company_id).delete()
                    cleanup.commit()
            finally:
                owner_engine.dispose()
        engine.dispose()
