import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.pagination import Page, PageParams, page_params
from app.modules.identity.models import User, UserRole
from app.modules.payroll.models import (
    PayrollRunStatus,
    PtSlab,
    ReimbursementStatus,
    SalaryStructure,
    TaxRegime,
    TaxSlab,
)
from app.modules.payroll.schemas import (
    EmployeeSalaryResponse,
    PayrollItemResponse,
    PayrollRunCreateRequest,
    PayrollRunDetailResponse,
    PayrollRunResponse,
    PtSlabPutRequest,
    PtSlabResponse,
    ReimbursementCreateRequest,
    ReimbursementResponse,
    ReimbursementReviewRequest,
    SalaryAssignRequest,
    SalaryStructureCreateRequest,
    SalaryStructureListItem,
    SalaryStructureResponse,
    SalaryStructureUpdateRequest,
    StatutoryConfigResponse,
    StatutoryConfigUpdateRequest,
    TaxSlabPostRequest,
    TaxSlabResponse,
)
from app.modules.payroll.repository import PayrollItemRepository
from app.modules.payroll.service import (
    EmployeeSalaryService,
    PayrollRunService,
    PtSlabService,
    ReimbursementService,
    SalaryStructureService,
    StatutoryConfigService,
    TaxSlabService,
)

structures_router = APIRouter(prefix="/payroll/structures", tags=["Payroll — Salary Structures"])
employee_salary_router = APIRouter(prefix="/payroll/employees", tags=["Payroll — Employee Salary"])
statutory_config_router = APIRouter(
    prefix="/payroll/statutory-config", tags=["Payroll — Statutory Config"]
)
pt_slabs_router = APIRouter(prefix="/payroll/pt-slabs", tags=["Payroll — PT Slabs"])
tax_slabs_router = APIRouter(prefix="/payroll/tax-slabs", tags=["Payroll — Tax Slabs"])


def _to_structure_response(structure: SalaryStructure) -> SalaryStructureResponse:
    return SalaryStructureResponse.model_validate(structure)


# --- Routes 78-82: salary structures -----------------------------------


