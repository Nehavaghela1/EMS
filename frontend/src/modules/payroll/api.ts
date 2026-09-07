import { apiClient } from "../../app/api-client";
import type { Page } from "../../shared/api/pagination";

export type ComponentType = "earning" | "deduction";
export type CalculationType = "fixed" | "percentage" | "balance";
export type PercentageOf = "ctc" | "basic";

export interface SalaryComponentInput {
  code: string;
  name: string;
  type: ComponentType;
  calculation_type: CalculationType;
  value?: string | null;
  percentage_of?: PercentageOf | null;
  is_taxable?: boolean;
  is_statutory?: boolean;
  display_order?: number;
}

export interface SalaryComponent extends SalaryComponentInput {
  id: string;
  structure_id: string;
  value: string | null;
  percentage_of: PercentageOf | null;
  is_taxable: boolean;
  is_statutory: boolean;
  display_order: number;
}

export interface SalaryStructureListItem {
  id: string;
  name: string;
  country: string;
  level: string | null;
  is_active: boolean;
  component_count: number;
  created_at: string;
}

export interface SalaryStructure {
  id: string;
  name: string;
  country: string;
  level: string | null;
  is_active: boolean;
  components: SalaryComponent[];
  created_at: string;
}

export interface SalaryStructureCreateInput {
  name: string;
  country?: string;
  level?: string | null;
  components: SalaryComponentInput[];
}

export interface SalaryAssignInput {
  structure_id: string;
  ctc: string;
  effective_from: string;
}

export interface EmployeeSalaryResponse {
  id: string;
  employee_id: string;
  structure_id: string;
  ctc: string;
  effective_from: string;
  created_at: string;
}

export interface StatutoryConfig {
  pf_enabled: boolean;
  pf_employee_rate: string;
  pf_employer_rate: string;
  pf_wage_ceiling: string;
  pf_restrict_to_ceiling: boolean;
  esi_enabled: boolean;
  esi_employee_rate: string;
  esi_employer_rate: string;
  esi_wage_ceiling: string;
  pt_enabled: boolean;
  pt_state: string;
  lwf_enabled: boolean;
  lwf_employee_amount: string;
  lwf_months: number[];
  tds_enabled: boolean;
  default_tax_regime: string;
}

export interface PtSlab {
  id: string;
  state: string;
  income_min: string;
  income_max: string | null;
  monthly_amount: string;
  special_month: number | null;
  special_month_amount: string | null;
  source_note: string | null;
}

export interface TaxSlab {
  id: string;
  country: string;
  financial_year: string;
  regime: string;
  min_income: string;
  max_income: string | null;
  rate_percent: string;
  cess_percent: string;
  surcharge_rules: Record<string, unknown> | null;
  source_note: string | null;
}

