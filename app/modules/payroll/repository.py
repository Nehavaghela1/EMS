import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.pagination import PageParams, paginate
from app.modules.payroll.models import (
    EmployeeSalary,
    PayrollItem,
    PayrollRun,
    PayrollRunStatus,
    PtSlab,
    SalaryComponent,
    SalaryStructure,
    StatutoryConfig,
    TaxRegime,
    TaxSlab,
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

    def list_structures(
        self, company_id: uuid.UUID, page_params: PageParams
    ) -> tuple[list[SalaryStructure], int, int]:
        stmt = (
            select(SalaryStructure)
            .where(SalaryStructure.company_id == company_id, SalaryStructure.deleted_at.is_(None))
            .order_by(SalaryStructure.name.asc())
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

    def count_active_assignments(self, structure_id: uuid.UUID, company_id: uuid.UUID) -> int:
        """Route 82's 409 gate: a structure currently assigned to any
        employee (an employee_salaries row with no effective_to, or one
        that has not yet ended) cannot be deleted."""
        today = date.today()
        return (
            self.db.scalar(
                select(EmployeeSalary.id)
                .where(
                    EmployeeSalary.structure_id == structure_id,
                    EmployeeSalary.company_id == company_id,
                    EmployeeSalary.deleted_at.is_(None),
                    EmployeeSalary.effective_from <= today,
                    or_(
                        EmployeeSalary.effective_to.is_(None), EmployeeSalary.effective_to >= today
                    ),
                )
                .limit(1)
            )
            is not None
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
        return list(self.db.scalars(stmt).all())

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

    def create(self, **kwargs) -> EmployeeSalary:
        salary = EmployeeSalary(**kwargs)
        self.db.add(salary)
        self.db.flush()
        return salary

    def close(self, salary: EmployeeSalary, effective_to: date) -> None:
        salary.effective_to = effective_to
        self.db.flush()


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

    def create(self, **kwargs) -> TaxSlab:
        slab = TaxSlab(**kwargs)
        self.db.add(slab)
        self.db.flush()
        return slab


class PayrollRunRepository:
    def __init__(self, db: Session):
        self.db = db

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


class PayrollItemRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **kwargs) -> PayrollItem:
        item = PayrollItem(**kwargs)
        self.db.add(item)
        self.db.flush()
        return item

    def list_by_run_id(
        self, run_id: uuid.UUID, company_id: uuid.UUID
    ) -> list[PayrollItem]:
        return list(
            self.db.scalars(
                select(PayrollItem).where(
                    PayrollItem.payroll_run_id == run_id,
                    PayrollItem.company_id == company_id,
                    PayrollItem.deleted_at.is_(None),
                )
            ).all()
        )

