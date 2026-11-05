import logging
import uuid
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.approval_authority import DEFAULT_FORBIDDEN_MESSAGE, can_approve_for
from app.core.config import settings
from app.core.encryption import DecryptionFailedError, decrypt_field, encrypt_field
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.pagination import PageParams
from app.core.regions import (
    DEFAULT_COUNTRY,
    allowed_country_codes,
    canonical_country,
    canonical_state,
    country_name,
    is_payroll_ready,
)
from app.core.roles import HR_LEVEL_ROLES
from app.core.time import utcnow
from app.modules.hr.models import Employee, EmploymentType, ResignationStatus
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole
from app.modules.identity.repository import CompanyRepository, UserRepository
from app.modules.payroll.models import (
    CalculationType,
    EmployeeBankAccount,
    EmployeeSalary,
    PayrollItem,
    PayrollRun,
    PayrollRunStatus,
    PayrollRunType,
    PercentageOf,
    PtSlab,
    Reimbursement,
    ReimbursementStatus,
    SalaryComponent,
    SalaryComponentType,
    SalaryStructure,
    StatutoryConfig,
    StatutoryRate,
    TaxSlab,
)
from app.modules.payroll.payment_files import PAYMENT_FILE_FORMATS, PaymentLine
from app.modules.payroll.payslip_engine import (
    ComponentSpec,
    EsiRateSpec,
    MissingRateError,
    PayslipInput,
    PfRateSpec,
    PTSlabSpec,
    SalarySegment,
    StatutoryConfigSpec,
    TaxSlabSpec,
    calculate_payslip,
)
from app.modules.payroll.repository import (
    EmployeeBankAccountRepository,
    EmployeeSalaryRepository,
    PayrollItemRepository,
    PayrollRunPaymentRepository,
    PayrollRunRepository,
    PtSlabRepository,
    ReimbursementRepository,
    SalaryComponentRepository,
    SalaryStructureRepository,
    StatutoryConfigRepository,
    StatutoryRateRepository,
    TaxSlabRepository,
)
from app.modules.payroll.schemas import (
    BankAccountRequest,
    BankAccountResponse,
    PayrollRunCreateRequest,
    PtSlabPutRequest,
    ReimbursementCreateRequest,
    ReimbursementReviewRequest,
    SalaryAssignRequest,
    SalaryComponentAmount,
    SalaryComponentCreateRequest,
    SalaryStructureCreateRequest,
    SalaryStructureUpdateRequest,
    StatutoryConfigResponse,
    StatutoryConfigUpdateRequest,
    StatutoryRateCreateRequest,
    StatutoryRateResponse,
    TaxSlabPostRequest,
    is_masked_account_number,
    mask_payout_account_number,
)
from app.modules.platform.service import AuditService, NotificationService
from app.modules.time_leave.models import AttendanceStatus, Leave
from app.modules.time_leave.repository import AttendanceRepository, LeaveRepository
from app.modules.time_leave.service import (
    LeaveService,
    require_deciding_role,
    verify_approval_authority,
)

logger = logging.getLogger(__name__)


class InvalidStructureError(AppError):
    """A structure's own components are internally inconsistent — a
    business-rule violation (400), not a request-body schema failure (422,
    reserved for FastAPI's own RequestValidationError)."""

    status_code = 400
    code = "invalid_structure"


class SalaryOverlapError(ConflictError):
    """Spec 7.6: no two employee_salaries rows for the same employee may
    overlap."""

    code = "salary_overlap"


class InsufficientCtcError(AppError):
    """Spec 19 WP-16 gate: percentage + fixed earnings must not exceed the
    CTC being assigned — a negative `balance` component means the
    structure was over-allocated for this specific CTC."""

    status_code = 400
    code = "insufficient_ctc"


# A structure's Basic-equivalent component must carry this exact code for
# `percentage_of=basic` components (e.g. HRA) to resolve against it — the
# same "stable key the engine reads" role Spec 7.6 assigns to `code` for
# every component (BASIC, HRA, EPF_EE, ...). Documented here once rather
# than repeated at every call site.
BASIC_CODE = "BASIC"


