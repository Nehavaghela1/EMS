"""Spec 13.1: `export_attendance_csv` — queued by `POST /attendance/export`
(route 49), unbounded row count is why it's a background job at all."""

import csv
import logging
import os
import uuid
from datetime import date as date_cls

from app.core.config import settings
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.hr.models import Employee
from app.modules.time_leave.models import AttendanceStatus
from app.modules.time_leave.repository import AttendanceRepository
from app.workers.celery_app import celery_app

logger = logging.getLogger("app")


@celery_app.task(name="app.workers.tasks.attendance.export_attendance_csv_task")
def export_attendance_csv_task(
    *,
    company_id: str,
    employee_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    department_id: str | None = None,
) -> dict:
    """13.2 rule 1: takes ids (strings — ORM objects don't serialize and
    would be stale by the time this runs), not objects. 13.2 rule 2: opens
    its own session and binds the tenant context — there is no HTTP request
    to inherit it from, and `bind_tenant_to_session` (not the one-shot
    `set_tenant_context`) keeps it applied across the whole task even
    though this one doesn't itself commit mid-task. 13.2 rule 3: idempotent
    — re-running just regenerates the same export, no state to double-write.
    """
    db = SessionLocal()
    try:
        cid = uuid.UUID(company_id)
        bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

        repo = AttendanceRepository(db)
        rows = repo.list_for_export(
            company_id=cid,
            employee_id=uuid.UUID(employee_id) if employee_id else None,
            date_from=date_cls.fromisoformat(date_from) if date_from else None,
            date_to=date_cls.fromisoformat(date_to) if date_to else None,
            status=AttendanceStatus(status) if status else None,
            department_id=uuid.UUID(department_id) if department_id else None,
        )

        employee_ids = {r.employee_id for r in rows}
        employees: dict[uuid.UUID, Employee] = {}
        if employee_ids:
            for employee_row in db.query(Employee).filter(Employee.id.in_(employee_ids)).all():
                employees[employee_row.id] = employee_row

        os.makedirs(settings.EXPORT_DIR, exist_ok=True)
        file_name = f"attendance_{cid}_{uuid.uuid4().hex[:8]}.csv"
        file_path = os.path.join(settings.EXPORT_DIR, file_name)
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "employee_code",
                    "first_name",
                    "last_name",
                    "date",
                    "check_in",
                    "check_out",
                    "status",
                    "hours_worked",
                    "source",
                ]
            )
            for row in rows:
                emp = employees.get(row.employee_id)
                writer.writerow(
                    [
                        emp.employee_code if emp else "",
                        emp.first_name if emp else "",
                        emp.last_name if emp else "",
                        row.date.isoformat(),
                        row.check_in.isoformat() if row.check_in else "",
                        row.check_out.isoformat() if row.check_out else "",
                        row.status.value,
                        str(row.hours_worked) if row.hours_worked is not None else "",
                        row.source.value,
                    ]
                )

        logger.info(
            "attendance_csv_exported",
            extra={"company_id": company_id, "file_path": file_path, "row_count": len(rows)},
        )
        return {"file_path": file_path, "row_count": len(rows)}
    finally:
        db.close()
