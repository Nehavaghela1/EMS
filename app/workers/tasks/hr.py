"""Celery tasks for HR module: employee CSV export, etc."""

import csv
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.csv_safety import csv_safe_cell
from app.core.exceptions import ExportTooLargeError
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.hr.models import Employee, EmploymentType
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import CompanyLocation, UserRole
from app.workers.celery_app import celery_app

logger = logging.getLogger("app")


def get_task_db_session():
    """Session factory for tasks. Overridable by tests."""
    return SessionLocal()


@celery_app.task(name="app.workers.tasks.hr.export_employees_csv_task")
def export_employees_csv_task(
    *,
    company_id: str,
    actor_id: str,
    actor_role: str,
    q: str | None = None,
    department_id: str | None = None,
    is_active: bool | None = None,
    level: str | None = None,
    employment_type: str | None = None,
    reporting_manager_id: str | None = None,
    role: str | None = None,
    employee_ids: list[str] | None = None,
) -> dict:
    """13.2: opens its own session and binds tenant context.
    Streams CSV with UTF-8 BOM and formula sanitization.
    Row cap at 50,000.
    """
    db = get_task_db_session()
    try:
        cid = uuid.UUID(company_id)
        bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

        repo = EmployeeRepository(db)
        direct_report_ids = None
        if actor_role == UserRole.manager.value:
            mgr_user_id = uuid.UUID(actor_id)
            mgr_emp = repo.get_by_user_id(cid, mgr_user_id)
            if mgr_emp:
                direct_report_ids = repo.list_direct_report_ids(cid, mgr_emp.id)
            else:
                direct_report_ids = []

        selected_uuids = [uuid.UUID(x) for x in employee_ids] if employee_ids else None
        emp_type_enum = EmploymentType(employment_type) if employment_type else None

        max_rows = getattr(settings, "MAX_EXPORT_ROWS", 50000)
        # Fetch up to max_rows + 1 to detect overflow without silent truncation
        employees = repo.list_for_export(
            company_id=cid,
            q=q,
            department_id=uuid.UUID(department_id) if department_id else None,
            is_active=is_active,
            level=level,
            employment_type=emp_type_enum,
            reporting_manager_id=uuid.UUID(reporting_manager_id) if reporting_manager_id else None,
            role=role,
            employee_ids=selected_uuids,
            direct_report_ids=direct_report_ids,
            limit=max_rows + 1,
        )

        if len(employees) > max_rows:
            raise ExportTooLargeError(
                f"Export result exceeds maximum row limit of {max_rows}. "
                "Please narrow your search filters."
            )

        os.makedirs(settings.EXPORT_DIR, exist_ok=True)
        # B2: random uuid4 hex, no company id, no sequential parts
        file_name = f"{uuid.uuid4().hex}.csv"
        file_path = os.path.join(settings.EXPORT_DIR, file_name)

        is_hr_or_owner = actor_role in (
            UserRole.owner.value,
            UserRole.hr_admin.value,
            UserRole.super_admin.value,
        )

        # Build department & location & manager lookup maps
        dept_ids = {e.department_id for e in employees if e.department_id}
        loc_ids = {e.location_id for e in employees if e.location_id}
        mgr_ids = {e.reporting_manager_id for e in employees if e.reporting_manager_id}

        from app.modules.hr.models import Department

        depts = db.query(Department).filter(Department.id.in_(dept_ids)).all() if dept_ids else []
        dept_map = {d.id: d.name for d in depts}

        locs = (
            db.query(CompanyLocation).filter(CompanyLocation.id.in_(loc_ids)).all()
            if loc_ids
            else []
        )
        loc_map = {loc.id: loc.name for loc in locs}

        mgrs = db.query(Employee).filter(Employee.id.in_(mgr_ids)).all() if mgr_ids else []
        mgr_map = {m.id: f"{m.first_name} {m.last_name or ''}".strip() for m in mgrs}

        if is_hr_or_owner:
            headers = [
                "Employee Code",
                "First Name",
                "Last Name",
                "Work Email",
                "Department",
                "Position",
                "Level",
                "Employment Type",
                "Reporting Manager",
                "Location",
                "Hire Date",
                "Status",
                "Phone",
                "Personal Email",
            ]
        else:
            headers = [
                "Employee Code",
                "First Name",
                "Last Name",
                "Work Email",
                "Department",
                "Position",
                "Level",
                "Employment Type",
                "Reporting Manager",
                "Location",
                "Hire Date",
                "Status",
            ]

        with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for emp in employees:
                status_str = "Active" if emp.is_active else "Inactive"
                dept_name = dept_map.get(emp.department_id, "") if emp.department_id else ""
                loc_name = loc_map.get(emp.location_id, "") if emp.location_id else ""
                mgr_name = (
                    mgr_map.get(emp.reporting_manager_id, "") if emp.reporting_manager_id else ""
                )
                hire_str = emp.hire_date.isoformat() if emp.hire_date else ""

                if is_hr_or_owner:
                    row = [
                        csv_safe_cell(emp.employee_code),
                        csv_safe_cell(emp.first_name),
                        csv_safe_cell(emp.last_name or ""),
                        csv_safe_cell(emp.email),
                        csv_safe_cell(dept_name),
                        csv_safe_cell(emp.position or ""),
                        csv_safe_cell(emp.level or ""),
                        csv_safe_cell(emp.employment_type.value if emp.employment_type else ""),
                        csv_safe_cell(mgr_name),
                        csv_safe_cell(loc_name),
                        csv_safe_cell(hire_str),
                        csv_safe_cell(status_str),
                        csv_safe_cell(emp.phone or ""),
                        csv_safe_cell(emp.personal_email or ""),
                    ]
                else:
                    row = [
                        csv_safe_cell(emp.employee_code),
                        csv_safe_cell(emp.first_name),
                        csv_safe_cell(emp.last_name or ""),
                        csv_safe_cell(emp.email),
                        csv_safe_cell(dept_name),
                        csv_safe_cell(emp.position or ""),
                        csv_safe_cell(emp.level or ""),
                        csv_safe_cell(emp.employment_type.value if emp.employment_type else ""),
                        csv_safe_cell(mgr_name),
                        csv_safe_cell(loc_name),
                        csv_safe_cell(hire_str),
                        csv_safe_cell(status_str),
                    ]
                writer.writerow(row)

        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=24)
        download_name = f"employees_{now.strftime('%Y-%m-%d')}.csv"

        logger.info(
            "employees_csv_exported",
            extra={"company_id": company_id, "file_path": file_path, "row_count": len(employees)},
        )
        return {
            "company_id": company_id,
            "requester_id": actor_id,
            "requester_role": actor_role,
            "file_path": file_path,
            "row_count": len(employees),
            "file_name": download_name,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.hr.delete_expired_exports_task")
def delete_expired_exports_task() -> int:
    """B5: Hourly housekeeping task to delete export files older than 24 hours.
    C2: Deletes ONLY employee export files matching ^[0-9a-f]{32}\\.csv$.
    """
    import re

    export_dir = getattr(settings, "EXPORT_DIR", "var/exports")
    if not os.path.exists(export_dir):
        return 0

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    cutoff_ts = cutoff.timestamp()
    deleted_count = 0
    emp_export_pattern = re.compile(r"^[0-9a-f]{32}\.csv$")

    for fname in os.listdir(export_dir):
        if not emp_export_pattern.match(fname):
            continue
        fpath = os.path.join(export_dir, fname)
        try:
            stat = os.stat(fpath)
            if stat.st_mtime < cutoff_ts:
                os.remove(fpath)
                deleted_count += 1
                logger.info("expired_export_file_deleted", extra={"file_path": fpath})
        except OSError as e:
            logger.warning(
                "failed_to_delete_expired_export_file", extra={"file_path": fpath, "error": str(e)}
            )

    return deleted_count


@celery_app.task(name="app.workers.tasks.hr.apply_due_exits_task")
def apply_due_exits_task() -> dict[str, int]:
    """D4: Hourly scheduled job to apply exits for approved exits whose last working date
    is before today (UTC) and whose employee is still active.
    Processes one employee at a time with row lock and independent commit.
    """
    from app.modules.hr.models import Employee, ResignationStatus
    from app.modules.hr.service import EmployeeService

    db = get_task_db_session()
    applied_count = 0
    error_count = 0
    try:
        bind_tenant_to_session(db, company_id=None, is_platform_admin=True)
        today_utc = datetime.now(UTC).date()

        # Query candidates: active employees with approved exit and last_working_date < today
        candidates = db.execute(
            select(Employee.id, Employee.company_id)
            .where(
                Employee.is_active.is_(True),
                Employee.resignation_status == ResignationStatus.approved,
                Employee.last_working_date < today_utc,
                Employee.deleted_at.is_(None),
            )
        ).all()

        for emp_id, co_id in candidates:
            try:
                emp_service = EmployeeService(db)
                applied_emp = emp_service.apply_exit(co_id, emp_id, actor=None)
                if applied_emp:
                    applied_count += 1
            except Exception as e:
                db.rollback()
                error_count += 1
                logger.warning(
                    "failed_to_apply_due_exit",
                    extra={"employee_id": str(emp_id), "company_id": str(co_id), "error": str(e)},
                )
    finally:
        db.close()

    return {"applied_count": applied_count, "error_count": error_count}
