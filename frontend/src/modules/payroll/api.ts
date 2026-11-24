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
  /** The row's edition. Sent back on save so a stale page cannot overwrite a
   * newer edit; see SalaryStructureUpdateInput.version. */
  version: number;
  component_count: number;
  created_at: string;
  updated_at: string;
  created_by_email: string | null;
  updated_by_email: string | null;
}

export interface SalaryStructure {
  id: string;
  name: string;
  country: string;
  level: string | null;
  is_active: boolean;
  version: number;
  components: SalaryComponent[];
  created_at: string;
  updated_at: string;
  created_by_email: string | null;
  updated_by_email: string | null;
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
  revision_reason?: string | null;
  hourly_rate?: string | null;
}

export interface EmployeeSalaryResponse {
  id: string;
  employee_id: string;
  structure_id: string;
  ctc: string;
  hourly_rate?: string | null;
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
  payout_bank_name?: string | null;
  payout_account_number?: string | null;
  payout_ifsc_code?: string | null;
  payout_enabled?: boolean;
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
  error_message?: string | null;
  is_attendance_unlocked?: boolean;
  attendance_unlocked_at?: string | null;
  attendance_unlocked_by?: string | null;
  attendance_unlock_reason?: string | null;
  created_at: string;
}

export interface PayrollItemLine {
  code: string;
  name: string;
  amount: string;
  project_id?: string;
  project_name?: string;
  hours?: string;
  rate?: string;
  is_fallback?: boolean;
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
  created_at?: string;
  updated_at?: string;
}

export interface PayrollRunDetail {
  run: PayrollRun;
  items: PayrollItem[];
}

export type ReimbursementType = "travel" | "food" | "medical" | "telephone" | "other";
export type ReimbursementStatus = "pending" | "approved" | "rejected" | "paid" | "withdrawn";

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

export async function listStructures(page = 1, limit = 20, company_id?: string): Promise<Page<SalaryStructureListItem>> {
  const res = await apiClient.get<Page<SalaryStructureListItem>>("/payroll/structures", {
    params: { page, limit, company_id: company_id || undefined },
  });
  return res.data;
}

export async function createStructure(data: SalaryStructureCreateInput): Promise<SalaryStructure> {
  const res = await apiClient.post<SalaryStructure>("/payroll/structures", data);
  return res.data;
}

export interface SalaryStructureUpdateInput {
  name?: string;
  level?: string | null;
  is_active?: boolean;
  components?: SalaryComponentInput[];
  /** The edition this edit started from. The API refuses the save with a 409
   * if the structure has been changed by someone else since. */
  version?: number;
}

/** PUT /payroll/structures/{id} — components are replaced whole, never patched. */
export async function updateStructure(
  id: string,
  data: SalaryStructureUpdateInput
): Promise<SalaryStructure> {
  const res = await apiClient.put<SalaryStructure>(`/payroll/structures/${id}`, data);
  return res.data;
}

