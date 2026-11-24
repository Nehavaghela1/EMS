import { apiClient } from "../../app/api-client";
import type { Page } from "../../shared/api/pagination";

export type CycleType = "annual" | "half_yearly" | "quarterly";
export type CycleStatus = "draft" | "active" | "closed";
export type GoalStatus = "draft" | "in_progress" | "completed";
// "peer" is reserved for future 360-degree peer review workflows; not currently implemented in endpoints or UI.
export type ReviewerRole = "self" | "manager" | "peer";

export interface PerformanceCycle {
  id: string;
  name: string;
  cycle_type: CycleType;
  start_date: string;
  end_date: string;
  status: CycleStatus;
  self_review_deadline: string | null;
  manager_review_deadline: string | null;
  created_at: string;
}

export interface PerformanceCycleCreateInput {
  name: string;
  cycle_type: CycleType;
  start_date: string;
  end_date: string;
  self_review_deadline?: string | null;
  manager_review_deadline?: string | null;
}

export interface GoalCreateItem {
  title: string;
  description?: string | null;
  weightage: string;
  target_value?: string | null;
}

export interface GoalsCreateInput {
  cycle_id: string;
  employee_id?: string;
  goals: GoalCreateItem[];
}

export interface PerformanceGoal {
  id: string;
  progress?: number;
  employee_id: string;
  cycle_id: string;
  title: string;
  description: string | null;
  weightage: string;
  target_value: string | null;
  status: GoalStatus;
  self_rating: string | null;
  self_comments: string | null;
  self_review_status?: "draft" | "submitted" | null;
  self_review_id?: string | null;
  created_at: string;
}

export interface SelfReviewInput {
  rating: string;
  comments?: string | null;
}

export interface ManagerReviewInput {
  rating: string;
  comments?: string | null;
}

export interface PerformanceReview {
  id: string;
  goal_id: string;
  reviewer_id: string;
  reviewer_role: ReviewerRole;
  rating: string;
  comments: string | null;
  submitted_at: string;
}

export interface PerformanceSummary {
  id: string;
  employee_id: string;
  employee_name?: string | null;
  employee_code?: string | null;
  cycle_id: string;
  final_rating: string;
  overall_comments: string | null;
  salary_revision_recommended: boolean;
  recommended_increment_percent: string | null;
  reviewed_by: string;
  reviewed_by_name?: string | null;
  finalized_at: string;
}

export interface ListSummariesParams {
  cycle_id: string;
  page?: number;
  limit?: number;
}

export async function listPerformanceSummaries(params: ListSummariesParams): Promise<Page<PerformanceSummary>> {
  const res = await apiClient.get<Page<PerformanceSummary>>("/performance/summaries", { params });
  return res.data;
}

export interface SummaryFinalizeInput {
  cycle_id: string;
  overall_comments?: string | null;
  salary_revision_recommended?: boolean;
  recommended_increment_percent?: string | null;
}

export interface PerformanceReport {
  active_cycle: PerformanceCycle | null;
  total_employees: number;
  completed_reviews: number;
  completion_rate_percent: string;
  rating_distribution: Record<string, number>;
}

// API Methods
export async function listPerformanceCycles(status?: string, page = 1, limit = 20): Promise<Page<PerformanceCycle>> {
  const res = await apiClient.get<Page<PerformanceCycle>>("/performance/cycles", {
    params: { status_filter: status, page, limit },
  });
  return res.data;
}

export async function createPerformanceCycle(data: PerformanceCycleCreateInput): Promise<PerformanceCycle> {
  const res = await apiClient.post<PerformanceCycle>("/performance/cycles", data);
  return res.data;
}

export interface PerformanceCycleUpdateInput {
  status?: CycleStatus | null;
  self_review_deadline?: string | null;
  manager_review_deadline?: string | null;
}

export async function updatePerformanceCycle(
  id: string,
  data: PerformanceCycleUpdateInput | CycleStatus
): Promise<PerformanceCycle> {
  const payload = typeof data === "string" ? { status: data } : data;
  const res = await apiClient.put<PerformanceCycle>(`/performance/cycles/${id}`, payload);
  return res.data;
}

export async function setPerformanceGoals(data: GoalsCreateInput): Promise<PerformanceGoal[]> {
  const res = await apiClient.post<PerformanceGoal[]>("/performance/goals", data);
  return res.data;
}

export async function listPerformanceGoals(employeeId: string): Promise<PerformanceGoal[]> {
  const res = await apiClient.get<PerformanceGoal[]>(`/performance/goals/${employeeId}`);
  return res.data;
}

export async function updatePerformanceGoal(
  id: string,
  data: Partial<GoalCreateItem & { status: GoalStatus; reason: string }>
): Promise<PerformanceGoal> {
  const res = await apiClient.put<PerformanceGoal>(`/performance/goals/${id}`, data);
  return res.data;
}

/** PUT /performance/goals/{id}/progress — 0 to 100; the server keeps the history. */
export async function updateGoalProgress(goalId: string, progress: number, notes?: string): Promise<PerformanceGoal> {
  const { data } = await apiClient.put<PerformanceGoal>(`/performance/goals/${goalId}/progress`, { progress, notes });
  return data;
}

export async function submitSelfReview(goalId: string, data: SelfReviewInput): Promise<PerformanceReview> {
  const res = await apiClient.post<PerformanceReview>(`/performance/goals/${goalId}/self-review`, data);
  return res.data;
}

