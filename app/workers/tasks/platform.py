"""Spec 13.1: `export_audit_logs_csv` — queued by `POST /audit-logs/export`
(route 129), same "unbounded row count" reason as attendance export."""

import csv
import logging
import os
import uuid
from datetime import date as date_cls

from app.core.config import settings
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.platform.repository import AuditRepository
from app.workers.celery_app import celery_app

logger = logging.getLogger("app")


@celery_app.task(name="app.workers.tasks.platform.export_audit_logs_csv_task")
def export_audit_logs_csv_task(
    *,
    company_id: str,
    action: str | None = None,
    actor_email: str | None = None,
    entity_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """13.2 rule 1: takes ids/strings, not objects. Rule 2: opens its own
    session and binds the tenant context. Rule 3: idempotent — re-running
    just regenerates the same export.

    `audit_logs` has no RLS (7.8) — `AuditRepository` filters by
    `company_id` explicitly, same as the request-time read path, so
    `bind_tenant_to_session` here is for consistency with every other task
    rather than something this specific query depends on.
    """
    db = SessionLocal()
    try:
        cid = uuid.UUID(company_id)
        bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

        repo = AuditRepository(db)
        rows = repo.list_for_export(
            company_id=cid,
            action=action,
            actor_email=actor_email,
            entity_type=entity_type,
            date_from=date_cls.fromisoformat(date_from) if date_from else None,
            date_to=date_cls.fromisoformat(date_to) if date_to else None,
        )

        os.makedirs(settings.EXPORT_DIR, exist_ok=True)
        file_name = f"audit_logs_{cid}_{uuid.uuid4().hex[:8]}.csv"
        file_path = os.path.join(settings.EXPORT_DIR, file_name)
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "created_at",
                    "actor_email",
                    "action",
                    "entity_type",
                    "entity_id",
                    "details",
                ]
            )
            for row in rows:
                writer.writerow(
                    [
                        row.created_at.isoformat(),
                        row.actor_email or "",
                        row.action,
                        row.entity_type or "",
                        str(row.entity_id) if row.entity_id else "",
                        row.details or "",
                    ]
                )

        logger.info(
            "audit_logs_csv_exported",
            extra={"company_id": company_id, "file_path": file_path, "row_count": len(rows)},
        )
        return {"company_id": company_id, "file_path": file_path, "row_count": len(rows)}
    finally:
        db.close()
