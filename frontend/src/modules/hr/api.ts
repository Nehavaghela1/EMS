import { apiClient } from "../../app/api-client";
import type { Page } from "../../shared/api/pagination";

export type EmploymentType = "full_time" | "part_time" | "contract" | "intern";
export type InvitationStatus = "not_sent" | "sent" | "activated" | "expired";

export interface Department {
  id: string;
  name: string;
  description: string | null;
  head_employee_id: string | null;
  employee_count: number;
  created_at: string;
}

export interface DepartmentCreateInput {
  name: string;
  description?: string | null;
}

export interface DepartmentUpdateInput {
  name?: string;
  description?: string | null;
  head_employee_id?: string | null;
}

export interface Employee {
  id: string;
  user_id: string | null;
  employee_code: string;
  first_name: string;
  last_name: string | null;
  email: string;
  personal_email: string | null;
  phone: string | null;
  department_id: string | null;
  position: string | null;
  level: string | null;
  reporting_manager_id: string | null;
  employment_type: EmploymentType;
  hire_date: string;
  probation_end_date: string | null;
  notice_period_days?: number;
  is_active: boolean;
  invitation_status: InvitationStatus;
  resignation_status?: string;
  resignation_date?: string | null;
  last_working_date?: string | null;
  notice_waived?: boolean;
  notice_recovery_days?: number;
  separation_type?: string | null;
  termination_reason?: string | null;
  severance_pay?: number | string | null;
  pending_reimbursements?: number | string | null;
  gratuity_bonus?: number | string | null;
  asset_deductions?: number | string | null;
  it_clearance?: boolean;
  hr_clearance?: boolean;
  finance_clearance?: boolean;
  fnf_settled_at?: string | null;
  company_id?: string | null;
  company_name?: string | null;
  created_at: string;
}

export interface EmployeeCreateInput {
  first_name: string;
  last_name?: string | null;
  email: string;
  personal_email?: string | null;
  phone?: string | null;
  department_id?: string | null;
  position?: string | null;
  level?: string | null;
  reporting_manager_id?: string | null;
  employment_type?: EmploymentType;
  hire_date: string;
  probation_end_date?: string | null;
  notice_period_days?: number;
  company_id?: string | null;
}

export interface EmployeeUpdateInput {
  last_name?: string | null;
  personal_email?: string | null;
  phone?: string | null;
  department_id?: string | null;
  position?: string | null;
  level?: string | null;
  reporting_manager_id?: string | null;
  employment_type?: EmploymentType;
  probation_end_date?: string | null;
  notice_period_days?: number;
}

export interface EmployeeCreateResponse extends Employee {
  invite: { sent_to: string; expires_at: string };
}

export interface ListEmployeesParams {
  q?: string;
  department_id?: string;
  company_id?: string;
  is_active?: boolean;
  level?: string;
  employment_type?: string;
  reporting_manager_id?: string;
  sort?: string;
  page?: number;
  limit?: number;
}

export async function listEmployees(params: ListEmployeesParams = {}): Promise<Page<Employee>> {
  const { data } = await apiClient.get<Page<Employee>>("/employees", { params });
  return data;
}

export async function getEmployee(id: string): Promise<Employee> {
  const { data } = await apiClient.get<Employee>(`/employees/${id}`);
  return data;
}

export async function getMyEmployee(): Promise<Employee> {
  const { data } = await apiClient.get<Employee>("/employees/me");
  return data;
}

export async function createEmployee(input: EmployeeCreateInput): Promise<EmployeeCreateResponse> {
  const { data } = await apiClient.post<EmployeeCreateResponse>("/employees", input);
  return data;
}

export async function updateEmployee(id: string, input: EmployeeUpdateInput): Promise<Employee> {
  const { data } = await apiClient.put<Employee>(`/employees/${id}`, input);
  return data;
}

export async function toggleActiveEmployee(id: string): Promise<Employee> {
  const { data } = await apiClient.post<Employee>(`/employees/${id}/toggle-active`);
  return data;
}

export async function deactivateEmployee(id: string): Promise<void> {
  await apiClient.delete(`/employees/${id}`);
}