def _round(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


NO_SALARY_MESSAGE = "No salary is currently assigned to this employee."


def _name_taken(name: str) -> str:
    return f"A salary structure named '{name}' already exists."


class SalaryStructureService:
    """Routes 78-82 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = SalaryStructureRepository(db)
        self.component_repo = SalaryComponentRepository(db)
        self.run_repo = PayrollRunRepository(db)
        self.audit = AuditService(db)

    def _get_or_404(self, company_id: uuid.UUID, structure_id: uuid.UUID) -> SalaryStructure:
        structure = self.repo.get_by_id(structure_id, company_id)
        if structure is None:
            raise NotFoundError("Salary structure not found.")
        return structure

    def _assert_name_free(
        self, company_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
    ) -> None:
        if self.repo.get_by_name(company_id, name, exclude_id) is not None:
            raise ConflictError(_name_taken(name))

    def _add_components(
        self,
        company_id: uuid.UUID,
        structure_id: uuid.UUID,
        components: list[SalaryComponentCreateRequest],
    ) -> None:
        for c in components:
            self.component_repo.create(
                company_id=company_id,
                structure_id=structure_id,
                name=c.name,
                code=c.code,
                type=c.type,
                calculation_type=c.calculation_type,
                value=c.value,
                percentage_of=c.percentage_of,
                is_taxable=c.is_taxable,
                is_statutory=c.is_statutory,
                display_order=c.display_order,
            )

    def _assert_assigned_salaries_stay_valid(
        self,
        company_id: uuid.UUID,
        structure_id: uuid.UUID,
        components: list[SalaryComponentCreateRequest],
    ) -> None:
        """An edit may not make a salary that is in force today, or starts later, refuse its
        own CTC check (Spec 19 WP-16 gate)."""
        salaries = self.repo.list_current_and_future_salaries(
            structure_id, company_id, utcnow().date()
        )
        earnings = [
            SalaryComponent(
                id=uuid.uuid4(),
                code=c.code,
                name=c.name,
                type=c.type,
                calculation_type=c.calculation_type,
                value=c.value,
                percentage_of=c.percentage_of,
            )
            for c in components
            if c.type == SalaryComponentType.earning
        ]
        broken = 0
        for salary in salaries:
            try:
                check_ctc_covers_earnings(earnings, salary.ctc)
            except InsufficientCtcError:
                broken += 1
        if broken:
            raise ConflictError(
                f"This edit would make {broken} {'salary' if broken == 1 else 'salaries'} "
                "on this structure invalid. Revise those salaries first."
            )

    @staticmethod
    def _validate_components(components: list[SalaryComponentCreateRequest]) -> None:
        """Structural sanity, checkable without a concrete CTC (Spec 19
        WP-16 gate's other half — the CTC-dependent "sums to 100%" check
        happens at assignment time, in assign_salary, where a real CTC
        exists to check it against)."""
        codes = [c.code for c in components]
        if len(codes) != len(set(codes)):
            raise InvalidStructureError("Component codes must be unique within a structure.")

        balance_count = sum(1 for c in components if c.calculation_type == CalculationType.balance)
        if balance_count > 1:
            raise InvalidStructureError("A structure may have at most one `balance` component.")

        percentage_of_ctc_total = Decimal("0")
        for c in components:
            if c.calculation_type == CalculationType.percentage:
                if c.value is None or c.percentage_of is None:
                    raise InvalidStructureError(
                        f"Component '{c.code}' is percentage-based and needs both value and "
                        "percentage_of."
                    )
                if c.percentage_of == PercentageOf.ctc:
                    percentage_of_ctc_total += c.value
            elif c.calculation_type == CalculationType.fixed:
                if c.value is None:
                    raise InvalidStructureError(f"Component '{c.code}' is fixed and needs a value.")
            elif c.calculation_type == CalculationType.statutory:
                if not c.is_statutory:
                    raise InvalidStructureError(
                        f"Component '{c.code}' is calculation_type=statutory and must have "
                        "is_statutory=true."
                    )
            elif c.calculation_type == CalculationType.balance:
                if c.value is not None:
                    raise InvalidStructureError(
                        f"Component '{c.code}' is calculation_type=balance and must not carry a "
                        "value — balance is whatever remains of CTC, computed at assignment time."
                    )

        if percentage_of_ctc_total > 100:
            raise InvalidStructureError(
                f"Percentage-of-CTC components sum to {percentage_of_ctc_total}%, over 100%."
            )

        has_percentage_of_basic = any(
            c.calculation_type == CalculationType.percentage
            and c.percentage_of == PercentageOf.basic
            for c in components
        )
        if has_percentage_of_basic and BASIC_CODE not in codes:
            raise InvalidStructureError(
                f"A component uses percentage_of=basic but no component is coded '{BASIC_CODE}'."
            )

    def create_structure(
        self, company_id: uuid.UUID, data: SalaryStructureCreateRequest, actor: User
    ) -> SalaryStructure:
        self._validate_components(data.components)
        self._assert_name_free(company_id, data.name)
        try:
            structure = self.repo.create(
                company_id=company_id, name=data.name, country=data.country, level=data.level
            )
        except IntegrityError as exc:
            # Two requests passed the look-up above at the same moment; the unique index decided.
            self.db.rollback()
            raise ConflictError(_name_taken(data.name)) from exc
        self._add_components(company_id, structure.id, data.components)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="SALARY_STRUCTURE_CREATED",
            entity_type="salary_structure",
            entity_id=structure.id,
            details={"structure_id": str(structure.id), "component_count": len(data.components)},
        )
        self.db.commit()
        reloaded = self.repo.get_by_id(structure.id, company_id)  # reload with components
        assert reloaded is not None
        return reloaded

    def list_structures(
        self, company_id: uuid.UUID, page_params: PageParams
    ) -> tuple[list[SalaryStructure], int, int]:
        return self.repo.list_structures(company_id, page_params)

    def get_structure(self, company_id: uuid.UUID, structure_id: uuid.UUID) -> SalaryStructure:
        return self._get_or_404(company_id, structure_id)

    def update_structure(
        self,
        company_id: uuid.UUID,
        structure_id: uuid.UUID,
        data: SalaryStructureUpdateRequest,
        actor: User,
    ) -> SalaryStructure:
        structure = self._get_or_404(company_id, structure_id)
        updates = data.model_dump(exclude={"components"}, exclude_unset=True)
        # Every check runs before the first write, so a refused edit changes nothing.
        if "name" in updates:
            self._assert_name_free(company_id, updates["name"], exclude_id=structure.id)
        if data.components is not None:
            self._validate_components(data.components)
            if self.run_repo.count_in_flight(company_id):
                raise ConflictError(
                    "Components cannot be edited while a payroll run is processing or "
                    "waiting for approval."
                )
            self._assert_assigned_salaries_stay_valid(company_id, structure.id, data.components)

        if updates:
            try:
                self.repo.update(structure, **updates)
            except IntegrityError as exc:
                self.db.rollback()
                raise ConflictError(_name_taken(updates.get("name", ""))) from exc
        details: dict = {"structure_id": str(structure.id)}
        fields = sorted(updates.keys())
        if data.components is not None:
            self.component_repo.delete_all_for_structure(structure.id, company_id)
            self._add_components(company_id, structure.id, data.components)
            fields = sorted([*fields, "components"])
            details["component_count"] = len(data.components)
        details["fields"] = fields

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="SALARY_STRUCTURE_UPDATED",
            entity_type="salary_structure",
            entity_id=structure.id,
            details=details,
        )
        self.db.commit()
        reloaded = self.repo.get_by_id(structure.id, company_id)
        assert reloaded is not None
        return reloaded

    def delete_structure(self, company_id: uuid.UUID, structure_id: uuid.UUID, actor: User) -> None:
        structure = self._get_or_404(company_id, structure_id)
        in_use = len(
            self.repo.list_current_and_future_salaries(structure.id, company_id, utcnow().date())
        )
        if in_use:
            raise ConflictError(
                f"Cannot delete this structure: {in_use} current or future "
                f"{'salary uses' if in_use == 1 else 'salaries use'} it."
            )
        self.repo.soft_delete(structure)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="SALARY_STRUCTURE_DELETED",
            entity_type="salary_structure",
            entity_id=structure.id,
            details={"structure_id": str(structure.id)},
        )
        self.db.commit()


def _resolve_earning_amounts(
    earnings: list[SalaryComponent], ctc: Decimal
) -> dict[uuid.UUID, Decimal]:
    """Percentage-of-CTC and fixed earnings first, then percentage-of-BASIC
    (which needs Basic's own resolved rupee amount), then `balance` absorbs
    whatever remains of the CTC. The one place this resolution logic lives
    — both resolve_earning_breakdown (for display) and assign_salary (for
    the CTC-sufficiency gate) call this, so there is exactly one balance
    calculation to get right, not two that could drift apart.
    """
    resolved: dict[uuid.UUID, Decimal] = {}
    basic_amount: Decimal | None = None

    for c in earnings:
        # value is only nullable for balance/statutory components (Spec
        # 7.6); _validate_components already guarantees a percentage or
        # fixed component always carries one — the asserts below are for
        # mypy, not a runtime possibility this branch actually hits.
        if c.calculation_type == CalculationType.percentage and c.percentage_of == PercentageOf.ctc:
            assert c.value is not None
            amount = _round(ctc * c.value / Decimal("100"))
            resolved[c.id] = amount
            if c.code == BASIC_CODE:
                basic_amount = amount
        elif c.calculation_type == CalculationType.fixed:
            assert c.value is not None
            resolved[c.id] = _round(c.value)

    for c in earnings:
        if (
            c.calculation_type == CalculationType.percentage
            and c.percentage_of == PercentageOf.basic
        ):
            assert c.value is not None
            base = basic_amount if basic_amount is not None else Decimal("0")
            resolved[c.id] = _round(base * c.value / Decimal("100"))

    non_balance_total = sum(resolved.values(), Decimal("0"))
    balance_component = next(
        (c for c in earnings if c.calculation_type == CalculationType.balance), None
    )
    if balance_component is not None:
        resolved[balance_component.id] = _round(ctc - non_balance_total)

    return resolved


def resolve_earning_breakdown(
    components: list[SalaryComponent], ctc: Decimal
) -> tuple[list[SalaryComponentAmount], list[SalaryComponentAmount], Decimal]:
    """The structural (non-statutory) part of a salary breakdown — resolves
    earnings against a concrete CTC via `_resolve_earning_amounts`.
    Deductions are listed but never computed here — is_statutory ones
    (PF/ESI/PT/TDS) are the payslip engine's job (WP-18), not this
    session's.
    """
    earnings = [c for c in components if c.type == SalaryComponentType.earning]
    deductions = [c for c in components if c.type == SalaryComponentType.deduction]
    resolved = _resolve_earning_amounts(earnings, ctc)

    earning_amounts = [
        SalaryComponentAmount(
            code=c.code,
            name=c.name,
            type=c.type,
            amount=resolved.get(c.id) if c.calculation_type != CalculationType.statutory else None,
            note="Computed by the payroll run, not shown here."
            if c.calculation_type == CalculationType.statutory
            else None,
        )
        for c in sorted(earnings, key=lambda c: c.display_order)
    ]
    deduction_amounts = [
        SalaryComponentAmount(
            code=c.code,
            name=c.name,
            type=c.type,
            amount=None if c.is_statutory else (_round(c.value) if c.value is not None else None),
            note="Computed by the payroll run, not shown here." if c.is_statutory else None,
        )
        for c in sorted(deductions, key=lambda c: c.display_order)
    ]
    gross = sum((a.amount for a in earning_amounts if a.amount is not None), Decimal("0"))
    return earning_amounts, deduction_amounts, gross


def check_ctc_covers_earnings(earning_components: list[SalaryComponent], ctc: Decimal) -> None:
    """Spec 19 WP-16 gate: with a balance component the CTC must be at least the fixed and
    percentage earnings (the balance is what is left and may not go negative); without one the
    earnings must total the CTC exactly. Raises InsufficientCtcError with the numbers."""
    resolved = _resolve_earning_amounts(earning_components, ctc)
    balance_component = next(
        (c for c in earning_components if c.calculation_type == CalculationType.balance), None
    )
    non_balance_total = sum(
        (
            amount
            for cid, amount in resolved.items()
            if balance_component is None or cid != balance_component.id
        ),
        Decimal("0"),
    )
    if balance_component is not None:
        if resolved[balance_component.id] < 0:
            raise InsufficientCtcError(
                f"This structure's fixed and percentage earnings total {non_balance_total}, "
                f"more than the {ctc} CTC being assigned.",
                details={"required_minimum": str(non_balance_total)},
            )
    elif non_balance_total != _round(ctc):
        raise InsufficientCtcError(
            f"This structure has no `balance` component, and its earnings total "
            f"{non_balance_total}, not the {ctc} CTC being assigned.",
            details={"components_total": str(non_balance_total)},
        )


class EmployeeSalaryService:
    """Route 83-84 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = EmployeeSalaryRepository(db)
        self.structure_repo = SalaryStructureRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.payroll_item_repo = PayrollItemRepository(db)
        self.audit = AuditService(db)

    def assign_salary(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, data: SalaryAssignRequest, actor: User
    ) -> tuple[EmployeeSalary, SalaryStructure, list, list, Decimal]:
        target_company_id = company_id
        # The employee row is locked first: two assignments for one employee queue up here, so
        # the second one sees the first one's row when it looks for overlaps.
        if actor.role == UserRole.super_admin:
            found = self.employee_repo.get_by_id_any_status(employee_id, None)
            if found is None:
                raise NotFoundError("Employee not found.")
            target_company_id = found.company_id
            employee = self.employee_repo.get_by_id_for_update(
                employee_id, target_company_id, allow_inactive=True
            )
        else:
            employee = self.employee_repo.get_by_id_for_update(employee_id, target_company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")

        structure = self.structure_repo.get_by_id(data.structure_id, target_company_id)
        if structure is None:
            raise NotFoundError("Salary structure not found.")
        if not structure.is_active:
            raise ConflictError("This salary structure is inactive and cannot be assigned.")

        if self.repo.count_for_employee(employee_id, target_company_id) and not (
            data.revision_reason
        ):
            raise ValidationError("A reason is required when revising an existing salary.")

        # A new salary is open-ended, so it overlaps every existing row that is still open or
        # ends on/after its start. The one open-ended row that started earlier is closed below;
        # everything else is a conflict.
        open_ended = None
        for row in self.repo.get_overlapping(employee_id, target_company_id, data.effective_from):
            if row.effective_to is None:
                if row.effective_from >= data.effective_from:
                    raise SalaryOverlapError(
                        "Cannot assign salary with effective_from on or before "
                        "existing open-ended salary. Existing salary starts on "
                        f"{row.effective_from.isoformat()}."
                    )
                open_ended = row
            else:
                raise SalaryOverlapError(
                    f"This overlaps an existing salary period "
                    f"({row.effective_from.isoformat()} to {row.effective_to.isoformat()})."
                )

        # History that a payslip already relies on is not rewritten: no start in, or before, a
        # month that an approved or paid run has already paid this employee for.
        paid = self.payroll_item_repo.first_released_month_from(
            employee_id, target_company_id, data.effective_from.year, data.effective_from.month
        )
        if paid is not None:
            raise ConflictError(
                f"This employee has already been paid for {paid[1]:02d}/{paid[0]} by an approved "
                "or paid payroll run. Choose a start date after that month."
            )

        # Validate the CTC actually covers the structure's fixed + percentage
        # earnings before committing anything (Spec 19 WP-16 gate): with a
        # balance component, the CTC must be at least the non-balance total
        # (balance is then whatever's left, and must not go negative);
        # without one, the earnings must total the CTC exactly.
        earning_components = [
            c for c in structure.components if c.type == SalaryComponentType.earning
        ]
        check_ctc_covers_earnings(earning_components, data.ctc)

        # Closing the old row and creating the new one are one save: any failure rolls both back.
        try:
            if open_ended is not None:
                self.repo.close(open_ended, data.effective_from - timedelta(days=1))
            salary = self.repo.create(
                company_id=target_company_id,
                employee_id=employee_id,
                structure_id=data.structure_id,
                ctc=data.ctc,
                effective_from=data.effective_from,
                revision_reason=data.revision_reason,
                created_by=actor.id,
            )
            self.audit.record(
                company_id=target_company_id,
                actor=actor,
                action="EMPLOYEE_SALARY_ASSIGNED",
                entity_type="employee_salary",
                entity_id=salary.id,
                details={
                    "employee_id": str(employee_id),
                    "structure_id": str(data.structure_id),
                    "effective_from": data.effective_from.isoformat(),
                },
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if "ex_employee_salaries_no_overlap" in str(exc.orig):
                raise SalaryOverlapError(
                    "This overlaps an existing salary period for this employee."
                ) from exc
            raise
        except Exception:
            self.db.rollback()
            raise
        earnings, deductions, gross = resolve_earning_breakdown(structure.components, salary.ctc)
        return salary, structure, earnings, deductions, gross

    def get_current_salary(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, current_user: User
    ) -> tuple[EmployeeSalary, SalaryStructure, list, list, Decimal]:
        """Route 84: Own, HR, Super Admin."""
        employee, lookup_company_id = self._employee_visible_to(
            company_id, employee_id, current_user
        )
        salary = self.repo.get_in_force(employee_id, lookup_company_id, utcnow().date())
        if salary is None:
            raise NotFoundError(NO_SALARY_MESSAGE)
        # A structure deleted after the salary was assigned still describes that salary.
        structure = self.structure_repo.get_by_id_including_deleted(
            salary.structure_id, lookup_company_id
        )
        if structure is None:
            raise NotFoundError("Salary structure not found.")
        self._audit_hr_view(lookup_company_id, employee, current_user, "employee_salary")
        earnings, deductions, gross = resolve_earning_breakdown(structure.components, salary.ctc)
        return salary, structure, earnings, deductions, gross

    def list_history(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        current_user: User,
        page_params: PageParams,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> tuple[list[tuple[EmployeeSalary, str]], int, int]:
        """Every salary row of an employee, newest first, with its structure's name."""
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ValidationError("from_date must not be after to_date.")
        employee, lookup_company_id = self._employee_visible_to(
            company_id, employee_id, current_user
        )
        rows, total, pages = self.repo.list_history(
            employee_id, lookup_company_id, page_params, from_date, to_date
        )
        names = self.repo.structure_names([r.structure_id for r in rows], lookup_company_id)
        self._audit_hr_view(lookup_company_id, employee, current_user, "employee_salary_history")
        return [(r, names.get(r.structure_id, "")) for r in rows], total, pages

    def _employee_visible_to(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, current_user: User
    ) -> tuple[Employee, uuid.UUID]:
        """Own salary, or owner / HR admin for anyone in the company, or super admin. A
        manager gets no access, not even to a direct report. Another company's employee and a
        missing one are the same 404."""
        if current_user.role == UserRole.super_admin:
            employee = self.employee_repo.get_by_id_any_status(employee_id, None)
            if employee is None:
                raise NotFoundError("Employee not found.")
            return employee, employee.company_id
        employee = self.employee_repo.get_by_id_any_status(employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        is_hr = current_user.role in HR_LEVEL_ROLES
        is_own = employee.user_id == current_user.id
        if not (is_hr or is_own):
            raise ForbiddenError("You do not have permission to view this employee's salary.")
        return employee, company_id

    def _audit_hr_view(
        self, company_id: uuid.UUID, employee: Employee, viewer: User, entity_type: str
    ) -> None:
        """An owner or HR admin reading someone else's pay leaves one audit row (ids only)."""
        if viewer.role not in (UserRole.hr_admin, UserRole.owner) or employee.user_id == viewer.id:
            return
        self.audit.record(
            company_id=company_id,
            actor=viewer,
            action="SALARY_VIEWED_BY_HR",
            entity_type=entity_type,
            entity_id=employee.id,
            details={"employee_id": str(employee.id)},
        )
        self.db.commit()


# 5.7: only a company's own owner and hr_admin read or change its payout (bank) settings;
# a platform account (super_admin) must not move a company's bank details.
PAYOUT_ROLES = (UserRole.owner, UserRole.hr_admin)
PAYOUT_FIELDS = frozenset(
    {"payout_bank_name", "payout_account_number", "payout_ifsc_code", "payout_enabled"}
)
PAYOUT_ACCOUNT_COLUMN = "payout_account_number"
PAYOUT_FORBIDDEN_MESSAGE = "You do not have permission to view or change the payout settings."

# 5.6 reimbursement claims. The age window and the receipt types are the claim rules the
# business set for this module (input rules, not statutory figures).
MAX_EXPENSE_AGE_DAYS = 90
RECEIPT_FILE_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})
MAX_CHAIN_DEPTH = 20
CLAIMS_PAGE_URL = "/payroll/reimbursements"
CLAIM_NOT_FOUND_MESSAGE = "Reimbursement claim not found."
RECEIPT_NOT_FOUND_MESSAGE = "Receipt file not found."
RECEIPT_FORBIDDEN_MESSAGE = "You do not have permission to view this receipt."
RECEIPT_IN_USE_MESSAGE = "This receipt is already attached to another claim."
DUPLICATE_CLAIM_MESSAGE = "A claim for the same date, type and amount already exists."


class StatutoryConfigService:
    """Routes 85-86 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = StatutoryConfigRepository(db)
        self.rate_repo = StatutoryRateRepository(db)
        self.company_repo = CompanyRepository(db)
        self.audit = AuditService(db)

    def company_country(self, company_id: uuid.UUID) -> str:
        """The company's country: the one source for which payroll rules apply. The config's
        own `country` column is only a copy made when the row is created."""
        company = self.company_repo.get_by_id(company_id)
        return company.country if company is not None else DEFAULT_COUNTRY

    def get_or_create(self, company_id: uuid.UUID) -> StatutoryConfig:
        """Lazily created on first access with the column defaults (every switch on, the new
        regime). Rates and ceilings are not stored here: they are the platform's
        effective-dated rows in `statutory_rates` (5.2)."""
        config = self.repo.get_by_company(company_id)
        if config is not None:
            return config
        config = self.repo.create(company_id=company_id, country=self.company_country(company_id))
        self.db.commit()
        return config

    # --- payout settings (5.7) ---------------------------------------------

    def view(
        self, company_id: uuid.UUID, actor: User, *, reveal: bool = False
    ) -> StatutoryConfigResponse:
        """The company's statutory settings. The payout account number is always masked,
        unless `reveal` is set: then the plain number is returned and the reveal is audited
        (every time). Platform accounts never see any payout field."""
        config = self.get_or_create(company_id)
        if not reveal:
            return self._response(config, actor)
        if actor.role not in PAYOUT_ROLES:
            raise ForbiddenError(PAYOUT_FORBIDDEN_MESSAGE)
        number = self._stored_number(config)
        if number is not None:
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="PAYOUT_ACCOUNT_REVEALED",
                entity_type="statutory_config",
                entity_id=config.id,
                details={"fields": [PAYOUT_ACCOUNT_COLUMN]},
            )
            self.db.commit()
        return self._response(config, actor, revealed=number)

    def update(
        self, company_id: uuid.UUID, data: StatutoryConfigUpdateRequest, actor: User
    ) -> StatutoryConfigResponse:
        changes = data.model_dump(exclude_unset=True)
        payout_touched = PAYOUT_FIELDS & changes.keys()
        if payout_touched and actor.role not in PAYOUT_ROLES:
            raise ForbiddenError(PAYOUT_FORBIDDEN_MESSAGE)
        config = self.get_or_create(company_id)
        self._check_professional_tax(config, changes, self.company_country(company_id))

        number_columns: dict[str, object] = {}
        if "payout_account_number" in changes:
            number_columns = self._number_columns(config, changes.pop("payout_account_number"))

        if payout_touched:
            self._assert_payout_can_be_enabled(config, changes, number_columns)

        # Field names only: the audit row never holds a value (not even a masked one).
        fields = sorted([*changes, *([PAYOUT_ACCOUNT_COLUMN] if number_columns else [])])
        if fields:
            self.repo.update(config, **changes, **number_columns, updated_by=actor.id)
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="STATUTORY_CONFIG_UPDATED",
                entity_type="statutory_config",
                entity_id=config.id,
                details={"fields": fields},
            )
            self.db.commit()
        return self._response(config, actor)

    @staticmethod
    def _check_professional_tax(
        config: StatutoryConfig, changes: dict[str, object], country: str
    ) -> None:
        """The professional-tax state is CHOSEN from the states of the company's country (a
        match ignores case and is stored in the canonical spelling); switching professional
        tax on needs a state. Settings that do not touch either are never blocked here."""
        if "pt_state" in changes and changes["pt_state"] is not None:
            canonical = canonical_state(country, str(changes["pt_state"]))
            if canonical is None:
                raise ValidationError(
                    f"The professional-tax state must be one of the states of "
                    f"{country_name(country)} in the shared list.",
                    details={"field": "pt_state"},
                )
            changes["pt_state"] = canonical
        if "pt_enabled" in changes or "pt_state" in changes:
            enabled = changes.get("pt_enabled", config.pt_enabled)
            state = changes["pt_state"] if "pt_state" in changes else config.pt_state
            if enabled and not state:
                raise ValidationError(
                    "Professional tax is switched on, so a state must be chosen.",
                    details={"field": "pt_state"},
                )

    def _response(
        self, config: StatutoryConfig, actor: User, *, revealed: str | None = None
    ) -> StatutoryConfigResponse:
        country = self.company_country(config.company_id)
        response = StatutoryConfigResponse.model_validate(config)
        response = response.model_copy(
            update={
                "country": country,
                "effective_rates": [
                    StatutoryRateResponse.model_validate(rate)
                    for rate in self.rate_repo.list_in_force(country, utcnow().date())
                ],
            }
        )
        if actor.role not in PAYOUT_ROLES:
            return response.model_copy(
                update={
                    "payout_bank_name": None,
                    "payout_account_number": None,
                    "payout_ifsc_code": None,
                    "payout_enabled": False,
                }
            )
        shown = revealed or mask_payout_account_number(config.payout_account_last4)
        return response.model_copy(update={"payout_account_number": shown})

    @staticmethod
    def _stored_number(config: StatutoryConfig) -> str | None:
        if config.payout_account_number_enc is None:
            return None
        return decrypt_field(
            bytes(config.payout_account_number_enc),
            company_id=config.company_id,
            column=PAYOUT_ACCOUNT_COLUMN,
        )

    def _number_columns(self, config: StatutoryConfig, submitted: str | None) -> dict[str, object]:
        """The column values to write for a submitted account number: nothing when the value
        is the mask or the number already stored, a fresh encryption otherwise."""
        if submitted is None:
            if config.payout_account_number_enc is None:
                return {}
            return {"payout_account_number_enc": None, "payout_account_last4": None}
        if is_masked_account_number(submitted):
            stored_last4 = config.payout_account_last4
            if stored_last4 is None or submitted.lstrip("*") not in ("", stored_last4):
                raise ValidationError("The masked account number does not match the stored one.")
            return {}
        if config.payout_account_last4 == submitted[-4:]:
            try:
                if self._stored_number(config) == submitted:
                    return {}
            except DecryptionFailedError:
                pass  # a damaged stored value is replaced by the number just entered
        return {
            "payout_account_number_enc": encrypt_field(
                submitted, company_id=config.company_id, column=PAYOUT_ACCOUNT_COLUMN
            ),
            "payout_account_last4": submitted[-4:],
        }

    @staticmethod
    def _assert_payout_can_be_enabled(
        config: StatutoryConfig, changes: dict[str, object], number_columns: dict[str, object]
    ) -> None:
        enabled = changes.get("payout_enabled", config.payout_enabled)
        if not enabled:
            return
        bank = changes.get("payout_bank_name", config.payout_bank_name)
        ifsc = changes.get("payout_ifsc_code", config.payout_ifsc_code)
        number = number_columns.get("payout_account_number_enc", config.payout_account_number_enc)
        if not (bank and ifsc and number):
            raise ValidationError(
                "Payout can be enabled only when the bank name, account number and IFSC code "
                "are all set."
            )


_ONE_PAISA = Decimal("0.01")

# 5.8 bank details. The column names are part of the encryption's associated data (a number
# copied to another column fails to decrypt); the snapshot of an approved run has its own.
BANK_ACCOUNT_COLUMN = "bank_account_number"
PAYMENT_ACCOUNT_COLUMN = "payment_account_number"
BANK_ROLES = (UserRole.owner, UserRole.hr_admin)
BANK_FORBIDDEN_MESSAGE = "You do not have permission to view or change these bank details."
BANK_NOT_FOUND_MESSAGE = "No bank details are saved for this employee."
BANK_EMPLOYEE_NOT_FOUND_MESSAGE = "Employee not found."
BANK_INACTIVE_MESSAGE = "Bank details can be saved only for an active employee."
BANK_NOTIFICATION_TYPE = "bank_details_changed"
BANK_PAGE_URL = "/payroll/bank-account"
PAYMENT_EXCLUDED_NO_BANK = "no_bank_details"
PAYMENT_EXCLUDED_NET_PAY = "net_pay_not_positive"
PAYMENT_EXCLUDED_UNREADABLE = "bank_details_unreadable"
NO_PAYMENT_LINES_MESSAGE = (
    "This run was approved before payment files existed, so it has no saved payment details; "
    "a file cannot be built for it."
)
NOBODY_PAYABLE_MESSAGE = (
    "Nobody in this run can be paid by file: every employee is missing bank details or has no "
    "net pay."
)


def _assert_contiguous(ranges: list[tuple[Decimal, Decimal | None]], what: str) -> None:
    """A slab set must start at 0.00, have no gap and no overlap (the next lower bound is the
    previous upper bound plus one paisa) and end with an open-ended slab (5.2 rule 6)."""
    ordered = sorted(ranges, key=lambda r: r[0])
    if ordered[0][0] != 0:
        raise ValidationError(f"The first {what} must start at 0.00.")
    for index, (low, high) in enumerate(ordered):
        is_last = index == len(ordered) - 1
        if high is not None and high < low:
            raise ValidationError(f"A {what} has an upper limit below its lower limit ({low}).")
        if high is None and not is_last:
            raise ValidationError(f"Only the last {what} may have no upper limit.")
        if is_last and high is not None:
            raise ValidationError(f"The last {what} must have no upper limit.")
        if high is not None:
            expected = high + _ONE_PAISA
            following = ordered[index + 1][0]
            if following < expected:
                raise ValidationError(f"The {what}s overlap at {following}.")
            if following > expected:
                raise ValidationError(f"The {what}s have a gap between {high} and {following}.")


def _listed_country(code: str) -> str:
    """The upper-case code of a country in the shared list, else a 422 naming the codes."""
    country = canonical_country(code)
    if country is None:
        raise ValidationError(
            f"Country must be one of: {allowed_country_codes()}.",
            details={"field": "country", "allowed": allowed_country_codes().split(", ")},
        )
    return country


def _periods(rows: list[tuple[date, date | None]]) -> str:
    return ", ".join(f"{start} to {end}" if end else f"{start} onwards" for start, end in rows)


class StatutoryRateService:
    """`/payroll/statutory-rates` (5.2): platform-managed, effective-dated PF and ESI rows."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = StatutoryRateRepository(db)
        self.audit = AuditService(db)

    def list_rates(
        self,
        page_params: PageParams,
        scheme: str | None,
        on_date: date | None,
        country: str | None = None,
    ) -> tuple[list[StatutoryRate], int, int]:
        if country is not None:
            country = _listed_country(country)
        return self.repo.list_rates(page_params, scheme, on_date, country)

    def add_rate(self, data: StatutoryRateCreateRequest, actor: User) -> StatutoryRate:
        """A new rate adds a row and ends the open row the day before, in one save. Rows of
        a scheme in one country never overlap: checked here (naming the dates) and by the
        database."""
        country = _listed_country(data.country)
        rows = self.repo.list_for_scheme_locked(country, data.scheme)
        start = data.effective_from
        open_row = next((r for r in rows if r.effective_to is None), None)
        clash = (open_row is not None and start <= open_row.effective_from) or any(
            r.effective_to is not None and start <= r.effective_to for r in rows
        )
        if clash:
            raise ConflictError(
                f"A new {data.scheme.upper()} rate starting {start} would overlap or precede the "
                f"existing rates ({_periods([(r.effective_from, r.effective_to) for r in rows])}). "
                "A new rate must start after the current rate's start date and outside every "
                "ended period."
            )
        try:
            if open_row is not None:
                self.repo.set_effective_to(open_row, start - timedelta(days=1))
            rate = self.repo.create(
                country=country,
                scheme=data.scheme,
                employee_rate=data.employee_rate,
                employer_rate=data.employer_rate,
                wage_ceiling=data.wage_ceiling,
                employer_epf_rate=data.employer_epf_rate,
                employer_eps_rate=data.employer_eps_rate,
                edli_rate=data.edli_rate,
                admin_charge_rate=data.admin_charge_rate,
                employee_exempt_daily_wage=data.employee_exempt_daily_wage,
                effective_from=start,
                effective_to=None,
                source_url=data.source_url,
                source_title=data.source_title,
                source_note=data.source_note,
                verified_on=data.verified_on,
            )
        except IntegrityError:
            # Two simultaneous adds: the exclusion constraint decides, the loser is a 409.
            self.db.rollback()
            raise ConflictError(
                f"Another {data.scheme.upper()} rate was added at the same time and overlaps "
                f"the one starting {start}. Reload and try again."
            ) from None
        self.audit.record(
            company_id=actor.company_id,
            actor=actor,
            action="STATUTORY_RATE_ADDED",
            entity_type="statutory_rate",
            entity_id=rate.id,
            details={
                "country": rate.country,
                "scheme": rate.scheme,
                "rate_id": str(rate.id),
                "closed_rate_id": str(open_row.id) if open_row is not None else None,
            },
        )
        self.db.commit()
        return rate


class PtSlabService:
    """Routes 87-88 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = PtSlabRepository(db)
        self.audit = AuditService(db)

    def list_for_company(self, company_id: uuid.UUID) -> list:
        """The slabs of the company's own professional-tax state; none while no state is
        chosen (there is no default state)."""
        config = StatutoryConfigService(self.db).get_or_create(company_id)
        if not config.pt_state:
            return []
        country = StatutoryConfigService(self.db).company_country(company_id)
        return self.repo.list_for_state(country, config.pt_state)

    def add_slab_set(self, data: PtSlabPutRequest, actor: User) -> list:
        """SA only. Always adds a new effective-dated set and ends the state's open set the
        day before — never mutates a historical row, so a payroll date before this change
        keeps resolving to whatever was in force then (Spec 12)."""
        country = _listed_country(data.country)
        state = canonical_state(country, data.state)
        if state is None:
            raise ValidationError(
                f"The state must be one of the states of {country_name(country)} in the "
                "shared list.",
                details={"field": "state"},
            )
        _assert_contiguous([(s.income_min, s.income_max) for s in data.slabs], "slab")
        existing = self.repo.list_open_locked(country, state)
        everything = self.repo.list_for_state(country, state)
        start = data.effective_from
        if any(
            r.effective_from >= start or (r.effective_to and start <= r.effective_to)
            for r in everything
        ):
            known = sorted({(r.effective_from, r.effective_to) for r in everything})
            raise ConflictError(
                f"A new {state} professional-tax set starting {start} must start after the "
                f"current set's start date and outside every ended period (existing: "
                f"{_periods(known)})."
            )
        if existing:
            self.repo.set_effective_to(existing, start - timedelta(days=1))
        created = [
            self.repo.create(
                country=country,
                state=state,
                income_min=row.income_min,
                income_max=row.income_max,
                monthly_amount=row.monthly_amount,
                special_month=row.special_month,
                special_month_amount=row.special_month_amount,
                effective_from=start,
                effective_to=None,
                source_url=data.source_url,
                source_title=data.source_title,
                source_note=data.source_note,
                verified_on=data.verified_on,
            )
            for row in data.slabs
        ]
        self.audit.record(
            company_id=actor.company_id,
            actor=actor,
            action="PT_SLAB_SET_ADDED",
            entity_type="pt_slab",
            entity_id=created[0].id,
            details={
                "country": country,
                "state": state,
                "slab_ids": [str(s.id) for s in created],
            },
        )
        self.db.commit()
        return created


class TaxSlabService:
    """Routes 89-90 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = TaxSlabRepository(db)
        self.audit = AuditService(db)

    def list_for(self, country: str, financial_year: str, regime=None) -> list:
        return self.repo.list_for(_listed_country(country), financial_year, regime)

    def add_bracket_set(self, data: TaxSlabPostRequest, actor: User) -> list:
        """SA only. Same append-only reasoning as PtSlabService: a financial year and regime
        gets one bracket set; a second one is refused instead of mixing with the first."""
        _listed_country(data.country)
        _assert_contiguous([(b.min_income, b.max_income) for b in data.brackets], "bracket")
        if self.repo.list_for(data.country, data.financial_year, data.regime):
            raise ConflictError(
                f"The {data.regime.value} regime for financial year {data.financial_year} "
                "already has a bracket set; existing rows are never changed."
            )
        created = [
            self.repo.create(
                country=data.country,
                financial_year=data.financial_year,
                regime=data.regime,
                min_income=bracket.min_income,
                max_income=bracket.max_income,
                rate_percent=bracket.rate_percent,
                cess_percent=data.cess_percent,
                surcharge_rules=data.surcharge_rules,
                effective_from=data.effective_from,
                source_url=data.source_url,
                source_title=data.source_title,
                source_note=data.source_note,
                verified_on=data.verified_on,
            )
            for bracket in data.brackets
        ]
        self.audit.record(
            company_id=actor.company_id,
            actor=actor,
            action="TAX_SLAB_SET_ADDED",
            entity_type="tax_slab",
            entity_id=created[0].id,
            details={
                "country": data.country,
                "financial_year": data.financial_year,
                "regime": data.regime.value,
                "slab_ids": [str(s.id) for s in created],
            },
        )
        self.db.commit()
        return created


_ONE = Decimal("1")
_HALF = Decimal("0.5")
_ZERO = Decimal("0")

CANNOT_APPROVE_OWN_RUN = "You cannot approve a payroll run that you created."


@dataclass(frozen=True)
class AttendanceSummary:
    lop_days: Decimal
    absent_days: Decimal
    half_days: Decimal
    paid_leave_days: Decimal
    # The loss of pay of each date, so that a month split across salary rows charges every
    # such day at the daily rate of the segment that contains it (5.3 / 5.4, B3).
    lop_by_date: tuple[tuple[date, Decimal], ...] = ()


def summarise_attendance(
    *,
    month_start: date,
    month_end: date,
    working_dates: list[date],
    joined_on: date,
    last_working_date: date | None,
    attendance: dict[date, AttendanceStatus],
    leaves: list[tuple[Leave, bool]],
    attendance_exempt: bool,
) -> AttendanceSummary:
    """Loss of pay for one employee and month, one date at a time so that no date is counted
    twice. A calendar day before joining or after the approved last working date is loss of
    pay. On a working date, an approved leave decides (unpaid = loss of pay, paid = none) and
    attendance is not looked at; otherwise a missing or `absent` row is a full day and a
    `half_day` row half a day. Weekends and holidays are never loss of pay. Mispunch and
    pending_regularization rows are not deducted."""
    working = set(working_dates)
    leave_on: dict[date, tuple[bool, Decimal]] = {}
    for leave, is_paid in leaves:
        fraction = _HALF if leave.is_half_day else _ONE
        day = max(leave.start_date, month_start)
        stop = min(leave.end_date, month_end)
        while day <= stop:
            leave_on.setdefault(day, (is_paid, fraction))
            day += timedelta(days=1)

    lop = absent = half = paid_leave = _ZERO
    lop_dates: list[tuple[date, Decimal]] = []
    day = month_start
    while day <= month_end:
        lop_before = lop
        if day < joined_on or (last_working_date is not None and day > last_working_date):
            lop += _ONE
        elif day in working:
            covered = leave_on.get(day)
            if covered is not None:
                is_paid, fraction = covered
                if is_paid:
                    paid_leave += fraction
                else:
                    lop += fraction
            elif not attendance_exempt:
                status = attendance.get(day)
                if status is None or status == AttendanceStatus.absent:
                    lop += _ONE
                    absent += _ONE
                elif status == AttendanceStatus.half_day:
                    lop += _HALF
                    half += _ONE
        if lop != lop_before:
            lop_dates.append((day, lop - lop_before))
        day += timedelta(days=1)
    return AttendanceSummary(lop, absent, half, paid_leave, tuple(lop_dates))


@dataclass(frozen=True)
class MonthRates:
    """What a payroll month needs, resolved on the first day of that month."""

    pf: PfRateSpec | None
    esi: EsiRateSpec | None
    pt_slabs: list[PtSlab]
    tax_slabs: list[TaxSlab]
    financial_year: str


class PayrollRunService:
    """Routes 91-94 (Spec 10.6, Spec 11.9)."""

    def __init__(self, db: Session):
        self.db = db
        self.rate_repo = StatutoryRateRepository(db)
        self.repo = PayrollRunRepository(db)
        self.item_repo = PayrollItemRepository(db)
        self.reimbursement_repo = ReimbursementRepository(db)
        self.statutory_service = StatutoryConfigService(db)
        self.pt_repo = PtSlabRepository(db)
        self.tax_repo = TaxSlabRepository(db)
        self.salary_repo = EmployeeSalaryRepository(db)
        self.structure_repo = SalaryStructureRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.leave_repo = LeaveRepository(db)
        self.attendance_repo = AttendanceRepository(db)
        self.leave_service = LeaveService(db)
        from app.modules.projects.repository import ProjectRepository

        self.project_repo = ProjectRepository(db)
        self.payment_repo = PayrollRunPaymentRepository(db)
        self.bank_repo = EmployeeBankAccountRepository(db)
        self.audit = AuditService(db)

    def create_run(
        self,
        company_id: uuid.UUID,
        data: PayrollRunCreateRequest,
        idempotency_key: str,
        actor: User,
    ) -> PayrollRun:
        # 1. Idempotency Check (Spec 11.9 Step 2)
        existing = self.repo.get_by_idempotency_key(company_id, idempotency_key)
        if existing is not None:
            return existing

        # 2. Only a completed month can be paid
        today = utcnow().date()
        if (data.year, data.month) >= (today.year, today.month):
            raise ValidationError(
                "Payroll can only be run for a completed month.",
                details={"field": "month"},
            )

        # A company's country decides which payroll rules apply; a country whose statutory
        # tables are not ready is refused before any run row exists (5.2).
        country = self.statutory_service.company_country(company_id)
        if not is_payroll_ready(country):
            raise ConflictError(f"Payroll rules for {country_name(country)} are not available yet")

        # 3. Check regular run uniqueness per company/month/year
        regular_message = f"A regular payroll run for {data.month}/{data.year} already exists."
        if data.run_type == "regular":
            if self.repo.get_regular_run(company_id, data.month, data.year) is not None:
                raise ConflictError(regular_message)

        # The company's statutory config is created lazily and that commits, so it must exist
        # before the run row does: a commit after the insert would save a half-built run.
        statutory_config = self.statutory_service.get_or_create(company_id)

        # The rates in force on the first day of the payroll month. A row that is missing
        # stops the run here, before any run row exists, with a clear 409.
        month_rates = self._rates_for_month(statutory_config, data, country)

        # 4. Create Draft Run with Idempotency Key (Spec 11.9 Step 3 & 4). The unique indexes
        # decide a race between two simultaneous creates: the loser gets the same answer as
        # the sequential case instead of a 500.
        run_type_enum = (
            PayrollRunType.off_cycle if data.run_type == "off_cycle" else PayrollRunType.regular
        )
        try:
            run = self.repo.create(
                company_id=company_id,
                month=data.month,
                year=data.year,
                status=PayrollRunStatus.processing,
                run_type=run_type_enum,
                idempotency_key=idempotency_key,
                run_by=actor.id,
            )
        except IntegrityError:
            self.db.rollback()
            retry_existing = self.repo.get_by_idempotency_key(company_id, idempotency_key)
            if retry_existing is not None:
                return retry_existing
            if data.run_type == "regular":
                raise ConflictError(regular_message) from None
            raise

        try:
            return self._generate_run(company_id, data, run, actor, statutory_config, month_rates)
        except Exception:
            # Nothing of a half-built run may stay: no run row, no item, no locked claim.
            self.db.rollback()
            raise

    @staticmethod
    def _component_specs(structure: SalaryStructure) -> list[ComponentSpec]:
        return [
            ComponentSpec(
                code=c.code,
                name=c.name,
                type=c.type.value,
                calculation_type=c.calculation_type.value,
                value=c.value,
                percentage_of=c.percentage_of.value if c.percentage_of else None,
                is_taxable=c.is_taxable,
                is_statutory=c.is_statutory,
                display_order=c.display_order,
            )
            for c in structure.components
        ]

    def _salary_segments(
        self,
        company_id: uuid.UUID,
        rows: list[EmployeeSalary],
        month_end_components: list[ComponentSpec],
        month_start: date,
        month_end: date,
        lop_by_date: tuple[tuple[date, Decimal], ...],
    ) -> list[SalarySegment] | None:
        """Split the month by calendar days over the salary rows that overlap it: each row's
        days are the overlap of its dates with the month, and each loss-of-pay day belongs to
        the row that contains it. `[]` when no row overlaps (the plain whole-month path);
        None when a row's structure is missing."""
        segments: list[SalarySegment] = []
        for index, row in enumerate(rows):
            start = max(row.effective_from, month_start)
            end = min(row.effective_to or month_end, month_end)
            if end < start:
                continue
            if index == len(rows) - 1:
                components = month_end_components
            else:
                structure = self.structure_repo.get_by_id(row.structure_id, company_id)
                if structure is None:
                    return None
                components = self._component_specs(structure)
            lop = sum((amount for day, amount in lop_by_date if start <= day <= end), _ZERO)
            segments.append(
                SalarySegment(
                    salary_id=str(row.id),
                    from_date=start,
                    to_date=end,
                    days=(end - start).days + 1,
                    ctc_annual=row.ctc,
                    components=components,
                    lop_days=lop,
                )
            )
        return segments

    def _rates_for_month(
        self, statutory_config: StatutoryConfig, data: PayrollRunCreateRequest, country: str
    ) -> "MonthRates":
        """PF, ESI, professional-tax and income-tax rows of the company's country in force on
        the FIRST day of the payroll month (a change effective mid-month applies from the next
        month). An item that is switched on and has no row in force stops the run with a 409;
        nothing is guessed, and there is no default state."""
        first_day = date(data.year, data.month, 1)
        when = f"{first_day}; ask the platform administrator to add it"

        pf_spec: PfRateSpec | None = None
        if statutory_config.pf_enabled:
            pf_row = self.rate_repo.get_in_force(country, "epf", first_day)
            if pf_row is None:
                raise MissingRateError(f"No EPF rate is in force on {when}.")
            pf_spec = PfRateSpec(pf_row.employee_rate, pf_row.employer_rate, pf_row.wage_ceiling)

        esi_spec: EsiRateSpec | None = None
        if statutory_config.esi_enabled:
            esi_row = self.rate_repo.get_in_force(country, "esi", first_day)
            if esi_row is None:
                raise MissingRateError(f"No ESI rate is in force on {when}.")
            esi_spec = EsiRateSpec(
                esi_row.employee_rate,
                esi_row.employer_rate,
                esi_row.wage_ceiling,
                esi_row.employee_exempt_daily_wage,
            )

        pt_state = statutory_config.pt_state
        if statutory_config.pt_enabled and not pt_state:
            raise MissingRateError(
                "Professional tax is switched on but no professional-tax state is set; choose "
                "the state in the company's statutory settings or switch professional tax off."
            )
        pt_rows = (
            self.pt_repo.list_for_state(country, pt_state, on_date=first_day)
            if statutory_config.pt_enabled and pt_state
            else []
        )
        if statutory_config.pt_enabled and not pt_rows:
            raise MissingRateError(
                f"No professional-tax slabs for {pt_state} are in force on {when}."
            )

        # Financial year key (April to March)
        fy_str = (
            f"{data.year}-{data.year + 1}" if data.month >= 4 else f"{data.year - 1}-{data.year}"
        )
        tax_rows = (
            self.tax_repo.list_in_force(
                country, fy_str, statutory_config.default_tax_regime, first_day
            )
            if statutory_config.tds_enabled
            else []
        )
        if statutory_config.tds_enabled and not tax_rows:
            raise MissingRateError(
                f"No income-tax slabs for the {statutory_config.default_tax_regime.value} "
                f"regime, financial year {fy_str}, are in force on {when}."
            )
        return MonthRates(pf_spec, esi_spec, pt_rows, tax_rows, fy_str)

    def _generate_run(
        self,
        company_id: uuid.UUID,
        data: PayrollRunCreateRequest,
        run: PayrollRun,
        actor: User,
        statutory_config: StatutoryConfig,
        month_rates: "MonthRates",
    ) -> PayrollRun:
        # 5. Generate Payroll Items
        # Statutory config (made before the run row), PT slabs, Tax slabs
        statutory_spec = StatutoryConfigSpec(
            pf_enabled=statutory_config.pf_enabled,
            pf_restrict_to_ceiling=statutory_config.pf_restrict_to_ceiling,
            esi_enabled=statutory_config.esi_enabled,
            pt_enabled=statutory_config.pt_enabled,
            pt_state=statutory_config.pt_state,
            lwf_enabled=statutory_config.lwf_enabled,
            lwf_employee_amount=statutory_config.lwf_employee_amount,
            lwf_months=tuple(statutory_config.lwf_months or []),
            tds_enabled=statutory_config.tds_enabled,
            default_tax_regime=statutory_config.default_tax_regime.value,
        )

        run_date = date(data.year, data.month, 1)
        fy_str = month_rates.financial_year
        pt_spec_list = [
            PTSlabSpec(
                state=s.state,
                income_min=s.income_min,
                income_max=s.income_max,
                monthly_amount=s.monthly_amount,
                special_month=s.special_month,
                special_month_amount=s.special_month_amount,
            )
            for s in month_rates.pt_slabs
        ]

        tax_spec_list = [
            TaxSlabSpec(
                country=s.country,
                financial_year=s.financial_year,
                regime=s.regime.value,
                min_income=s.min_income,
                max_income=s.max_income,
                rate_percent=s.rate_percent,
                cess_percent=s.cess_percent,
                surcharge_rules=s.surcharge_rules,
            )
            for s in month_rates.tax_slabs
        ]

        _, last_day = monthrange(data.year, data.month)
        month_start = date(data.year, data.month, 1)
        month_end = date(data.year, data.month, last_day)

        skipped: list[dict[str, str]] = []
        employees = self._select_employees(company_id, data, skipped)

        total_gross = Decimal("0.00")
        total_deductions = Decimal("0.00")
        total_net = Decimal("0.00")
        total_employer_cost = Decimal("0.00")
        processed_count = 0

        for emp in employees:
            # Not employed at all in this month: nothing to pay.
            last_working_date = self._approved_last_working_date(emp)
            if emp.hire_date > month_end or (
                last_working_date is not None and last_working_date < month_start
            ):
                skipped.append({"employee_id": str(emp.id), "reason": "not_employed_in_month"})
                continue

            # Every salary row that overlaps the month (a raise that starts mid-month gives
            # two or more). The last one is the salary at the month end. With none, fall back to
            # the earlier lookups so that nothing changes for an employee without a row in the
            # month.
            month_salaries = self.salary_repo.list_overlapping_month(
                emp.id, company_id, month_start, month_end
            )
            salary_record: EmployeeSalary | None
            if month_salaries:
                salary_record = month_salaries[-1]
            else:
                salary_record = self.salary_repo.get_in_force(emp.id, company_id, month_end)
                if salary_record is None:
                    # Fallback to run_date (month_start) or latest open-ended salary
                    salary_record = self.salary_repo.get_in_force(emp.id, company_id, run_date)
                if salary_record is None:
                    salary_record = self.salary_repo.get_open_ended(emp.id, company_id)
            if salary_record is None:
                skipped.append({"employee_id": str(emp.id), "reason": "no_salary"})
                continue

            structure = self.structure_repo.get_by_id(salary_record.structure_id, company_id)
            if structure is None:
                skipped.append({"employee_id": str(emp.id), "reason": "no_structure"})
                continue

            component_specs = self._component_specs(structure)

            # ── Attendance: pay is prorated over the calendar days of the month ───────
            working_days = Decimal(str(last_day))
            summary = summarise_attendance(
                month_start=month_start,
                month_end=month_end,
                working_dates=self.leave_service.working_dates(
                    company_id, emp.department_id, month_start, month_end
                ),
                joined_on=emp.hire_date,
                last_working_date=self._approved_last_working_date(emp),
                attendance=self.attendance_repo.status_by_date(
                    company_id, emp.id, month_start, month_end
                ),
                leaves=self.leave_repo.list_approved_overlapping(
                    company_id, emp.id, month_start, month_end
                ),
                attendance_exempt=emp.is_attendance_exempt,
            )
            lop_days = summary.lop_days
            paid_leave_days = summary.paid_leave_days
            absent_days = summary.absent_days
            present_days = max(Decimal("0.0"), working_days - lop_days - paid_leave_days)

            # ── Reimbursements: approved, not yet locked to any run ───────────
            # IMPORTANT: reimbursements are tax-free expense paybacks. They are
            # NEVER added to earnings_json (which would inflate taxable gross and
            # distort TDS/ESI calculations). They live only in reimbursement_amount
            # and are added to net_pay after statutory deductions.
            reimbursements = self.reimbursement_repo.list_unpaid_approved(company_id, emp.id)
            reimbursement_amount = sum((r.amount for r in reimbursements), Decimal("0.00"))

            # ── Timesheet hours: only billable for contract/hourly employees ──
            # Salaried employees (full_time, part_time, intern) use project
            # timesheet hours for project-cost tracking and client billing only —
            # their paycheck is their fixed monthly CTC regardless of hours logged.
            is_hourly = emp.employment_type == EmploymentType.contract

            approved_time_entries = self.project_repo.list_time_entries(
                company_id=company_id,
                employee_id=emp.id,
                status="approved",
                start_date=month_start,
                end_date=month_end,
            )
            total_approved_project_hours = sum(
                (Decimal(str(te.hours)) for te in approved_time_entries), Decimal("0.00")
            )

            # Hourly rate: use explicit hourly_rate if set, else fall back to
            # monthly_ctc / 160 (standard Indian payroll convention).
            if is_hourly and total_approved_project_hours > 0:
                if salary_record.hourly_rate is not None:
                    hourly_rate = salary_record.hourly_rate
                else:
                    monthly_ctc = _round(salary_record.ctc / Decimal("12"))
                    hourly_rate = _round(monthly_ctc / Decimal("160.00"))
                project_hours_pay = _round(total_approved_project_hours * hourly_rate)
            else:
                # Salaried: hours are for project tracking only — no pay impact
                project_hours_pay = Decimal("0.00")
                hourly_rate = Decimal("0.00")

            # ── Year-to-date gross & TDS in the financial year so far ─────────
            # Computed from approved/paid runs in the same FY, excluding the current run
            # to prevent double-counting on draft rebuilds.
            fy_start_year = data.year if data.month >= 4 else data.year - 1
            gross_earned_ytd = self.item_repo.get_ytd_gross_for_employee(
                company_id=company_id,
                employee_id=emp.id,
                start_year=fy_start_year,
                exclude_run_id=run.id,
            )
            tds_paid_ytd = self.item_repo.get_ytd_tds_for_employee(
                company_id=company_id,
                employee_id=emp.id,
                start_year=fy_start_year,
                exclude_run_id=run.id,
            )

            # ── Engine: compute earned_gross and statutory deductions ──────────
            # The engine applies the LOP ratio (paid_days/working_days) to scale
            # earned_gross down. Statutory deductions (EPF, ESI, PT) are then
            # computed on earned_gross — not full gross — satisfying Indian law.
            segments = self._salary_segments(
                company_id,
                month_salaries,
                component_specs,
                month_start,
                month_end,
                summary.lop_by_date,
            )
            if segments is None:
                skipped.append({"employee_id": str(emp.id), "reason": "no_structure"})
                continue

            payslip_in = PayslipInput(
                ctc_annual=salary_record.ctc,
                components=component_specs,
                segments=segments or None,
                last_working_date=self._approved_last_working_date(emp),
                statutory=statutory_spec,
                pt_slabs=pt_spec_list,
                tax_slabs=tax_spec_list,
                month=data.month,
                year=data.year,
                financial_year=fy_str,
                pf_rate=month_rates.pf,
                esi_rate=month_rates.esi,
                working_days=working_days,
                present_days=present_days,
                paid_leave_days=paid_leave_days,
                lop_days=lop_days,
                gross_earned_ytd=gross_earned_ytd,
                tds_paid_ytd=tds_paid_ytd,
                # reimbursement_amount fed to engine so net_salary is correct.
                # Engine formula: net = earned_gross - deductions + reimbursement_amount
                reimbursement_amount=reimbursement_amount,
            )

            payslip_out = calculate_payslip(payslip_in)

            # ── Build snapshot JSON ──────────────────────────────────────────
            # earnings_json: only salary components from the structure.
            # For hourly employees, add the PROJECT_HOURS line as a base-pay
            # replacement (their gross IS the hours pay).
            earnings_json = [
                {"code": e.code, "name": e.name, "amount": str(e.amount)}
                for e in payslip_out.earnings
            ]
            if is_hourly and project_hours_pay > Decimal("0.00"):
                earnings_json.append(
                    {
                        "code": "PROJECT_HOURS",
                        "name": (
                            f"Hourly Pay — {total_approved_project_hours} hrs"
                            f" @ ₹{hourly_rate}/hr (approved project timesheets)"
                        ),
                        "amount": str(project_hours_pay),
                    }
                )

            # deductions_json: statutory lines only (EPF, ESI, PT, TDS, LWF).
            # LOP is NOT a subtracted deduction line — it is already reflected in
            # the lower earned_gross produced by the engine. Adding it again here
            # would cause a double-deduction. The frontend displays it as an
            # informational attendance note using payroll_item.lop_days.
            deductions_json = [
                {"code": d.code, "name": d.name, "amount": str(d.amount)}
                for d in payslip_out.deductions
            ]
            employer_json = [
                {"code": er.code, "name": er.name, "amount": str(er.amount)}
                for er in payslip_out.employer_contributions
            ]

            # For hourly employees their project_hours_pay IS their gross;
            # for salaried employees the engine's earned_gross is the gross.
            final_gross = payslip_out.gross_salary + project_hours_pay
            final_net = payslip_out.net_salary + project_hours_pay
            final_employer_cost = payslip_out.employer_cost + project_hours_pay

            self.item_repo.create(
                company_id=company_id,
                payroll_run_id=run.id,
                employee_id=emp.id,
                ctc_snapshot=salary_record.ctc,
                gross_salary=final_gross,
                total_deductions=payslip_out.total_deductions,
                net_salary=final_net,
                employer_cost=final_employer_cost,
                earnings_json=earnings_json,
                deductions_json=deductions_json,
                employer_contributions_json=employer_json,
                working_days=working_days,
                present_days=present_days,
                absent_days=absent_days,
                half_days=summary.half_days,
                paid_leave_days=paid_leave_days,
                lop_days=lop_days,
                reimbursement_amount=reimbursement_amount,
                salary_segments_json=[
                    {
                        "salary_id": s.salary_id,
                        "from_date": s.from_date.isoformat(),
                        "to_date": s.to_date.isoformat(),
                        "days": s.days,
                        "ctc": str(s.ctc_annual),
                    }
                    for s in segments
                ]
                if segments
                else [
                    {
                        "salary_id": str(salary_record.id),
                        "from_date": month_start.isoformat(),
                        "to_date": month_end.isoformat(),
                        "days": last_day,
                        "ctc": str(salary_record.ctc),
                    }
                ],
            )

            # ── Reimbursement lifecycle: lock into this run ─────────────────
            # Phase 1 of 3: mark added_to_payroll_run_id so the claim cannot be
            # included in another run. Status stays APPROVED until approve_run
            # finalises the pay run (Phase 2). If the run is deleted before
            # approval, delete_run clears added_to_payroll_run_id back to NULL
            # (Phase 3), releasing the claim for the next cycle.
            for r in reimbursements:
                self.reimbursement_repo.update(r, added_to_payroll_run_id=run.id)

            total_gross += final_gross
            total_deductions += payslip_out.total_deductions
            total_net += final_net
            total_employer_cost += final_employer_cost
            processed_count += 1

        self.repo.update(
            run,
            status=PayrollRunStatus.pending_approval
            if processed_count > 0
            else PayrollRunStatus.draft,
            total_employees=processed_count,
            total_gross=total_gross,
            total_deductions=total_deductions,
            total_net=total_net,
            total_employer_cost=total_employer_cost,
            skipped_json=skipped,
        )

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PAYROLL_RUN_CREATED",
            entity_type="payroll_run",
            entity_id=run.id,
            details={
                "month": data.month,
                "year": data.year,
                "run_type": data.run_type,
                "status": run.status.value,
                "total_employees": processed_count,
                "skipped_count": len(skipped),
            },
        )
        self.db.commit()
        return run

    def _select_employees(
        self,
        company_id: uuid.UUID,
        data: PayrollRunCreateRequest,
        skipped: list[dict[str, str]],
    ) -> list[Employee]:
        if data.employee_ids:
            employees: list[Employee] = []
            for eid in dict.fromkeys(data.employee_ids):  # one item per employee, in order
                found = self.employee_repo.get_by_id(eid, company_id)
                if found is None:
                    skipped.append({"employee_id": str(eid), "reason": "employee_not_found"})
                else:
                    employees.append(found)
            return employees

        employees = []
        page = 1
        while True:
            batch, _, pages = self.employee_repo.list_employees(
                company_id=company_id,
                q=None,
                department_id=None,
                is_active=True,
                level=None,
                employment_type=None,
                reporting_manager_id=None,
                sort=None,
                page_params=PageParams(page=page, limit=1000),
            )
            employees.extend(batch)
            if page >= pages:
                return employees
            page += 1

    @staticmethod
    def _approved_last_working_date(emp: Employee) -> date | None:
        if emp.resignation_status == ResignationStatus.approved:
            return emp.last_working_date
        return None

    def list_runs(
        self, company_id: uuid.UUID, page_params: PageParams, status: PayrollRunStatus | None = None
    ) -> tuple[list[PayrollRun], int, int]:
        return self.repo.list_runs(company_id, page_params, status)

    def get_run_detail(
        self, company_id: uuid.UUID, run_id: uuid.UUID
    ) -> tuple[PayrollRun, list[PayrollItem], list[tuple[uuid.UUID, str]] | None]:
        """The run, its items and, once its payment lines exist, who was left out of the
        payment file and why (employee id and reason only). None when there are no lines."""
        run = self.repo.get_by_id(run_id, company_id)
        if run is None:
            raise NotFoundError("Payroll run not found.")
        items = self.item_repo.list_by_run_id(run.id, company_id)
        lines = self.payment_repo.list_for_run(run.id, company_id)
        exclusions = (
            [(line.employee_id, line.excluded_reason) for line in lines if line.excluded_reason]
            if lines
            else None
        )
        return run, items, exclusions

    def _snapshot_payments(self, run: PayrollRun, company_id: uuid.UUID) -> None:
        """Save the payment lines of an approved run: the bank details as they are at this
        moment, so a later change never alters the run's file. A missing or unreadable bank
        detail or a net pay of 0 or less leaves the employee out with a reason; it never stops
        the approval."""
        items = self.item_repo.list_by_run_id(run.id, company_id)
        employee_ids = [item.employee_id for item in items]
        codes = self.payment_repo.employee_codes(company_id, employee_ids)
        banks = self.bank_repo.active_by_employee(company_id, employee_ids)
        for item in items:
            amount = item.net_salary.quantize(_ONE_PAISA, rounding=ROUND_HALF_UP)
            fields: dict[str, object] = {}
            reason: str | None = None
            bank = banks.get(item.employee_id)
            if bank is None:
                reason = PAYMENT_EXCLUDED_NO_BANK
            elif amount <= 0:
                reason = PAYMENT_EXCLUDED_NET_PAY
            else:
                try:
                    number = decrypt_field(
                        bytes(bank.account_number_enc),
                        company_id=company_id,
                        column=BANK_ACCOUNT_COLUMN,
                    )
                    fields = {
                        "account_holder": bank.account_holder,
                        "bank_name": bank.bank_name,
                        "account_number_enc": encrypt_field(
                            number, company_id=company_id, column=PAYMENT_ACCOUNT_COLUMN
                        ),
                        "account_last4": bank.account_last4,
                        "ifsc_code": bank.ifsc_code,
                    }
                except AppError:
                    reason = PAYMENT_EXCLUDED_UNREADABLE
            self.payment_repo.create(
                company_id=company_id,
                payroll_run_id=run.id,
                employee_id=item.employee_id,
                employee_code=codes[item.employee_id],
                amount=amount,
                excluded_reason=reason,
                **fields,
            )

    def approve_run(self, company_id: uuid.UUID, run_id: uuid.UUID, actor: User) -> PayrollRun:
        from sqlalchemy import update

        run = self.repo.get_by_id_for_update(run_id, company_id)
        if run is None:
            raise NotFoundError("Payroll run not found.")

        if run.status == PayrollRunStatus.approved:
            return run
        if run.status != PayrollRunStatus.pending_approval:
            raise ConflictError(
                f"A payroll run with status '{run.status.value}' cannot be approved; "
                "only a run in 'pending_approval' can."
            )
        # Maker-checker: the person who created the run does not approve it (an owner may,
        # so a company with one HR person and an owner still works).
        if run.run_by == actor.id and actor.role not in (UserRole.owner, UserRole.super_admin):
            raise ForbiddenError(CANNOT_APPROVE_OWN_RUN)

        self.repo.update(
            run,
            status=PayrollRunStatus.approved,
            approved_by=actor.id,
            approved_at=utcnow(),
        )

        # Phase 2 of 3: Bulk-transition all claims locked into this run from
        # APPROVED → PAID now that the pay run is formally finalised.
        # This is the only place status becomes PAID for reimbursements.
        self.db.execute(
            update(Reimbursement)
            .where(
                Reimbursement.company_id == company_id,
                Reimbursement.added_to_payroll_run_id == run.id,
                Reimbursement.status == ReimbursementStatus.approved,
            )
            .values(status=ReimbursementStatus.paid)
        )

        # The payment lines are saved in this same commit (5.8).
        self._snapshot_payments(run, company_id)

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PAYROLL_RUN_APPROVED",
            entity_type="payroll_run",
            entity_id=run.id,
            details={
                "month": run.month,
                "year": run.year,
                "status": run.status.value,
                "total_employees": run.total_employees,
            },
        )
        self.db.commit()
        return run

    def delete_run(self, company_id: uuid.UUID, run_id: uuid.UUID, actor: User) -> None:
        """Delete/cancel a payroll run. Allowed only if status in
        ('draft', 'processing', 'pending_approval') and not 'approved'/'paid'.
        """
        run = self.repo.get_by_id_for_update(run_id, company_id)
        if run is None:
            raise NotFoundError("Payroll run not found.")

        if run.status in (PayrollRunStatus.approved, PayrollRunStatus.paid):
            raise ConflictError(
                f"Cannot delete a payroll run with status '{run.status.value}'. "
                "Only draft/unapproved runs can be deleted."
            )

        # Phase 3 of 3: Unlink all reimbursements that were locked into this
        # run but never finalised. Since approve_run hasn't been called yet,
        # their status is still APPROVED (not PAID). Clear the run reference so
        # they roll forward into the next pay cycle automatically.
        from sqlalchemy import update

        self.db.execute(
            update(Reimbursement)
            .where(
                Reimbursement.company_id == company_id,
                Reimbursement.added_to_payroll_run_id == run.id,
                Reimbursement.status == ReimbursementStatus.approved,
            )
            .values(added_to_payroll_run_id=None)
        )

        # Delete the run (cascade deletes payroll items)
        self.repo.delete(run)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PAYROLL_RUN_DELETED",
            entity_type="payroll_run",
            entity_id=run_id,
            details={
                "month": run.month,
                "year": run.year,
                "status": run.status.value,
                "total_employees": run.total_employees,
            },
        )
        self.db.commit()


