export type ProjectStatus = "planning" | "active" | "on_hold" | "completed" | "cancelled";
export type TaskPriority = "critical" | "high" | "medium" | "low";
export type TaskStatus = "todo" | "in_progress" | "review" | "done";
export type TimeEntryStatus = "draft" | "submitted" | "approved" | "rejected";
export type MilestoneStatus = "pending" | "in_progress" | "completed" | "missed";
export type MemberRole = "lead" | "member";

export interface Project {
  id: string;
  company_id: string;
  company_name?: string;
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
  company_id?: string;
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
  employee_name?: string;
  employee_email?: string;
  employee_code?: string;
  designation?: string;
  department_name?: string;
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
  assigned_to_name?: string;
  assigned_to_email?: string;
  assigned_to_code?: string;
  assigned_to_designation?: string;
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
  employee_name?: string;
  employee_email?: string;
  employee_code?: string;
  task_title?: string;
  project_name?: string;
  project_code?: string;
  rejection_reason?: string;
}

export interface ProjectDocument {
  id: string;
  company_id: string;
  project_id: string;
  file_id: string;
  name: string;
  file_size: number;
  file_type: string;
  description?: string;
  uploaded_by?: string;
  uploaded_by_name?: string;
  created_at: string;
  download_url?: string;
}

export interface TimeEntryCreatePayload {
  project_id: string;
  task_id?: string;
  employee_id?: string;
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