export async function submitManagerReview(goalId: string, data: ManagerReviewInput): Promise<PerformanceReview> {
  const res = await apiClient.post<PerformanceReview>(`/performance/goals/${goalId}/manager-review`, data);
  return res.data;
}

export async function getPerformanceSummary(employeeId: string): Promise<PerformanceSummary | null> {
  const res = await apiClient.get<PerformanceSummary | null>(`/performance/summary/${employeeId}`);
  return res.data;
}

export async function finalizePerformanceSummary(
  employeeId: string,
  data: SummaryFinalizeInput
): Promise<PerformanceSummary> {
  const res = await apiClient.post<PerformanceSummary>(`/performance/summary/${employeeId}`, data);
  return res.data;
}

export async function getPerformanceReport(): Promise<PerformanceReport> {
  const res = await apiClient.get<PerformanceReport>("/performance/report");
  return res.data;
}

// --- PIP (Performance Improvement Plan) API ---
export interface PerformancePIP {
  id: string;
  employee_id: string;
  employee_name?: string | null;
  employee_code?: string | null;
  mentor_id?: string | null;
  mentor_name?: string | null;
  title: string;
  description?: string | null;
  milestones_kpis?: string | null;
  start_date: string;
  end_date: string;
  // Mirrors PIPStatus in app/modules/performance/models.py. "draft" and
  // "extended" were missing, so a draft plan fell through to the closed branch
  // and was shown as concluded.
  status: "draft" | "active" | "extended" | "passed" | "failed" | "cancelled";
  outcome_notes?: string | null;
  evaluated_at?: string | null;
  evaluated_by?: string | null;
  evaluated_by_name?: string | null;
  created_at: string;
}

export interface PIPCreateInput {
  employee_id: string;
  mentor_id?: string | null;
  title: string;
  description?: string | null;
  milestones_kpis?: string | null;
  start_date: string;
  end_date: string;
}

export interface PIPEvaluateInput {
  outcome: "passed" | "failed" | "cancelled";
  outcome_notes?: string | null;
}

export async function listPIPs(params?: { employee_id?: string; status?: string }): Promise<PerformancePIP[]> {
  const res = await apiClient.get<PerformancePIP[]>("/performance/pips", { params });
  return res.data;
}

export async function getActivePIP(employeeId: string): Promise<PerformancePIP | null> {
  const res = await apiClient.get<PerformancePIP | null>(`/performance/pips/active/${employeeId}`);
  return res.data;
}

export async function initiatePIP(data: PIPCreateInput): Promise<PerformancePIP> {
  const res = await apiClient.post<PerformancePIP>("/performance/pips", data);
  return res.data;
}

export async function activatePIP(pipId: string): Promise<PerformancePIP> {
  const res = await apiClient.post<PerformancePIP>(`/performance/pips/${pipId}/activate`);
  return res.data;
}

export async function evaluatePIP(pipId: string, data: PIPEvaluateInput): Promise<PerformancePIP> {
  const res = await apiClient.post<PerformancePIP>(`/performance/pips/${pipId}/evaluate`, data);
  return res.data;
}

export interface GoalProgressHistoryItem {
  id: string;
  goal_id: string;
  updated_by_id: string;
  old_progress: number;
  new_progress: number;
  notes: string | null;
  created_at: string;
}

export interface PIPCheckIn {
  id: string;
  company_id: string;
  pip_id: string;
  note: string;
  created_by: string;
  created_at: string;
}

export interface PIPCheckInCreateInput {
  note: string;
}

export async function reopenReview(reviewId: string, data: { reason: string }): Promise<PerformanceReview> {
  const res = await apiClient.post<PerformanceReview>(`/performance/reviews/${reviewId}/reopen`, data);
  return res.data;
}

export async function getGoalProgressHistory(goalId: string): Promise<GoalProgressHistoryItem[]> {
  const res = await apiClient.get<GoalProgressHistoryItem[]>(`/performance/goals/${goalId}/history`);
  return res.data;
}

export async function listPIPCheckIns(pipId: string): Promise<PIPCheckIn[]> {
  const res = await apiClient.get<PIPCheckIn[]>(`/performance/pips/${pipId}/check-ins`);
  return res.data;
}

export async function addPIPCheckIn(pipId: string, data: PIPCheckInCreateInput): Promise<PIPCheckIn> {
  const res = await apiClient.post<PIPCheckIn>(`/performance/pips/${pipId}/check-ins`, data);
  return res.data;
}

export interface PIPSeparationDecisionInput {
  decision: "separate" | "extend" | "retain";
  last_working_date?: string | null;
  notice_choice?: "served" | "waived" | "pay_in_lieu" | null;
  new_end_date?: string | null;
  reason?: string | null;
}

export interface SeparationDecision {
  id: string;
  pip_id: string;
  decision: "separate" | "extend" | "retain";
  decided_by: string;
  decided_at: string;
  last_working_date?: string | null;
  notice_choice?: string | null;
  notes?: string | null;
}

export async function decidePIPSeparation(
  pipId: string,
  data: PIPSeparationDecisionInput
): Promise<SeparationDecision> {
  const res = await apiClient.post<SeparationDecision>(
    `/performance/pips/${pipId}/separation-decision`,
    data
  );
  return res.data;
}