class PayslipService:
    """Routes 95-96 (Spec 10.6). A payslip is the stored item of its run, read as it was
    issued; an employee sees it only once the run is approved or paid."""

    def __init__(self, db: Session):
        self.db = db
        self.item_repo = PayrollItemRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.audit = AuditService(db)

    def list_own(
        self, actor: User, page_params: PageParams, year: int | None, month: int | None
    ) -> tuple[list[PayrollItem], int, int]:
        employee = self.employee_repo.get_by_user_id(actor.company_id, actor.id)
        if employee is None:
            return [], 0, 0
        return self.item_repo.list_payslips(
            actor.company_id,
            employee.id,
            page_params,
            released_only=True,
            year=year,
            month=month,
        )

    def list_for_employee(
        self,
        actor: User,
        employee_id: uuid.UUID,
        page_params: PageParams,
        year: int | None,
        month: int | None,
    ) -> tuple[list[PayrollItem], int, int]:
        company_id = actor.company_id
        employee = self.employee_repo.get_by_id(employee_id, company_id)
        if employee is None and actor.role == UserRole.super_admin:
            employee = self.item_repo.find_employee_any_company(employee_id)
            if employee is not None:
                company_id = employee.company_id
        if employee is None:
            raise NotFoundError("Employee not found.")

        items, total, pages = self.item_repo.list_payslips(
            company_id,
            employee.id,
            page_params,
            released_only=False,
            year=year,
            month=month,
        )
        if employee.user_id != actor.id:
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="PAYSLIP_VIEWED_BY_HR",
                entity_type="employee",
                entity_id=employee.id,
                details={"employee_id": str(employee.id), "run_count": total},
            )
            self.db.commit()
        return items, total, pages


