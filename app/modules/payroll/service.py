import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole
from app.modules.payroll.models import (
    CalculationType,
    EmployeeSalary,
    PercentageOf,
    PayrollItem,
    PayrollRun,
    PayrollRunStatus,
    PayrollRunType,
    SalaryComponent,
    SalaryComponentType,
    SalaryStructure,
    StatutoryConfig,
)
from app.modules.payroll.repository import (
    EmployeeSalaryRepository,
    PayrollItemRepository,
    PayrollRunRepository,
    PtSlabRepository,
    SalaryComponentRepository,
    SalaryStructureRepository,
    StatutoryConfigRepository,
    TaxSlabRepository,
)
from app.modules.payroll.schemas import (
    PayrollRunCreateRequest,
    PtSlabPutRequest,
    SalaryAssignRequest,
    SalaryComponentAmount,
    SalaryComponentCreateRequest,
    SalaryStructureCreateRequest,
    SalaryStructureUpdateRequest,
    StatutoryConfigUpdateRequest,
    TaxSlabPostRequest,
)
from app.modules.payroll.payslip_engine import (
    ComponentSpec,
    PayslipInput,
    PTSlabSpec,
    StatutoryConfigSpec,
    TaxSlabSpec,
    calculate_payslip,
)
from app.modules.platform.service import AuditService


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