@structures_router.post("", response_model=SalaryStructureResponse, status_code=201)
def create_structure(
    data: SalaryStructureCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    structure = SalaryStructureService(db).create_structure(user.company_id, data, user)
    return _to_structure_response(structure)


@structures_router.get("", response_model=Page[SalaryStructureListItem])
def list_structures(
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    items, total, pages = SalaryStructureService(db).list_structures(user.company_id, params)
    return Page(
        items=[
            SalaryStructureListItem(
                id=s.id,
                name=s.name,
                country=s.country,
                level=s.level,
                is_active=s.is_active,
                component_count=len(s.components),
                created_at=s.created_at,
            )
            for s in items
        ],
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@structures_router.get("/{structure_id}", response_model=SalaryStructureResponse)
def get_structure(
    structure_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    structure = SalaryStructureService(db).get_structure(user.company_id, structure_id)
    return _to_structure_response(structure)


@structures_router.put("/{structure_id}", response_model=SalaryStructureResponse)
def update_structure(
    structure_id: uuid.UUID,
    data: SalaryStructureUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    structure = SalaryStructureService(db).update_structure(
        user.company_id, structure_id, data, user
    )
    return _to_structure_response(structure)


@structures_router.delete("/{structure_id}", status_code=204)
def delete_structure(
    structure_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    SalaryStructureService(db).delete_structure(user.company_id, structure_id, user)


# --- Routes 83-84: employee salary assignment ---------------------------


@employee_salary_router.post(
    "/{employee_id}/assign", response_model=EmployeeSalaryResponse, status_code=201
)
def assign_salary(
    employee_id: uuid.UUID,
    data: SalaryAssignRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    salary, structure, earnings, deductions, gross = EmployeeSalaryService(db).assign_salary(
        user.company_id, employee_id, data, user
    )
    return EmployeeSalaryResponse(
        employee_id=salary.employee_id,
        structure_id=salary.structure_id,
        structure_name=structure.name,
        ctc=salary.ctc,
        effective_from=salary.effective_from,
        effective_to=salary.effective_to,
        revision_reason=salary.revision_reason,
        earnings=earnings,
        deductions=deductions,
        gross_earnings=gross,
    )


@employee_salary_router.get("/{employee_id}/salary", response_model=EmployeeSalaryResponse)
def get_employee_salary(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = EmployeeSalaryService(db)
    salary, structure, earnings, deductions, gross = service.get_current_salary(
        user.company_id, employee_id, user
    )
    return EmployeeSalaryResponse(
        employee_id=salary.employee_id,
        structure_id=salary.structure_id,
        structure_name=structure.name,
        ctc=salary.ctc,
        effective_from=salary.effective_from,
        effective_to=salary.effective_to,
        revision_reason=salary.revision_reason,
        earnings=earnings,
        deductions=deductions,
        gross_earnings=gross,
    )


# --- Routes 85-86: statutory config --------------------------------------


def _to_statutory_config_response(config) -> StatutoryConfigResponse:
    return StatutoryConfigResponse.model_validate(config)


@statutory_config_router.get("", response_model=StatutoryConfigResponse)
def get_statutory_config(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    config = StatutoryConfigService(db).get_or_create(user.company_id)
    return _to_statutory_config_response(config)


@statutory_config_router.put("", response_model=StatutoryConfigResponse)
def update_statutory_config(
    data: StatutoryConfigUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    config = StatutoryConfigService(db).update(user.company_id, data, user)
    return _to_statutory_config_response(config)


# --- Routes 87-88: PT slabs -----------------------------------------------


def _to_pt_slab_response(slab: PtSlab) -> PtSlabResponse:
    return PtSlabResponse.model_validate(slab)


@pt_slabs_router.get("", response_model=list[PtSlabResponse])
def list_pt_slabs(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    config = StatutoryConfigService(db).get_or_create(user.company_id)
    state = config.pt_state or "Gujarat"
    slabs = PtSlabService(db).list_for_state(state)
    return [_to_pt_slab_response(s) for s in slabs]


@pt_slabs_router.put("", response_model=list[PtSlabResponse])
def put_pt_slabs(
    data: PtSlabPutRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.super_admin)),
):
    slabs = PtSlabService(db).add_slab_set(data, user)
    return [_to_pt_slab_response(s) for s in slabs]


# --- Routes 89-90: tax slabs -----------------------------------------------


def _to_tax_slab_response(slab: TaxSlab) -> TaxSlabResponse:
    return TaxSlabResponse.model_validate(slab)


@tax_slabs_router.get("", response_model=list[TaxSlabResponse])
def list_tax_slabs(
    financial_year: str,
    regime: TaxRegime | None = None,
    country: str = "IN",
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.super_admin)),
):
    slabs = TaxSlabService(db).list_for(country, financial_year, regime)
    return [_to_tax_slab_response(s) for s in slabs]


@tax_slabs_router.post("", response_model=list[TaxSlabResponse], status_code=201)
def post_tax_slabs(
    data: TaxSlabPostRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.super_admin)),
):
    slabs = TaxSlabService(db).add_bracket_set(data, user)
    return [_to_tax_slab_response(s) for s in slabs]


from app.modules.hr.repository import EmployeeRepository

# --- Routes 91-94: payroll runs --------------------------------------------

payroll_runs_router = APIRouter(prefix="/payroll/runs", tags=["Payroll — Payroll Runs"])


@payroll_runs_router.post("", response_model=PayrollRunResponse, status_code=202)
def create_payroll_run(
    data: PayrollRunCreateRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required.",
        )

    service = PayrollRunService(db)
    run = service.create_run(
        company_id=user.company_id,
        data=data,
        idempotency_key=idempotency_key,
        actor=user,
    )
    return PayrollRunResponse.model_validate(run)


@payroll_runs_router.get("", response_model=Page[PayrollRunResponse])
def list_payroll_runs(
    status_filter: PayrollRunStatus | None = None,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    service = PayrollRunService(db)
    runs, total, pages = service.list_runs(user.company_id, params, status_filter)
    items = [PayrollRunResponse.model_validate(r) for r in runs]
    return Page(
        items=items,
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@payroll_runs_router.get("/{id}", response_model=PayrollRunDetailResponse)
def get_payroll_run_detail(
    id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.employee, UserRole.manager)),
):
    service = PayrollRunService(db)
    run, items = service.get_run_detail(user.company_id, id)

    # An employee cannot see a payslip before the run is approved (Spec 11.9, Gate WP-19)
    if user.role not in (UserRole.hr_admin, UserRole.super_admin):
        if run.status != PayrollRunStatus.approved:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Payroll run has not been approved yet.",
            )
        emp = EmployeeRepository(db).get_by_user_id(user.company_id, user.id)
        emp_id = emp.id if emp else None
        items = [item for item in items if item.employee_id == emp_id]

    return PayrollRunDetailResponse(
        run=PayrollRunResponse.model_validate(run),
        items=[PayrollItemResponse.model_validate(i) for i in items],
    )


@payroll_runs_router.post("/{id}/approve", response_model=PayrollRunResponse)
def approve_payroll_run(
    id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    service = PayrollRunService(db)
    run = service.approve_run(user.company_id, id, user)
    return PayrollRunResponse.model_validate(run)


# --- Routes 95-96: payslips -----------------------------------------------

payslips_router = APIRouter(prefix="/payroll/payslips", tags=["Payroll — Payslips"])


@payslips_router.get("/me", response_model=list[PayrollItemResponse])
def list_my_payslips(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    emp = EmployeeRepository(db).get_by_user_id(user.company_id, user.id)
    if not emp:
        return []
    items = PayrollItemRepository(db).list_by_employee_id(user.company_id, emp.id)
    return [PayrollItemResponse.model_validate(i) for i in items]


@payslips_router.get("/{employee_id}", response_model=list[PayrollItemResponse])
def list_employee_payslips(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    items = PayrollItemRepository(db).list_by_employee_id(user.company_id, employee_id)
    return [PayrollItemResponse.model_validate(i) for i in items]


# --- Routes 97-99: reimbursements ------------------------------------------

reimbursements_router = APIRouter(prefix="/payroll/reimbursements", tags=["Payroll — Reimbursements"])


@reimbursements_router.post("", response_model=ReimbursementResponse, status_code=201)
def submit_reimbursement_claim(
    data: ReimbursementCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = ReimbursementService(db)
    claim = service.submit_claim(user.company_id, data, user)
    return ReimbursementResponse.model_validate(claim)


@reimbursements_router.get("", response_model=Page[ReimbursementResponse])
def list_reimbursement_claims(
    status_filter: ReimbursementStatus | None = None,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    service = ReimbursementService(db)
    claims, total, pages = service.list_claims(user.company_id, user, params, status_filter)
    items = [ReimbursementResponse.model_validate(c) for c in claims]
    return Page(
        items=items,
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@reimbursements_router.put("/{id}", response_model=ReimbursementResponse)
def review_reimbursement_claim(
    id: uuid.UUID,
    data: ReimbursementReviewRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.manager)),
):
    service = ReimbursementService(db)
    claim = service.review_claim(user.company_id, id, data, user)
    return ReimbursementResponse.model_validate(claim)