class EmployeeBankAccountService:
    """An employee's bank details (5.8). The employee keeps their own; owner and HR admin keep
    anyone's. The account number is encrypted, shown masked, and revealed in full only to
    owner and HR admin, with an audit row every time."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = EmployeeBankAccountRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.company_repo = CompanyRepository(db)
        self.user_repo = UserRepository(db)
        self.audit = AuditService(db)
        self.notify = NotificationService(db)

    def _target(self, actor: User, employee_id: uuid.UUID | None, *, write: bool) -> Employee:
        """The employee whose details are meant: the caller's own when `employee_id` is None."""
        own = self.employee_repo.get_by_user_id(actor.company_id, actor.id)
        if employee_id is None:
            if own is None:
                raise NotFoundError("Employee profile not found for current user.")
            target = own
        else:
            if actor.role not in BANK_ROLES and (own is None or own.id != employee_id):
                raise ForbiddenError(BANK_FORBIDDEN_MESSAGE)
            found = self.employee_repo.get_by_id_any_status(employee_id, actor.company_id)
            if found is None:
                raise NotFoundError(BANK_EMPLOYEE_NOT_FOUND_MESSAGE)
            target = found
        if write and not target.is_active:
            raise ConflictError(BANK_INACTIVE_MESSAGE)
        return target

    @staticmethod
    def _response(account: EmployeeBankAccount, number: str | None = None) -> BankAccountResponse:
        shown = number or mask_payout_account_number(account.account_last4)
        return BankAccountResponse(
            employee_id=account.employee_id,
            account_holder=account.account_holder,
            bank_name=account.bank_name,
            account_number=shown or "",
            ifsc_code=account.ifsc_code,
            updated_at=account.updated_at,
        )

    def view(
        self, actor: User, employee_id: uuid.UUID | None, *, reveal: bool = False
    ) -> BankAccountResponse:
        if reveal and actor.role not in BANK_ROLES:
            raise ForbiddenError(BANK_FORBIDDEN_MESSAGE)
        employee = self._target(actor, employee_id, write=False)
        account = self.repo.get_active(employee.id, actor.company_id)
        if account is None:
            raise NotFoundError(BANK_NOT_FOUND_MESSAGE)
        if not reveal:
            return self._response(account)
        number = decrypt_field(
            bytes(account.account_number_enc),
            company_id=actor.company_id,
            column=BANK_ACCOUNT_COLUMN,
        )
        self.audit.record(
            company_id=actor.company_id,
            actor=actor,
            action="BANK_ACCOUNT_REVEALED",
            entity_type="employee_bank_account",
            entity_id=account.id,
            details={"employee_id": str(employee.id)},
        )
        self.db.commit()
        return self._response(account, number)

    def save(
        self, actor: User, employee_id: uuid.UUID | None, data: BankAccountRequest
    ) -> BankAccountResponse:
        company_id = actor.company_id
        employee = self._target(actor, employee_id, write=True)
        company = self.company_repo.get_by_id(company_id)
        if company is None or not is_payroll_ready(company.country):
            name = country_name(company.country) if company is not None else "this country"
            raise ConflictError(f"Payroll rules for {name} are not available yet")

        current = self.repo.get_active(employee.id, company_id, lock=True)
        blob, number_changed = self._number(current, data.account_number, company_id)
        changed = [
            name
            for name, differs in (
                (
                    "account_holder",
                    current is None or current.account_holder != data.account_holder,
                ),
                ("bank_name", current is None or current.bank_name != data.bank_name),
                ("ifsc_code", current is None or current.ifsc_code != data.ifsc_code),
                ("account_number", number_changed),
            )
            if differs
        ]
        if current is not None and not changed:
            return self._response(current)

        if current is not None:
            self.repo.deactivate(current, utcnow())
        account = self.repo.create(
            company_id=company_id,
            employee_id=employee.id,
            account_holder=data.account_holder,
            bank_name=data.bank_name,
            account_number_enc=blob,
            account_last4=(
                current.account_last4
                if not number_changed and current is not None
                else data.account_number[-4:]
            ),
            ifsc_code=data.ifsc_code,
            is_active=True,
            created_by=actor.id,
        )
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="BANK_ACCOUNT_SAVED",
            entity_type="employee_bank_account",
            entity_id=account.id,
            details={
                "employee_id": str(employee.id),
                "fields": changed,
                "first_save": current is None,
            },
        )
        self.db.commit()
        self._notify_change(actor, employee)
        return self._response(account)

    def _number(
        self, current: EmployeeBankAccount | None, submitted: str, company_id: uuid.UUID
    ) -> tuple[bytes, bool]:
        """The blob to store and whether the number differs from the stored one. The mask (or
        the stored number itself) keeps the stored blob; a new number is encrypted afresh."""
        if is_masked_account_number(submitted):
            if current is None:
                raise ValidationError(
                    "No account number is stored yet; enter the full number.",
                    details={"field": "account_number"},
                )
            if submitted.lstrip("*") not in ("", current.account_last4):
                raise ValidationError(
                    "The masked account number does not match the stored one.",
                    details={"field": "account_number"},
                )
            return bytes(current.account_number_enc), False
        if current is not None and current.account_last4 == submitted[-4:]:
            try:
                stored = decrypt_field(
                    bytes(current.account_number_enc),
                    company_id=company_id,
                    column=BANK_ACCOUNT_COLUMN,
                )
            except DecryptionFailedError:
                stored = None  # a damaged stored value is replaced by the number just entered
            if stored == submitted:
                return bytes(current.account_number_enc), False
        return encrypt_field(submitted, company_id=company_id, column=BANK_ACCOUNT_COLUMN), True

    def _notify_change(self, actor: User, employee: Employee) -> None:
        """Tell the other side, after the save is committed: the employee when someone else
        changed their details, HR-level users when the employee did. No number in the text."""
        company_id = actor.company_id
        if employee.user_id == actor.id:
            recipients = [
                user.id
                for user in self.user_repo.list_active_by_roles(company_id, BANK_ROLES)
                if user.id != actor.id
            ]
            title = "Employee bank details changed"
            message = f"Employee {employee.employee_code} changed their bank details."
        else:
            recipients = [employee.user_id] if employee.user_id is not None else []
            title = "Your bank details were changed"
            message = "Your bank details were updated by HR. Check them on the payroll page."
        try:
            for user_id in recipients:
                self.notify.notify(
                    company_id=company_id,
                    user_id=user_id,
                    type=BANK_NOTIFICATION_TYPE,
                    title=title,
                    message=message,
                    action_url=BANK_PAGE_URL,
                    entity_type="employee",
                    entity_id=employee.id,
                )
            self.db.commit()
        except Exception:  # noqa: BLE001 - the save is already committed; a notice must not undo it
            self.db.rollback()
            logger.warning("bank_details_notification_failed", exc_info=True)


