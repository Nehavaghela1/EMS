import { apiClient } from "../../app/api-client";
import type { Page } from "../../shared/api/pagination";

export type CycleType = "annual" | "half_yearly" | "quarterly";
export type CycleStatus = "draft" | "active" | "closed";
export type GoalStatus = "draft" | "in_progress" | "completed";
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
  goals: GoalCreateItem[];
}

export interface PerformanceGoal {
  id: string;
  employee_id: string;
  cycle_id: string;
  title: string;
  description: string | null;
  weightage: string;
  target_value: string | null;
  status: GoalStatus;
  self_rating: string | null;
  self_comments: string | null;
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
  cycle_id: string;
  final_rating: string;
  overall_comments: string | null;
  salary_revision_recommended: boolean;
  recommended_increment_percent: string | null;
  reviewed_by: string;
  finalized_at: string;
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

export async function updatePerformanceCycle(id: string, status: CycleStatus): Promise<PerformanceCycle> {
  const res = await apiClient.put<PerformanceCycle>(`/performance/cycles/${id}`, { status });
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
  data: Partial<GoalCreateItem & { status: GoalStatus }>
): Promise<PerformanceGoal> {
  const res = await apiClient.put<PerformanceGoal>(`/performance/goals/${id}`, data);
  return res.data;
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
