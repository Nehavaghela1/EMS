import { apiClient } from "../../app/api-client";

/** Mirrors app/modules/platform/service.py's four `_*_data` methods
 * exactly (Spec 11.10) — one field set per role. Fields the backend
 * hardcodes to 0/None because the underlying table doesn't exist yet
 * (payroll, tasks) are deliberately NOT in these interfaces: a page that
 * rendered them would show "Pending reimbursements: 0" as if it were a
 * real count, not a forward dependency. */
export interface SuperAdminDashboardData {
  company_counts_by_status: Record<string, number>;
  pending_approvals: number;
  platform_user_count: number;
}

export interface HrAdminDashboardData {
  headcount: number;
  present_today: number;
  on_leave_today: number;
  pending_leave_requests: number;
  recent_hires: { id: string; first_name: string; last_name: string | null; hire_date: string }[];
  department_distribution: Record<string, number>;
}

export interface ManagerDashboardData {
  team_headcount: number;
  team_present_today: number;
  team_leave_requests_awaiting: number;
}

export interface EmployeeDashboardData {
  attendance_this_month: Record<string, number>;
  leave_balances: { leave_type_id: string; leave_type_name: string | null; available: string }[];
  pending_requests: number;
}

export type DashboardResponse =
  | { role: "super_admin"; generated_at: string; data: SuperAdminDashboardData }
  | { role: "hr_admin"; generated_at: string; data: HrAdminDashboardData }
  | { role: "manager"; generated_at: string; data: ManagerDashboardData }
  | { role: "employee"; generated_at: string; data: EmployeeDashboardData };

export async function fetchDashboard(): Promise<DashboardResponse> {
  const { data } = await apiClient.get<DashboardResponse>("/dashboard");
  return data;
}

export interface Announcement {
  id: string;
  company_id: string;
  title: string;
  content: string;
  target_role: string;
  created_by?: string;
  expires_at?: string;
  created_at: string;
}

export async function fetchAnnouncements(): Promise<Announcement[]> {
  const { data } = await apiClient.get<Announcement[]>("/announcements");
  return data;
}

export async function createAnnouncement(payload: { title: string; content: string; target_role?: string; expires_at?: string }): Promise<Announcement> {
  const { data } = await apiClient.post<Announcement>("/announcements", payload);
  return data;
}

export async function deleteAnnouncement(id: string): Promise<void> {
  await apiClient.delete(`/announcements/${id}`);
}

export interface SearchResultItem {
  id: string;
  type: "employee" | "project" | "task";
  title: string;
  subtitle?: string;
  url: string;
}

export interface GlobalSearchResponse {
  query: string;
  total_results: number;
  results: SearchResultItem[];
}

export async function globalSearch(q: string): Promise<GlobalSearchResponse> {
  const { data } = await apiClient.get<GlobalSearchResponse>("/search", { params: { q } });
  return data;
}

export interface EmployeeDocument {
  id: string;
  company_id: string;
  employee_id: string;
  file_object_id: string;
  document_type: string;
  name: string;
  created_at: string;
  download_url?: string;
}

export async function fetchEmployeeDocuments(employeeId: string): Promise<EmployeeDocument[]> {
  const { data } = await apiClient.get<EmployeeDocument[]>(`/documents/${employeeId}`);
  return data;
}

export async function uploadFile(file: File): Promise<{ file_object_id: string; file_name: string; file_type: string; file_size: number }> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post("/files/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function attachEmployeeDocument(payload: { employee_id: string; file_object_id: string; document_type: string; name: string }): Promise<EmployeeDocument> {
  const { data } = await apiClient.post<EmployeeDocument>("/documents", payload);
  return data;
}