class SalaryStructureService:
    """Routes 78-82 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = SalaryStructureRepository(db)
        self.component_repo = SalaryComponentRepository(db)
        self.audit = AuditService(db)

    def _get_or_404(self, company_id: uuid.UUID, structure_id: uuid.UUID) -> SalaryStructure:
        structure = self.repo.get_by_id(structure_id, company_id)
        if structure is None:
            raise NotFoundError("Salary structure not found.")
        return structure

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
        structure = self.repo.create(
            company_id=company_id, name=data.name, country=data.country, level=data.level
        )
        for c in data.components:
            self.component_repo.create(
                company_id=company_id,
                structure_id=structure.id,
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
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="SALARY_STRUCTURE_CREATED",
            entity_type="salary_structure",
            entity_id=structure.id,
            details={"name": structure.name, "component_count": len(data.components)},
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
        if updates:
            self.repo.update(structure, **updates)

        if data.components is not None:
            self._validate_components(data.components)
            self.component_repo.delete_all_for_structure(structure.id, company_id)
            for c in data.components:
                self.component_repo.create(
                    company_id=company_id,
                    structure_id=structure.id,
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

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="SALARY_STRUCTURE_UPDATED",
            entity_type="salary_structure",
            entity_id=structure.id,
            details={"fields": sorted(updates.keys())},
        )
        self.db.commit()
        reloaded = self.repo.get_by_id(structure.id, company_id)
        assert reloaded is not None
        return reloaded

    def delete_structure(self, company_id: uuid.UUID, structure_id: uuid.UUID, actor: User) -> None:
        structure = self._get_or_404(company_id, structure_id)
        if self.repo.count_active_assignments(structure.id, company_id):
            raise ConflictError(
                "Cannot delete a structure currently assigned to an active employee."
            )
        self.repo.soft_delete(structure)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="SALARY_STRUCTURE_DELETED",
            entity_type="salary_structure",
            entity_id=structure.id,
            details={"name": structure.name},
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


class EmployeeSalaryService:
    """Route 83-84 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = EmployeeSalaryRepository(db)
        self.structure_repo = SalaryStructureRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.audit = AuditService(db)

    def assign_salary(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, data: SalaryAssignRequest, actor: User
    ) -> tuple[EmployeeSalary, SalaryStructure, list, list, Decimal]:
        employee = self.employee_repo.get_by_id(employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        structure = self.structure_repo.get_by_id(data.structure_id, company_id)
        if structure is None:
            raise NotFoundError("Salary structure not found.")

        overlapping = self.repo.get_overlapping(employee_id, company_id, data.effective_from)
        open_ended = None
        for row in overlapping:
            if row.effective_to is None:
                if row.effective_from >= data.effective_from:
                    raise SalaryOverlapError(
                        "This employee already has a salary period starting on or after "
                        f"{data.effective_from.isoformat()}."
                    )
                open_ended = row
            else:
                raise SalaryOverlapError(
                    f"This overlaps an existing salary period "
                    f"({row.effective_from} to {row.effective_to})."
                )

        # Validate the CTC actually covers the structure's fixed + percentage
        # earnings before committing anything (Spec 19 WP-16 gate): with a
        # balance component, the CTC must be at least the non-balance total
        # (balance is then whatever's left, and must not go negative);
        # without one, the earnings must total the CTC exactly.
        earning_components = [
            c for c in structure.components if c.type == SalaryComponentType.earning
        ]
        resolved = _resolve_earning_amounts(earning_components, data.ctc)
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
                    f"more than the {data.ctc} CTC being assigned.",
                    details={"required_minimum": str(non_balance_total)},
                )
        elif non_balance_total != _round(data.ctc):
            raise InsufficientCtcError(
                f"This structure has no `balance` component, and its earnings total "
                f"{non_balance_total}, not the {data.ctc} CTC being assigned.",
                details={"components_total": str(non_balance_total)},
            )

        if open_ended is not None:
            self.repo.close(open_ended, data.effective_from - timedelta(days=1))

        salary = self.repo.create(
            company_id=company_id,
            employee_id=employee_id,
            structure_id=data.structure_id,
            ctc=data.ctc,
            effective_from=data.effective_from,
            revision_reason=data.revision_reason,
            created_by=actor.id,
        )
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="EMPLOYEE_SALARY_ASSIGNED",
            entity_type="employee_salary",
            entity_id=salary.id,
            details={
                "employee_id": str(employee_id),
                "structure_id": str(data.structure_id),
                "ctc": str(data.ctc),
                "effective_from": data.effective_from.isoformat(),
            },
        )
        self.db.commit()
        earnings, deductions, gross = resolve_earning_breakdown(structure.components, salary.ctc)
        return salary, structure, earnings, deductions, gross

    def get_current_salary(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, current_user: User
    ) -> tuple[EmployeeSalary, SalaryStructure, list, list, Decimal]:
        """Route 84: Own, HR."""
        employee = self.employee_repo.get_by_id_any_status(employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        is_hr = current_user.role == UserRole.hr_admin
        is_own = employee.user_id == current_user.id
        if not (is_hr or is_own):
            raise ForbiddenError("You do not have permission to view this employee's salary.")

        salary = self.repo.get_in_force(employee_id, company_id, date.today())
        if salary is None:
            raise NotFoundError("No salary is currently assigned to this employee.")
        structure = self.structure_repo.get_by_id(salary.structure_id, company_id)
        assert structure is not None  # FK guarantees this
        earnings, deductions, gross = resolve_earning_breakdown(structure.components, salary.ctc)
        return salary, structure, earnings, deductions, gross


# Verified 2026-09-03 against EPFO's and ESIC's own published rates (Spec
# 12.2) — a one-time row-population default for a NEW company's
# statutory_configs, mirroring the same literal-Decimal-default pattern
# CompanySettings already uses for half_day_hours_threshold/full_day_hours.
# The payslip engine (WP-18) will read a company's own row from this table,
# never one of these literals directly — a rate change is a data update to
# an existing row via route 86, never a code change.
_DEFAULT_PF_EMPLOYEE_RATE = Decimal("12.000")
_DEFAULT_PF_EMPLOYER_RATE = Decimal("12.000")
_DEFAULT_PF_WAGE_CEILING = Decimal("15000.00")
_DEFAULT_ESI_EMPLOYEE_RATE = Decimal("0.750")
_DEFAULT_ESI_EMPLOYER_RATE = Decimal("3.250")
_DEFAULT_ESI_WAGE_CEILING = Decimal("21000.00")


class StatutoryConfigService:
    """Routes 85-86 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = StatutoryConfigRepository(db)
        self.audit = AuditService(db)

    def get_or_create(self, company_id: uuid.UUID) -> StatutoryConfig:
        """Lazily created on first access with the verified defaults above
        — every company approved before this session existed still gets a
        correct row the first time anyone asks for it, with no backfill
        migration needed."""
        config = self.repo.get_by_company(company_id)
        if config is not None:
            return config
        config = self.repo.create(
            company_id=company_id,
            pf_employee_rate=_DEFAULT_PF_EMPLOYEE_RATE,
            pf_employer_rate=_DEFAULT_PF_EMPLOYER_RATE,
            pf_wage_ceiling=_DEFAULT_PF_WAGE_CEILING,
            esi_employee_rate=_DEFAULT_ESI_EMPLOYEE_RATE,
            esi_employer_rate=_DEFAULT_ESI_EMPLOYER_RATE,
            esi_wage_ceiling=_DEFAULT_ESI_WAGE_CEILING,
        )
        self.db.commit()
        return config

    def update(
        self, company_id: uuid.UUID, data: StatutoryConfigUpdateRequest, actor: User
    ) -> StatutoryConfig:
        config = self.get_or_create(company_id)
        updates = data.model_dump(exclude_unset=True)
        if updates:
            self.repo.update(config, **updates, updated_by=actor.id)
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="STATUTORY_CONFIG_UPDATED",
                entity_type="statutory_config",
                entity_id=config.id,
                details={"fields": sorted(updates.keys())},
            )
            self.db.commit()
        return config


class PtSlabService:
    """Routes 87-88 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = PtSlabRepository(db)

    def list_for_state(self, state: str) -> list:
        return self.repo.list_for_state(state)

    def add_slab_set(self, data: PtSlabPutRequest, actor: User) -> list:
        """SA only. Always adds a new effective-dated set — never mutates
        a historical row, so a payroll date before this change keeps
        resolving to whatever was in force then (Spec 12)."""
        created = [
            self.repo.create(
                state=data.state,
                income_min=row.income_min,
                income_max=row.income_max,
                monthly_amount=row.monthly_amount,
                special_month=row.special_month,
                special_month_amount=row.special_month_amount,
                effective_from=data.effective_from,
                effective_to=None,
                source_note=data.source_note,
            )
            for row in data.slabs
        ]
        self.db.commit()
        return created


class TaxSlabService:
    """Routes 89-90 (Spec 10.6)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = TaxSlabRepository(db)

    def list_for(self, country: str, financial_year: str, regime=None) -> list:
        return self.repo.list_for(country, financial_year, regime)

    def add_bracket_set(self, data: TaxSlabPostRequest, actor: User) -> list:
        """SA only. Same append-only reasoning as PtSlabService."""
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
                source_note=data.source_note,
            )
            for bracket in data.brackets
        ]
        self.db.commit()
        return created


class PayrollRunService:
    """Routes 91-94 (Spec 10.6, Spec 11.9)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = PayrollRunRepository(db)
        self.item_repo = PayrollItemRepository(db)
        self.statutory_service = StatutoryConfigService(db)
        self.pt_repo = PtSlabRepository(db)
        self.tax_repo = TaxSlabRepository(db)
        self.salary_repo = EmployeeSalaryRepository(db)
        self.structure_repo = SalaryStructureRepository(db)
        self.employee_repo = EmployeeRepository(db)
        self.audit = AuditService(db)

    def create_run(
        self,
        company_id: uuid.UUID,
        data: PayrollRunCreateRequest,
        idempotency_key: str,
        actor: User,
    ) -> PayrollRun:
        from sqlalchemy.exc import IntegrityError
        from app.core.time import utcnow

        # 1. Idempotency Check (Spec 11.9 Step 2)
        existing = self.repo.get_by_idempotency_key(company_id, idempotency_key)
        if existing is not None:
            return existing

        # 2. Check regular run uniqueness per company/month/year
        if data.run_type == "regular":
            from sqlalchemy import select
            existing_regular = self.db.scalar(
                select(PayrollRun).where(
                    PayrollRun.company_id == company_id,
                    PayrollRun.month == data.month,
                    PayrollRun.year == data.year,
                    PayrollRun.run_type == PayrollRunType.regular,
                    PayrollRun.deleted_at.is_(None),
                )
            )
            if existing_regular is not None:
                raise ConflictError(
                    f"A regular payroll run for {data.month}/{data.year} already exists."
                )

        # 3. Create Draft Run with Idempotency Key (Spec 11.9 Step 3 & 4)
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
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            retry_existing = self.repo.get_by_idempotency_key(company_id, idempotency_key)
            if retry_existing is not None:
                return retry_existing
            raise

        # 4. Generate Payroll Items
        # Fetch statutory configs, PT slabs, Tax slabs
        statutory_config = self.statutory_service.get_or_create(company_id)
        statutory_spec = StatutoryConfigSpec(
            pf_enabled=statutory_config.pf_enabled,
            pf_employee_rate=statutory_config.pf_employee_rate,
            pf_employer_rate=statutory_config.pf_employer_rate,
            pf_wage_ceiling=statutory_config.pf_wage_ceiling,
            pf_restrict_to_ceiling=statutory_config.pf_restrict_to_ceiling,
            esi_enabled=statutory_config.esi_enabled,
            esi_employee_rate=statutory_config.esi_employee_rate,
            esi_employer_rate=statutory_config.esi_employer_rate,
            esi_wage_ceiling=statutory_config.esi_wage_ceiling,
            pt_enabled=statutory_config.pt_enabled,
            pt_state=statutory_config.pt_state,
            lwf_enabled=statutory_config.lwf_enabled,
            lwf_employee_amount=statutory_config.lwf_employee_amount,
            lwf_months=tuple(statutory_config.lwf_months or []),
            tds_enabled=statutory_config.tds_enabled,
            default_tax_regime=statutory_config.default_tax_regime.value,
        )

        pt_state = statutory_config.pt_state or "Gujarat"
        run_date = date(data.year, data.month, 1)
        db_pt_slabs = self.pt_repo.list_for_state(pt_state, on_date=run_date)
        pt_spec_list = [
            PTSlabSpec(
                state=s.state,
                income_min=s.income_min,
                income_max=s.income_max,
                monthly_amount=s.monthly_amount,
                special_month=s.special_month,
                special_month_amount=s.special_month_amount,
            )
            for s in db_pt_slabs
        ]

        # Financial year key (April to March)
        if data.month >= 4:
            fy_str = f"{data.year}-{data.year + 1}"
        else:
            fy_str = f"{data.year - 1}-{data.year}"

        db_tax_slabs = self.tax_repo.list_for("IN", fy_str, statutory_config.default_tax_regime)
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
            for s in db_tax_slabs
        ]

        # Select employees to process
        if data.employee_ids:
            employees = [
                e
                for eid in data.employee_ids
                if (e := self.employee_repo.get_by_id(eid, company_id)) is not None
            ]
        else:
            employees, _, _ = self.employee_repo.list_employees(
                company_id=company_id,
                q=None,
                department_id=None,
                is_active=True,
                level=None,
                employment_type=None,
                reporting_manager_id=None,
                sort=None,
                page_params=PageParams(page=1, limit=1000),
            )

        total_gross = Decimal("0.00")
        total_deductions = Decimal("0.00")
        total_net = Decimal("0.00")
        total_employer_cost = Decimal("0.00")
        processed_count = 0

        for emp in employees:
            salary_record = self.salary_repo.get_in_force(emp.id, company_id, run_date)
            if salary_record is None:
                continue

            structure = self.structure_repo.get_by_id(salary_record.structure_id, company_id)
            if structure is None:
                continue

            component_specs = [
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

            payslip_in = PayslipInput(
                ctc_annual=salary_record.ctc,
                components=component_specs,
                statutory=statutory_spec,
                pt_slabs=pt_spec_list,
                tax_slabs=tax_spec_list,
                month=data.month,
                year=data.year,
                financial_year=fy_str,
                working_days=Decimal("30.0"),
                present_days=Decimal("30.0"),
                paid_leave_days=Decimal("0.0"),
                lop_days=Decimal("0.0"),
            )

            payslip_out = calculate_payslip(payslip_in)

            earnings_json = [{"code": e.code, "name": e.name, "amount": str(e.amount)} for e in payslip_out.earnings]
            deductions_json = [{"code": d.code, "name": d.name, "amount": str(d.amount)} for d in payslip_out.deductions]
            employer_json = [{"code": er.code, "name": er.name, "amount": str(er.amount)} for er in payslip_out.employer_contributions]

            self.item_repo.create(
                company_id=company_id,
                payroll_run_id=run.id,
                employee_id=emp.id,
                ctc_snapshot=salary_record.ctc,
                gross_salary=payslip_out.gross_salary,
                total_deductions=payslip_out.total_deductions,
                net_salary=payslip_out.net_salary,
                employer_cost=payslip_out.employer_cost,
                earnings_json=earnings_json,
                deductions_json=deductions_json,
                employer_contributions_json=employer_json,
                working_days=Decimal("30.0"),
                present_days=Decimal("30.0"),
                absent_days=Decimal("0.0"),
                half_days=Decimal("0.0"),
                paid_leave_days=Decimal("0.0"),
                lop_days=Decimal("0.0"),
                reimbursement_amount=Decimal("0.00"),
            )

            total_gross += payslip_out.gross_salary
            total_deductions += payslip_out.total_deductions
            total_net += payslip_out.net_salary
            total_employer_cost += payslip_out.employer_cost
            processed_count += 1

        self.repo.update(
            run,
            status=PayrollRunStatus.pending_approval if processed_count > 0 else PayrollRunStatus.draft,
            total_employees=processed_count,
            total_gross=total_gross,
            total_deductions=total_deductions,
            total_net=total_net,
            total_employer_cost=total_employer_cost,
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
                "total_employees": processed_count,
                "total_net": str(total_net),
            },
        )
        self.db.commit()
        return run

    def list_runs(
        self, company_id: uuid.UUID, page_params: PageParams, status: PayrollRunStatus | None = None
    ) -> tuple[list[PayrollRun], int, int]:
        return self.repo.list_runs(company_id, page_params, status)

    def get_run_detail(
        self, company_id: uuid.UUID, run_id: uuid.UUID
    ) -> tuple[PayrollRun, list[PayrollItem]]:
        run = self.repo.get_by_id(run_id, company_id)
        if run is None:
            raise NotFoundError("Payroll run not found.")
        items = self.item_repo.list_by_run_id(run.id, company_id)
        return run, items

    def approve_run(
        self, company_id: uuid.UUID, run_id: uuid.UUID, actor: User
    ) -> PayrollRun:
        from app.core.time import utcnow

        run = self.repo.get_by_id(run_id, company_id)
        if run is None:
            raise NotFoundError("Payroll run not found.")

        if run.status == PayrollRunStatus.approved:
            return run

        self.repo.update(
            run,
            status=PayrollRunStatus.approved,
            approved_by=actor.id,
            approved_at=utcnow(),
        )
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="PAYROLL_RUN_APPROVED",
            entity_type="payroll_run",
            entity_id=run.id,
            details={"month": run.month, "year": run.year, "total_net": str(run.total_net)},
        )
        self.db.commit()
        return run

