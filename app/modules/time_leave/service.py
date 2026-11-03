import logging
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.email_templates import leave_decision_email
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.pagination import PageParams
from app.core.roles import HR_LEVEL_ROLES
from app.core.time import utcnow
from app.modules.hr.models import Employee
from app.modules.hr.repository import DepartmentRepository, EmployeeRepository
from app.modules.identity.models import CompanySettings, LeaveYearType, User, UserRole
from app.modules.identity.repository import CompanySettingsRepository
from app.modules.platform.service import (
    AuditService,
    DashboardService,
    NotificationService,
    jsonable,
)
from app.modules.time_leave.geofence import verify_employee_geofence
from app.modules.time_leave.models import (
    Attendance,
    AttendanceRegularizationRequest,
    AttendanceSource,
    AttendanceStatus,
    EmployeeShift,
    Holiday,
    Leave,
    LeaveBalance,
    LeaveStatus,
    LeaveType,
    RegularizationStatus,
    Shift,
)
from app.modules.time_leave.repository import (
    AttendanceRepository,
    EmployeeShiftRepository,
    HolidayRepository,
    LeaveBalanceRepository,
    LeaveRepository,
    LeaveTypeRepository,
    ShiftRepository,
)
from app.modules.time_leave.schemas import (
    AttendanceExportRequest,
    AttendanceRegularizationApprove,
    AttendanceRegularizationCreate,
    AttendanceRegularizeRequest,
    CheckInRequest,
    HolidayCreateRequest,
    LeaveApplyRequest,
    LeaveDecisionRequest,
    LeaveTypeCreateRequest,
    LeaveTypeUpdateRequest,
    ShiftAssignmentUpdateRequest,
    ShiftAssignRequest,
    ShiftCreateRequest,
    ShiftUpdateRequest,
)
from app.workers.tasks.email import send_email_task

logger = logging.getLogger("app")


def verify_approval_authority(
    db: Session,
    current_user: User,
    target_employee: Employee,
) -> bool:
    """Validates if current_user can approve/reject leaves or regularizations
    for target_employee using shared approval authority.
    """
    from app.core.approval_authority import can_approve_for

    return can_approve_for(db, current_user, target_employee, allow_owner_super_admin_self=True)


_SEES_EVERYONE = HR_LEVEL_ROLES


class AlreadyCheckedInError(ConflictError):
    def __init__(self) -> None:
        super().__init__("Already checked in for today.")


class NoCheckInError(AppError):
    status_code = 400
    code = "no_check_in"

    def __init__(self) -> None:
        super().__init__("No check-in record found for today.")


class InvalidCheckOutError(AppError):
    status_code = 400
    code = "invalid_check_out"

    def __init__(self) -> None:
        super().__init__("Check-out time must be after check-in.")


class InvalidReferenceError(AppError):
    """A body field references another resource that doesn't exist in this
    company — a business-rule violation (400), not a schema failure (422).
    Mirrors app.modules.hr.service's class of the same name; kept local so
    this module doesn't reach into hr's service layer for an exception."""

    status_code = 400
    code = "invalid_reference"


class LeaveValidationError(AppError):
    """Spec 11.3 steps 3, 5, 6 — a business-rule violation (400), not a
    schema failure (422)."""

    status_code = 400
    code = "invalid_leave_request"


class LeaveOverlapError(ConflictError):
    """Spec 11.3 step 7: 409, naming the conflicting dates."""

    code = "leave_overlap"

    def __init__(self, conflicts: list[dict]) -> None:
        super().__init__(
            "This leave overlaps an existing pending or approved leave.",
            details={"conflicts": conflicts},
        )


class InsufficientLeaveBalanceError(AppError):
    """Spec 11.3 step 8."""

    status_code = 400
    code = "insufficient_leave_balance"

    def __init__(self, *, available: Decimal, requested: Decimal) -> None:
        super().__init__(
            f"Insufficient leave balance: {available} available, {requested} requested.",
            details={"available": str(available), "requested": str(requested)},
        )


