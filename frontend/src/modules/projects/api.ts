import { apiClient } from "../../app/api-client";
import type {
  Project, ProjectCreatePayload, ProjectUpdatePayload, ProjectSummary,
  ProjectMember, Task, TaskCreatePayload, TaskComment,
  TimeEntry, TimeEntryCreatePayload, Milestone, MilestoneCreatePayload
} from "./types";

export async function fetchProjects(status?: string): Promise<Project[]> {
  const query = status ? `?status=${status}` : "";
  const res = await apiClient.get<Project[]>(`/projects${query}`);
  return res.data;
}

export async function createProject(payload: ProjectCreatePayload): Promise<Project> {
  const res = await apiClient.post<Project>("/projects", payload);
  return res.data;
}

export async function fetchProject(projectId: string): Promise<Project> {
  const res = await apiClient.get<Project>(`/projects/${projectId}`);
  return res.data;
}

export async function updateProject(projectId: string, payload: ProjectUpdatePayload): Promise<Project> {
  const res = await apiClient.put<Project>(`/projects/${projectId}`, payload);
  return res.data;
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiClient.delete<void>(`/projects/${projectId}`);
}

export async function fetchProjectSummary(projectId: string): Promise<ProjectSummary> {
  const res = await apiClient.get<ProjectSummary>(`/projects/${projectId}/summary`);
  return res.data;
}

// Members
export async function fetchProjectMembers(projectId: string): Promise<ProjectMember[]> {
  const res = await apiClient.get<ProjectMember[]>(`/projects/${projectId}/members`);
  return res.data;
}

export async function addProjectMember(projectId: string, employeeId: string, role: string): Promise<ProjectMember> {
  const res = await apiClient.post<ProjectMember>(`/projects/${projectId}/members`, { employee_id: employeeId, role });
  return res.data;
}

export async function removeProjectMember(projectId: string, employeeId: string): Promise<void> {
  await apiClient.delete<void>(`/projects/${projectId}/members/${employeeId}`);
}

// Tasks
export async function fetchTasks(projectId: string, status?: string): Promise<Task[]> {
  const query = status ? `?status=${status}` : "";
  const res = await apiClient.get<Task[]>(`/projects/${projectId}/tasks${query}`);
  return res.data;
}

export async function createTask(projectId: string, payload: TaskCreatePayload): Promise<Task> {
  const res = await apiClient.post<Task>(`/projects/${projectId}/tasks`, payload);
  return res.data;
}

export async function updateTask(taskId: string, payload: Partial<Task>): Promise<Task> {
  const res = await apiClient.put<Task>(`/projects/tasks/${taskId}`, payload);
  return res.data;
}

export async function deleteTask(taskId: string): Promise<void> {
  await apiClient.delete<void>(`/projects/tasks/${taskId}`);
}

// Comments
export async function fetchTaskComments(taskId: string): Promise<TaskComment[]> {
  const res = await apiClient.get<TaskComment[]>(`/projects/tasks/${taskId}/comments`);
  return res.data;
}

export async function addTaskComment(taskId: string, comment: string): Promise<TaskComment> {
  const res = await apiClient.post<TaskComment>(`/projects/tasks/${taskId}/comments`, { comment });
  return res.data;
}

// Time Entries
export async function fetchTimeEntries(params?: { projectId?: string; status?: string; startDate?: string; endDate?: string }): Promise<TimeEntry[]> {
  const q = new URLSearchParams();
  if (params?.projectId) q.append("project_id", params.projectId);
  if (params?.status) q.append("status", params.status);
  if (params?.startDate) q.append("start_date", params.startDate);
  if (params?.endDate) q.append("end_date", params.endDate);
  const queryString = q.toString() ? `?${q.toString()}` : "";
  const res = await apiClient.get<TimeEntry[]>(`/projects/time-entries${queryString}`);
  return res.data;
}

export async function createTimeEntry(payload: TimeEntryCreatePayload): Promise<TimeEntry> {
  const res = await apiClient.post<TimeEntry>("/projects/time-entries", payload);
  return res.data;
}

export async function approveRejectTimeEntry(entryId: string, statusAction: "approved" | "rejected"): Promise<TimeEntry> {
  const res = await apiClient.post<TimeEntry>(`/projects/time-entries/${entryId}/approve?status_action=${statusAction}`, {});
  return res.data;
}

export async function deleteTimeEntry(entryId: string): Promise<void> {
  await apiClient.delete<void>(`/projects/time-entries/${entryId}`);
}

// Milestones
export async function fetchMilestones(projectId: string): Promise<Milestone[]> {
  const res = await apiClient.get<Milestone[]>(`/projects/${projectId}/milestones`);
  return res.data;
}

export async function createMilestone(projectId: string, payload: MilestoneCreatePayload): Promise<Milestone> {
  const res = await apiClient.post<Milestone>(`/projects/${projectId}/milestones`, payload);
  return res.data;
}

export async function updateMilestone(milestoneId: string, payload: Partial<Milestone>): Promise<Milestone> {
  const res = await apiClient.put<Milestone>(`/projects/milestones/${milestoneId}`, payload);
  return res.data;
}

export async function deleteMilestone(milestoneId: string): Promise<void> {
  await apiClient.delete<void>(`/projects/milestones/${milestoneId}`);
}
