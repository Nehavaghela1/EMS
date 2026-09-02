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
  notice_period_days: number;
  is_active: boolean;
  invitation_status: InvitationStatus;
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
}

export type EmployeeUpdateInput = Partial<EmployeeCreateInput>;

export interface EmployeeCreateResponse extends Employee {
  invite: { sent_to: string; expires_at: string };
}

export interface ListEmployeesParams {
  q?: string;
  department_id?: string;
  is_active?: boolean;
  sort?: string;
  page: number;
  limit: number;
}

export async function listEmployees(params: ListEmployeesParams): Promise<Page<Employee>> {
  const { data } = await apiClient.get<Page<Employee>>("/employees", { params });
  return data;
}

export async function getEmployee(id: string): Promise<Employee> {
  const { data } = await apiClient.get<Employee>(`/employees/${id}`);
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

export async function getMyEmployee(): Promise<Employee> {
  const { data } = await apiClient.get<Employee>("/employees/me");
  return data;
}

export interface ListDepartmentsParams {
  q?: string;
  sort?: string;
  page: number;
  limit: number;
}

export async function listDepartments(params: ListDepartmentsParams): Promise<Page<Department>> {
  const { data } = await apiClient.get<Page<Department>>("/departments", { params });
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
