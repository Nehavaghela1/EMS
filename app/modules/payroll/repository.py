import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.pagination import PageParams, paginate
from app.modules.hr.models import Employee
from app.modules.payroll.models import (
    EmployeeSalary,
    PayrollItem,
    PayrollRun,
    PayrollRunStatus,
    PayrollRunType,
    PtSlab,
    Reimbursement,
    ReimbursementStatus,
    ReimbursementType,
    SalaryComponent,
    SalaryStructure,
    StatutoryConfig,
    StatutoryRate,
    TaxRegime,
    TaxSlab,
)
from app.modules.platform.models import FileObject

# A claim in one of these states keeps its receipt and counts for the duplicate check.
OPEN_STATUSES = (
    ReimbursementStatus.pending,
    ReimbursementStatus.approved,
    ReimbursementStatus.paid,
)


class SalaryStructureRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, structure_id: uuid.UUID, company_id: uuid.UUID) -> SalaryStructure | None:
        return self.db.scalar(
            select(SalaryStructure)
            .options(selectinload(SalaryStructure.components))
            .where(
                SalaryStructure.id == structure_id,
                SalaryStructure.company_id == company_id,
                SalaryStructure.deleted_at.is_(None),
            )
        )

    def get_by_id_including_deleted(
        self, structure_id: uuid.UUID, company_id: uuid.UUID
    ) -> SalaryStructure | None:
        """For showing a salary that was assigned under a structure which was deleted later."""
        return self.db.scalar(
            select(SalaryStructure)
            .options(selectinload(SalaryStructure.components))
            .where(SalaryStructure.id == structure_id, SalaryStructure.company_id == company_id)
        )

    def get_by_name(
        self, company_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
    ) -> SalaryStructure | None:
        """A live structure with this name, ignoring case and surrounding spaces."""
        stmt = select(SalaryStructure).where(
            SalaryStructure.company_id == company_id,
            func.lower(SalaryStructure.name) == name.strip().lower(),
            SalaryStructure.deleted_at.is_(None),
        )
        if exclude_id is not None:
            stmt = stmt.where(SalaryStructure.id != exclude_id)
        return self.db.scalar(stmt)

    def list_structures(
        self, company_id: uuid.UUID, page_params: PageParams
    ) -> tuple[list[SalaryStructure], int, int]:
        stmt = (
            select(SalaryStructure)
            .options(selectinload(SalaryStructure.components))
            .where(SalaryStructure.company_id == company_id, SalaryStructure.deleted_at.is_(None))
            .order_by(func.lower(SalaryStructure.name).asc(), SalaryStructure.id.asc())
        )
        return paginate(self.db, stmt, page_params)

    def create(self, **kwargs) -> SalaryStructure:
        structure = SalaryStructure(**kwargs)
        self.db.add(structure)
        self.db.flush()
        return structure

    def update(self, structure: SalaryStructure, **kwargs) -> SalaryStructure:
        for key, value in kwargs.items():
            setattr(structure, key, value)
        self.db.flush()
        return structure

    def soft_delete(self, structure: SalaryStructure) -> None:
        from app.core.time import utcnow

        structure.deleted_at = utcnow()
        self.db.flush()

    def list_current_and_future_salaries(
        self, structure_id: uuid.UUID, company_id: uuid.UUID, today: date
    ) -> list[EmployeeSalary]:
        """Salaries on this structure that are in force today or start later (an
        employee_salaries row with no effective_to, or one that has not ended yet)."""
        return list(
            self.db.scalars(
                select(EmployeeSalary).where(
                    EmployeeSalary.structure_id == structure_id,
                    EmployeeSalary.company_id == company_id,
                    EmployeeSalary.deleted_at.is_(None),
                    or_(
                        EmployeeSalary.effective_to.is_(None), EmployeeSalary.effective_to >= today
                    ),
                )
            ).all()
        )


class SalaryComponentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **kwargs) -> SalaryComponent:
        component = SalaryComponent(**kwargs)
        self.db.add(component)
        self.db.flush()
        return component

    def delete_all_for_structure(self, structure_id: uuid.UUID, company_id: uuid.UUID) -> None:
        """Used by route 81's wholesale component replacement. A hard
        delete, not soft — these rows have no independent identity a
        reviewer needs to keep once the structure itself is edited (the
        structure row's own audit trail, not per-component history, is
        what matters here; the historical payslip snapshot lives in
        payroll_items.earnings_json, not in this table — Spec 7.6)."""
        self.db.query(SalaryComponent).filter(
            SalaryComponent.structure_id == structure_id, SalaryComponent.company_id == company_id
        ).delete()
        self.db.flush()


class EmployeeSalaryRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_overlapping_month(
        self, employee_id: uuid.UUID, company_id: uuid.UUID, month_start: date, month_end: date
    ) -> list[EmployeeSalary]:
        """Every salary row whose dates touch the month, oldest first."""
        return list(
            self.db.scalars(
                select(EmployeeSalary)
                .where(
                    EmployeeSalary.employee_id == employee_id,
                    EmployeeSalary.company_id == company_id,
                    EmployeeSalary.deleted_at.is_(None),
                    EmployeeSalary.effective_from <= month_end,
                    or_(
                        EmployeeSalary.effective_to.is_(None),
                        EmployeeSalary.effective_to >= month_start,
                    ),
                )
                .order_by(EmployeeSalary.effective_from.asc())
            ).all()
        )

    def get_open_ended(
        self, employee_id: uuid.UUID, company_id: uuid.UUID
    ) -> EmployeeSalary | None:
        return self.db.scalar(
            select(EmployeeSalary).where(
                EmployeeSalary.employee_id == employee_id,
                EmployeeSalary.company_id == company_id,
                EmployeeSalary.deleted_at.is_(None),
                EmployeeSalary.effective_to.is_(None),
            )
        )

    def get_latest(self, employee_id: uuid.UUID, company_id: uuid.UUID) -> EmployeeSalary | None:
        return self.db.scalar(
            select(EmployeeSalary)
            .where(
                EmployeeSalary.employee_id == employee_id,
                EmployeeSalary.company_id == company_id,
                EmployeeSalary.deleted_at.is_(None),
            )
            .order_by(EmployeeSalary.effective_from.desc())
        )

    def get_overlapping(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID,
        effective_from: date,
        exclude_id: uuid.UUID | None = None,
    ) -> list[EmployeeSalary]:
        """Any existing row whose range could overlap a new one starting at
        effective_from (open-ended). Excludes a row by id so re-closing the
        previously-open row (see the service) doesn't count as its own
        overlap."""
        stmt = select(EmployeeSalary).where(
            EmployeeSalary.employee_id == employee_id,
            EmployeeSalary.company_id == company_id,
            EmployeeSalary.deleted_at.is_(None),
            or_(
                EmployeeSalary.effective_to.is_(None), EmployeeSalary.effective_to >= effective_from
            ),
        )
        if exclude_id is not None:
            stmt = stmt.where(EmployeeSalary.id != exclude_id)
        return list(self.db.scalars(stmt.order_by(EmployeeSalary.effective_from.asc())).all())

    def get_in_force(
        self, employee_id: uuid.UUID, company_id: uuid.UUID, on_date: date
    ) -> EmployeeSalary | None:
        """The row where effective_from <= on_date AND (effective_to IS
        NULL OR effective_to >= on_date) — Spec 7.6's own definition of
        "the one in force." Lookup by date, never "the latest row.\""""
        return self.db.scalar(
            select(EmployeeSalary).where(
                EmployeeSalary.employee_id == employee_id,
                EmployeeSalary.company_id == company_id,
                EmployeeSalary.deleted_at.is_(None),
                EmployeeSalary.effective_from <= on_date,
                or_(EmployeeSalary.effective_to.is_(None), EmployeeSalary.effective_to >= on_date),
            )
        )

    def list_history(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID,
        page_params: PageParams,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> tuple[list[EmployeeSalary], int, int]:
        """Every live salary row of the employee, newest first; the date filters apply to the
        row's effective_from."""
        stmt = select(EmployeeSalary).where(
            EmployeeSalary.employee_id == employee_id,
            EmployeeSalary.company_id == company_id,
            EmployeeSalary.deleted_at.is_(None),
        )
        if from_date is not None:
            stmt = stmt.where(EmployeeSalary.effective_from >= from_date)
        if to_date is not None:
            stmt = stmt.where(EmployeeSalary.effective_from <= to_date)
        stmt = stmt.order_by(EmployeeSalary.effective_from.desc(), EmployeeSalary.id.asc())
        return paginate(self.db, stmt, page_params)

    def structure_names(
        self, structure_ids: list[uuid.UUID], company_id: uuid.UUID
    ) -> dict[uuid.UUID, str]:
        """Names of structures, deleted ones included (history keeps showing them)."""
        if not structure_ids:
            return {}
        rows = self.db.execute(
            select(SalaryStructure.id, SalaryStructure.name).where(
                SalaryStructure.id.in_(structure_ids), SalaryStructure.company_id == company_id
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    def create(self, **kwargs) -> EmployeeSalary:
        salary = EmployeeSalary(**kwargs)
        self.db.add(salary)
        self.db.flush()
        return salary

    def update(self, salary: EmployeeSalary, **kwargs) -> EmployeeSalary:
        for key, value in kwargs.items():
            setattr(salary, key, value)
        self.db.flush()
        return salary

    def close(self, salary: EmployeeSalary, effective_to: date) -> None:
        salary.effective_to = effective_to
        self.db.flush()

    def count_for_employee(self, employee_id: uuid.UUID, company_id: uuid.UUID) -> int:
        from sqlalchemy import func

        return (
            self.db.scalar(
                select(func.count())
                .select_from(EmployeeSalary)
                .where(
                    EmployeeSalary.employee_id == employee_id,
                    EmployeeSalary.company_id == company_id,
                    EmployeeSalary.deleted_at.is_(None),
                )
            )
            or 0
        )


class StatutoryConfigRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_company(self, company_id: uuid.UUID) -> StatutoryConfig | None:
        return self.db.scalar(
            select(StatutoryConfig).where(StatutoryConfig.company_id == company_id)
        )

    def create(self, **kwargs) -> StatutoryConfig:
        config = StatutoryConfig(**kwargs)
        self.db.add(config)
        self.db.flush()
        return config

    def update(self, config: StatutoryConfig, **kwargs) -> StatutoryConfig:
        for key, value in kwargs.items():
            setattr(config, key, value)
        self.db.flush()
        return config


class PtSlabRepository:
    """RLS: No — government-defined, platform-managed (Spec 7.6)."""

    def __init__(self, db: Session):
        self.db = db

    def list_for_state(self, state: str, on_date: date | None = None) -> list[PtSlab]:
        """All slabs for a state, or — when on_date is given — only the
        bracket set in force on that date (lookup by date, never "the
        latest row," Spec 12)."""
        stmt = select(PtSlab).where(PtSlab.state == state, PtSlab.deleted_at.is_(None))
        if on_date is not None:
            stmt = stmt.where(
                PtSlab.effective_from <= on_date,
                or_(PtSlab.effective_to.is_(None), PtSlab.effective_to >= on_date),
            )
        return list(self.db.scalars(stmt.order_by(PtSlab.income_min.asc())).all())

    def get_for_income(self, state: str, monthly_income, on_date: date) -> PtSlab | None:
        return self.db.scalar(
            select(PtSlab).where(
                PtSlab.state == state,
                PtSlab.deleted_at.is_(None),
                PtSlab.income_min <= monthly_income,
                or_(PtSlab.income_max.is_(None), PtSlab.income_max >= monthly_income),
                PtSlab.effective_from <= on_date,
                or_(PtSlab.effective_to.is_(None), PtSlab.effective_to >= on_date),
            )
        )

    def list_open_locked(self, state: str) -> list[PtSlab]:
        """The slabs of `state` that have no end date, locked for the duration of the save."""
        return list(
            self.db.scalars(
                select(PtSlab)
                .where(
                    PtSlab.state == state,
                    PtSlab.effective_to.is_(None),
                    PtSlab.deleted_at.is_(None),
                )
                .with_for_update()
            ).all()
        )

    def set_effective_to(self, slabs: list[PtSlab], effective_to: date) -> None:
        for slab in slabs:
            slab.effective_to = effective_to
        self.db.flush()

    def create(self, **kwargs) -> PtSlab:
        slab = PtSlab(**kwargs)
        self.db.add(slab)
        self.db.flush()
        return slab


class TaxSlabRepository:
    """RLS: No — government-defined, platform-managed (Spec 7.6)."""

    def __init__(self, db: Session):
        self.db = db

    def list_for(
        self, country: str, financial_year: str, regime: TaxRegime | None = None
    ) -> list[TaxSlab]:
        stmt = select(TaxSlab).where(
            TaxSlab.country == country,
            TaxSlab.financial_year == financial_year,
            TaxSlab.deleted_at.is_(None),
        )
        if regime is not None:
            stmt = stmt.where(TaxSlab.regime == regime)
        return list(
            self.db.scalars(stmt.order_by(TaxSlab.regime.asc(), TaxSlab.min_income.asc())).all()
        )

    def list_in_force(
        self, country: str, financial_year: str, regime: TaxRegime, on_date: date
    ) -> list[TaxSlab]:
        """The brackets of one financial year and regime that had started by `on_date`."""
        return list(
            self.db.scalars(
                select(TaxSlab)
                .where(
                    TaxSlab.country == country,
                    TaxSlab.financial_year == financial_year,
                    TaxSlab.regime == regime,
                    TaxSlab.effective_from <= on_date,
                    TaxSlab.deleted_at.is_(None),
                )
                .order_by(TaxSlab.min_income.asc())
            ).all()
        )

    def create(self, **kwargs) -> TaxSlab:
        slab = TaxSlab(**kwargs)
        self.db.add(slab)
        self.db.flush()
        return slab


class StatutoryRateRepository:
    """RLS: No — government-defined, platform-managed (5.2)."""

    def __init__(self, db: Session):
        self.db = db

    def list_rates(
        self,
        page_params: PageParams,
        scheme: str | None = None,
        on_date: date | None = None,
    ) -> tuple[list[StatutoryRate], int, int]:
        stmt = select(StatutoryRate).where(StatutoryRate.deleted_at.is_(None))
        if scheme is not None:
            stmt = stmt.where(StatutoryRate.scheme == scheme)
        if on_date is not None:
            stmt = stmt.where(
                StatutoryRate.effective_from <= on_date,
                or_(StatutoryRate.effective_to.is_(None), StatutoryRate.effective_to >= on_date),
            )
        stmt = stmt.order_by(StatutoryRate.scheme.asc(), StatutoryRate.effective_from.asc())
        return paginate(self.db, stmt, page_params)

    def list_in_force(self, on_date: date) -> list[StatutoryRate]:
        """One row per scheme: the rates in force on `on_date`."""
        return list(
            self.db.scalars(
                select(StatutoryRate)
                .where(
                    StatutoryRate.deleted_at.is_(None),
                    StatutoryRate.effective_from <= on_date,
                    or_(
                        StatutoryRate.effective_to.is_(None),
                        StatutoryRate.effective_to >= on_date,
                    ),
                )
                .order_by(StatutoryRate.scheme.asc())
            ).all()
        )

    def get_in_force(self, scheme: str, on_date: date) -> StatutoryRate | None:
        """The one row of `scheme` in force on `on_date` (rows never overlap)."""
        return self.db.scalar(
            select(StatutoryRate).where(
                StatutoryRate.scheme == scheme,
                StatutoryRate.deleted_at.is_(None),
                StatutoryRate.effective_from <= on_date,
                or_(StatutoryRate.effective_to.is_(None), StatutoryRate.effective_to >= on_date),
            )
        )

    def list_for_scheme_locked(self, scheme: str) -> list[StatutoryRate]:
        """Every row of the scheme, locked until the caller's transaction ends, so two
        simultaneous adds look at the same state one after the other."""
        return list(
            self.db.scalars(
                select(StatutoryRate)
                .where(StatutoryRate.scheme == scheme, StatutoryRate.deleted_at.is_(None))
                .order_by(StatutoryRate.effective_from.asc())
                .with_for_update()
            ).all()
        )

    def create(self, **kwargs) -> StatutoryRate:
        rate = StatutoryRate(**kwargs)
        self.db.add(rate)
        self.db.flush()
        return rate

    def set_effective_to(self, rate: StatutoryRate, effective_to: date) -> None:
        rate.effective_to = effective_to
        self.db.flush()


class PayrollRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def count_in_flight(self, company_id: uuid.UUID) -> int:
        """Runs of the company that are being calculated or wait for approval."""
        return (
            self.db.scalar(
                select(func.count())
                .select_from(PayrollRun)
                .where(
                    PayrollRun.company_id == company_id,
                    PayrollRun.deleted_at.is_(None),
                    PayrollRun.status.in_(
                        [PayrollRunStatus.processing, PayrollRunStatus.pending_approval]
                    ),
                )
            )
            or 0
        )

    def get_by_id(self, run_id: uuid.UUID, company_id: uuid.UUID) -> PayrollRun | None:
        return self.db.scalar(
            select(PayrollRun)
            .options(selectinload(PayrollRun.items))
            .where(
                PayrollRun.id == run_id,
                PayrollRun.company_id == company_id,
                PayrollRun.deleted_at.is_(None),
            )
        )

    def get_by_id_for_update(self, run_id: uuid.UUID, company_id: uuid.UUID) -> PayrollRun | None:
        """Like get_by_id but locks the row, so two approvals or deletes of one run queue up."""
        return self.db.scalar(
            select(PayrollRun)
            .where(
                PayrollRun.id == run_id,
                PayrollRun.company_id == company_id,
                PayrollRun.deleted_at.is_(None),
            )
            .with_for_update()
        )

    def get_regular_run(self, company_id: uuid.UUID, month: int, year: int) -> PayrollRun | None:
        return self.db.scalar(
            select(PayrollRun).where(
                PayrollRun.company_id == company_id,
                PayrollRun.month == month,
                PayrollRun.year == year,
                PayrollRun.run_type == PayrollRunType.regular,
                PayrollRun.deleted_at.is_(None),
            )
        )

    def get_by_idempotency_key(
        self, company_id: uuid.UUID, idempotency_key: str
    ) -> PayrollRun | None:
        return self.db.scalar(
            select(PayrollRun).where(
                PayrollRun.company_id == company_id,
                PayrollRun.idempotency_key == idempotency_key,
                PayrollRun.deleted_at.is_(None),
            )
        )

    def list_runs(
        self, company_id: uuid.UUID, page_params: PageParams, status: PayrollRunStatus | None = None
    ) -> tuple[list[PayrollRun], int, int]:
        stmt = (
            select(PayrollRun)
            .where(PayrollRun.company_id == company_id, PayrollRun.deleted_at.is_(None))
            .order_by(PayrollRun.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(PayrollRun.status == status)
        return paginate(self.db, stmt, page_params)

    def create(self, **kwargs) -> PayrollRun:
        run = PayrollRun(**kwargs)
        self.db.add(run)
        self.db.flush()
        return run

    def update(self, run: PayrollRun, **kwargs) -> PayrollRun:
        for key, value in kwargs.items():
            setattr(run, key, value)
        self.db.flush()
        return run

    def delete(self, run: PayrollRun) -> None:
        self.db.delete(run)
        self.db.flush()


class PayrollItemRepository:
    def __init__(self, db: Session):
        self.db = db

    def first_released_month_from(
        self, employee_id: uuid.UUID, company_id: uuid.UUID, year: int, month: int
    ) -> tuple[int, int] | None:
        """The earliest (year, month), from the given month on, that an approved or paid run
        has already paid this employee for; None when there is none."""
        row = self.db.execute(
            select(PayrollRun.year, PayrollRun.month)
            .join(PayrollItem, PayrollItem.payroll_run_id == PayrollRun.id)
            .where(
                PayrollItem.employee_id == employee_id,
                PayrollItem.company_id == company_id,
                PayrollRun.company_id == company_id,
                PayrollRun.deleted_at.is_(None),
                PayrollRun.status.in_([PayrollRunStatus.approved, PayrollRunStatus.paid]),
                PayrollRun.year * 12 + PayrollRun.month >= year * 12 + month,
            )
            .order_by(PayrollRun.year.asc(), PayrollRun.month.asc())
            .limit(1)
        ).first()
        return (row[0], row[1]) if row else None

    def create(self, **kwargs) -> PayrollItem:
        item = PayrollItem(**kwargs)
        self.db.add(item)
        self.db.flush()
        return item

    def list_by_run_id(self, run_id: uuid.UUID, company_id: uuid.UUID) -> list[PayrollItem]:
        return list(
            self.db.scalars(
                select(PayrollItem).where(
                    PayrollItem.payroll_run_id == run_id,
                    PayrollItem.company_id == company_id,
                    PayrollItem.deleted_at.is_(None),
                )
            ).all()
        )

    def list_by_employee_id(
        self, company_id: uuid.UUID, employee_id: uuid.UUID
    ) -> list[PayrollItem]:
        return list(
            self.db.scalars(
                select(PayrollItem)
                .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
                .where(
                    PayrollItem.company_id == company_id,
                    PayrollItem.employee_id == employee_id,
                    PayrollRun.status == PayrollRunStatus.approved,
                    PayrollItem.deleted_at.is_(None),
                )
                .order_by(PayrollRun.year.desc(), PayrollRun.month.desc())
            ).all()
        )

    def list_payslips(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        page_params: PageParams,
        *,
        released_only: bool,
        year: int | None = None,
        month: int | None = None,
    ) -> tuple[list[PayrollItem], int, int]:
        """One employee's payslips, newest month first. `released_only` keeps the runs the
        employee may see (approved or paid); HR-level callers pass False."""
        stmt = (
            select(PayrollItem)
            .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
            .where(
                PayrollItem.company_id == company_id,
                PayrollItem.employee_id == employee_id,
                PayrollItem.deleted_at.is_(None),
                PayrollRun.deleted_at.is_(None),
            )
            .order_by(PayrollRun.year.desc(), PayrollRun.month.desc(), PayrollRun.created_at.desc())
        )
        if released_only:
            stmt = stmt.where(
                PayrollRun.status.in_([PayrollRunStatus.approved, PayrollRunStatus.paid])
            )
        if year is not None:
            stmt = stmt.where(PayrollRun.year == year)
        if month is not None:
            stmt = stmt.where(PayrollRun.month == month)
        return paginate(self.db, stmt, page_params)

    def find_employee_any_company(self, employee_id: uuid.UUID) -> Employee | None:
        """For the platform super admin only, who is not tied to one company."""
        return self.db.scalar(
            select(Employee).where(Employee.id == employee_id, Employee.deleted_at.is_(None))
        )

    def get_ytd_gross_for_employee(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        start_year: int,
        exclude_run_id: uuid.UUID | None = None,
    ) -> Decimal:
        """Sums gross_salary for the employee across approved/paid runs in the financial year
        (April of start_year through March of start_year + 1), excluding the specified run
        if provided (e.g. current rebuild).
        """
        stmt = (
            select(func.coalesce(func.sum(PayrollItem.gross_salary), Decimal("0.00")))
            .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
            .where(
                PayrollItem.company_id == company_id,
                PayrollItem.employee_id == employee_id,
                PayrollRun.status.in_([PayrollRunStatus.approved, PayrollRunStatus.paid]),
                PayrollItem.deleted_at.is_(None),
                PayrollRun.deleted_at.is_(None),
                or_(
                    and_(PayrollRun.year == start_year, PayrollRun.month >= 4),
                    and_(PayrollRun.year == start_year + 1, PayrollRun.month <= 3),
                ),
            )
        )
        if exclude_run_id is not None:
            stmt = stmt.where(PayrollItem.payroll_run_id != exclude_run_id)
        result = self.db.scalar(stmt)
        return Decimal(str(result or "0.00"))

    def get_ytd_tds_for_employee(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        start_year: int,
        exclude_run_id: uuid.UUID | None = None,
    ) -> Decimal:
        """Sums TDS deducted for the employee across approved/paid runs in the financial year
        (April of start_year through March of start_year + 1), reading from deductions_json,
        and excluding the specified run if provided.
        """
        stmt = (
            select(PayrollItem.deductions_json)
            .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
            .where(
                PayrollItem.company_id == company_id,
                PayrollItem.employee_id == employee_id,
                PayrollRun.status.in_([PayrollRunStatus.approved, PayrollRunStatus.paid]),
                PayrollItem.deleted_at.is_(None),
                PayrollRun.deleted_at.is_(None),
                or_(
                    and_(PayrollRun.year == start_year, PayrollRun.month >= 4),
                    and_(PayrollRun.year == start_year + 1, PayrollRun.month <= 3),
                ),
            )
        )
        if exclude_run_id is not None:
            stmt = stmt.where(PayrollItem.payroll_run_id != exclude_run_id)

        rows = self.db.scalars(stmt).all()
        total_tds = Decimal("0.00")
        for deductions in rows:
            if isinstance(deductions, list):
                for d in deductions:
                    if isinstance(d, dict) and d.get("code") == "TDS":
                        total_tds += Decimal(str(d.get("amount", "0.00")))
        return total_tds


class ReimbursementRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, reimbursement_id: uuid.UUID, company_id: uuid.UUID) -> Reimbursement | None:
        return self.db.scalar(
            select(Reimbursement).where(
                Reimbursement.id == reimbursement_id,
                Reimbursement.company_id == company_id,
                Reimbursement.deleted_at.is_(None),
            )
        )

    def get_by_id_for_update(
        self, reimbursement_id: uuid.UUID, company_id: uuid.UUID
    ) -> Reimbursement | None:
        """The claim, row-locked until the caller's transaction ends: two people deciding or
        withdrawing at the same moment are served one after the other."""
        return self.db.scalar(
            select(Reimbursement)
            .where(
                Reimbursement.id == reimbursement_id,
                Reimbursement.company_id == company_id,
                Reimbursement.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def get_receipt_file(self, company_id: uuid.UUID, file_id: uuid.UUID) -> FileObject | None:
        return self.db.scalar(
            select(FileObject).where(
                FileObject.id == file_id,
                FileObject.company_id == company_id,
                FileObject.deleted_at.is_(None),
            )
        )

    def receipt_in_use(self, company_id: uuid.UUID, file_object_id: uuid.UUID) -> bool:
        """Is the receipt attached to a pending, approved or paid claim?"""
        return (
            self.db.scalar(
                select(Reimbursement.id)
                .where(
                    Reimbursement.company_id == company_id,
                    Reimbursement.file_object_id == file_object_id,
                    Reimbursement.status.in_(OPEN_STATUSES),
                    Reimbursement.deleted_at.is_(None),
                )
                .limit(1)
            )
            is not None
        )

    def open_duplicate_exists(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        expense_date: date,
        claim_type: ReimbursementType,
        amount: Decimal,
    ) -> bool:
        return (
            self.db.scalar(
                select(Reimbursement.id)
                .where(
                    Reimbursement.company_id == company_id,
                    Reimbursement.employee_id == employee_id,
                    Reimbursement.expense_date == expense_date,
                    Reimbursement.type == claim_type,
                    Reimbursement.amount == amount,
                    Reimbursement.status.in_(OPEN_STATUSES),
                    Reimbursement.deleted_at.is_(None),
                )
                .limit(1)
            )
            is not None
        )

    def list_unpaid_approved(
        self, company_id: uuid.UUID, employee_id: uuid.UUID
    ) -> list[Reimbursement]:
        return list(
            self.db.scalars(
                select(Reimbursement)
                .where(
                    Reimbursement.company_id == company_id,
                    Reimbursement.employee_id == employee_id,
                    Reimbursement.status == ReimbursementStatus.approved,
                    Reimbursement.added_to_payroll_run_id.is_(None),
                    Reimbursement.deleted_at.is_(None),
                )
                .with_for_update()
            ).all()
        )

    def list_claims(
        self,
        company_id: uuid.UUID,
        page_params: PageParams,
        employee_id: uuid.UUID | None = None,
        employee_ids: list[uuid.UUID] | None = None,
        status: ReimbursementStatus | None = None,
        month: int | None = None,
        year: int | None = None,
    ) -> tuple[list[Reimbursement], int, int]:
        stmt = (
            select(Reimbursement)
            .where(
                Reimbursement.company_id == company_id,
                Reimbursement.deleted_at.is_(None),
            )
            .order_by(Reimbursement.created_at.desc(), Reimbursement.id.desc())
        )

        if employee_id is not None:
            stmt = stmt.where(Reimbursement.employee_id == employee_id)
        elif employee_ids is not None:
            stmt = stmt.where(Reimbursement.employee_id.in_(employee_ids))

        if status is not None:
            stmt = stmt.where(Reimbursement.status == status)
        if month is not None:
            stmt = stmt.where(func.extract("month", Reimbursement.expense_date) == month)
        if year is not None:
            stmt = stmt.where(func.extract("year", Reimbursement.expense_date) == year)

        return paginate(self.db, stmt, page_params)

    def create(self, **kwargs) -> Reimbursement:
        claim = Reimbursement(**kwargs)
        self.db.add(claim)
        self.db.flush()
        return claim

    def update(self, claim: Reimbursement, **kwargs) -> Reimbursement:
        for key, value in kwargs.items():
            setattr(claim, key, value)
        self.db.flush()
        return claim
