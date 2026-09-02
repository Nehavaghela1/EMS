import { apiClient } from "../../app/api-client";
import type { Page } from "../../shared/api/pagination";

// --- Attendance (routes 43-49) --------------------------------------------

export type AttendanceStatus = "present" | "absent" | "half_day" | "wfh" | "on_leave" | "holiday" | "weekend";

export interface Attendance {
  id: string;
  employee_id: string;
  date: string;
  check_in: string | null;
  check_out: string | null;
  status: AttendanceStatus;
  hours_worked: string | null;
  source: string;
  notes: string | null;
  created_at: string;
}

export async function checkIn(): Promise<Attendance> {
  const { data } = await apiClient.post<Attendance>("/attendance/check-in");
  return data;
}

export async function checkOut(): Promise<Attendance> {
  const { data } = await apiClient.post<Attendance>("/attendance/check-out");
  return data;
}

export interface ListAttendanceParams {
  employee_id?: string;
  date_from?: string;
  date_to?: string;
  page: number;
  limit: number;
}

export async function listAttendance(params: ListAttendanceParams): Promise<Page<Attendance>> {
  const { data } = await apiClient.get<Page<Attendance>>("/attendance", { params });
  return data;
}

export interface RegularizeAttendanceInput {
  status?: AttendanceStatus;
  notes?: string;
  reason: string;
}

export async function regularizeAttendance(id: string, input: RegularizeAttendanceInput): Promise<Attendance> {
  const { data } = await apiClient.put<Attendance>(`/attendance/${id}`, input);
  return data;
}

// --- Shifts (routes 50-54) -------------------------------------------------

export interface Shift {
  id: string;
  name: string;
  start_time: string;
  end_time: string;
  break_minutes: number;
  night_allowance: string;
  is_active: boolean;
  created_at: string;
}

export interface ShiftInput {
  name: string;
  start_time: string;
  end_time: string;
  break_minutes?: number;
  night_allowance?: string;
}

export async function listShifts(page: number, limit: number): Promise<Page<Shift>> {
  const { data } = await apiClient.get<Page<Shift>>("/shifts", { params: { page, limit } });
  return data;
}

export async function createShift(input: ShiftInput): Promise<Shift> {
  const { data } = await apiClient.post<Shift>("/shifts", input);
  return data;
}

export async function updateShift(id: string, input: Partial<ShiftInput & { is_active: boolean }>): Promise<Shift> {
  const { data } = await apiClient.put<Shift>(`/shifts/${id}`, input);
  return data;
}

export async function deleteShift(id: string): Promise<void> {
  await apiClient.delete(`/shifts/${id}`);
}

export interface AssignShiftInput {
  employee_id: string;
  effective_from: string;
  effective_to?: string;
}

export interface EmployeeShift {
  id: string;
  employee_id: string;
  shift_id: string;
  effective_from: string;
  effective_to: string | null;
}

export async function assignShift(shiftId: string, input: AssignShiftInput): Promise<EmployeeShift> {
  const { data } = await apiClient.post<EmployeeShift>(`/shifts/${shiftId}/assign`, input);
  return data;
}

// --- Leave types (read-only here — routes 58-60 are page 26's job) --------

export interface LeaveType {
  id: string;
  name: string;
  code: string;
  annual_allowance: string;
  carry_forward_limit: string;
  max_consecutive_days: number | null;
  requires_approval: boolean;
  is_paid: boolean;
  is_encashable: boolean;
  is_active: boolean;
}

export async function listLeaveTypes(): Promise<LeaveType[]> {
  const { data } = await apiClient.get<LeaveType[]>("/leave-types");
  return data;
}

// --- Leaves (routes 61-66) -------------------------------------------------

export type LeaveStatus = "pending" | "approved" | "rejected" | "cancelled";

export interface Leave {
  id: string;
  employee_id: string;
  leave_type_id: string;
  start_date: string;
  end_date: string;
  total_days: string;
  is_half_day: boolean;
  reason: string;
  status: LeaveStatus;
  approved_by: string | null;
  approved_at: string | null;
  rejection_reason: string | null;
  created_at: string;
}

export interface ListLeavesParams {
  status?: LeaveStatus;
  page: number;
  limit: number;
}

export async function listLeaves(params: ListLeavesParams): Promise<Page<Leave>> {
  const { data } = await apiClient.get<Page<Leave>>("/leaves", { params });
  return data;
}

export interface ApplyLeaveInput {
  employee_id?: string;
  leave_type_id: string;
  start_date: string;
  end_date: string;
  is_half_day?: boolean;
  reason: string;
}

export async function applyLeave(input: ApplyLeaveInput): Promise<Leave> {
  const { data } = await apiClient.post<Leave>("/leaves", input);
  return data;
}

export async function decideLeave(
  id: string,
  status: "approved" | "rejected",
  rejectionReason?: string,
): Promise<Leave> {
  const { data } = await apiClient.put<Leave>(`/leaves/${id}`, {
    status,
    rejection_reason: rejectionReason,
  });
  return data;
}

export async function cancelLeave(id: string): Promise<Leave> {
  const { data } = await apiClient.delete<Leave>(`/leaves/${id}`);
  return data;
}

export interface LeaveBalance {
  leave_type_id: string;
  leave_type_name: string;
  year: number;
  opening_balance: string;
  allocated: string;
  used: string;
  encashed: string;
  available: string;
}

export async function getLeaveBalance(employeeId: string, year: number): Promise<LeaveBalance[]> {
  const { data } = await apiClient.get<LeaveBalance[]>(`/leaves/balance/${employeeId}`, { params: { year } });
  return data;
}
