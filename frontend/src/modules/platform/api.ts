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
