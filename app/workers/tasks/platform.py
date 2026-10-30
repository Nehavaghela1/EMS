"""Spec 13.1: `export_audit_logs_csv` — queued by `POST /audit-logs/export`
(route 129), same "unbounded row count" reason as attendance export.
Includes cleanup_expired_exports_task for removing exports older than 24h.
"""

import csv
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from datetime import date as date_cls

from app.core.config import settings
from app.core.csv_safety import csv_safe_cell
from app.core.exceptions import ExportTooLargeError
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.platform.repository import AuditRepository
from app.workers.celery_app import celery_app

logger = logging.getLogger("app")


def get_task_db_session():
    """Session factory for tasks. Overridable by tests."""
    return SessionLocal()


@celery_app.task(name="app.workers.tasks.platform.export_audit_logs_csv_task")
def export_audit_logs_csv_task(
    *,
    company_id: str,
    requester_id: str | None = None,
    action: str | None = None,
    actor_email: str | None = None,
    entity_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """13.2 rule 1: takes ids/strings, not objects. Rule 2: opens its own
    session and binds the tenant context. Rule 3: idempotent — re-running
    just regenerates the same export. Row cap enforced at 100,000.
    """
    db = get_task_db_session()
    try:
        cid = uuid.UUID(company_id)
        bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

        parsed_from = date_cls.fromisoformat(date_from) if date_from else None
        parsed_to = date_cls.fromisoformat(date_to) if date_to else None

        repo = AuditRepository(db)
        count = repo.count_for_export(
            company_id=cid,
            action=action,
            actor_email=actor_email,
            entity_type=entity_type,
            date_from=parsed_from,
            date_to=parsed_to,
        )
        if count > 100_000:
            raise ExportTooLargeError(
                "Audit log export exceeds maximum limit of 100,000 rows. "
                "Please narrow your search filters."
            )

        rows = repo.list_for_export(
            company_id=cid,
            action=action,
            actor_email=actor_email,
            entity_type=entity_type,
            date_from=parsed_from,
            date_to=parsed_to,
        )
        if len(rows) > 100_000:
            raise ExportTooLargeError(
                "Audit log export exceeds maximum limit of 100,000 rows. "
                "Please narrow your search filters."
            )

        os.makedirs(settings.EXPORT_DIR, exist_ok=True)
        file_name = f"audit_logs_{cid}_{uuid.uuid4().hex[:8]}.csv"
        file_path = os.path.join(settings.EXPORT_DIR, file_name)
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "created_at",
                    "actor_email",
                    "action",
                    "entity_type",
                    "entity_id",
                    "ip_address",
                    "request_id",
                    "details",
                ]
            )
            for row in rows:
                details_json = json.dumps(row.details) if row.details is not None else ""
                writer.writerow(
                    [
                        csv_safe_cell(row.created_at.isoformat()),
                        csv_safe_cell(row.actor_email or ""),
                        csv_safe_cell(row.action),
                        csv_safe_cell(row.entity_type or ""),
                        csv_safe_cell(str(row.entity_id) if row.entity_id else ""),
                        csv_safe_cell(str(row.ip_address) if row.ip_address else ""),
                        csv_safe_cell(str(row.request_id) if row.request_id else ""),
                        csv_safe_cell(details_json),
                    ]
                )

        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=24)

        logger.info(
            "audit_logs_csv_exported",
            extra={"company_id": company_id, "file_path": file_path, "row_count": len(rows)},
        )
        return {
            "company_id": company_id,
            "requester_id": requester_id,
            "file_path": file_path,
            "row_count": len(rows),
            "expires_at": expires_at.isoformat(),
        }
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.platform.cleanup_expired_exports_task")
def cleanup_expired_exports_task() -> int:
    """Removes files in settings.EXPORT_DIR older than 24 hours (by modified time)
    whose names start with a known export prefix (audit_logs_, employees_, attendance_);
    logs counts only.
    """
    export_dir = getattr(settings, "EXPORT_DIR", "var/exports")
    if not os.path.exists(export_dir):
        return 0

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    cutoff_ts = cutoff.timestamp()
    deleted_count = 0
    known_prefixes = ("audit_logs_", "employees_", "attendance_")

    for fname in os.listdir(export_dir):
        if not fname.startswith(known_prefixes):
            continue
        fpath = os.path.join(export_dir, fname)
        try:
            stat = os.stat(fpath)
            if stat.st_mtime < cutoff_ts:
                os.remove(fpath)
                deleted_count += 1
        except OSError as e:
            logger.warning(
                "failed_to_delete_expired_export",
                extra={"file_path": fpath, "error": str(e)},
            )

    logger.info("expired_exports_cleaned", extra={"deleted_count": deleted_count})
    return deleted_count