class PaymentFileService:
    """`GET /payroll/runs/{id}/payment-file` (5.8): the file is built from the payment lines
    saved when the run was approved, never from today's bank details."""

    def __init__(self, db: Session):
        self.db = db
        self.run_repo = PayrollRunRepository(db)
        self.payment_repo = PayrollRunPaymentRepository(db)
        self.company_repo = CompanyRepository(db)
        self.audit = AuditService(db)

    def export(
        self, actor: User, run_id: uuid.UUID, format_name: str
    ) -> tuple[bytes, str, str, int]:
        """The file bytes, its name, its content type and how many employees were left out."""
        company_id = actor.company_id
        file_format = PAYMENT_FILE_FORMATS.get(format_name)
        if file_format is None:
            known = ", ".join(sorted(PAYMENT_FILE_FORMATS))
            raise ValidationError(
                f"Unknown payment file format '{format_name}'. Known formats: {known}.",
                details={"field": "format", "allowed": sorted(PAYMENT_FILE_FORMATS)},
            )
        run = self.run_repo.get_by_id(run_id, company_id)
        if run is None:
            raise NotFoundError("Payroll run not found.")
        if run.status not in (PayrollRunStatus.approved, PayrollRunStatus.paid):
            raise ConflictError(
                f"A payment file can be made only for an approved or paid run; this run is "
                f"'{run.status.value}'."
            )
        lines = self.payment_repo.list_for_run(run.id, company_id)
        if not lines:
            raise ConflictError(NO_PAYMENT_LINES_MESSAGE)
        payable = [line for line in lines if line.excluded_reason is None]
        if not payable:
            raise ConflictError(NOBODY_PAYABLE_MESSAGE)
        company = self.company_repo.get_by_id(company_id)
        currency = company.currency if company is not None else ""
        paid_on = (run.approved_at or run.updated_at).date().isoformat()
        rows = [
            PaymentLine(
                payment_reference=f"PAY-{run.year}{run.month:02d}-{line.employee_code}",
                employee_code=line.employee_code,
                account_holder=line.account_holder or "",
                bank_name=line.bank_name or "",
                account_number=decrypt_field(
                    bytes(line.account_number_enc or b""),
                    company_id=company_id,
                    column=PAYMENT_ACCOUNT_COLUMN,
                ),
                ifsc=line.ifsc_code or "",
                amount=f"{line.amount:.2f}",
                currency=currency,
                payment_date=paid_on,
                narration=f"Salary {run.year}-{run.month:02d}",
            )
            for line in payable
        ]
        content = file_format.build(rows)
        excluded = len(lines) - len(payable)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PAYMENT_FILE_EXPORTED",
            entity_type="payroll_run",
            entity_id=run.id,
            details={
                "format": file_format.name,
                "row_count": len(rows),
                "excluded_count": excluded,
            },
        )
        self.db.commit()
        return (
            content,
            file_format.filename(run.year, run.month),
            file_format.content_type,
            excluded,
        )