class AttendanceService:
    """Routes 43-49 (10.4), hours calculation (11.5)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = AttendanceRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.settings_repo = CompanySettingsRepository(db)
        self.audit = AuditService(db)
        self.notify = NotificationService(db)
        # Imported lazily to avoid circular imports at module level
        from app.modules.identity.repository import CompanyLocationRepository

        self.location_repo = CompanyLocationRepository(db)

    def _resolve_scope(self, company_id: uuid.UUID, current_user: User) -> list[uuid.UUID] | None:
        """None = unrestricted (HR/SA). A list = restricted to exactly these
        employee ids (self for an employee, self + direct reports for a manager)."""
        if current_user.role in _SEES_EVERYONE:
            return None
        caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
        if caller_employee is None:
            return []
        if current_user.role == UserRole.manager:
            reports = self.employee_repo.list_direct_report_ids(company_id, caller_employee.id)
            return [caller_employee.id] + [r for r in reports if r != caller_employee.id]
        return [caller_employee.id]

    def check_in(
        self, company_id: uuid.UUID, current_user: User, body: CheckInRequest | None = None
    ) -> Attendance:
        """Route 43. 409 if a record already exists for today — the
        database's `uq_attendance_employee_id_date` is the real backstop
        (11.5); this proactive check just gives a friendlier message.

        When `body` carries GPS coordinates the employee's assigned
        CompanyLocation is fetched and the Haversine formula validates
        the distance against its geofence_radius_meters.  If no
        geofence is configured the check is silently skipped."""
        employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
        if employee is None:
            raise NotFoundError("You do not have an employee record.")
        today = utcnow().date()
        existing_att = self.repo.get_by_employee_and_date(company_id, employee.id, today)
        if existing_att:
            if existing_att.status == AttendanceStatus.on_leave:
                raise ConflictError("You are on approved leave today.")
            raise AlreadyCheckedInError()

        # ── Geofence validation ──────────────────────────────────────────────
        fence_notes: str | None = None
        if employee.location_id is not None:
            location = self.location_repo.get_by_id(employee.location_id, company_id)
            if location is not None:
                emp_lat = body.latitude if body else None
                emp_lon = body.longitude if body else None
                distance = verify_employee_geofence(
                    emp_lat=emp_lat,
                    emp_lon=emp_lon,
                    office_lat=float(location.latitude) if location.latitude is not None else None,
                    office_lon=float(location.longitude)
                    if location.longitude is not None
                    else None,
                    radius_m=location.geofence_radius_meters,
                    is_remote_exempt=location.is_remote_exempt,
                )
                if distance is not None and body is not None:
                    accuracy_str = (
                        f", accuracy={body.device_accuracy:.0f}m" if body.device_accuracy else ""
                    )
                    fence_notes = (
                        f"GPS check-in: {emp_lat:.6f},{emp_lon:.6f} — "
                        f"{distance:.0f}m from office "
                        f"(limit {location.geofence_radius_meters}m{accuracy_str})"
                    )

        # Auto-flag past unclosed shifts as mispunch
        past_open = (
            self.repo.db.query(Attendance)
            .filter(
                Attendance.company_id == company_id,
                Attendance.employee_id == employee.id,
                Attendance.date < today,
                Attendance.check_in.is_not(None),
                Attendance.check_out.is_(None),
                Attendance.deleted_at.is_(None),
                Attendance.status != AttendanceStatus.mispunch,
                Attendance.status != AttendanceStatus.pending_regularization,
            )
            .all()
        )
        for po in past_open:
            po.status = AttendanceStatus.mispunch
        try:
            record = self.repo.create(
                company_id=company_id,
                employee_id=employee.id,
                date=today,
                check_in=utcnow(),
                status=AttendanceStatus.present,
                source=AttendanceSource.web,
                notes=fence_notes,
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AlreadyCheckedInError() from exc
        DashboardService.invalidate_company_dashboards(company_id)
        return record

    def check_out(self, company_id: uuid.UUID, current_user: User) -> Attendance:
        """Route 44. 400 with no check-in, or check_out <= check_in.
        hours_worked is real elapsed time between two TIMESTAMPTZ values —
        correct across a midnight boundary with no special-casing, unlike
        naive TIME-of-day arithmetic on a shift's start/end would be."""
        employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
        if employee is None:
            raise NotFoundError("You do not have an employee record.")
        record = self.repo.get_open_for_employee(company_id, employee.id)
        if record is None:
            raise NoCheckInError()
        assert record.check_in is not None  # guaranteed by get_open_for_employee's own filter
        now = utcnow()
        if now <= record.check_in:
            raise InvalidCheckOutError()

        hours = (Decimal((now - record.check_in).total_seconds()) / Decimal(3600)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        settings_row = self.settings_repo.get_by_company(company_id)
        half_thresh = settings_row.half_day_hours_threshold if settings_row else Decimal("4")
        # Rule B: Status thresholds. Total worked time < 1.0 hr (e.g. short 4-second punch)
        # must never be marked as half day — it is absent / invalid punch.
        # 1.0 <= hours < half_thresh is half_day, and hours >= half_thresh is present.
        if hours < Decimal("1.0"):
            status = AttendanceStatus.absent
        elif hours < half_thresh:
            status = AttendanceStatus.half_day
        else:
            status = AttendanceStatus.present

        self.repo.update(record, check_out=now, hours_worked=hours, status=status)
        self.db.commit()
        DashboardService.invalidate_company_dashboards(company_id)
        return record

    def list_attendance(
        self,
        company_id: uuid.UUID,
        current_user: User,
        *,
        employee_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: AttendanceStatus | None,
        department_id: uuid.UUID | None,
        page_params: PageParams,
    ) -> tuple[list[Attendance], int, int]:
        """Route 45: employees see own, managers their team, HR everyone."""
        allowed = self._resolve_scope(company_id, current_user)
        if allowed is not None:
            if not allowed:
                return [], 0, 0
            if employee_id is not None and employee_id not in allowed:
                return [], 0, 0
        return self.repo.list_attendance(
            company_id=company_id,
            allowed_employee_ids=allowed,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            department_id=department_id,
            page_params=page_params,
        )

    def _assert_can_view(
        self, company_id: uuid.UUID, record: Attendance, current_user: User
    ) -> None:
        if current_user.role in _SEES_EVERYONE:
            return
        caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
        if caller_employee is not None and record.employee_id == caller_employee.id:
            return
        if current_user.role == UserRole.manager and caller_employee is not None:
            report_ids = self.employee_repo.list_direct_report_ids(company_id, caller_employee.id)
            if record.employee_id in report_ids:
                return
        raise ForbiddenError("You do not have permission to view this attendance record.")

    def get_attendance(
        self, company_id: uuid.UUID, attendance_id: uuid.UUID, current_user: User
    ) -> Attendance:
        """Route 46: Own, Mgr, HR."""
        record = self.repo.get_by_id(attendance_id, company_id)
        if record is None:
            raise NotFoundError("Attendance record not found.")
        self._assert_can_view(company_id, record, current_user)
        return record

    def regularize(
        self,
        company_id: uuid.UUID,
        attendance_id: uuid.UUID,
        data: AttendanceRegularizeRequest,
        actor: User,
    ) -> Attendance:
        """Route 47, HR only. There is no separate approve/reject decision
        workflow for attendance regularization in this codebase — this
        direct HR correction IS the decision, audited as
        ATTENDANCE_REGULARIZED (the WP-11 task's "regularisation approved"
        deliverable)."""
        record = self.repo.get_by_id(attendance_id, company_id)
        if record is None:
            raise NotFoundError("Attendance record not found.")

        previous = {
            "check_in": record.check_in.isoformat() if record.check_in else None,
            "check_out": record.check_out.isoformat() if record.check_out else None,
            "status": record.status.value,
            "notes": record.notes,
        }
        updates = data.model_dump(exclude={"reason"}, exclude_unset=True)

        eff_check_in = updates.get("check_in", record.check_in)
        eff_check_out = updates.get("check_out", record.check_out)

        if eff_check_in and eff_check_out and eff_check_out > eff_check_in:
            calc_hours = (
                Decimal((eff_check_out - eff_check_in).total_seconds()) / Decimal(3600)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            updates["hours_worked"] = calc_hours
            if "status" not in updates or updates["status"] is None:
                settings_row = self.settings_repo.get_by_company(company_id)
                half_thresh = (
                    settings_row.half_day_hours_threshold if settings_row else Decimal("4")
                )
                if calc_hours < Decimal("1.0"):
                    updates["status"] = AttendanceStatus.absent
                elif calc_hours < half_thresh:
                    updates["status"] = AttendanceStatus.half_day
                else:
                    updates["status"] = AttendanceStatus.present

        note_suffix = f" [Regularized by {actor.email}]"
        existing_notes = updates.get("notes") or record.notes or ""
        if note_suffix.strip() not in existing_notes:
            updates["notes"] = (existing_notes + note_suffix).strip()

        self.repo.update(record, **updates)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="ATTENDANCE_REGULARIZED",
            entity_type="attendance",
            entity_id=record.id,
            details={
                "reason": data.reason,
                "previous": previous,
                "new": jsonable(updates),
            },
        )
        if record.employee_id:
            employee = self.employee_repo.get_by_id_any_status(record.employee_id, company_id)
            if employee is not None and employee.user_id is not None:
                self.notify.notify(
                    company_id=company_id,
                    user_id=employee.user_id,
                    type="attendance_regularized",
                    title="Attendance corrected",
                    message=f"Your attendance for {record.date} was corrected by HR: {data.reason}",
                    entity_type="attendance",
                    entity_id=record.id,
                )
        self.db.commit()
        DashboardService.invalidate_company_dashboards(company_id)
        return record

    def request_regularization(
        self,
        company_id: uuid.UUID,
        attendance_id: uuid.UUID,
        data: AttendanceRegularizationCreate,
        current_user: User,
    ) -> AttendanceRegularizationRequest:
        record = self.repo.get_by_id(attendance_id, company_id)
        if record is None:
            raise NotFoundError("Attendance record not found.")
        self._assert_can_view(company_id, record, current_user)

        # Determine manager
        employee = self.employee_repo.get_by_id_any_status(record.employee_id, company_id)
        manager_id = employee.reporting_manager_id if employee else None

        req = AttendanceRegularizationRequest(
            attendance_id=attendance_id,
            employee_id=record.employee_id,
            manager_id=manager_id,
            requested_check_in=data.requested_check_in,
            requested_check_out=data.requested_check_out,
            reason=data.reason,
            attachment_url=data.attachment_url,
            status=RegularizationStatus.pending,
            company_id=company_id,
        )
        self.repo.create_regularization_request(req)

        # For Owner / Super Admin: Auto-approve immediately since no manager is above them
        if current_user.role in [UserRole.owner, UserRole.super_admin]:
            req.status = RegularizationStatus.approved
            req.approved_by = current_user.id
            req.approved_at = utcnow()
            req.admin_notes = "Auto-approved for Owner / Leadership"

            eff_check_in = data.requested_check_in
            eff_check_out = data.requested_check_out
            if eff_check_in:
                record.check_in = eff_check_in
            if eff_check_out:
                record.check_out = eff_check_out
            if record.check_in and record.check_out and record.check_out > record.check_in:
                from decimal import ROUND_HALF_UP

                calc_hours = (
                    Decimal((record.check_out - record.check_in).total_seconds()) / Decimal(3600)
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                record.hours_worked = calc_hours
                settings_row = self.settings_repo.get_by_company(company_id)
                half_thresh = (
                    settings_row.half_day_hours_threshold if settings_row else Decimal("4")
                )
                if calc_hours < Decimal("1.0"):
                    record.status = AttendanceStatus.absent
                elif calc_hours < half_thresh:
                    record.status = AttendanceStatus.half_day
                else:
                    record.status = AttendanceStatus.present
            else:
                record.status = AttendanceStatus.absent

            record.notes = ((record.notes or "") + " [Auto-regularized by Owner]").strip()
            self.db.commit()
            DashboardService.invalidate_company_dashboards(company_id)
            return req

        record.status = AttendanceStatus.pending_regularization

        # Notify manager if present
        if manager_id:
            mgr_employee = self.employee_repo.get_by_id_any_status(manager_id, company_id)
            if mgr_employee and mgr_employee.user_id:
                emp_name = (
                    f"{employee.first_name} {employee.last_name or ''}".strip()
                    if employee
                    else "An employee"
                )
                self.notify.notify(
                    company_id=company_id,
                    user_id=mgr_employee.user_id,
                    type="regularization_requested",
                    title="Attendance Regularization Request",
                    message=f"{emp_name} requested attendance regularization for {record.date}.",
                    action_url="/attendance",
                    entity_type="attendance",
                    entity_id=record.id,
                )

        self.db.commit()
        return req

    def approve_regularization(
        self,
        company_id: uuid.UUID,
        regularization_id: uuid.UUID,
        data: AttendanceRegularizationApprove,
        current_user: User,
    ) -> AttendanceRegularizationRequest:
        req = self.repo.get_regularization_by_id(regularization_id, company_id)
        if req is None:
            raise NotFoundError("Regularization request not found.")
        target_employee = self.employee_repo.get_by_id_any_status(req.employee_id, company_id)
        if target_employee is None:
            raise NotFoundError("Employee for this regularization request not found.")

        verify_approval_authority(self.db, current_user, target_employee)

        if req.status != RegularizationStatus.pending:
            raise ConflictError(
                f"Regularization request is not pending (current status: {req.status.value})."
            )

        if data.status not in ("approved", "rejected"):
            raise AppError("Status must be approved or rejected")

        if data.status == "rejected" and not (
            data.rejection_reason and data.rejection_reason.strip()
        ):
            raise AppError("Rejection reason is mandatory when rejecting a regularization request.")

        req.status = RegularizationStatus(data.status)
        req.approved_by = current_user.id
        req.approved_at = utcnow()
        req.rejection_reason = data.rejection_reason.strip() if data.rejection_reason else None
        if data.admin_notes is not None:
            req.admin_notes = data.admin_notes.strip() or None

        record = self.repo.get_by_id(req.attendance_id, company_id)

        if req.status == RegularizationStatus.approved and record:
            eff_check_in = (
                data.adjusted_check_in
                if data.adjusted_check_in is not None
                else req.requested_check_in
            )
            eff_check_out = (
                data.adjusted_check_out
                if data.adjusted_check_out is not None
                else req.requested_check_out
            )

            if eff_check_in:
                record.check_in = eff_check_in
            if eff_check_out:
                record.check_out = eff_check_out

            if record.check_in and record.check_out and record.check_out > record.check_in:
                from decimal import ROUND_HALF_UP

                calc_hours = (
                    Decimal((record.check_out - record.check_in).total_seconds()) / Decimal(3600)
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                record.hours_worked = calc_hours

                settings_row = self.settings_repo.get_by_company(company_id)
                half_thresh = (
                    settings_row.half_day_hours_threshold if settings_row else Decimal("4")
                )
                if calc_hours < Decimal("1.0"):
                    record.status = AttendanceStatus.absent
                elif calc_hours < half_thresh:
                    record.status = AttendanceStatus.half_day
                else:
                    record.status = AttendanceStatus.present
            else:
                record.status = AttendanceStatus.absent

            # Append admin notes to attendance record notes if provided
            if req.admin_notes:
                note_line = f" [HR: {req.admin_notes}]"
                record.notes = ((record.notes or "") + note_line).strip()

        elif req.status == RegularizationStatus.rejected and record:
            record.status = AttendanceStatus.mispunch

        # Notify employee of decision
        emp = self.employee_repo.get_by_id_any_status(req.employee_id, company_id)
        if emp and emp.user_id:
            status_text = "approved" if req.status == RegularizationStatus.approved else "rejected"
            message_text = (
                f"Your attendance regularization request for "
                f"{record.date if record else 'your shift'} has been {status_text}."
            )
            self.notify.notify(
                company_id=company_id,
                user_id=emp.user_id,
                type=f"regularization_{status_text}",
                title=f"Attendance Regularization {status_text.capitalize()}",
                message=message_text,
                action_url="/attendance",
                entity_type="attendance",
                entity_id=record.id if record else None,
            )

        self.db.commit()
        DashboardService.invalidate_company_dashboards(company_id)
        return req

    def delete_attendance(
        self, company_id: uuid.UUID, attendance_id: uuid.UUID, actor: User
    ) -> None:
        """Route 48, HR only. Soft delete (7.1's universal rule; `attendance`
        is not append-only)."""
        record = self.repo.get_by_id(attendance_id, company_id)
        if record is None:
            raise NotFoundError("Attendance record not found.")
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="ATTENDANCE_DELETED",
            entity_type="attendance",
            entity_id=record.id,
            details={"date": jsonable(record.date), "employee_id": jsonable(record.employee_id)},
        )
        self.repo.soft_delete(record)
        self.db.commit()
        DashboardService.invalidate_company_dashboards(company_id)

    def get_calendar(
        self,
        company_id: uuid.UUID,
        current_user: User,
        *,
        employee_id: uuid.UUID | None,
        month: int,
        year: int,
    ) -> dict:
        """Returns a normalized month-view for the attendance calendar matrix.

        Single pass over attendance, leave, and holiday rows for the period —
        never one query per day.  The caller's role gates which employee_id is
        permitted (own for employee, team for manager, anyone for HR)."""
        import calendar as _cal
        from decimal import Decimal

        # Resolve target employee
        if employee_id is None:
            emp = self.employee_repo.get_by_user_id(company_id, current_user.id)
            if emp is None:
                raise NotFoundError("You do not have an employee record.")
            employee_id = emp.id
        else:
            # Check target employee exists in company
            emp = self.employee_repo.get_by_id(employee_id, company_id)
            if emp is None:
                raise NotFoundError("Employee not found.")
            # Scope guard
            allowed = self._resolve_scope(company_id, current_user)
            if allowed is not None and employee_id not in allowed:
                raise ForbiddenError("You do not have permission to view this employee's calendar.")

        # Build the set of dates in the requested month
        days_in_month = _cal.monthrange(year, month)[1]
        start = date(year, month, 1)
        end = date(year, month, days_in_month)
        today = utcnow().date()

        # Company settings for weekends
        # 0=Monday ... 6=Sunday. Default weekend: Saturday(5), Sunday(6)
        weekend_days = {5, 6}

        # Index attendance rows by date
        att_rows = (
            self.repo.db.query(Attendance)
            .filter(
                Attendance.company_id == company_id,
                Attendance.employee_id == employee_id,
                Attendance.date >= start,
                Attendance.date <= end,
                Attendance.deleted_at.is_(None),
            )
            .all()
        )
        att_by_date: dict[date, Attendance] = {r.date: r for r in att_rows}

        # Index all holidays by date (dept-specific or company-wide, both mandatory and optional)
        holiday_rows = (
            self.repo.db.query(Holiday)
            .filter(
                Holiday.company_id == company_id,
                Holiday.date >= start,
                Holiday.date <= end,
                Holiday.deleted_at.is_(None),
            )
            .all()
        )
        hol_by_date: dict[date, Holiday] = {}
        for h in holiday_rows:
            if h.applies_to_department_id is None or h.applies_to_department_id == (
                emp.department_id if emp else None
            ):
                # If there's already a mandatory holiday for this date, prefer it
                if h.date not in hol_by_date or (
                    not h.is_optional and hol_by_date[h.date].is_optional
                ):
                    hol_by_date[h.date] = h

        # Index approved/pending leaves by their date range
        leave_rows = (
            self.repo.db.query(Leave)
            .filter(
                Leave.company_id == company_id,
                Leave.employee_id == employee_id,
                Leave.start_date <= end,
                Leave.end_date >= start,
                Leave.status.in_([LeaveStatus.approved, LeaveStatus.pending]),
                Leave.deleted_at.is_(None),
            )
            .all()
        )
        # Build leave_type names cache
        leave_type_ids = {lv.leave_type_id for lv in leave_rows}
        lt_map: dict[uuid.UUID, str] = {}
        if leave_type_ids:
            from app.modules.time_leave.models import LeaveType as _LT

            lt_rows = self.repo.db.query(_LT).filter(_LT.id.in_(leave_type_ids)).all()
            lt_map = {r.id: r.name for r in lt_rows}
        leave_by_date: dict[date, Leave] = {}
        for lv in leave_rows:
            d = lv.start_date
            while d <= lv.end_date:
                if start <= d <= end:
                    leave_by_date[d] = lv
                d += timedelta(days=1)

        # Build day cells
        days = []
        summary: dict[str, int] = {}
        for day_num in range(1, days_in_month + 1):
            d = date(year, month, day_num)
            dow = d.isoweekday() - 1  # 0=Mon…6=Sun
            is_today = d == today
            is_future = d > today
            att = att_by_date.get(d)
            hol = hol_by_date.get(d)
            leave = leave_by_date.get(d)

            # Enterprise Priority Hierarchy (Zoho / Keka):
            # Priority 1: Approved / Pending Leave
            if leave is not None:
                if leave.status == LeaveStatus.approved:
                    status = "on_leave"
                    badge = lt_map.get(leave.leave_type_id, "On Leave")
                else:
                    status = "pending_leave"
                    badge = f"Pending ({lt_map.get(leave.leave_type_id, 'Leave')})"
                work_hours = att.hours_worked if att else None
                check_in_val = att.check_in if att else None
                check_out_val = att.check_out if att else None
                holiday_name = None
                leave_type_name = lt_map.get(leave.leave_type_id)

            # Priority 2: Gazetted Public Holiday (Mandatory only counts as day off)
            elif hol is not None and not hol.is_optional:
                status = "holiday"
                work_hours = att.hours_worked if att else None
                check_in_val = att.check_in if att else None
                check_out_val = att.check_out if att else None
                badge = hol.name
                holiday_name = hol.name
                leave_type_name = None

            # Priority 3: Attendance Punches (punches beat weekend)
            elif att is not None:
                check_in_val = att.check_in
                check_out_val = att.check_out
                work_hours = att.hours_worked
                holiday_name = hol.name if (hol and hol.is_optional) else None
                leave_type_name = None

                # Rule: Today and currently clocked in without check-out
                if is_today and check_in_val and not check_out_val:
                    status = "in_progress"
                    badge = "Clocked In"
                elif att.status == AttendanceStatus.pending_regularization:
                    status = "pending_regularization"
                    badge = "Regularizing"
                elif att.status == AttendanceStatus.mispunch:
                    status = "mispunch"
                    badge = "Missing Punch"
                elif work_hours is not None:
                    hours_dec = Decimal(str(work_hours))
                    if hours_dec >= Decimal("7.5"):
                        status = "present"
                        badge = None
                    elif hours_dec >= Decimal("4.0"):
                        status = "half_day"
                        badge = "Half Day"
                    elif is_today and check_in_val and not check_out_val:
                        status = "in_progress"
                        badge = "Clocked In"
                    else:
                        status = att.status.value
                        badge = "Under Min" if status == "absent" else None
                else:
                    if is_today and check_in_val and not check_out_val:
                        status = "in_progress"
                        badge = "Clocked In"
                    elif d < today and check_in_val and not check_out_val:
                        status = "mispunch"
                        badge = "Missing Punch"
                    else:
                        status = att.status.value
                        badge = None

            # Priority 4: Attendance Exempt (e.g. CEO/Owner on today or past work days)
            elif (
                emp
                and getattr(emp, "is_attendance_exempt", False)
                and dow not in weekend_days
                and not is_future
            ):
                status = "exempt"
                badge = "Exempt"
                work_hours = None
                check_in_val = None
                check_out_val = None
                holiday_name = hol.name if (hol and hol.is_optional) else None
                leave_type_name = None

            # Priority 5: Weekly Off / Weekend
            elif dow in weekend_days:
                status = "weekend"
                work_hours = None
                check_in_val = None
                check_out_val = None
                badge = "Weekend"
                holiday_name = hol.name if (hol and hol.is_optional) else None
                leave_type_name = None

            # Priority 6: Future Work Days
            elif is_future:
                status = "no_record"
                work_hours = None
                check_in_val = None
                check_out_val = None
                badge = "Optional Holiday" if (hol and hol.is_optional) else None
                holiday_name = hol.name if (hol and hol.is_optional) else None
                leave_type_name = None

            # Priority 7: Past or Today Unpunched Working Day -> Absent
            # (with optional holiday badge if applicable)
            else:
                status = "absent"
                badge = "Optional Holiday" if (hol and hol.is_optional) else None
                work_hours = None
                check_in_val = None
                check_out_val = None
                holiday_name = hol.name if (hol and hol.is_optional) else None
                leave_type_name = None

            summary[status] = summary.get(status, 0) + 1
            days.append(
                {
                    "date": d,
                    "day_of_week": dow,
                    "status": status,
                    "work_duration_hours": work_hours,
                    "check_in": check_in_val,
                    "check_out": check_out_val,
                    "badge_label": badge,
                    "holiday_name": holiday_name,
                    "leave_type_name": leave_type_name,
                    "is_today": is_today,
                    "is_future": is_future,
                }
            )

        return {
            "employee_id": employee_id,
            "month": month,
            "year": year,
            "days": days,
            "summary": summary,
        }

    def queue_export(
        self,
        company_id: uuid.UUID,
        data: AttendanceExportRequest,
        user_id: uuid.UUID | None = None,
    ) -> str:
        """Route 49: queues the real Celery job (13.1), returns its id."""
        from app.core.jobs import register_job
        from app.workers.tasks.attendance import export_attendance_csv_task

        task = export_attendance_csv_task.delay(
            company_id=str(company_id),
            requester_id=str(user_id) if user_id else None,
            employee_id=str(data.employee_id) if data.employee_id else None,
            date_from=data.date_from.isoformat() if data.date_from else None,
            date_to=data.date_to.isoformat() if data.date_to else None,
            status=data.status.value if data.status else None,
            department_id=str(data.department_id) if data.department_id else None,
        )
        register_job(
            task.id,
            company_id=company_id,
            user_id=user_id,
            kind="attendance_export",
        )
        return task.id


class ShiftService:
    """Routes 50-54 (10.4)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = ShiftRepository(db)
        self.employee_shift_repo = EmployeeShiftRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.audit = AuditService(db)

    def list_shifts(
        self, company_id: uuid.UUID, page_params: PageParams
    ) -> tuple[list[Shift], int, int]:
        return self.repo.list_shifts(company_id, page_params)

    def create_shift(
        self, company_id: uuid.UUID, data: ShiftCreateRequest, actor: User | None = None
    ) -> Shift:
        existing = self.repo.get_by_name(company_id, data.name)
        if existing:
            raise ConflictError(f"A shift named '{data.name}' already exists.")
        shift = self.repo.create(company_id=company_id, **data.model_dump())
        if actor:
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="SHIFT_CREATED",
                entity_type="shift",
                entity_id=shift.id,
                details={"name": data.name},
            )
        self.db.commit()
        return shift

    def _get_or_404(self, company_id: uuid.UUID, shift_id: uuid.UUID) -> Shift:
        shift = self.repo.get_by_id(shift_id, company_id)
        if shift is None:
            raise NotFoundError("Shift not found.")
        return shift

    def get_shift(self, company_id: uuid.UUID, shift_id: uuid.UUID) -> Shift:
        return self._get_or_404(company_id, shift_id)

    def update_shift(
        self,
        company_id: uuid.UUID,
        shift_id: uuid.UUID,
        data: ShiftUpdateRequest,
        actor: User | None = None,
    ) -> Shift:
        shift = self._get_or_404(company_id, shift_id)
        update_data = data.model_dump(exclude_unset=True)
        if "name" in update_data and update_data["name"] is not None:
            existing = self.repo.get_by_name(company_id, update_data["name"])
            if existing and existing.id != shift.id:
                raise ConflictError(f"A shift named '{update_data['name']}' already exists.")
        self.repo.update(shift, **update_data)
        if actor:
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="SHIFT_UPDATED",
                entity_type="shift",
                entity_id=shift.id,
                details={"updated_fields": list(update_data.keys())},
            )
        self.db.commit()
        return shift

    def delete_shift(
        self, company_id: uuid.UUID, shift_id: uuid.UUID, actor: User | None = None
    ) -> None:
        """Route 53: blocked if currently or in future assigned."""
        shift = self._get_or_404(company_id, shift_id)
        today = utcnow().date()
        count = self.repo.count_current_and_future_assignments(shift_id, company_id, today)
        if count > 0:
            raise ConflictError(
                f"Cannot delete a shift with {count} current or future assignment(s).",
                details={"assignment_count": count},
            )
        self.repo.soft_delete(shift)
        if actor:
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="SHIFT_DELETED",
                entity_type="shift",
                entity_id=shift.id,
                details={"name": shift.name},
            )
        self.db.commit()

    def assign_shift(
        self,
        company_id: uuid.UUID,
        shift_id: uuid.UUID,
        data: ShiftAssignRequest,
        actor: User | None = None,
    ) -> EmployeeShift:
        """Route 54: rejects overlapping assignments for the same employee."""
        shift = self._get_or_404(company_id, shift_id)
        if not shift.is_active:
            raise ConflictError("A deactivated shift cannot be newly assigned.")
        # Row lock on the employee to make overlap checks race-safe
        employee = self.employee_repo.get_by_id_for_update(data.employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        if data.effective_to is not None and data.effective_to < data.effective_from:
            raise ValidationError(
                "effective_to must be on or after effective_from.",
                details={"field": "effective_to"},
            )
        overlapping = self.employee_shift_repo.get_overlapping(
            company_id=company_id,
            employee_id=data.employee_id,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
        )
        if overlapping:
            first_overlap = overlapping[0]
            raise ConflictError(
                f"This employee already has a shift assignment overlapping these dates "
                f"({first_overlap.effective_from} to {first_overlap.effective_to or 'ongoing'})."
            )
        assignment = self.employee_shift_repo.create(
            company_id=company_id,
            employee_id=data.employee_id,
            shift_id=shift_id,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
        )
        if actor:
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="SHIFT_ASSIGNED",
                entity_type="employee_shift",
                entity_id=assignment.id,
                details={
                    "shift_id": jsonable(shift_id),
                    "employee_id": jsonable(data.employee_id),
                    "effective_from": jsonable(data.effective_from),
                    "effective_to": jsonable(data.effective_to),
                },
            )
        self.db.commit()
        return assignment

    def update_assignment(
        self,
        company_id: uuid.UUID,
        assignment_id: uuid.UUID,
        data: ShiftAssignmentUpdateRequest,
        actor: User | None = None,
    ) -> EmployeeShift:
        assignment = self.employee_shift_repo.get_by_id(assignment_id, company_id)
        if assignment is None:
            raise NotFoundError("Shift assignment not found.")
        if data.effective_to is not None and data.effective_to < assignment.effective_from:
            raise ValidationError(
                "effective_to must be on or after effective_from.",
                details={"field": "effective_to"},
            )
        self.employee_shift_repo.update(assignment, effective_to=data.effective_to)
        if actor:
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="SHIFT_ASSIGNMENT_ENDED",
                entity_type="employee_shift",
                entity_id=assignment.id,
                details={
                    "shift_id": jsonable(assignment.shift_id),
                    "employee_id": jsonable(assignment.employee_id),
                    "effective_to": jsonable(data.effective_to),
                },
            )
        self.db.commit()
        return assignment

    def get_assigned_shift(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        actor: User,
        as_of_date: date | None = None,
    ) -> tuple[EmployeeShift, Shift] | None:
        target_emp = self.employee_repo.get_by_id(employee_id, company_id)
        if target_emp is None:
            raise NotFoundError("Employee not found.")

        if actor.role == UserRole.employee:
            actor_emp = self.employee_repo.get_by_user_id(company_id, actor.id)
            if actor_emp is None or employee_id != actor_emp.id:
                raise ForbiddenError("You do not have permission to view this shift assignment.")
        elif actor.role == UserRole.manager:
            actor_emp = self.employee_repo.get_by_user_id(company_id, actor.id)
            if actor_emp is None:
                raise ForbiddenError("You do not have permission to view this shift assignment.")
            if employee_id != actor_emp.id:
                report_ids = self.employee_repo.list_direct_report_ids(company_id, actor_emp.id)
                if employee_id not in report_ids:
                    raise ForbiddenError(
                        "You do not have permission to view this shift assignment."
                    )
        elif actor.role in HR_LEVEL_ROLES:
            pass
        else:
            raise ForbiddenError("You do not have permission to view this shift assignment.")

        target_date = as_of_date or utcnow().date()
        return self.employee_shift_repo.get_assigned_shift(
            company_id=company_id,
            employee_id=employee_id,
            as_of_date=target_date,
        )


class HolidayService:
    """Routes 55-57 (10.4)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = HolidayRepository(db)
        self.department_repo = DepartmentRepository(db)
        self.audit = AuditService(db)

    def list_holidays(self, company_id: uuid.UUID, year: int) -> list[Holiday]:
        return self.repo.list_by_year(company_id, year)

    def create_holiday(
        self, company_id: uuid.UUID, data: HolidayCreateRequest, actor: User
    ) -> Holiday:
        if data.applies_to_department_id is not None:
            if self.department_repo.get_by_id(data.applies_to_department_id, company_id) is None:
                raise NotFoundError("Department not found.")
        try:
            holiday = self.repo.create(company_id=company_id, **data.model_dump())
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="HOLIDAY_CREATED",
                entity_type="holiday",
                entity_id=holiday.id,
                details={
                    "date": holiday.date,
                    "is_optional": holiday.is_optional,
                    "department_id": holiday.applies_to_department_id,
                },
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("A holiday already exists on this date.") from exc
        return holiday

    def delete_holiday(self, company_id: uuid.UUID, holiday_id: uuid.UUID, actor: User) -> None:
        holiday = self.repo.get_by_id(holiday_id, company_id)
        if holiday is None:
            raise NotFoundError("Holiday not found.")
        self.repo.soft_delete(holiday)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="HOLIDAY_DELETED",
            entity_type="holiday",
            entity_id=holiday.id,
            details={"date": holiday.date, "department_id": holiday.applies_to_department_id},
        )
        self.db.commit()

    @staticmethod
    def supported_regions() -> dict:
        from app.modules.time_leave.constants import COUNTRY_REGIONS_MAP

        return COUNTRY_REGIONS_MAP

    @staticmethod
    def preview_regional_holidays(country: str, state: str, year: int) -> list[dict]:
        """The known statutory list for a region. Country and state must be in the
        project's own region list; the year range is checked by the request schema.
        The lists are not independently verified: HR must confirm them against the
        official notification."""
        from app.modules.time_leave.constants import (
            COUNTRY_REGIONS_MAP,
            get_regional_statutory_holidays,
        )

        country_key = (country or "").strip().upper()
        region = COUNTRY_REGIONS_MAP.get(country_key)
        if region is None:
            raise ValidationError(
                "Unknown country.",
                details={"field": "country", "allowed": sorted(COUNTRY_REGIONS_MAP)},
            )
        states = {s.lower(): s for s in region["states"]}
        canonical_state = states.get((state or "").strip().lower())
        if canonical_state is None:
            raise ValidationError(
                f"Unknown state or region for {country_key}.", details={"field": "state"}
            )
        holidays_data = get_regional_statutory_holidays(
            state=canonical_state, year=year, country=country_key
        )
        if not holidays_data:
            raise ValidationError(
                f"No statutory holidays are known for {canonical_state} ({country_key}) in {year}.",
                details={"field": "year"},
            )
        return holidays_data

    def import_regional_holidays(
        self,
        company_id: uuid.UUID,
        actor: User,
        state: str = "Gujarat",
        year: int = 2026,
        country: str = "IN",
    ) -> tuple[int, list[Holiday]]:
        from datetime import date as dt_date

        holidays_data = self.preview_regional_holidays(country, state, year)

        # Fetch existing active holidays for this company and year to avoid duplicates
        existing_holidays = self.repo.list_by_year(company_id, year)
        existing_company_wide_dates = {
            h.date for h in existing_holidays if h.applies_to_department_id is None
        }

        imported_count = 0
        try:
            for item in holidays_data:
                d = dt_date.fromisoformat(item["date"])
                if d in existing_company_wide_dates:
                    continue

                self.repo.create(
                    company_id=company_id,
                    name=item["name"],
                    date=d,
                    is_optional=item.get("is_optional", False),
                    applies_to_department_id=None,
                )
                existing_company_wide_dates.add(d)
                imported_count += 1

            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="HOLIDAYS_IMPORTED",
                entity_type="holiday",
                details={"count": imported_count, "year": year},
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError(
                "Holidays were changed by another request while importing. Please try again."
            ) from exc
        all_year_holidays = self.repo.list_by_year(company_id, year)
        return imported_count, all_year_holidays


class LeaveTypeService:
    """Routes 58-60 (10.4)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = LeaveTypeRepository(db)
        self.audit = AuditService(db)

    def list_leave_types(
        self, company_id: uuid.UUID, actor: User, include_inactive: bool = False
    ) -> list[LeaveType]:
        """Everyone lists the active types; only HR-level may also ask for the inactive."""
        if include_inactive and actor.role not in HR_LEVEL_ROLES:
            raise ForbiddenError("Only HR can list deactivated leave types.")
        return self.repo.list_all(company_id, only_active=not include_inactive)

    def _conflict_for(
        self, company_id: uuid.UUID, name: str | None, code: str | None, own_id: uuid.UUID | None
    ) -> ConflictError | None:
        if code is not None:
            other = self.repo.get_by_code(company_id, code)
            if other is not None and other.id != own_id:
                return ConflictError("A leave type with this code already exists.")
        if name is not None:
            other = self.repo.get_by_name(company_id, name)
            if other is not None and other.id != own_id:
                return ConflictError("A leave type with this name already exists.")
        return None

    def create_leave_type(
        self, company_id: uuid.UUID, data: LeaveTypeCreateRequest, actor: User
    ) -> LeaveType:
        conflict = self._conflict_for(company_id, data.name, data.code, None)
        if conflict is not None:
            raise conflict
        try:
            leave_type = self.repo.create(company_id=company_id, **data.model_dump())
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="LEAVE_TYPE_CREATED",
                entity_type="leave_type",
                entity_id=leave_type.id,
                details={"leave_type_id": leave_type.id},
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("A leave type with this name or code already exists.") from exc
        return leave_type

    def update_leave_type(
        self,
        company_id: uuid.UUID,
        leave_type_id: uuid.UUID,
        data: LeaveTypeUpdateRequest,
        actor: User,
    ) -> LeaveType:
        leave_type = self.repo.get_by_id(leave_type_id, company_id)
        if leave_type is None:
            raise NotFoundError("Leave type not found.")

        # Only values that actually differ count as changes (a same-value request is a no-op).
        changes = {
            field: value
            for field, value in data.model_dump(exclude_unset=True).items()
            if getattr(leave_type, field) != value
        }
        if not changes:
            return leave_type

        merged_allowance = changes.get("annual_allowance", leave_type.annual_allowance)
        merged_carry = changes.get("carry_forward_limit", leave_type.carry_forward_limit)
        if merged_carry > merged_allowance:
            raise ValidationError(
                "carry_forward_limit cannot be more than annual_allowance.",
                details={"field": "carry_forward_limit"},
            )
        conflict = self._conflict_for(
            company_id, changes.get("name"), changes.get("code"), leave_type.id
        )
        if conflict is not None:
            raise conflict
        locked = [f for f in ("code", "is_paid") if f in changes]
        if locked and self.repo.has_leaves_or_balances(leave_type.id):
            raise ConflictError(
                "Code and paid/unpaid cannot change once leaves or balances exist for this type.",
                details={"fields": locked},
            )

        deactivated = changes.get("is_active") is False
        other_fields = sorted(f for f in changes if not (f == "is_active" and deactivated))
        try:
            self.repo.update(leave_type, **changes)
            if other_fields:
                self.audit.record(
                    company_id=company_id,
                    actor=actor,
                    action="LEAVE_TYPE_UPDATED",
                    entity_type="leave_type",
                    entity_id=leave_type.id,
                    details={"changed_fields": other_fields},
                )
            if deactivated:
                self.audit.record(
                    company_id=company_id,
                    actor=actor,
                    action="LEAVE_TYPE_DEACTIVATED",
                    entity_type="leave_type",
                    entity_id=leave_type.id,
                    details={"leave_type_id": leave_type.id},
                )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("A leave type with this name or code already exists.") from exc
        return leave_type


class LeaveService:
    """Routes 61-66 (10.4): the eight application validations, in order
    (11.3), and balance recompute in the same transaction as the status
    change (11.4)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = LeaveRepository(db)
        self.leave_type_repo = LeaveTypeRepository(db)
        self.balance_repo = LeaveBalanceRepository(db)
        self.holiday_repo = HolidayRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.attendance_repo = AttendanceRepository(db)
        self.settings_repo = CompanySettingsRepository(db)
        self.audit = AuditService(db)
        self.notify = NotificationService(db)

    def _leave_year(self, settings_row: CompanySettings | None, on_date: date) -> int:
        if settings_row is None or settings_row.leave_year_type == LeaveYearType.calendar:
            return on_date.year
        start_month = settings_row.leave_year_start_month
        return on_date.year if on_date.month >= start_month else on_date.year - 1

    def _weekend_days(self, settings_row: CompanySettings | None) -> set[int]:
        return set(settings_row.weekend_days) if settings_row else {6, 7}

    def _total_days(
        self,
        company_id: uuid.UUID,
        settings_row: CompanySettings | None,
        department_id: uuid.UUID | None,
        start_date: date,
        end_date: date,
        is_half_day: bool,
    ) -> Decimal:
        """Spec 11.3: dates inclusive, minus weekends (company_settings.
        weekend_days) and holidays applying to the employee's department."""
        if is_half_day and start_date == end_date:
            return Decimal("0.5")
        weekend_days = self._weekend_days(settings_row)
        holidays = {
            h.date
            for h in self.holiday_repo.list_in_range(
                company_id, start_date, end_date, department_id
            )
        }
        count = 0
        current = start_date
        while current <= end_date:
            if current.isoweekday() not in weekend_days and current not in holidays:
                count += 1
            current += timedelta(days=1)
        return Decimal(count)

    def _new_balance_fields(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, leave_type: LeaveType, year: int
    ) -> dict:
        """A new year opens with the unused balance of the year before, up to the
        type's carry-forward limit; an overspent year carries nothing. With no
        row for the year before, nothing is carried."""
        opening = Decimal("0")
        previous = self.balance_repo.get(employee_id, leave_type.id, year - 1)
        if previous is not None:
            unused = max(self._available(previous), Decimal("0"))
            opening = min(unused, leave_type.carry_forward_limit)
        return {
            "company_id": company_id,
            "employee_id": employee_id,
            "leave_type_id": leave_type.id,
            "year": year,
            "opening_balance": opening,
            "allocated": leave_type.annual_allowance,
        }

    def _get_or_allocate_balance(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        leave_type: LeaveType,
        year: int,
        *,
        lock: bool = False,
    ) -> LeaveBalance:
        """Balance is materialized the first time this employee needs this
        leave type in this year (lazy path); seeding by HR creates the same row.
        With `lock=True` the row is held with SELECT ... FOR UPDATE until commit.
        """
        find = self.balance_repo.get_for_update if lock else self.balance_repo.get
        balance = find(employee_id, leave_type.id, year)
        if balance is None:
            balance, _ = self.balance_repo.create_if_missing(
                **self._new_balance_fields(company_id, employee_id, leave_type, year)
            )
            if lock:
                balance = find(employee_id, leave_type.id, year) or balance
        return balance

    def require_available_balance_locked(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        leave_type: LeaveType,
        year: int,
        requested: Decimal,
    ) -> LeaveBalance | None:
        """Locks the balance row and refuses when a paid type cannot cover
        `requested` days, so the balance never goes negative. Unpaid types have
        no balance and no check. Call it again at approval (4.6) in the same
        transaction as the deduction."""
        if not leave_type.is_paid:
            return None
        balance = self._get_or_allocate_balance(
            company_id, employee_id, leave_type, year, lock=True
        )
        available = self._available(balance)
        if available < requested:
            raise InsufficientLeaveBalanceError(available=available, requested=requested)
        return balance

    def current_leave_year(self, company_id: uuid.UUID) -> int:
        return self._leave_year(self.settings_repo.get_by_company(company_id), utcnow().date())

    @staticmethod
    def _available(balance: LeaveBalance) -> Decimal:
        return balance.opening_balance + balance.allocated - balance.used - balance.encashed

    def apply_leave(
        self, company_id: uuid.UUID, data: LeaveApplyRequest, current_user: User
    ) -> Leave:
        """Route 62. Every validation in 11.3, in order — the first failure
        wins."""
        target_employee_id = data.employee_id
        if target_employee_id is None:
            caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
            if caller_employee is None:
                raise NotFoundError("You do not have an employee record.")
            target_employee_id = caller_employee.id

        # 1. The employee exists, is active, and belongs to the caller's company.
        employee = self.employee_repo.get_by_id(target_employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")

        # 2. The caller is that employee, HR, or that employee's manager.
        is_hr = current_user.role in HR_LEVEL_ROLES
        is_own = employee.user_id == current_user.id
        is_manager = False
        if current_user.role == UserRole.manager:
            caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
            is_manager = (
                caller_employee is not None and employee.reporting_manager_id == caller_employee.id
            )
        if not (is_hr or is_own or is_manager):
            raise ForbiddenError(
                "You do not have permission to apply for leave on behalf of this employee."
            )

        # 3. end_date >= start_date.
        if data.end_date < data.start_date:
            raise LeaveValidationError(
                "end_date must be on or after start_date.", details={"field": "end_date"}
            )

        # 4. leave_type_id exists, belongs to this company, and is active.
        leave_type = self.leave_type_repo.get_by_id(data.leave_type_id, company_id)
        if leave_type is None or not leave_type.is_active:
            raise NotFoundError("Leave type not found.")

        # 5. start_date >= today, unless the caller is HR (may back-date; audited).
        today = utcnow().date()
        if data.start_date < today:
            if not is_hr:
                raise LeaveValidationError(
                    "Cannot apply for leave in the past.", details={"field": "start_date"}
                )
            logger.info(
                "leave_backdated_by_hr",
                extra={
                    "actor_id": str(current_user.id),
                    "employee_id": str(employee.id),
                    "start_date": data.start_date.isoformat(),
                },
            )

        settings_row = self.settings_repo.get_by_company(company_id)
        total_days = self._total_days(
            company_id,
            settings_row,
            employee.department_id,
            data.start_date,
            data.end_date,
            data.is_half_day,
        )

        # 6. max_consecutive_days on the leave type is not exceeded.
        if (
            leave_type.max_consecutive_days is not None
            and total_days > leave_type.max_consecutive_days
        ):
            raise LeaveValidationError(
                f"This leave type allows at most {leave_type.max_consecutive_days} "
                "consecutive day(s).",
                details={
                    "field": "end_date",
                    "max_consecutive_days": leave_type.max_consecutive_days,
                },
            )

        # 7. No overlap with an existing pending/approved leave for this employee.
        overlapping = self.repo.get_overlapping(
            company_id=company_id,
            employee_id=employee.id,
            start_date=data.start_date,
            end_date=data.end_date,
        )
        if overlapping:
            conflicts = [
                {
                    "id": str(o.id),
                    "start_date": o.start_date.isoformat(),
                    "end_date": o.end_date.isoformat(),
                }
                for o in overlapping
            ]
            raise LeaveOverlapError(conflicts)

        # 8. Sufficient balance for the year, unless the leave type is unpaid (LOP).
        self.require_available_balance_locked(
            company_id,
            employee.id,
            leave_type,
            self._leave_year(settings_row, data.start_date),
            total_days,
        )

        # Determine if owner / super_admin: auto-approve immediately
        is_leadership = current_user.role in [UserRole.owner, UserRole.super_admin]
        initial_status = LeaveStatus.approved if is_leadership else LeaveStatus.pending

        leave = self.repo.create(
            company_id=company_id,
            employee_id=employee.id,
            leave_type_id=leave_type.id,
            start_date=data.start_date,
            end_date=data.end_date,
            total_days=total_days,
            is_half_day=data.is_half_day,
            reason=data.reason,
            status=initial_status,
            approved_by=current_user.id if is_leadership else None,
            approved_at=utcnow() if is_leadership else None,
        )

        if is_leadership:
            if leave_type is not None and leave_type.is_paid:
                year = self._leave_year(settings_row, leave.start_date)
                balance = self._get_or_allocate_balance(company_id, employee.id, leave_type, year)
                self.balance_repo.update(balance, used=balance.used + leave.total_days)
            self._write_attendance_for_leave(company_id, settings_row, employee, leave)
            self.audit.record(
                company_id=company_id,
                actor=current_user,
                action="LEAVE_APPROVED",
                entity_type="leave",
                entity_id=leave.id,
                details={
                    "auto_approved": True,
                    "role": current_user.role.value,
                    "reason": data.reason,
                    "days": str(total_days),
                },
            )
        elif employee.reporting_manager_id:
            # Notify manager if present
            mgr = self.employee_repo.get_by_id_any_status(employee.reporting_manager_id, company_id)
            if mgr and mgr.user_id:
                emp_name = f"{employee.first_name} {employee.last_name or ''}".strip()
                lt_name = leave_type.name if leave_type else "Leave"
                message_text = (
                    f"{emp_name} requested {total_days} day(s) {lt_name} "
                    f"from {data.start_date} to {data.end_date}."
                )
                self.notify.notify(
                    company_id=company_id,
                    user_id=mgr.user_id,
                    type="leave_requested",
                    title="New Leave Request",
                    message=message_text,
                    action_url="/leave",
                    entity_type="leave",
                    entity_id=leave.id,
                )

        self.db.commit()
        return leave

    def _assert_can_view(self, company_id: uuid.UUID, employee, current_user: User) -> None:
        if current_user.role in HR_LEVEL_ROLES:
            return
        if employee is not None and employee.user_id == current_user.id:
            return
        if current_user.role == UserRole.manager and employee is not None:
            caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
            if caller_employee is not None and employee.reporting_manager_id == caller_employee.id:
                return
        raise ForbiddenError("You do not have permission to view this leave.")

    def get_leave(self, company_id: uuid.UUID, leave_id: uuid.UUID, current_user: User) -> Leave:
        """Route 63: Own, Mgr, HR."""
        leave = self.repo.get_by_id(leave_id, company_id)
        if leave is None:
            raise NotFoundError("Leave not found.")
        employee = self.employee_repo.get_by_id_any_status(leave.employee_id, company_id)
        self._assert_can_view(company_id, employee, current_user)
        return leave

    def list_leaves(
        self,
        company_id: uuid.UUID,
        current_user: User,
        *,
        employee_id: uuid.UUID | None,
        status: LeaveStatus | None,
        leave_type_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        page_params: PageParams,
    ) -> tuple[list[Leave], int, int]:
        """Route 61: scoped by role, the same shape as attendance's list."""
        allowed: list[uuid.UUID] | None
        if current_user.role in _SEES_EVERYONE:
            allowed = None
        else:
            caller_employee = self.employee_repo.get_by_user_id(company_id, current_user.id)
            if caller_employee is None:
                return [], 0, 0
            if current_user.role == UserRole.manager:
                allowed = self.employee_repo.list_direct_report_ids(company_id, caller_employee.id)
            else:
                allowed = [caller_employee.id]
        if allowed is not None:
            if not allowed:
                return [], 0, 0
            if employee_id is not None and employee_id not in allowed:
                return [], 0, 0
        return self.repo.list_leaves(
            company_id=company_id,
            allowed_employee_ids=allowed,
            employee_id=employee_id,
            status=status,
            leave_type_id=leave_type_id,
            date_from=date_from,
            date_to=date_to,
            page_params=page_params,
        )

    def _write_attendance_for_leave(
        self,
        company_id: uuid.UUID,
        settings_row: CompanySettings | None,
        employee,
        leave: Leave,
    ) -> None:
        weekend_days = self._weekend_days(settings_row)
        holidays = {
            h.date
            for h in self.holiday_repo.list_in_range(
                company_id, leave.start_date, leave.end_date, employee.department_id
            )
        }
        current = leave.start_date
        while current <= leave.end_date:
            if current.isoweekday() not in weekend_days and current not in holidays:
                self.attendance_repo.upsert_for_leave(
                    company_id=company_id,
                    employee_id=employee.id,
                    on_date=current,
                    status=AttendanceStatus.on_leave,
                )
            current += timedelta(days=1)

    def _reverse_attendance_for_leave(self, company_id: uuid.UUID, employee, leave: Leave) -> None:
        """Undoes exactly what approval wrote: soft-deletes the `on_leave`,
        `source=system` rows the upsert created. A day the employee had
        already marked for real (present/wfh, source=web) before approval,
        if any, was overwritten by the upsert and cannot be recovered — the
        schema keeps no history of what a row was before an upsert; this is
        the only reversal the current data model supports."""
        current = leave.start_date
        while current <= leave.end_date:
            record = self.attendance_repo.get_by_employee_and_date(company_id, employee.id, current)
            if (
                record is not None
                and record.source == AttendanceSource.system
                and record.status == AttendanceStatus.on_leave
            ):
                self.attendance_repo.soft_delete(record)
            current += timedelta(days=1)

    def decide_leave(
        self, company_id: uuid.UUID, leave_id: uuid.UUID, data: LeaveDecisionRequest, actor: User
    ) -> Leave:
        """Route 64: Mgr (own reports only), HR. Approval auto-marks
        attendance and recomputes the balance inside the same transaction
        as the status change (11.4) — one commit, at the end."""
        leave = self.repo.get_by_id(leave_id, company_id)
        if leave is None:
            raise NotFoundError("Leave not found.")
        employee = self.employee_repo.get_by_id_any_status(leave.employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee for this leave request not found.")
        verify_approval_authority(self.db, actor, employee)

        if leave.status != LeaveStatus.pending:
            raise ConflictError(f"Leave is not pending (current status: {leave.status.value}).")

        if data.status == "approved":
            leave_type = self.leave_type_repo.get_by_id(leave.leave_type_id, company_id)
            settings_row = self.settings_repo.get_by_company(company_id)
            self.repo.update(
                leave, status=LeaveStatus.approved, approved_by=actor.id, approved_at=utcnow()
            )
            if leave_type is not None and leave_type.is_paid:
                year = self._leave_year(settings_row, leave.start_date)
                balance = self._get_or_allocate_balance(company_id, employee.id, leave_type, year)
                self.balance_repo.update(balance, used=balance.used + leave.total_days)
            self._write_attendance_for_leave(company_id, settings_row, employee, leave)
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="LEAVE_APPROVED",
                entity_type="leave",
                entity_id=leave.id,
                details={
                    "employee_id": jsonable(employee.id),
                    "start_date": jsonable(leave.start_date),
                    "end_date": jsonable(leave.end_date),
                },
            )
            if employee.user_id is not None:
                self.notify.notify(
                    company_id=company_id,
                    user_id=employee.user_id,
                    type="leave_approved",
                    title="Leave approved",
                    message=f"Your leave from {leave.start_date} to {leave.end_date} was approved.",
                    entity_type="leave",
                    entity_id=leave.id,
                )
            self._send_leave_decision_email(
                employee, leave, status="approved", rejection_reason=None
            )
            # Spec 11.10's literal wording: "on attendance mark, leave
            # approval, and employee create/deactivate" — approval only,
            # not rejection (a rejected leave changes nothing the cached
            # dashboard fields summarize).
            DashboardService.invalidate_company_dashboards(company_id)
        else:
            if not data.rejection_reason:
                raise LeaveValidationError(
                    "A rejection reason is required.", details={"field": "rejection_reason"}
                )
            self.repo.update(
                leave, status=LeaveStatus.rejected, rejection_reason=data.rejection_reason
            )
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="LEAVE_REJECTED",
                entity_type="leave",
                entity_id=leave.id,
                details={
                    "employee_id": jsonable(employee.id),
                    "rejection_reason": data.rejection_reason,
                },
            )
            if employee.user_id is not None:
                self.notify.notify(
                    company_id=company_id,
                    user_id=employee.user_id,
                    type="leave_rejected",
                    title="Leave rejected",
                    message=f"Your leave from {leave.start_date} to {leave.end_date} was rejected: "
                    f"{data.rejection_reason}",
                    entity_type="leave",
                    entity_id=leave.id,
                )
            self._send_leave_decision_email(
                employee, leave, status="rejected", rejection_reason=data.rejection_reason
            )

        self.db.commit()
        return leave

    def _send_leave_decision_email(
        self, employee, leave: Leave, *, status: str, rejection_reason: str | None
    ) -> None:
        """Matches the in-app notification above (Spec 11.10) — sent to the
        employee's work email, unlike the pre-activation invitation email,
        since deciding a leave only happens after the employee already has
        a working account (or, for HR applying on someone's behalf, is at
        least reachable at their work address either way)."""
        subject, text_body, html_body = leave_decision_email(
            first_name=employee.first_name,
            status=status,
            start_date=leave.start_date.isoformat(),
            end_date=leave.end_date.isoformat(),
            rejection_reason=rejection_reason,
        )
        send_email_task.delay(
            to=employee.email, subject=subject, text_body=text_body, html_body=html_body
        )

    def cancel_leave(self, company_id: uuid.UUID, leave_id: uuid.UUID, actor: User) -> Leave:
        """Route 65: the employee cancels their own **pending** leave; HR
        may additionally cancel an **approved** leave, reversing the
        attendance rows and restoring the balance (11.3)."""
        leave = self.repo.get_by_id(leave_id, company_id)
        if leave is None:
            raise NotFoundError("Leave not found.")
        employee = self.employee_repo.get_by_id_any_status(leave.employee_id, company_id)
        is_hr = actor.role in HR_LEVEL_ROLES
        is_own = employee is not None and employee.user_id == actor.id

        if leave.status == LeaveStatus.pending:
            if not (is_hr or is_own):
                raise ForbiddenError("You do not have permission to cancel this leave.")
            self.repo.update(leave, status=LeaveStatus.cancelled)
        elif leave.status == LeaveStatus.approved:
            if not is_hr:
                raise ForbiddenError("Only HR may cancel an approved leave.")
            assert employee is not None
            settings_row = self.settings_repo.get_by_company(company_id)
            self._reverse_attendance_for_leave(company_id, employee, leave)
            leave_type = self.leave_type_repo.get_by_id(leave.leave_type_id, company_id)
            if leave_type is not None and leave_type.is_paid:
                year = self._leave_year(settings_row, leave.start_date)
                balance = self.balance_repo.get(employee.id, leave_type.id, year)
                if balance is not None:
                    self.balance_repo.update(
                        balance, used=max(balance.used - leave.total_days, Decimal("0"))
                    )
            self.repo.update(leave, status=LeaveStatus.cancelled)
        else:
            raise ConflictError(f"Cannot cancel a leave that is {leave.status.value}.")

        self.db.commit()
        return leave

    def get_balance(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        year: int | None,
        current_user: User,
    ) -> list[tuple[LeaveBalance, str]]:
        """Route 66: the employee, their direct manager (read only), HR-level.
        Another company's employee is the same 404 as a missing one, for every
        role including super_admin. `year` defaults to the company's current
        leave year. Returns (balance, leave_type_name) pairs."""
        employee = self.employee_repo.get_by_id(employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        is_hr = current_user.role in HR_LEVEL_ROLES
        is_own = employee.user_id == current_user.id
        is_manager = False
        if current_user.role == UserRole.manager:
            caller = self.employee_repo.get_by_user_id(company_id, current_user.id)
            is_manager = caller is not None and employee.reporting_manager_id == caller.id
        if not (is_hr or is_own or is_manager):
            raise ForbiddenError("You do not have permission to view this balance.")

        target_year = year if year is not None else self.current_leave_year(company_id)
        balances = self.balance_repo.list_for_employee_year(employee_id, target_year)
        leave_type_names = {lt.id: lt.name for lt in self.leave_type_repo.list_all(company_id)}
        return [(b, leave_type_names.get(b.leave_type_id, "Unknown")) for b in balances]

    def allocate_balances_for_employee(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, year: int | None, actor: User
    ) -> list[tuple["LeaveBalance", str]]:
        """HR-callable batch seeding: creates a LeaveBalance row for every active
        leave type the company has configured, for the given employee and year
        (default: the current leave year). Skips types that already have a row, so
        repeating it changes nothing. Returns all (balance, type_name) pairs
        after seeding, including pre-existing ones.
        """
        employee = self.employee_repo.get_by_id(employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        target_year = year if year is not None else self.current_leave_year(company_id)

        all_types = self.leave_type_repo.list_all(company_id)
        created = 0
        for lt in (t for t in all_types if t.is_active):
            if self.balance_repo.get(employee_id, lt.id, target_year) is None:
                _, was_created = self.balance_repo.create_if_missing(
                    **self._new_balance_fields(company_id, employee_id, lt, target_year)
                )
                created += int(was_created)

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="LEAVE_BALANCES_SEEDED",
            entity_type="leave_balance",
            entity_id=employee_id,
            details={"employee_id": employee_id, "year": target_year, "created_count": created},
        )
        self.db.commit()
        balances = self.balance_repo.list_for_employee_year(employee_id, target_year)
        type_name_map = {lt.id: lt.name for lt in all_types}
        return [(b, type_name_map.get(b.leave_type_id, "Unknown")) for b in balances]
