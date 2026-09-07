export type ProjectStatus = "planning" | "active" | "on_hold" | "completed" | "cancelled";
export type TaskPriority = "critical" | "high" | "medium" | "low";
export type TaskStatus = "todo" | "in_progress" | "review" | "done";
export type TimeEntryStatus = "draft" | "submitted" | "approved" | "rejected";
export type MilestoneStatus = "pending" | "in_progress" | "completed" | "missed";
export type MemberRole = "lead" | "member";

export interface Project {
  id: string;
  company_id: string;
  name: string;
  code: string;
  description?: string;
  status: ProjectStatus;
  start_date?: string;
  deadline?: string;
  budget?: number;
  manager_id?: string;
  client_name?: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreatePayload {
  name: string;
  code: string;
  description?: string;
  status?: ProjectStatus;
  start_date?: string;
  deadline?: string;
  budget?: number;
  manager_id?: string;
  client_name?: string;
}

export interface ProjectUpdatePayload {
  name?: string;
  code?: string;
  description?: string;
  status?: ProjectStatus;
  start_date?: string;
  deadline?: string;
  budget?: number;
  manager_id?: string;
  client_name?: string;
}

export interface ProjectMember {
  id: string;
  company_id: string;
  project_id: string;
  employee_id: string;
  role: MemberRole;
  joined_at: string;
  left_at?: string;
  created_at: string;
}

export interface Task {
  id: string;
  company_id: string;
  project_id: string;
  title: string;
  description?: string;
  assigned_to?: string;
  priority: TaskPriority;
  status: TaskStatus;
  due_date?: string;
  estimated_hours?: number;
  completed_at?: string;
  created_by?: string;
  created_at: string;
  updated_at: string;
}

export interface TaskCreatePayload {
  title: string;
  description?: string;
  assigned_to?: string;
  priority?: TaskPriority;
  status?: TaskStatus;
  due_date?: string;
  estimated_hours?: number;
}

export interface TaskComment {
  id: string;
  company_id: string;
  task_id: string;
  user_id: string;
  comment: string;
  created_at: string;
}

export interface TimeEntry {
  id: string;
  company_id: string;
  project_id: string;
  task_id?: string;
  employee_id: string;
  date: string;
  hours: number;
  description?: string;
  is_billable: boolean;
  status: TimeEntryStatus;
  approved_by?: string;
  approved_at?: string;
  created_at: string;
  updated_at: string;
}

export interface TimeEntryCreatePayload {
  project_id: string;
  task_id?: string;
  date: string;
  hours: number;
  description?: string;
  is_billable?: boolean;
}

export interface Milestone {
  id: string;
  company_id: string;
  project_id: string;
  title: string;
  description?: string;
  due_date?: string;
  status: MilestoneStatus;
  completion_percentage: number;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}

export interface MilestoneCreatePayload {
  title: string;
  description?: string;
  due_date?: string;
  status?: MilestoneStatus;
  completion_percentage?: number;
}

export interface ProjectSummary {
  project: Project;
  total_tasks: number;
  completed_tasks: number;
  overdue_tasks: number;
  completion_percentage: number;
  total_logged_hours: number;
  total_billable_hours: number;
  members_count: number;
  milestones_count: number;
  completed_milestones_count: number;
}