export interface PayrollRun {
  id: string;
  company_id: string;
  month: number;
  year: number;
  status: string;
  run_type: string;
  idempotency_key: string;
  total_employees: number | null;
  total_gross: string | null;
  total_deductions: string | null;
  total_net: string | null;
  total_employer_cost: string | null;
  approved_by: string | null;
  approved_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface PayrollItemLine {
  code: string;
  name: string;
  amount: string;
}

export interface PayrollItem {
  id: string;
  payroll_run_id: string;
  employee_id: string;
  ctc_snapshot: string;
  gross_salary: string;
  total_deductions: string;
  net_salary: string;
  employer_cost: string;
  earnings_json: PayrollItemLine[];
  deductions_json: PayrollItemLine[];
  employer_contributions_json: PayrollItemLine[];
  working_days: string;
  present_days: string;
  absent_days: string;
  half_days: string;
  paid_leave_days: string;
  lop_days: string;
  reimbursement_amount: string;
}

export interface PayrollRunDetail {
  run: PayrollRun;
  items: PayrollItem[];
}

export type ReimbursementType = "travel" | "food" | "medical" | "telephone" | "other";
export type ReimbursementStatus = "pending" | "approved" | "rejected" | "paid";

export interface Reimbursement {
  id: string;
  employee_id: string;
  type: ReimbursementType;
  amount: string;
  expense_date: string;
  description: string;
  file_object_id: string | null;
  status: ReimbursementStatus;
  approved_by: string | null;
  approved_at: string | null;
  rejection_reason: string | null;
  added_to_payroll_run_id: string | null;
  created_at: string;
}

export interface ReimbursementCreateInput {
  type: ReimbursementType;
  amount: string;
  expense_date: string;
  description: string;
  file_object_id?: string | null;
}

export interface ReimbursementReviewInput {
  action: "approve" | "reject";
  rejection_reason?: string | null;
}

// API Functions

// 1. Structures
export async function listStructures(page = 1, limit = 20): Promise<Page<SalaryStructureListItem>> {
  const res = await apiClient.get<Page<SalaryStructureListItem>>("/payroll/structures", {
    params: { page, limit },
  });
  return res.data;
}

export async function createStructure(data: SalaryStructureCreateInput): Promise<SalaryStructure> {
  const res = await apiClient.post<SalaryStructure>("/payroll/structures", data);
  return res.data;
}

export async function getStructure(id: string): Promise<SalaryStructure> {
  const res = await apiClient.get<SalaryStructure>(`/payroll/structures/${id}`);
  return res.data;
}

export async function assignEmployeeSalary(
  employeeId: string,
  data: SalaryAssignInput
): Promise<EmployeeSalaryResponse> {
  const res = await apiClient.post<EmployeeSalaryResponse>(
    `/payroll/employees/${employeeId}/assign`,
    data
  );
  return res.data;
}

// 2. Statutory Config & Slabs
export async function getStatutoryConfig(): Promise<StatutoryConfig> {
  const res = await apiClient.get<StatutoryConfig>("/payroll/statutory-config");
  return res.data;
}

export async function updateStatutoryConfig(
  data: Partial<StatutoryConfig>
): Promise<StatutoryConfig> {
  const res = await apiClient.put<StatutoryConfig>("/payroll/statutory-config", data);
  return res.data;
}

export async function listPtSlabs(state = "Gujarat"): Promise<PtSlab[]> {
  const res = await apiClient.get<PtSlab[]>("/payroll/pt-slabs", { params: { state } });
  return res.data;
}

export async function listTaxSlabs(
  country = "IN",
  financial_year = "2026-2027",
  regime = "new"
): Promise<TaxSlab[]> {
  const res = await apiClient.get<TaxSlab[]>("/payroll/tax-slabs", {
    params: { country, financial_year, regime },
  });
  return res.data;
}

// 3. Payroll Runs
export async function createPayrollRun(
  month: number,
  year: number,
  run_type = "regular",
  employee_ids?: string[]
): Promise<PayrollRun> {
  // Generate random client-side Idempotency-Key
  const idempotencyKey = `run-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
  const res = await apiClient.post<PayrollRun>(
    "/payroll/runs",
    { month, year, run_type, employee_ids },
    { headers: { "Idempotency-Key": idempotencyKey } }
  );
  return res.data;
}

export async function listPayrollRuns(status?: string, page = 1, limit = 20): Promise<Page<PayrollRun>> {
  const res = await apiClient.get<Page<PayrollRun>>("/payroll/runs", {
    params: { status_filter: status, page, limit },
  });
  return res.data;
}

export async function getPayrollRunDetail(id: string): Promise<PayrollRunDetail> {
  const res = await apiClient.get<PayrollRunDetail>(`/payroll/runs/${id}`);
  return res.data;
}

export async function approvePayrollRun(id: string): Promise<PayrollRun> {
  const res = await apiClient.post<PayrollRun>(`/payroll/runs/${id}/approve`);
  return res.data;
}

// 4. Payslips & Reimbursements
export async function listMyPayslips(): Promise<PayrollItem[]> {
  const res = await apiClient.get<PayrollItem[]>("/payroll/payslips/me");
  return res.data;
}

export async function listEmployeePayslips(employeeId: string): Promise<PayrollItem[]> {
  const res = await apiClient.get<PayrollItem[]>(`/payroll/payslips/${employeeId}`);
  return res.data;
}

export async function submitReimbursement(
  data: ReimbursementCreateInput
): Promise<Reimbursement> {
  const res = await apiClient.post<Reimbursement>("/payroll/reimbursements", data);
  return res.data;
}

export async function listReimbursements(
  status?: ReimbursementStatus,
  page = 1,
  limit = 20
): Promise<Page<Reimbursement>> {
  const res = await apiClient.get<Page<Reimbursement>>("/payroll/reimbursements", {
    params: { status_filter: status, page, limit },
  });
  return res.data;
}

export async function reviewReimbursement(
  id: string,
  data: ReimbursementReviewInput
): Promise<Reimbursement> {
  const res = await apiClient.put<Reimbursement>(`/payroll/reimbursements/${id}`, data);
  return res.data;
}