class ReimbursementService:
    """Routes 97-99 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = ReimbursementRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.audit = AuditService(db)
        self.notify = NotificationService(db)

    # --- submit -------------------------------------------------------------

    def submit_claim(
        self, company_id: uuid.UUID, data: ReimbursementCreateRequest, actor: User
    ) -> Reimbursement:
        emp = self.employee_repo.get_by_user_id(company_id, actor.id)
        if emp is None:
            raise NotFoundError("Employee profile not found for current user.")

        today = utcnow().date()
        if data.expense_date > today:
            raise ValidationError("The expense date cannot be in the future.")
        if data.expense_date < today - timedelta(days=MAX_EXPENSE_AGE_DAYS):
            raise ValidationError(
                f"The expense date cannot be older than {MAX_EXPENSE_AGE_DAYS} days."
            )

        self._check_receipt(company_id, data.file_object_id, actor)
        if self.repo.receipt_in_use(company_id, data.file_object_id):
            raise ConflictError(RECEIPT_IN_USE_MESSAGE)
        if self.repo.open_duplicate_exists(
            company_id, emp.id, data.expense_date, data.type, data.amount
        ):
            raise ConflictError(DUPLICATE_CLAIM_MESSAGE)

        try:
            claim = self.repo.create(
                company_id=company_id,
                employee_id=emp.id,
                type=data.type,
                amount=data.amount,
                expense_date=data.expense_date,
                description=data.description,
                file_object_id=data.file_object_id,
                status=ReimbursementStatus.pending,
            )
        except IntegrityError as exc:
            # Two requests passed the checks above together; the unique indexes decide.
            self.db.rollback()
            if "uq_reimbursements_open_receipt" in str(exc.orig):
                raise ConflictError(RECEIPT_IN_USE_MESSAGE) from None
            raise ConflictError(DUPLICATE_CLAIM_MESSAGE) from None

        self._audit(company_id, actor, "REIMBURSEMENT_SUBMITTED", claim)
        name = f"{emp.first_name} {emp.last_name or ''}".strip()
        for user_id in self._chain_user_ids(company_id, emp):
            self._tell(
                company_id,
                user_id,
                "reimbursement_submitted",
                "New reimbursement claim",
                f"{name} submitted a reimbursement claim for review.",
                claim,
            )
        self.db.commit()
        return claim

    def _check_receipt(self, company_id: uuid.UUID, file_id: uuid.UUID, actor: User) -> None:
        """The receipt must be a file of this company that the claimant uploaded. Someone
        else's file, another company's file and a missing file all give the same answer."""
        receipt = self.repo.get_receipt_file(company_id, file_id)
        if receipt is None or receipt.uploaded_by != actor.id:
            raise NotFoundError(RECEIPT_NOT_FOUND_MESSAGE)
        if receipt.file_type not in RECEIPT_FILE_TYPES:
            raise ValidationError("The receipt must be a PDF, PNG or JPG file.")

    # --- list ---------------------------------------------------------------

    def list_claims(
        self,
        company_id: uuid.UUID,
        actor: User,
        page_params: PageParams,
        status: ReimbursementStatus | None = None,
        employee_id: uuid.UUID | None = None,
        month: int | None = None,
        year: int | None = None,
    ) -> tuple[list[Reimbursement], int, int]:
        if actor.role in HR_LEVEL_ROLES:
            return self.repo.list_claims(
                company_id,
                page_params,
                employee_id=employee_id,
                status=status,
                month=month,
                year=year,
            )
        own = self.employee_repo.get_by_user_id(company_id, actor.id)
        if own is None:
            return [], 0, 0
        visible = [own.id]
        if actor.role == UserRole.manager:
            visible += self.employee_repo.list_direct_report_ids(company_id, own.id)
        if employee_id is not None:
            # A filter can only narrow what the caller may already see.
            visible = [employee_id] if employee_id in visible else []
        return self.repo.list_claims(
            company_id, page_params, employee_ids=visible, status=status, month=month, year=year
        )

    # --- decide -------------------------------------------------------------

    def review_claim(
        self,
        company_id: uuid.UUID,
        reimbursement_id: uuid.UUID,
        data: ReimbursementReviewRequest,
        actor: User,
    ) -> Reimbursement:
        # A plain employee role never decides; refused before any lookup, with the message a
        # manager outside the reporting chain gets.
        require_deciding_role(actor)
        claim = self.repo.get_by_id_for_update(reimbursement_id, company_id)
        if claim is None:
            raise NotFoundError(CLAIM_NOT_FOUND_MESSAGE)
        target_emp = self.employee_repo.get_by_id_any_status(claim.employee_id, company_id)
        if target_emp is None:
            raise ForbiddenError(DEFAULT_FORBIDDEN_MESSAGE)
        verify_approval_authority(self.db, actor, target_emp)

        if claim.status != ReimbursementStatus.pending:
            raise ConflictError(
                f"Reimbursement claim is not pending (current status: {claim.status.value})."
            )

        # Block anyone from approving a claim already locked into a pay run
        if claim.added_to_payroll_run_id is not None:
            raise ConflictError(
                "This claim is already locked into a payroll run and cannot be modified."
            )

        approving = data.action == "approve"
        new_status = ReimbursementStatus.approved if approving else ReimbursementStatus.rejected
        self.repo.update(
            claim,
            status=new_status,
            approved_by=actor.id,
            approved_at=utcnow() if approving else None,
            rejection_reason=None if approving else data.rejection_reason,
        )
        self._audit(
            company_id,
            actor,
            "REIMBURSEMENT_APPROVED" if approving else "REIMBURSEMENT_REJECTED",
            claim,
        )
        if target_emp.user_id is not None:
            self._tell(
                company_id,
                target_emp.user_id,
                f"reimbursement_{new_status.value}",
                f"Reimbursement claim {new_status.value}",
                f"Your reimbursement claim was {new_status.value}.",
                claim,
            )
        self.db.commit()
        return claim

    # --- withdraw -----------------------------------------------------------

    def withdraw_claim(
        self, company_id: uuid.UUID, reimbursement_id: uuid.UUID, actor: User
    ) -> Reimbursement:
        claim = self.repo.get_by_id_for_update(reimbursement_id, company_id)
        if claim is None:
            raise NotFoundError(CLAIM_NOT_FOUND_MESSAGE)
        own = self.employee_repo.get_by_user_id(company_id, actor.id)
        if own is None or own.id != claim.employee_id:
            raise ForbiddenError("Only the person who made the claim can withdraw it.")
        if claim.status != ReimbursementStatus.pending or claim.added_to_payroll_run_id:
            raise ConflictError("Only a pending claim can be withdrawn.")

        self.repo.update(claim, status=ReimbursementStatus.withdrawn)
        self._audit(company_id, actor, "REIMBURSEMENT_WITHDRAWN", claim)
        self.db.commit()
        return claim

    # --- receipt view -------------------------------------------------------

    def open_receipt(
        self, company_id: uuid.UUID, reimbursement_id: uuid.UUID, actor: User
    ) -> tuple[Path, str, str]:
        """The stored receipt of a claim: (path on disk, file name, content type). Allowed
        for the claimant, anyone who may approve the claim (reporting chain, HR-level) and
        HR-level; everyone else gets one refusal. A view by anyone but the claimant is
        audited, in the same save, only when a file is really served."""
        claim = self.repo.get_by_id(reimbursement_id, company_id)
        if claim is None:
            raise NotFoundError(CLAIM_NOT_FOUND_MESSAGE)

        own = self.employee_repo.get_by_user_id(company_id, actor.id)
        is_claimant = own is not None and own.id == claim.employee_id
        if not is_claimant and actor.role not in HR_LEVEL_ROLES:
            target = self.employee_repo.get_by_id_any_status(claim.employee_id, company_id)
            try:
                can_approve_for(self.db, actor, target)
            except ForbiddenError:
                raise ForbiddenError(RECEIPT_FORBIDDEN_MESSAGE) from None

        receipt = (
            self.repo.get_receipt_file(company_id, claim.file_object_id)
            if claim.file_object_id is not None
            else None
        )
        if receipt is None:
            raise NotFoundError(RECEIPT_NOT_FOUND_MESSAGE)
        # The same containment and disk checks the platform file download makes.
        path = Path(receipt.storage_path).resolve()
        if not path.is_relative_to(Path(settings.UPLOAD_DIR).resolve()) or not path.is_file():
            raise NotFoundError(RECEIPT_NOT_FOUND_MESSAGE)

        if not is_claimant:
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="REIMBURSEMENT_RECEIPT_VIEWED",
                entity_type="reimbursement",
                entity_id=claim.id,
                details={
                    "employee_id": str(claim.employee_id),
                    "file_object_id": str(receipt.id),
                },
            )
            self.db.commit()
        return path, receipt.file_name, receipt.file_type

    # --- shared -------------------------------------------------------------

    def _audit(self, company_id: uuid.UUID, actor: User, action: str, claim: Reimbursement) -> None:
        """Ids, type and status only: never the description, the reason or the file name."""
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action=action,
            entity_type="reimbursement",
            entity_id=claim.id,
            details={
                "employee_id": str(claim.employee_id),
                "type": claim.type.value,
                "status": claim.status.value,
            },
        )

    def _tell(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        kind: str,
        title: str,
        message: str,
        claim: Reimbursement,
    ) -> None:
        self.notify.notify(
            company_id=company_id,
            user_id=user_id,
            type=kind,
            title=title,
            message=message,
            action_url=CLAIMS_PAGE_URL,
            entity_type="reimbursement",
            entity_id=claim.id,
        )

    def _chain_user_ids(self, company_id: uuid.UUID, employee: Employee) -> list[uuid.UUID]:
        """Users of the active managers above the employee: the people who can approve."""
        users: list[uuid.UUID] = []
        seen = {employee.id}
        current = employee.reporting_manager_id
        for _ in range(MAX_CHAIN_DEPTH):
            if current is None or current in seen:
                break
            seen.add(current)
            manager = self.employee_repo.get_by_id_any_status(current, company_id)
            if manager is None:
                break
            if manager.is_active and manager.user_id is not None:
                users.append(manager.user_id)
            current = manager.reporting_manager_id
        return users