/** DELETE /payroll/structures/{id} — the server refuses (409) while employees use it. */
export async function deleteStructure(id: string): Promise<void> {
  await apiClient.delete(`/payroll/structures/${id}`);
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

// ── Global Statutory Rates & Compliance (Platform Super Admin API) ─────────────
export interface StatutoryRate {
  id: string;
  country: string;
  scheme: "epf" | "esi";
  employee_rate: string;
  employer_rate: string;
  wage_ceiling: string;
  employer_epf_rate: string | null;
  employer_eps_rate: string | null;
  edli_rate: string | null;
  admin_charge_rate: string | null;
  employee_exempt_daily_wage: string | null;
  effective_from: string;
  effective_to: string | null;
  source_url: string;
  source_title: string;
  source_note: string | null;
  verified_on: string;
  created_at?: string;
}

export interface StatutoryRateCreateInput {
  country: string;
  scheme: "epf" | "esi";
  employee_rate: number | string;
  employer_rate: number | string;
  wage_ceiling: number | string;
  employer_epf_rate?: number | string | null;
  employer_eps_rate?: number | string | null;
  edli_rate?: number | string | null;
  admin_charge_rate?: number | string | null;
  employee_exempt_daily_wage?: number | string | null;
  effective_from: string;
  source_url: string;
  source_title: string;
  verified_on: string;
  source_note?: string | null;
}

export async function listStatutoryRates(params?: {
  country?: string;
  scheme?: "epf" | "esi";
  on_date?: string;
  page?: number;
  limit?: number;
}): Promise<Page<StatutoryRate>> {
  const res = await apiClient.get<Page<StatutoryRate>>("/payroll/statutory-rates", {
    params: {
      country: params?.country || undefined,
      scheme: params?.scheme || undefined,
      on_date: params?.on_date || undefined,
      page: params?.page ?? 1,
      limit: params?.limit ?? 50,
    },
  });
  return res.data;
}

export async function createStatutoryRate(data: StatutoryRateCreateInput): Promise<StatutoryRate> {
  const res = await apiClient.post<StatutoryRate>("/payroll/statutory-rates", data);
  return res.data;
}

export interface RegionStateItem {
  code: string;
  name: string;
  states: string[];
}

export async function listSupportedRegions(): Promise<RegionStateItem[]> {
  const res = await apiClient.get<RegionStateItem[]>("/regions");
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

/** GET /payroll/runs/{id}/payment-file — the bank advice for an approved run.
 * A refusal (409 for a run that is not approved) comes back as a Blob; it is read
 * back into JSON so parseApiError can show the server's own message. */
export async function downloadPaymentFile(runId: string): Promise<void> {
  try {
    const response = await apiClient.get<Blob>(`/payroll/runs/${runId}/payment-file`, {
      params: { format: "csv" },
      responseType: "blob",
    });
    const disposition = String(response.headers?.["content-disposition"] ?? "");
    const match = /filename="([^"]+)"/.exec(disposition);
    const url = window.URL.createObjectURL(response.data);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", match?.[1] ?? `bank_advice_${runId}.csv`);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    const resp = (err as { response?: { data?: unknown } }).response;
    if (resp && resp.data instanceof Blob) {
      try {
        resp.data = JSON.parse(await resp.data.text());
      } catch {
        // keep the original error
      }
    }
    throw err;
  }
}

/** Opens a claim's receipt. The API serves it as an attachment, so the blob is
 * saved under the file name the server sends. */
export async function downloadReimbursementReceipt(claimId: string): Promise<void> {
  try {
    const response = await apiClient.get<Blob>(`/payroll/reimbursements/${claimId}/receipt`, {
      responseType: "blob",
    });
    const disposition = String(response.headers?.["content-disposition"] ?? "");
    const match = /filename="([^"]+)"/.exec(disposition);
    const url = window.URL.createObjectURL(response.data);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", match?.[1] ?? `receipt_${claimId}`);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    const resp = (err as { response?: { data?: unknown } }).response;
    if (resp && resp.data instanceof Blob) {
      try {
        resp.data = JSON.parse(await resp.data.text());
      } catch {
        // keep the original error
      }
    }
    throw err;
  }
}

export async function approvePayrollRun(id: string): Promise<PayrollRun> {
  const res = await apiClient.post<PayrollRun>(`/payroll/runs/${id}/approve`);
  return res.data;
}

export async function deletePayrollRun(id: string): Promise<void> {
  await apiClient.delete(`/payroll/runs/${id}`);
}

export async function unlockPayrollRunAttendance(
  id: string,
  reason: string
): Promise<PayrollRun> {
  const res = await apiClient.post<PayrollRun>(`/payroll/runs/${id}/unlock-attendance`, {
    unlocked: true,
    reason,
  });
  return res.data;
}

export async function relockPayrollRunAttendance(
  id: string,
  reason: string
): Promise<PayrollRun> {
  const res = await apiClient.post<PayrollRun>(`/payroll/runs/${id}/lock-attendance`, {
    unlocked: false,
    reason,
  });
  return res.data;
}

export interface SendPayslipsRecipientResult {
  employee_id: string;
  status: "queued" | "skipped";
  reason: string | null;
}