export async function reactivateEmployee(id: string): Promise<Employee> {
  const { data } = await apiClient.post<Employee>(`/employees/${id}/toggle-active`);
  return data;
}

export async function resendInvite(id: string): Promise<EmployeeCreateResponse> {
  const { data } = await apiClient.post<EmployeeCreateResponse>(`/employees/${id}/resend-invite`);
  return data;
}

export interface ListDepartmentsParams {
  page?: number;
  limit?: number;
}

export async function listDepartments(params: ListDepartmentsParams = {}): Promise<Page<Department>> {
  const { data } = await apiClient.get<Page<Department>>("/departments", { params });
  return data;
}

export async function getDepartment(id: string): Promise<Department> {
  const { data } = await apiClient.get<Department>(`/departments/${id}`);
  return data;
}

export async function createDepartment(input: DepartmentCreateInput): Promise<Department> {
  const { data } = await apiClient.post<Department>("/departments", input);
  return data;
}

export async function updateDepartment(id: string, input: DepartmentUpdateInput): Promise<Department> {
  const { data } = await apiClient.put<Department>(`/departments/${id}`, input);
  return data;
}

export async function deleteDepartment(id: string): Promise<void> {
  await apiClient.delete(`/departments/${id}`);
}

export interface ResignationSubmitInput {
  resignation_date?: string;
  last_working_date?: string;
  reason?: string;
}

export interface ResignationApproveInput {
  approved: boolean;
  last_working_date?: string;
  notice_waived?: boolean;
  notice_recovery_days?: number;
}

export interface TerminationInput {
  termination_date: string;
  reason: string;
  severance_pay?: number;
  notice_pay_in_lieu?: number;
  notes?: string;
}

export interface FnFClearanceInput {
  it_clearance?: boolean;
  hr_clearance?: boolean;
  finance_clearance?: boolean;
  severance_pay?: number;
  pending_reimbursements?: number;
  gratuity_bonus?: number;
  asset_deductions?: number;
  mark_settled?: boolean;
}

export interface FnFSettlement {
  employee_id: string;
  employee_name: string;
  last_working_date: string;
  separation_type?: string | null;
  termination_reason?: string | null;
  notice_days_required: number;
  notice_days_served: number;
  notice_waived: boolean;
  notice_recovery_days: number;
  notice_recovery_amount: string | number;
  encashable_leave_days: string | number;
  leave_encashment_amount: string | number;
  unpaid_salary_days: number;
  unpaid_salary_amount: string | number;
  severance_pay: string | number;
  pending_reimbursements: string | number;
  gratuity_bonus: string | number;
  asset_deductions: string | number;
  it_clearance: boolean;
  hr_clearance: boolean;
  finance_clearance: boolean;
  can_release_settlement: boolean;
  fnf_settled_at: string | null;
  total_settlement_amount: string | number;
}

export async function submitResignation(employeeId: string, input: ResignationSubmitInput): Promise<Employee> {
  const { data } = await apiClient.post<Employee>(`/employees/${employeeId}/resignation`, input);
  return data;
}

export async function approveResignation(employeeId: string, input: ResignationApproveInput): Promise<Employee> {
  const { data } = await apiClient.put<Employee>(`/employees/${employeeId}/resignation/approve`, input);
  return data;
}

export async function terminateEmployee(employeeId: string, input: TerminationInput): Promise<Employee> {
  const { data } = await apiClient.post<Employee>(`/employees/${employeeId}/terminate`, input);
  return data;
}

export async function getFnFSettlement(employeeId: string): Promise<FnFSettlement> {
  const { data } = await apiClient.get<FnFSettlement>(`/employees/${employeeId}/fnf`);
  return data;
}

export async function updateFnFClearance(employeeId: string, input: FnFClearanceInput): Promise<FnFSettlement> {
  const { data } = await apiClient.put<FnFSettlement>(`/employees/${employeeId}/fnf/clearance`, input);
  return data;
}

export async function listResignations(): Promise<Employee[]> {
  const { data } = await apiClient.get<Employee[]>("/employees/resignations");
  return data;
}