export interface SendPayslipsResponse {
  run_id: string;
  delivery: "console" | "queued";
  total_selected: number;
  queued_count: number;
  skipped_count: number;
  recipients: SendPayslipsRecipientResult[];
}

export async function sendPayrollRunPayslips(
  id: string,
  employeeIds: string[] = []
): Promise<SendPayslipsResponse> {
  const res = await apiClient.post<SendPayslipsResponse>(`/payroll/runs/${id}/send-payslips`, {
    employee_ids: employeeIds,
  });
  return res.data;
}



// 4. Payslips & Reimbursements
export async function listMyPayslips(): Promise<PayrollItem[]> {
  const res = await apiClient.get<PayrollItem[] | { items: PayrollItem[] }>("/payroll/payslips/me");
  if (Array.isArray(res.data)) {
    return res.data;
  }
  return (res.data as { items?: PayrollItem[] })?.items || [];
}

export async function listEmployeePayslips(employeeId: string): Promise<PayrollItem[]> {
  const res = await apiClient.get<PayrollItem[] | { items: PayrollItem[] }>(`/payroll/payslips/${employeeId}`);
  if (Array.isArray(res.data)) {
    return res.data;
  }
  return (res.data as { items?: PayrollItem[] })?.items || [];
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
    params: { status, page, limit },
  });
  return res.data;
}

/** POST /payroll/reimbursements/{id}/withdraw — the claimant withdraws a pending claim. */
export async function withdrawReimbursement(id: string): Promise<Reimbursement> {
  const res = await apiClient.post<Reimbursement>(`/payroll/reimbursements/${id}/withdraw`);
  return res.data;
}

export async function reviewReimbursement(
  id: string,
  data: ReimbursementReviewInput
): Promise<Reimbursement> {
  const res = await apiClient.put<Reimbursement>(`/payroll/reimbursements/${id}`, data);
  return res.data;
}

export interface SalaryHistoryItem {
  id: string;
  structure_id: string;
  structure_name: string;
  ctc: string;
  effective_from: string;
  effective_to?: string | null;
  revision_reason?: string | null;
  created_at: string;
}

export async function getEmployeeSalaryHistory(
  employeeId: string,
  params?: { page?: number; limit?: number; from_date?: string; to_date?: string }
): Promise<Page<SalaryHistoryItem>> {
  const res = await apiClient.get<Page<SalaryHistoryItem>>(`/payroll/employees/${employeeId}/salary-history`, {
    params,
  });
  return res.data;
}

export interface BankAccountRequest {
  account_holder: string;
  bank_name: string;
  account_number: string;
  ifsc_code: string;
}

export interface BankAccountResponse {
  employee_id: string;
  account_holder: string;
  bank_name: string;
  account_number: string;
  ifsc_code: string;
  updated_at: string;
}

export async function getMyBankAccount(): Promise<BankAccountResponse> {
  const res = await apiClient.get<BankAccountResponse>("/payroll/bank-account/me");
  return res.data;
}

export async function saveMyBankAccount(data: BankAccountRequest): Promise<BankAccountResponse> {
  const res = await apiClient.put<BankAccountResponse>("/payroll/bank-account/me", data);
  return res.data;
}

export async function getEmployeeBankAccount(employeeId: string): Promise<BankAccountResponse> {
  const res = await apiClient.get<BankAccountResponse>(`/payroll/employees/${employeeId}/bank-account`);
  return res.data;
}

export async function saveEmployeeBankAccount(
  employeeId: string,
  data: BankAccountRequest
): Promise<BankAccountResponse> {
  const res = await apiClient.put<BankAccountResponse>(`/payroll/employees/${employeeId}/bank-account`, data);
  return res.data;
}

export interface PayrollPaymentRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  employee_code: string;
  amount: string;
  status: string;
  bank_reference?: string | null;
  paid_on?: string | null;
}

export async function getPayrollRunPayments(runId: string): Promise<PayrollPaymentRecord[]> {
  const res = await apiClient.get<PayrollPaymentRecord[]>(`/payroll/runs/${runId}/payments`);
  return res.data;
}
