import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  fetchProjectSummary, fetchTasks, createTask, updateTask,
  fetchProjectMembers, addProjectMember, removeProjectMember,
  fetchMilestones, createMilestone, updateMilestone, updateProject,
  fetchTaskComments, addTaskComment,
  fetchTimeEntries, createTimeEntry,
  fetchProjectDocuments, uploadProjectDocument, deleteProjectDocument
} from "../api";
import type {
  ProjectSummary, ProjectStatus, Task, TaskStatus, TaskPriority,
  ProjectMember, Milestone, MilestoneStatus, TaskComment, TimeEntry,
  ProjectDocument
} from "../types";
import { listEmployees, type Employee } from "../../hr/api";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { useTimer } from "../../../app/timer-context";
import { formatDate, formatDateTime } from "../../../shared/utils/date";

export function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { activeTimer, startTimer, stopTimer, formatTime, elapsedSeconds } = useTimer();
  const canManage = user?.role === "hr_admin" || user?.role === "super_admin" || user?.role === "manager";
  const [taskFilter, setTaskFilter] = useState<"all" | "my">("all");

  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [timeLogs, setTimeLogs] = useState<TimeEntry[]>([]);
  const [employeeList, setEmployeeList] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"kanban" | "milestones" | "team" | "timelogs" | "documents" | "settings">("kanban");

  // Enterprise Role & Ownership Permissions
  // Teammates can view tasks (Read-Only). Only Assignee, Project Lead, or Admins can modify/complete/track tasks.
  const isProjectLead = Boolean(
    user?.employee?.id && members.some((m) => m.employee_id === user.employee?.id && m.role === "lead")
  );

  const canModifyTask = (t: Task) => {
    if (canManage || isProjectLead) return true;
    if (user?.employee?.id && t.assigned_to === user.employee.id) return true;
    return false;
  };

  const getTaskLockMessage = (t: Task) => {
    const assignee = t.assigned_to_name || "the Assignee";
    return `Only ${assignee} or the Project Lead can modify this task.`;
  };

  // Documents State
  const [documents, setDocuments] = useState<ProjectDocument[]>([]);
  const [showDocModal, setShowDocModal] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [docDesc, setDocDesc] = useState("");
  const [uploadingDoc, setUploadingDoc] = useState(false);

  // Drag-and-drop State
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null);
  const [dragOverCol, setDragOverCol] = useState<TaskStatus | null>(null);

  // Log Time Modal in Project with 3 Modes: duration, range, stopwatch
  const [showTimeModal, setShowTimeModal] = useState(false);
  const [timeInputMode, setTimeInputMode] = useState<"duration" | "range" | "stopwatch">("duration");
  const [logEmployeeId, setLogEmployeeId] = useState("");
  const [logDate, setLogDate] = useState(new Date().toISOString().slice(0, 10));
  const [logHours, setLogHours] = useState("");
  const [logStartTime, setLogStartTime] = useState("09:00");
  const [logEndTime, setLogEndTime] = useState("17:00");
  const [logBreakMinutes, setLogBreakMinutes] = useState("60");
  const [logDesc, setLogDesc] = useState("");
  const [logTaskId, setLogTaskId] = useState("");
  const [logBillable, setLogBillable] = useState(true);
  const [submittingTime, setSubmittingTime] = useState(false);

  // Task Modal (Create & Edit)
  const [showTaskModal, setShowTaskModal] = useState(false);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDesc, setTaskDesc] = useState("");
  const [taskPriority, setTaskPriority] = useState<TaskPriority>("medium");
  const [taskStatus, setTaskStatus] = useState<TaskStatus>("todo");
  const [taskDueDate, setTaskDueDate] = useState("");
  const [taskEstHours, setTaskEstHours] = useState("");
  const [taskAssignedTo, setTaskAssignedTo] = useState("");
  const [submittingTask, setSubmittingTask] = useState(false);

  // Milestone Modal (Create & Edit)
  const [showMilestoneModal, setShowMilestoneModal] = useState(false);
  const [editingMsId, setEditingMsId] = useState<string | null>(null);
  const [msTitle, setMsTitle] = useState("");
  const [msDesc, setMsDesc] = useState("");
  const [msDueDate, setMsDueDate] = useState("");
  const [msPct, setMsPct] = useState("0");
  const [msStatus, setMsStatus] = useState<MilestoneStatus>("pending");
  const [submittingMs, setSubmittingMs] = useState(false);

  // Project Edit Modal
  const [showProjectEditModal, setShowProjectEditModal] = useState(false);
  const [editProjName, setEditProjName] = useState("");
  const [editProjCode, setEditProjCode] = useState("");
  const [editProjClient, setEditProjClient] = useState("");
  const [editProjBudget, setEditProjBudget] = useState("");
  const [editProjStatus, setEditProjStatus] = useState<ProjectStatus>("active");
  const [editProjStartDate, setEditProjStartDate] = useState("");
  const [editProjDeadline, setEditProjDeadline] = useState("");
  const [editProjDesc, setEditProjDesc] = useState("");
  const [submittingProjectEdit, setSubmittingProjectEdit] = useState(false);

  // Add Member Modal
  const [showMemberModal, setShowMemberModal] = useState(false);
  const [memberEmployeeId, setMemberEmployeeId] = useState("");
  const [memberRole, setMemberRole] = useState<"lead" | "member">("member");
  const [submittingMember, setSubmittingMember] = useState(false);

  // Comment Modal
  const [activeCommentTask, setActiveCommentTask] = useState<Task | null>(null);
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [newComment, setNewComment] = useState("");
  const [loadingComments, setLoadingComments] = useState(false);

  const { notify } = useToast();

  async function loadData() {
    if (!id) return;
    try {
      setLoading(true);
      const [sumRes, taskRes, memRes, msRes, timeRes, empRes, docRes] = await Promise.all([
        fetchProjectSummary(id),
        fetchTasks(id),
        fetchProjectMembers(id),
        fetchMilestones(id),
        fetchTimeEntries({ projectId: id }).catch(() => []),
        canManage ? listEmployees({ page: 1, limit: 100 }).catch(() => ({ items: [] })) : Promise.resolve({ items: [] } as any),
        fetchProjectDocuments(id).catch(() => []),
      ]);
      setSummary(sumRes);
      setTasks(taskRes);
      setMembers(memRes);
      setMilestones(msRes);
      setTimeLogs(timeRes);
      setEmployeeList(empRes.items || []);
      setDocuments(docRes);
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to load project details", "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, [id]);

  // Task Actions (Create / Edit)
  function openNewTaskModal() {
    setEditingTaskId(null);
    setTaskTitle("");
    setTaskDesc("");
    setTaskPriority("medium");
    setTaskStatus("todo");
    setTaskDueDate("");
    setTaskEstHours("");
    setTaskAssignedTo("");
    setShowTaskModal(true);
  }

  function openEditTaskModal(task: Task) {
    setEditingTaskId(task.id);
    setTaskTitle(task.title);
    setTaskDesc(task.description || "");
    setTaskPriority(task.priority);
    setTaskStatus(task.status);
    setTaskDueDate(task.due_date ? task.due_date.slice(0, 10) : "");
    setTaskEstHours(task.estimated_hours ? String(task.estimated_hours) : "");
    setTaskAssignedTo(task.assigned_to || "");
    setShowTaskModal(true);
  }

  async function handleSaveTask(e: React.FormEvent) {
    e.preventDefault();
    if (!id || !taskTitle) return;
    try {
      setSubmittingTask(true);
      if (editingTaskId) {
        await updateTask(editingTaskId, {
          title: taskTitle,
          description: taskDesc || undefined,
          priority: taskPriority,
          status: taskStatus,
          due_date: taskDueDate || undefined,
          estimated_hours: taskEstHours ? parseFloat(taskEstHours) : undefined,
          assigned_to: taskAssignedTo || undefined,
        });
        notify("Task updated successfully!", "success");
      } else {
        await createTask(id, {
          title: taskTitle,
          description: taskDesc || undefined,
          priority: taskPriority,
          status: taskStatus,
          due_date: taskDueDate || undefined,
          estimated_hours: taskEstHours ? parseFloat(taskEstHours) : undefined,
          assigned_to: taskAssignedTo || undefined,
        });
        notify("Task created!", "success");
      }
      setShowTaskModal(false);
      loadData();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to save task", "error");
    } finally {
      setSubmittingTask(false);
    }
  }

  async function handleUploadDocument(e: React.FormEvent) {
    e.preventDefault();
    if (!id || !uploadFile) return;
    try {
      setUploadingDoc(true);
      const newDoc = await uploadProjectDocument(id, uploadFile, docDesc);
      setDocuments([newDoc, ...documents]);
      setShowDocModal(false);
      setUploadFile(null);
      setDocDesc("");
      notify("Document uploaded successfully!", "success");
    } catch (err: any) {
      const errorMsg =
        err?.response?.data?.error?.details?.errors?.[0]?.msg ||
        err?.response?.data?.error?.message ||
        err?.response?.data?.message ||
        err?.message ||
        "Failed to upload document. Please ensure the file is under 25MB.";
      notify(errorMsg, "error");
    } finally {
      setUploadingDoc(false);
    }
  }

  async function handleDeleteDocument(docId: string) {
    if (!id || !confirm("Are you sure you want to delete this document?")) return;
    try {
      await deleteProjectDocument(id, docId);
      setDocuments(documents.filter((d) => d.id !== docId));
      notify("Document deleted", "info");
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || "Failed to delete document", "error");
    }
  }

  async function handleStatusChange(taskId: string, newStatus: TaskStatus) {
    try {
      await updateTask(taskId, { status: newStatus });
      notify("Task status updated", "success");
      loadData();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to update status", "error");
    }
  }

  // Milestone Actions (Create / Edit)
  function openNewMilestoneModal() {
    setEditingMsId(null);
    setMsTitle("");
    setMsDesc("");
    setMsDueDate("");
    const defaultPct = summary?.completion_percentage || 0;
    setMsPct(String(defaultPct));
    setMsStatus(defaultPct >= 100 ? "completed" : defaultPct > 0 ? "in_progress" : "pending");
    setShowMilestoneModal(true);
  }

  function openEditMilestoneModal(ms: Milestone) {
    setEditingMsId(ms.id);
    setMsTitle(ms.title);
    setMsDesc(ms.description || "");
    setMsDueDate(ms.due_date ? ms.due_date.slice(0, 10) : "");
    setMsPct(String(ms.completion_percentage));
    setMsStatus(ms.status);
    setShowMilestoneModal(true);
  }

  async function handleSaveMilestone(e: React.FormEvent) {
    e.preventDefault();
    if (!id || !msTitle) return;
    try {
      setSubmittingMs(true);
      if (editingMsId) {
        await updateMilestone(editingMsId, {
          title: msTitle,
          description: msDesc || undefined,
          due_date: msDueDate || undefined,
          completion_percentage: parseFloat(msPct),
          status: msStatus,
        });
        notify("Milestone updated!", "success");
      } else {
        await createMilestone(id, {
          title: msTitle,
          description: msDesc || undefined,
          due_date: msDueDate || undefined,
          completion_percentage: parseFloat(msPct),
          status: msStatus,
        });
        notify("Milestone created!", "success");
      }
      setShowMilestoneModal(false);
      loadData();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to save milestone", "error");
    } finally {
      setSubmittingMs(false);
    }
  }

  // Project Edit Actions
  function openEditProjectModal() {
    if (!summary?.project) return;
    const p = summary.project;
    setEditProjName(p.name);
    setEditProjCode(p.code);
    setEditProjClient(p.client_name || "");
    setEditProjBudget(p.budget ? String(p.budget) : "");
    setEditProjStatus(p.status);
    setEditProjStartDate(p.start_date ? p.start_date.slice(0, 10) : "");
    setEditProjDeadline(p.deadline ? p.deadline.slice(0, 10) : "");
    setEditProjDesc(p.description || "");
    setShowProjectEditModal(true);
  }

  async function handleSaveProject(e: React.FormEvent) {
    e.preventDefault();
    if (!id || !editProjName || !editProjCode) return;
    try {
      setSubmittingProjectEdit(true);
      await updateProject(id, {
        name: editProjName,
        code: editProjCode,
        client_name: editProjClient || undefined,
        budget: editProjBudget ? parseFloat(editProjBudget) : undefined,
        status: editProjStatus,
        start_date: editProjStartDate || undefined,
        deadline: editProjDeadline || undefined,
        description: editProjDesc || undefined,
      });
      notify("Project updated successfully!", "success");
      setShowProjectEditModal(false);
      loadData();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to update project", "error");
    } finally {
      setSubmittingProjectEdit(false);
    }
  }

  // Member Actions
  async function handleAddMember(e: React.FormEvent) {
    e.preventDefault();
    if (!id || !memberEmployeeId) return;
    try {
      setSubmittingMember(true);
      await addProjectMember(id, memberEmployeeId, memberRole);
      notify("Member added!", "success");
      setShowMemberModal(false);
      setMemberEmployeeId("");
      loadData();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to add member", "error");
    } finally {
      setSubmittingMember(false);
    }
  }

  async function handleRemoveMember(employeeId: string) {
    if (!id || !confirm("Remove member from project?")) return;
    try {
      await removeProjectMember(id, employeeId);
      notify("Member removed", "success");
      loadData();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to remove member", "error");
    }
  }

  // Time Log Action
  async function handleLogTime(e: React.FormEvent) {
    e.preventDefault();
    if (!id || !logHours || !logDate) {
      notify("Please provide date and hours", "error");
      return;
    }
    const hrs = parseFloat(logHours);
    if (hrs <= 0 || hrs > 24) {
      notify("Hours must be between 0.1 and 24", "error");
      return;
    }
    try {
      setSubmittingTime(true);
      await createTimeEntry({
        project_id: id,
        task_id: logTaskId || undefined,
        employee_id: logEmployeeId || undefined,
        date: logDate,
        hours: hrs,
        description: logDesc || undefined,
        is_billable: logBillable,
      });
      notify("Time entry logged successfully!", "success");
      setShowTimeModal(false);
      setLogHours("");
      setLogDesc("");
      setLogTaskId("");
      setLogEmployeeId("");
      loadData();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to log time", "error");
    } finally {
      setSubmittingTime(false);
    }
  }

  // Task Comments
  async function openTaskComments(task: Task) {
    setActiveCommentTask(task);
    try {
      setLoadingComments(true);
      const res = await fetchTaskComments(task.id);
      setComments(res);
    } catch (err: any) {
      notify("Failed to load comments", "error");
    } finally {
      setLoadingComments(false);
    }
  }

  async function handlePostComment(e: React.FormEvent) {
    e.preventDefault();
    if (!activeCommentTask || !newComment) return;
    try {
      await addTaskComment(activeCommentTask.id, newComment);
      notify("Comment posted", "success");
      setNewComment("");
      const res = await fetchTaskComments(activeCommentTask.id);
      setComments(res);
    } catch (err: any) {
      notify("Failed to post comment", "error");
    }
  }

  if (loading || !summary) {
    return <p className="text-muted">Loading workspace details...</p>;
  }

  const { project } = summary;
  const kanbanColumns: { key: TaskStatus; title: string; color: string }[] = [
    { key: "todo", title: "To Do", color: "#64748b" },
    { key: "in_progress", title: "In Progress", color: "#3b82f6" },
    { key: "review", title: "In Review", color: "#f59e0b" },
    { key: "done", title: "Completed", color: "#10b981" },
  ];

  const priorityBadges: Record<TaskPriority, string> = {
    critical: "badge-danger",
    high: "badge-warning",
    medium: "badge-muted",
    low: "badge-secondary",
  };

  return (
    <div className="stack gap-6">
      {/* Back Link */}
      <div>
        <Link to="/projects" className="btn btn-ghost btn-sm" style={{ paddingLeft: 0, textDecoration: "none" }}>
          ← Back to Projects
        </Link>
      </div>

      {/* Page Header */}
      <div className="row-between align-center">
        <div>
          <div className="row gap-2 align-center mb-1">
            <span className="badge badge-muted font-mono" style={{ fontSize: "12px", fontWeight: 700, letterSpacing: "0.5px" }}>
              {project.code}
            </span>
            <span className={`badge ${project.status === "active" ? "badge-success" : "badge-muted"}`} style={{ textTransform: "uppercase", fontSize: "11px", letterSpacing: "0.5px" }}>
              {project.status}
            </span>
            {project.company_name && (
              <span
                className="badge"
                style={{
                  fontSize: "11px",
                  background: "rgba(37, 99, 235, 0.1)",
                  color: "var(--color-primary, #2563eb)",
                  border: "1px solid rgba(37, 99, 235, 0.2)",
                }}
              >
                🏢 {project.company_name}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <h1 style={{ margin: 0, fontSize: "1.75rem", fontWeight: 700, letterSpacing: "-0.02em" }}>{project.name}</h1>
            {canManage && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                style={{
                  padding: "4px 6px",
                  borderRadius: "4px",
                  color: "#64748b",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
                onClick={openEditProjectModal}
                title="Edit Project Workspace"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
              </button>
            )}
          </div>
          {project.client_name && (
            <p className="text-muted text-sm mt-1" style={{ margin: 0 }}>
              Client: <strong style={{ color: "var(--color-text)" }}>{project.client_name}</strong>
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          {canManage && (
            <button
              type="button"
              className="btn btn-outline"
              style={{ display: "flex", alignItems: "center", gap: "6px" }}
              onClick={openEditProjectModal}
              title="Edit Project"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              Edit Project
            </button>
          )}
          <button className="btn btn-primary" onClick={openNewTaskModal}>
            + Add Task
          </button>
        </div>
      </div>

      {/* Analytics Stats Grid - Standalone Cards */}
      <div className="stat-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem" }}>
        <div className="card">
          <span className="stat-label" style={{ fontWeight: 600, letterSpacing: "0.04em", fontSize: "11px" }}>TASKS PROGRESS</span>
          <div className="row-between align-center mt-1">
            <div className="stat-value text-primary" style={{ margin: 0, fontSize: "1.75rem" }}>{summary.completion_percentage}%</div>
            <span className="text-muted text-xs font-mono">{summary.completed_tasks}/{summary.total_tasks} done</span>
          </div>
          <div style={{ width: "100%", height: "4px", background: "#e2e8f0", borderRadius: "2px", marginTop: "10px", overflow: "hidden" }}>
            <div style={{ width: `${summary.completion_percentage}%`, height: "100%", background: "var(--color-primary)", borderRadius: "2px" }} />
          </div>
        </div>

        <div className="card">
          <span className="stat-label" style={{ fontWeight: 600, letterSpacing: "0.04em", fontSize: "11px" }}>LOGGED HOURS</span>
          <div className="stat-value" style={{ margin: 0, fontSize: "1.75rem" }}>
            {summary.total_logged_hours} <span style={{ fontSize: "0.95rem", fontWeight: 500, color: "var(--color-text-muted)" }}>hrs</span>
          </div>
          <div className="text-muted text-xs mt-2">{summary.total_billable_hours} hrs Billable</div>
        </div>

        <div className="card">
          <span className="stat-label" style={{ fontWeight: 600, letterSpacing: "0.04em", fontSize: "11px" }}>OVERDUE TASKS</span>
          <div className={`stat-value ${summary.overdue_tasks > 0 ? "text-danger" : "text-success"}`} style={{ margin: 0, fontSize: "1.75rem" }}>
            {summary.overdue_tasks}
          </div>
          <div className="text-muted text-xs mt-2" style={{ fontWeight: 500 }}>
            {summary.delivery_health === "Needs Attention" || summary.overdue_tasks > 0 ? (
              <span className="text-danger">⚠️ Needs Attention</span>
            ) : summary.delivery_health === "In Progress" || (Number(summary.completion_percentage) === 0 && Number(summary.total_logged_hours) > 0) ? (
              <span style={{ color: "var(--color-primary, #2563eb)" }}>🔵 In Progress</span>
            ) : summary.delivery_health === "On Schedule" || Number(summary.completion_percentage) > 0 ? (
              <span className="text-success">✓ On Track</span>
            ) : (
              <span style={{ color: "#64748b" }}>⚪ Not Started</span>
            )}
          </div>
        </div>

        <div className="card">
          <span className="stat-label" style={{ fontWeight: 600, letterSpacing: "0.04em", fontSize: "11px" }}>TEAM SIZE</span>
          <div className="stat-value" style={{ margin: 0, fontSize: "1.75rem" }}>{summary.members_count}</div>
          <div className="text-muted text-xs mt-2">Active Members</div>
        </div>
      </div>

      {/* Zoho Style Tabs Bar */}
      <div className="tab-bar flex justify-between items-center" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
        <div className="flex gap-2">
          <button
            type="button"
            className={`tab-item ${activeTab === "kanban" ? "active" : ""}`}
            onClick={() => setActiveTab("kanban")}
          >
            Tasks Kanban ({tasks.length})
          </button>
          <button
            type="button"
            className={`tab-item ${activeTab === "milestones" ? "active" : ""}`}
            onClick={() => setActiveTab("milestones")}
          >
            Milestones ({milestones.length})
          </button>
          <button
            type="button"
            className={`tab-item ${activeTab === "team" ? "active" : ""}`}
            onClick={() => setActiveTab("team")}
          >
            Users & Team ({members.length})
          </button>
          <button
            type="button"
            className={`tab-item ${activeTab === "timelogs" ? "active" : ""}`}
            onClick={() => setActiveTab("timelogs")}
          >
            Time Logs ({timeLogs.length})
          </button>
          <button
            type="button"
            className={`tab-item ${activeTab === "documents" ? "active" : ""}`}
            onClick={() => setActiveTab("documents")}
          >
            📁 Documents & Files ({documents.length})
          </button>
          <button
            type="button"
            className={`tab-item ${activeTab === "settings" ? "active" : ""}`}
            onClick={() => setActiveTab("settings")}
          >
            Overview & Budget
          </button>
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            className="btn btn-sm btn-outline"
            onClick={() => setShowTimeModal(true)}
          >
            ⏱️ Log Time
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={openNewTaskModal}
          >
            + Add Task
          </button>
        </div>
      </div>

      {/* TAB 1: KANBAN BOARD */}
      {activeTab === "kanban" && (
        <div>
          {/* Kanban Toolbar with View Mode Filter ("All Tasks" vs "My Tasks") */}
          <div
            className="flex items-center justify-between mb-4 p-2"
            style={{
              background: "#f8fafc",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-md)",
            }}
          >
            <div className="flex items-center gap-2">
              <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--color-muted)" }}>
                View Mode:
              </span>
              <div
                style={{
                  display: "inline-flex",
                  borderRadius: "6px",
                  background: "#e2e8f0",
                  padding: "2px",
                }}
              >
                <button
                  type="button"
                  onClick={() => setTaskFilter("all")}
                  style={{
                    padding: "4px 12px",
                    fontSize: "0.8rem",
                    fontWeight: taskFilter === "all" ? 600 : 500,
                    borderRadius: "4px",
                    background: taskFilter === "all" ? "#fff" : "transparent",
                    color: taskFilter === "all" ? "var(--color-primary)" : "var(--color-muted)",
                    boxShadow: taskFilter === "all" ? "0 1px 2px rgba(0,0,0,0.08)" : "none",
                    border: "none",
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  🌐 All Tasks ({tasks.length})
                </button>
                <button
                  type="button"
                  onClick={() => setTaskFilter("my")}
                  style={{
                    padding: "4px 12px",
                    fontSize: "0.8rem",
                    fontWeight: taskFilter === "my" ? 600 : 500,
                    borderRadius: "4px",
                    background: taskFilter === "my" ? "#fff" : "transparent",
                    color: taskFilter === "my" ? "var(--color-primary)" : "var(--color-muted)",
                    boxShadow: taskFilter === "my" ? "0 1px 2px rgba(0,0,0,0.08)" : "none",
                    border: "none",
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  👤 My Tasks ({tasks.filter((t) => t.assigned_to === user?.employee?.id).length})
                </button>
              </div>
            </div>

            <div className="flex items-center gap-2 text-xs text-muted">
              {isProjectLead && <span className="badge badge-primary">👑 Project Lead</span>}
              {!canManage && !isProjectLead && (
                <span>Teammate View: Read-only access to peers' tasks</span>
              )}
            </div>
          </div>

          <div className="kanban-board">
            {kanbanColumns.map((col) => {
              const visibleTasks = taskFilter === "my"
                ? tasks.filter((t) => t.assigned_to === user?.employee?.id)
                : tasks;
              const colTasks = visibleTasks.filter((t) => t.status === col.key);
              const isOver = dragOverCol === col.key;
              return (
                <div
                  key={col.key}
                  className={`kanban-col ${isOver ? "drag-over" : ""}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (dragOverCol !== col.key) setDragOverCol(col.key);
                  }}
                  onDragLeave={(e) => {
                    // Only clear if leaving the column element itself
                    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
                    if (dragOverCol === col.key) setDragOverCol(null);
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragOverCol(null);
                    const taskId = e.dataTransfer.getData("text/plain") || draggedTaskId;
                    if (taskId) {
                      const targetTask = tasks.find((t) => t.id === taskId);
                      if (targetTask && !canModifyTask(targetTask)) {
                        notify(getTaskLockMessage(targetTask), "error");
                        setDraggedTaskId(null);
                        return;
                      }
                      handleStatusChange(taskId, col.key);
                      setDraggedTaskId(null);
                    }
                  }}
                >
                  <div className="kanban-col-header">
                    <span className="kanban-col-title">
                      <span
                        style={{
                        width: 9,
                        height: 9,
                        borderRadius: "50%",
                        background: col.color,
                        display: "inline-block",
                      }}
                    />
                    <span style={{ color: "var(--color-text)", fontWeight: 600 }}>{col.title}</span>
                  </span>
                  <span className="kanban-col-count">{colTasks.length}</span>
                </div>

                <div className="stack gap-3" style={{ flex: 1, overflowY: "auto", minHeight: "120px" }}>
                  {colTasks.length === 0 ? (
                    <div
                      className="text-center text-muted text-xs p-4"
                      style={{
                        border: isOver ? "2px dashed #6366f1" : "1px dashed #cbd5e1",
                        borderRadius: "var(--radius-sm)",
                        background: isOver ? "rgba(238, 242, 255, 0.8)" : "rgba(255, 255, 255, 0.6)",
                        transition: "all 0.2s ease",
                      }}
                    >
                      {isOver ? "Drop card here" : "No tasks"}
                    </div>
                  ) : (
                    colTasks.map((task) => {
                      const isDraggingThis = draggedTaskId === task.id;
                      const hasPermission = canModifyTask(task);
                      const lockTooltip = getTaskLockMessage(task);

                      return (
                        <div
                          key={task.id}
                          className={`kanban-task-card ${isDraggingThis ? "is-dragging" : ""}`}
                          draggable={hasPermission}
                          onDragStart={(e) => {
                            if (!hasPermission) {
                              e.preventDefault();
                              notify(lockTooltip, "error");
                              return;
                            }
                            setDraggedTaskId(task.id);
                            e.dataTransfer.setData("text/plain", task.id);
                            e.dataTransfer.effectAllowed = "move";
                          }}
                          onDragEnd={() => {
                            setDraggedTaskId(null);
                            setDragOverCol(null);
                          }}
                          onDoubleClick={() => {
                            if (!hasPermission) {
                              notify(lockTooltip, "error");
                              return;
                            }
                            openEditTaskModal(task);
                          }}
                          onContextMenu={(e) => {
                            e.preventDefault();
                            if (!hasPermission) {
                              notify(lockTooltip, "error");
                              return;
                            }
                            if (task.status !== "done") {
                              handleStatusChange(task.id, "done");
                              notify("Task marked as Done!", "success");
                            } else {
                              handleStatusChange(task.id, "in_progress");
                              notify("Task reopened to In Progress", "info");
                            }
                          }}
                        >
                          {/* Card Header: Priority & Actions */}
                          <div className="flex items-center justify-between" style={{ gap: "8px" }}>
                            <span className={`badge ${priorityBadges[task.priority]}`} style={{ textTransform: "uppercase", fontSize: "10px", letterSpacing: "0.5px", fontWeight: 700 }}>
                              {task.priority}
                            </span>
                            <div className="flex items-center gap-1">
                              {/* Live Stopwatch Button (Zoho / Jira style) */}
                              {activeTimer?.taskId === task.id ? (
                                <button
                                  type="button"
                                  className="btn btn-sm"
                                  style={{
                                    padding: "2px 7px",
                                    fontSize: "11px",
                                    fontWeight: 700,
                                    background: "#fef2f2",
                                    color: "#dc2626",
                                    border: "1px solid #fca5a5",
                                    borderRadius: "4px",
                                    cursor: "pointer",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "3px",
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    const stopped = stopTimer();
                                    if (stopped) {
                                      const hrs = Math.max(0.1, +(elapsedSeconds / 3600).toFixed(2));
                                      setLogTaskId(task.id);
                                      setLogHours(hrs.toString());
                                      setLogDesc(`Worked on: ${task.title}`);
                                      setTimeInputMode("duration");
                                      setShowTimeModal(true);
                                    }
                                  }}
                                  title="Stop Timer & Log Time"
                                >
                                  <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#dc2626", display: "inline-block", animation: "pulse 1.5s infinite" }} />
                                  ⏱️ {formatTime(elapsedSeconds)}
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  className="btn btn-ghost btn-sm"
                                  disabled={!hasPermission}
                                  style={{
                                    padding: "2px 6px",
                                    fontSize: "11px",
                                    borderRadius: "4px",
                                    color: hasPermission ? "#2563eb" : "#94a3b8",
                                    background: hasPermission ? "#eff6ff" : "#f1f5f9",
                                    border: `1px solid ${hasPermission ? "#bfdbfe" : "#e2e8f0"}`,
                                    cursor: hasPermission ? "pointer" : "not-allowed",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "3px",
                                    fontWeight: 600,
                                    opacity: hasPermission ? 1 : 0.6,
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    if (!hasPermission) {
                                      notify(lockTooltip, "error");
                                      return;
                                    }
                                    if (!id) return;
                                    startTimer({
                                      id: task.id,
                                      title: task.title,
                                      projectId: id,
                                      projectName: summary?.project.name || "Project",
                                    });
                                    notify(`Timer started for "${task.title}"`, "info");
                                  }}
                                  title={hasPermission ? "Start Live Stopwatch Timer" : lockTooltip}
                                >
                                  ▶ Start
                                </button>
                              )}

                              {task.status !== "done" ? (
                                <button
                                  type="button"
                                  className="btn btn-sm"
                                  disabled={!hasPermission}
                                  style={{
                                    padding: "2px 7px",
                                    fontSize: "11px",
                                    fontWeight: 700,
                                    background: hasPermission ? "#ecfdf5" : "#f1f5f9",
                                    color: hasPermission ? "#059669" : "#94a3b8",
                                    border: `1px solid ${hasPermission ? "#a7f3d0" : "#e2e8f0"}`,
                                    borderRadius: "4px",
                                    cursor: hasPermission ? "pointer" : "not-allowed",
                                    opacity: hasPermission ? 1 : 0.5,
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    if (!hasPermission) {
                                      notify(lockTooltip, "error");
                                      return;
                                    }
                                    handleStatusChange(task.id, "done");
                                    notify("Task marked as Done!", "success");
                                  }}
                                  title={hasPermission ? "Mark as Done" : lockTooltip}
                                >
                                  ✓
                                </button>
                              ) : (
                                <span
                                  style={{
                                    fontSize: "11px",
                                    fontWeight: 700,
                                    color: "#10b981",
                                    background: "#d1fae5",
                                    padding: "2px 7px",
                                    borderRadius: "4px",
                                  }}
                                  title="Completed"
                                >
                                  ✓
                                </span>
                              )}
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                disabled={!hasPermission}
                                style={{
                                  padding: "3px 6px",
                                  borderRadius: "4px",
                                  color: hasPermission ? "#64748b" : "#cbd5e1",
                                  cursor: hasPermission ? "pointer" : "not-allowed",
                                  display: "flex",
                                  alignItems: "center",
                                  opacity: hasPermission ? 1 : 0.5,
                                }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (!hasPermission) {
                                    notify(lockTooltip, "error");
                                    return;
                                  }
                                  openEditTaskModal(task);
                                }}
                                title={hasPermission ? "Edit Task" : lockTooltip}
                              >
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                                </svg>
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                style={{ padding: "2px 5px", fontSize: "12px", color: "#64748b" }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openTaskComments(task);
                                }}
                                title="Task comments (Read & Collaborate)"
                              >
                                💬
                              </button>
                            </div>
                          </div>

                          {/* Card Body */}
                          <div className="kanban-task-body" style={{ marginTop: "2px" }}>
                            <h4 className="kanban-task-title" style={{ fontSize: "0.92rem", lineHeight: "1.35", fontWeight: 600 }}>
                              {task.title}
                            </h4>
                            {task.description && (
                              <p className="kanban-task-desc" style={{ fontSize: "0.8rem", color: "#64748b", marginTop: "2px" }}>
                                {task.description}
                              </p>
                            )}
                          </div>

                          {/* Card Dates & Estimates */}
                          <div className="flex items-center justify-between" style={{ fontSize: "0.78rem", color: "#64748b", marginTop: "4px" }}>
                            <span>{task.due_date ? `📅 ${formatDate(task.due_date)}` : "No due date"}</span>
                            {task.estimated_hours ? (
                              <span style={{ fontWeight: 600, fontFamily: "monospace" }}>⏱️ {task.estimated_hours}h</span>
                            ) : null}
                          </div>

                          {/* Card Assignee Footer with Avatar & Inline Reassignment */}
                          <div
                            className="flex items-center justify-between pt-2 mt-1"
                            style={{ borderTop: "1px solid #f1f5f9", fontSize: "0.78rem" }}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              <span
                                style={{
                                  width: "20px",
                                  height: "20px",
                                  borderRadius: "50%",
                                  background: task.assigned_to_name ? "#2563eb" : "#94a3b8",
                                  color: "#fff",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  fontSize: "10px",
                                  fontWeight: 700,
                                }}
                              >
                                {task.assigned_to_name ? task.assigned_to_name.charAt(0).toUpperCase() : "?"}
                              </span>
                              <select
                                value={task.assigned_to || ""}
                                disabled={!hasPermission}
                                onChange={async (e) => {
                                  if (!hasPermission) {
                                    notify(lockTooltip, "error");
                                    return;
                                  }
                                  const newAssigneeId = e.target.value || null;
                                  try {
                                    await updateTask(task.id, { assigned_to: newAssigneeId || undefined });
                                    notify("Task assignee updated", "success");
                                    loadData();
                                  } catch {
                                    notify("Failed to reassign task", "error");
                                  }
                                }}
                                style={{
                                  padding: "2px 6px",
                                  fontSize: "0.75rem",
                                  borderRadius: "4px",
                                  border: "1px solid #e2e8f0",
                                  background: hasPermission ? "transparent" : "#f8fafc",
                                  color: task.assigned_to ? "var(--color-primary, #2563eb)" : "var(--color-muted, #64748b)",
                                  fontWeight: 500,
                                  cursor: hasPermission ? "pointer" : "not-allowed",
                                  maxWidth: "150px",
                                  opacity: hasPermission ? 1 : 0.7,
                                }}
                                title={hasPermission ? "Reassign task to team member" : lockTooltip}
                              >
                                <option value="">Unassigned</option>
                                {members.map((m) => (
                                  <option key={m.employee_id} value={m.employee_id}>
                                    {m.employee_name || "Team Member"}
                                  </option>
                                ))}
                              </select>
                            </div>
                            {task.assigned_to_designation && (
                              <span className="text-muted text-xs" style={{ maxWidth: "110px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {task.assigned_to_designation}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            );
          })}
          </div>
        </div>
      )}

      {/* TAB 2: MILESTONES */}
      {activeTab === "milestones" && (
        <div className="stack gap-4">
          {canManage && (
            <div className="flex justify-end">
              <button className="btn btn-primary btn-sm" onClick={openNewMilestoneModal}>
                + Add Milestone
              </button>
            </div>
          )}

          {milestones.length === 0 ? (
            <div className="card text-center p-8">
              <p className="text-muted text-sm">No milestones created yet for this project.</p>
            </div>
          ) : (
            <div className="stack gap-3">
              {milestones.map((ms) => (
                <div
                  key={ms.id}
                  className="card row-between align-center p-4"
                  onDoubleClick={() => openEditMilestoneModal(ms)}
                  style={{ cursor: "pointer" }}
                  title="Double-click to edit milestone"
                >
                  <div style={{ flex: 1, paddingRight: "1rem" }}>
                    <div className="row gap-2 align-center mb-1">
                      <h4 style={{ margin: 0 }}>{ms.title}</h4>
                      <span className={`badge ${ms.status === "completed" ? "badge-success" : "badge-info"}`}>
                        {ms.status.toUpperCase()}
                      </span>
                      {canManage && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          style={{
                            padding: "3px 6px",
                            borderRadius: "4px",
                            color: "#64748b",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                          onClick={(e) => {
                            e.stopPropagation();
                            openEditMilestoneModal(ms);
                          }}
                          title="Edit Milestone"
                        >
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                          </svg>
                        </button>
                      )}
                    </div>
                    {ms.description && <p className="text-muted text-sm mb-1">{ms.description}</p>}
                    <span className="text-muted text-xs">Target Date: <strong>{ms.due_date ? formatDate(ms.due_date) : "Not set"}</strong></span>
                  </div>

                  <div style={{ width: "160px" }}>
                    <div className="row-between text-xs mb-1">
                      <span className="text-muted">Progress</span>
                      <strong className="font-mono">{ms.completion_percentage}%</strong>
                    </div>
                    <div style={{ width: "100%", height: "6px", background: "var(--color-border)", borderRadius: "3px", overflow: "hidden" }}>
                      <div style={{ width: `${ms.completion_percentage}%`, height: "100%", background: "var(--color-primary)", borderRadius: "3px" }} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 3: TEAM MEMBERS */}
      {activeTab === "team" && (
        <div className="stack gap-4">
          <div className="flex justify-between items-center">
            <div>
              <h3 style={{ margin: 0, fontSize: "1.1rem" }}>Project Users & Resources</h3>
              <p className="text-muted text-sm" style={{ margin: "2px 0 0" }}>
                Active team members, project leads and contributors
              </p>
            </div>
            {canManage && (
              <button className="btn btn-primary btn-sm" onClick={() => setShowMemberModal(true)}>
                + Assign Team Member
              </button>
            )}
          </div>

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Team Member</th>
                  <th>Role</th>
                  <th>Department</th>
                  <th>Assigned On</th>
                  {canManage && <th style={{ textAlign: "right" }}>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {members.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="text-center text-muted p-4">
                      No members assigned to this project yet.
                    </td>
                  </tr>
                ) : (
                  members.map((m) => {
                    const emp = employeeList.find((e) => e.id === m.employee_id);
                    const empName =
                      m.employee_name ||
                      (emp ? `${emp.first_name} ${emp.last_name || ""}`.trim() : "Team Member");
                    const empCode = m.employee_code || emp?.employee_code;
                    const empEmail = m.employee_email || emp?.email;
                    const empPosition = m.designation || emp?.position || "Staff";
                    const empDept = m.department_name || "General";
                    const initials = empName
                      .split(" ")
                      .map((n) => n[0])
                      .slice(0, 2)
                      .join("")
                      .toUpperCase();

                    return (
                      <tr key={m.id}>
                        <td>
                          <div className="flex items-center gap-2">
                            <div
                              style={{
                                width: "36px",
                                height: "36px",
                                borderRadius: "50%",
                                background: "linear-gradient(135deg, #3b82f6, #1d4ed8)",
                                color: "#ffffff",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontWeight: 700,
                                fontSize: "0.85rem",
                                flexShrink: 0,
                              }}
                            >
                              {initials}
                            </div>
                            <div>
                              <div className="flex items-center gap-2">
                                <span style={{ fontWeight: 600 }}>{empName}</span>
                                {empCode && (
                                  <span className="badge badge-muted text-xs" style={{ padding: "1px 5px" }}>
                                    {empCode}
                                  </span>
                                )}
                              </div>
                              {empEmail && <div className="text-muted text-xs">{empEmail}</div>}
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className="stack" style={{ gap: "2px" }}>
                            <span className={`badge ${m.role === "lead" ? "badge-primary" : "badge-muted"}`} style={{ alignSelf: "flex-start" }}>
                              {m.role === "lead" ? "👑 Project Lead" : "Contributor"}
                            </span>
                            <span className="text-muted text-xs">{empPosition}</span>
                          </div>
                        </td>
                        <td>{empDept}</td>
                        <td>{formatDate(m.joined_at)}</td>
                        {canManage && (
                          <td style={{ textAlign: "right" }}>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm text-danger"
                              onClick={() => handleRemoveMember(m.employee_id)}
                            >
                              Remove
                            </button>
                          </td>
                        )}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 4: TIME LOGS */}
      {activeTab === "timelogs" && (
        <div className="stack gap-4">
          <div className="flex justify-between items-center">
            <div>
              <h3 style={{ margin: 0, fontSize: "1.1rem" }}>Project Timesheets & Logs</h3>
              <p className="text-muted text-sm" style={{ margin: "2px 0 0" }}>
                Total recorded billable and non-billable hours
              </p>
            </div>
            <button className="btn btn-primary btn-sm" onClick={() => setShowTimeModal(true)}>
              ⏱️ Log Time Entry
            </button>
          </div>

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table className="table text-sm">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Logged By</th>
                  <th>Task</th>
                  <th>Hours</th>
                  <th>Billable</th>
                  <th>Description</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {timeLogs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center text-muted p-4">
                      No time entries recorded for this project yet.
                    </td>
                  </tr>
                ) : (
                  timeLogs.map((entry) => (
                    <tr key={entry.id}>
                      <td>{formatDate(entry.date)}</td>
                      <td>
                        <div className="flex items-center gap-2">
                          <div
                            style={{
                              width: "24px",
                              height: "24px",
                              borderRadius: "50%",
                              background: "#eff6ff",
                              color: "#2563eb",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              fontSize: "11px",
                              fontWeight: 700,
                            }}
                          >
                            {(entry.employee_name || "M").charAt(0).toUpperCase()}
                          </div>
                          <span style={{ fontWeight: 600 }}>{entry.employee_name || "Team Member"}</span>
                        </div>
                      </td>
                      <td>
                        <span className="text-muted text-xs">{entry.task_title || "General Project Work"}</span>
                      </td>
                      <td style={{ fontWeight: 700, color: "var(--color-primary)" }}>
                        {entry.hours} hrs
                      </td>
                      <td>
                        <span className={`badge ${entry.is_billable ? "badge-success" : "badge-muted"}`}>
                          {entry.is_billable ? "Billable" : "Non-billable"}
                        </span>
                      </td>
                      <td className="text-muted">{entry.description || "—"}</td>
                      <td>
                        <span
                          className={`badge ${
                            entry.status === "approved"
                              ? "badge-success"
                              : entry.status === "rejected"
                              ? "badge-danger"
                              : "badge-muted"
                          }`}
                        >
                          {entry.status}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 5: DOCUMENTS & FILES */}
      {activeTab === "documents" && (
        <div className="stack gap-4">
          <div className="flex justify-between items-center">
            <div>
              <h3 style={{ margin: 0, fontSize: "1.1rem" }}>Project Documents & Files</h3>
              <p className="text-muted text-sm" style={{ margin: "2px 0 0" }}>
                Project specifications, requirements, architecture blueprints, contracts, and deliverables
              </p>
            </div>
            <button className="btn btn-primary btn-sm" onClick={() => setShowDocModal(true)}>
              📁 Upload Document
            </button>
          </div>

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table className="table text-sm">
              <thead>
                <tr>
                  <th>Document Name</th>
                  <th>Type</th>
                  <th>Size</th>
                  <th>Uploaded By</th>
                  <th>Upload Date</th>
                  <th style={{ textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {documents.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="text-center text-muted p-4">
                      No documents uploaded for this project yet. Click "Upload Document" to attach project files.
                    </td>
                  </tr>
                ) : (
                  documents.map((doc) => (
                    <tr key={doc.id}>
                      <td>
                        <div className="flex items-center gap-2">
                          <span style={{ fontSize: "1.2rem" }}>📄</span>
                          <div>
                            <div style={{ fontWeight: 600 }}>{doc.name}</div>
                            {doc.description && <div className="text-muted text-xs">{doc.description}</div>}
                          </div>
                        </div>
                      </td>
                      <td>
                        <span className="badge badge-muted text-xs">
                          {doc.file_type.split("/")[1]?.toUpperCase() || doc.file_type}
                        </span>
                      </td>
                      <td>{doc.file_size ? `${(Number(doc.file_size) / 1024).toFixed(1)} KB` : "—"}</td>
                      <td>{doc.uploaded_by_name || "Team Member"}</td>
                      <td>{formatDate(doc.created_at)}</td>
                      <td style={{ textAlign: "right" }}>
                        <div className="flex gap-2 justify-end">
                          {doc.download_url && (
                            <a
                              href={doc.download_url}
                              target="_blank"
                              rel="noreferrer"
                              className="btn btn-outline btn-sm"
                              style={{ textDecoration: "none" }}
                            >
                              Download ↓
                            </a>
                          )}
                          {canManage && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm text-danger"
                              onClick={() => handleDeleteDocument(doc.id)}
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 5: OVERVIEW & BUDGET */}
      {activeTab === "settings" && (
        <div className="stack gap-4">
          <div className="grid-2" style={{ gap: "1rem" }}>
            <div className="card">
              <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.4rem" }}>
                Project Metadata
              </h3>
              <div className="form-grid">
                <div className="field">
                  <label>Project Code</label>
                  <div style={{ fontWeight: 600 }}>{project.code}</div>
                </div>
                <div className="field">
                  <label>Client</label>
                  <div>{project.client_name || "Internal Project"}</div>
                </div>
                <div className="field">
                  <label>Start Date</label>
                  <div>{project.start_date ? formatDate(project.start_date) : "Not set"}</div>
                </div>
                <div className="field">
                  <label>Target Deadline</label>
                  <div>{project.deadline ? formatDate(project.deadline) : "Flexible"}</div>
                </div>
                <div className="field">
                  <label>Status</label>
                  <div>
                    <span className={`badge ${project.status === "active" ? "badge-success" : "badge-muted"}`}>
                      {project.status.toUpperCase()}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="card">
              <div className="row-between align-center" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem", marginBottom: "1rem" }}>
                <h3 style={{ fontSize: "1rem", margin: 0, fontWeight: 600 }}>
                  Financial & Budget Summary
                </h3>
                <span className="badge badge-outline text-xs font-mono" style={{ padding: "2px 8px" }}>
                  Timesheet Costed
                </span>
              </div>
              <div className="form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1.25rem" }}>
                <div className="field">
                  <label style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-muted)" }}>Total Budget</label>
                  <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "var(--color-primary)" }}>
                    ₹{project.budget ? Number(project.budget).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "0.00"}
                  </div>
                  <span className="text-muted text-xs">Fixed Project Budget</span>
                </div>

                <div className="field">
                  <label style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-muted)" }}>Budget Spent</label>
                  <div style={{ fontSize: "1.35rem", fontWeight: 700, color: Number(summary.budget_spent || 0) > 0 ? "#b45309" : "var(--color-text-default)" }}>
                    ₹{Number(summary.budget_spent || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <span className="text-muted text-xs">Approved Billable × Hourly Cost</span>
                </div>

                <div className="field">
                  <label style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-muted)" }}>Remaining Budget</label>
                  <div
                    style={{
                      fontSize: "1.35rem",
                      fontWeight: 700,
                      color:
                        summary.budget_remaining !== undefined && summary.budget_remaining !== null
                          ? Number(summary.budget_remaining) < 0
                            ? "#dc2626"
                            : "#16a34a"
                          : "var(--color-text-default)",
                    }}
                  >
                    ₹
                    {summary.budget_remaining !== undefined && summary.budget_remaining !== null
                      ? Number(summary.budget_remaining).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                      : project.budget
                      ? Number(project.budget).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                      : "0.00"}
                  </div>
                  <span className="text-muted text-xs">Total Budget − Budget Spent</span>
                </div>

                <div className="field">
                  <label style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-muted)" }}>Logged vs. Billable</label>
                  <div style={{ fontSize: "1.15rem", fontWeight: 600 }}>
                    {Number(summary.approved_logged_hours !== undefined ? summary.approved_logged_hours : summary.total_logged_hours).toFixed(2)} hrs /{" "}
                    <span style={{ color: "var(--color-primary)" }}>
                      {Number(summary.approved_billable_hours !== undefined ? summary.approved_billable_hours : summary.total_billable_hours).toFixed(2)} hrs
                    </span>
                  </div>
                  <span className="text-muted text-xs">Filtered by approved timesheets</span>
                </div>

                <div className="field">
                  <label style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-muted)" }}>Delivery Health</label>
                  <div style={{ marginTop: "4px" }}>
                    {summary.delivery_health === "Needs Attention" || summary.overdue_tasks > 0 ? (
                      <span className="badge badge-danger" style={{ fontSize: "12px", padding: "4px 10px", fontWeight: 600 }}>
                        ⚠️ Needs Attention ({summary.overdue_tasks} Overdue)
                      </span>
                    ) : summary.delivery_health === "In Progress" || (Number(summary.completion_percentage) === 0 && Number(summary.total_logged_hours) > 0) ? (
                      <span className="badge badge-primary" style={{ fontSize: "12px", padding: "4px 10px", fontWeight: 600, background: "rgba(37, 99, 235, 0.12)", color: "#2563eb", border: "1px solid rgba(37, 99, 235, 0.3)" }}>
                        🔵 In Progress
                      </span>
                    ) : summary.delivery_health === "On Schedule" || Number(summary.completion_percentage) > 0 ? (
                      <span className="badge badge-success" style={{ fontSize: "12px", padding: "4px 10px", fontWeight: 600 }}>
                        ✓ On Schedule
                      </span>
                    ) : (
                      <span className="badge badge-muted" style={{ fontSize: "12px", padding: "4px 10px", fontWeight: 600 }}>
                        ⚪ Not Started
                      </span>
                    )}
                  </div>
                  <span className="text-muted text-xs" style={{ display: "block", marginTop: "4px" }}>
                    {Number(summary.completion_percentage)}% completed ({summary.completed_tasks}/{summary.total_tasks} tasks)
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TASK MODAL (CREATE / EDIT) */}
      {showTaskModal && (
        <div className="modal-backdrop" onClick={() => setShowTaskModal(false)}>
          <div className="modal card" style={{ maxWidth: "480px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{editingTaskId ? "Edit Task" : "+ Create Task"}</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowTaskModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleSaveTask} className="stack gap-4 my-2">
              <div className="field">
                <label>Task Title *</label>
                <input type="text" value={taskTitle} onChange={(e) => setTaskTitle(e.target.value)} required />
              </div>
              <div className="grid-2">
                <div className="field">
                  <label>Priority</label>
                  <select value={taskPriority} onChange={(e) => setTaskPriority(e.target.value as TaskPriority)}>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
                <div className="field">
                  <label>Status</label>
                  <select value={taskStatus} onChange={(e) => setTaskStatus(e.target.value as TaskStatus)}>
                    <option value="todo">To Do</option>
                    <option value="in_progress">In Progress</option>
                    <option value="review">In Review</option>
                    <option value="done">Completed</option>
                  </select>
                </div>
              </div>
              <div className="field">
                <label>Assign to Team Member</label>
                <select
                  value={taskAssignedTo}
                  onChange={(e) => setTaskAssignedTo(e.target.value)}
                  disabled={members.length === 0}
                >
                  <option value="">
                    {members.length === 0
                      ? "-- No members in project yet --"
                      : "-- Unassigned --"}
                  </option>
                  {members.map((m) => (
                    <option key={m.employee_id} value={m.employee_id}>
                      {m.employee_name || "Team Member"} ({m.designation || "Staff"} • {m.role === "lead" ? "👑 Lead" : "Member"})
                    </option>
                  ))}
                </select>
                {members.length === 0 ? (
                  <span className="field-hint text-warning" style={{ fontSize: "0.75rem", display: "block", marginTop: "3px" }}>
                    ⚠️ No members in this project yet. Add team members under the <strong>Users & Team</strong> tab first.
                  </span>
                ) : (
                  <span className="field-hint" style={{ fontSize: "0.75rem" }}>
                    Select an assigned team contributor or leave unassigned.
                  </span>
                )}
              </div>
              <div className="grid-2">
                <div className="field">
                  <label>Est. Hours</label>
                  <input type="number" step="any" min="0" placeholder="e.g. 15" value={taskEstHours} onChange={(e) => setTaskEstHours(e.target.value)} />
                </div>
                <div className="field">
                  <label>Due Date</label>
                  <input type="date" value={taskDueDate} onChange={(e) => setTaskDueDate(e.target.value)} />
                </div>
              </div>
              <div className="field">
                <label>Description</label>
                <textarea rows={3} value={taskDesc} onChange={(e) => setTaskDesc(e.target.value)} />
              </div>
              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowTaskModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submittingTask}>
                  {submittingTask ? "Saving..." : editingTaskId ? "Update Task" : "Create Task"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* COMMENTS MODAL */}
      {activeCommentTask && (
        <div className="modal-backdrop" onClick={() => setActiveCommentTask(null)}>
          <div className="modal card" style={{ maxWidth: "500px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Comments: {activeCommentTask.title}</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setActiveCommentTask(null)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <div className="stack gap-2 my-2" style={{ maxHeight: "280px", overflowY: "auto", padding: "0.25rem" }}>
              {loadingComments ? (
                <p className="text-muted">Loading comments...</p>
              ) : comments.length === 0 ? (
                <p className="text-muted text-sm text-center p-4">No comments yet. Start the conversation!</p>
              ) : (
                comments.map((c) => (
                  <div key={c.id} className="card p-3" style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)" }}>
                    <p style={{ margin: 0, fontSize: "0.9rem" }}>{c.comment}</p>
                    <span className="text-muted text-xs">{formatDateTime(c.created_at)}</span>
                  </div>
                ))
              )}
            </div>
            <form onSubmit={handlePostComment} className="flex gap-2 mt-3">
              <input
                type="text"
                style={{ flex: 1 }}
                placeholder="Write a comment..."
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                required
              />
              <button type="submit" className="btn btn-primary btn-sm">Post</button>
            </form>
          </div>
        </div>
      )}

      {/* MILESTONE MODAL (CREATE / EDIT) */}
      {showMilestoneModal && (
        <div className="modal-backdrop" onClick={() => setShowMilestoneModal(false)}>
          <div className="modal card" style={{ maxWidth: "480px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{editingMsId ? "Edit Milestone" : "+ Create Milestone"}</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowMilestoneModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleSaveMilestone} className="stack gap-4 my-2">
              <div className="field">
                <label>Milestone Title *</label>
                <input type="text" value={msTitle} onChange={(e) => setMsTitle(e.target.value)} required />
              </div>
              <div className="grid-2">
                <div className="field">
                  <div className="row-between align-center mb-1">
                    <label style={{ margin: 0 }}>Completion %</label>
                    {tasks.length > 0 && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-xs text-primary"
                        style={{ padding: "0 4px", fontSize: "0.7rem", fontWeight: 600 }}
                        onClick={() => {
                          const autoPct = summary.completion_percentage || 0;
                          setMsPct(String(autoPct));
                          if (autoPct >= 100) setMsStatus("completed");
                          else if (autoPct > 0) setMsStatus("in_progress");
                          notify(`Calculated ${autoPct}% based on completed tasks`, "info");
                        }}
                        title="Calculate percentage based on completed tasks in project"
                      >
                        ⚡ Sync from Tasks ({summary.completion_percentage}%)
                      </button>
                    )}
                  </div>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={msPct}
                    onChange={(e) => {
                      const val = e.target.value;
                      setMsPct(val);
                      if (Number(val) >= 100) setMsStatus("completed");
                      else if (Number(val) > 0 && msStatus === "pending") setMsStatus("in_progress");
                    }}
                  />
                  <span className="field-hint" style={{ fontSize: "0.72rem" }}>
                    Auto-calculates from linked project tasks ({summary.completed_tasks}/{summary.total_tasks} completed).
                  </span>
                </div>
                <div className="field">
                  <label>Status</label>
                  <select value={msStatus} onChange={(e) => setMsStatus(e.target.value as MilestoneStatus)}>
                    <option value="pending">Pending</option>
                    <option value="in_progress">In Progress</option>
                    <option value="completed">Completed</option>
                    <option value="missed">Missed</option>
                  </select>
                </div>
              </div>
              <div className="field">
                <label>Due Date</label>
                <input type="date" value={msDueDate} onChange={(e) => setMsDueDate(e.target.value)} />
              </div>
              <div className="field">
                <label>Description</label>
                <textarea rows={2} value={msDesc} onChange={(e) => setMsDesc(e.target.value)} />
              </div>
              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowMilestoneModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submittingMs}>
                  {submittingMs ? "Saving..." : editingMsId ? "Update Milestone" : "Create Milestone"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* EDIT PROJECT MODAL */}
      {showProjectEditModal && (
        <div className="modal-backdrop" onClick={() => setShowProjectEditModal(false)}>
          <div className="modal card" style={{ maxWidth: "540px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Edit Project Workspace</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowProjectEditModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleSaveProject} className="stack gap-4 my-2">
              <div className="grid-2">
                <div className="field">
                  <label>Project Name *</label>
                  <input
                    type="text"
                    value={editProjName}
                    onChange={(e) => setEditProjName(e.target.value)}
                    required
                  />
                </div>
                <div className="field">
                  <label>Project Code *</label>
                  <input
                    type="text"
                    value={editProjCode}
                    onChange={(e) => setEditProjCode(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="grid-2">
                <div className="field">
                  <label>Client Name</label>
                  <input
                    type="text"
                    placeholder="e.g. Internal Risk / FinCorp"
                    value={editProjClient}
                    onChange={(e) => setEditProjClient(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label>Budget ($ / Currency)</label>
                  <input
                    type="number"
                    step="100"
                    placeholder="e.g. 50000"
                    value={editProjBudget}
                    onChange={(e) => setEditProjBudget(e.target.value)}
                  />
                </div>
              </div>

              <div className="grid-2">
                <div className="field">
                  <label>Status</label>
                  <select
                    value={editProjStatus}
                    onChange={(e) => setEditProjStatus(e.target.value as ProjectStatus)}
                  >
                    <option value="planning">Planning</option>
                    <option value="active">Active</option>
                    <option value="on_hold">On Hold</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
                <div className="field">
                  <label>Target Deadline</label>
                  <input
                    type="date"
                    value={editProjDeadline}
                    onChange={(e) => setEditProjDeadline(e.target.value)}
                  />
                </div>
              </div>

              <div className="field">
                <label>Start Date</label>
                <input
                  type="date"
                  value={editProjStartDate}
                  onChange={(e) => setEditProjStartDate(e.target.value)}
                />
              </div>

              <div className="field">
                <label>Description / Scope</label>
                <textarea
                  rows={3}
                  value={editProjDesc}
                  onChange={(e) => setEditProjDesc(e.target.value)}
                  placeholder="Outline scope, goals and deliverables..."
                />
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setShowProjectEditModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={submittingProjectEdit}
                >
                  {submittingProjectEdit ? "Saving Changes..." : "Save Changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ADD MEMBER MODAL */}
      {showMemberModal && (
        <div className="modal-backdrop" onClick={() => setShowMemberModal(false)}>
          <div className="modal card" style={{ maxWidth: "480px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Assign Team Member</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowMemberModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleAddMember} className="stack gap-4 my-2">
              <div className="field">
                <label>Select Employee *</label>
                <select
                  value={memberEmployeeId}
                  onChange={(e) => setMemberEmployeeId(e.target.value)}
                  required
                >
                  <option value="">-- Choose Team Member --</option>
                  {employeeList.map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.first_name} {emp.last_name || ""} ({emp.employee_code} • {emp.position || "Staff"})
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Project Role</label>
                <select value={memberRole} onChange={(e) => setMemberRole(e.target.value as any)}>
                  <option value="member">Contributor / Developer</option>
                  <option value="lead">👑 Project Lead / Manager</option>
                </select>
              </div>
              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowMemberModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submittingMember}>
                  {submittingMember ? "Saving..." : "Assign Member"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* LOG TIME MODAL */}
      {showTimeModal && (
        <div className="modal-backdrop" onClick={() => setShowTimeModal(false)}>
          <div className="modal card" style={{ maxWidth: "480px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Log Hours: {project.name}</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowTimeModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>

            {/* 3 Modes Switcher (Zoho Projects / ClickUp style) */}
            <div style={{ display: "flex", gap: "6px", background: "#f1f5f9", padding: "4px", borderRadius: "6px", marginBottom: "1rem" }}>
              <button
                type="button"
                style={{
                  flex: 1,
                  padding: "6px 8px",
                  fontSize: "12px",
                  fontWeight: 600,
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  background: timeInputMode === "duration" ? "#fff" : "transparent",
                  color: timeInputMode === "duration" ? "#2563eb" : "#64748b",
                  boxShadow: timeInputMode === "duration" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
                }}
                onClick={() => setTimeInputMode("duration")}
              >
                🔢 Duration (Hours)
              </button>
              <button
                type="button"
                style={{
                  flex: 1,
                  padding: "6px 8px",
                  fontSize: "12px",
                  fontWeight: 600,
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  background: timeInputMode === "range" ? "#fff" : "transparent",
                  color: timeInputMode === "range" ? "#2563eb" : "#64748b",
                  boxShadow: timeInputMode === "range" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
                }}
                onClick={() => {
                  setTimeInputMode("range");
                  // Auto calculate hours from 09:00 to 17:00 minus 60min = 7.00
                  setLogHours("7.00");
                }}
              >
                🕒 Start / End Time
              </button>
              <button
                type="button"
                style={{
                  flex: 1,
                  padding: "6px 8px",
                  fontSize: "12px",
                  fontWeight: 600,
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  background: timeInputMode === "stopwatch" ? "#fff" : "transparent",
                  color: timeInputMode === "stopwatch" ? "#2563eb" : "#64748b",
                  boxShadow: timeInputMode === "stopwatch" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
                }}
                onClick={() => setTimeInputMode("stopwatch")}
              >
                ⏱️ Stopwatch
              </button>
            </div>

            <form onSubmit={handleLogTime} className="stack gap-4 my-2">
              {/* Employee Selector for Admins / Managers */}
              {canManage && (
                <div className="field">
                  <label>Log Time On Behalf Of (Employee)</label>
                  <select
                    value={logEmployeeId}
                    onChange={(e) => setLogEmployeeId(e.target.value)}
                  >
                    <option value="">
                      {members.length > 0 ? "-- Current User / Auto Member --" : "-- Select Employee --"}
                    </option>
                    {members.map((m) => (
                      <option key={m.employee_id} value={m.employee_id}>
                        {m.employee_name || "Team Member"} ({m.designation || "Staff"} • {m.role === "lead" ? "👑 Lead" : "Member"})
                      </option>
                    ))}
                    {employeeList
                      .filter((emp) => !members.some((m) => m.employee_id === emp.id))
                      .map((emp) => (
                        <option key={emp.id} value={emp.id}>
                          {emp.first_name} {emp.last_name || ""} ({emp.employee_code} • {emp.position || "Staff"}) [External]
                        </option>
                      ))}
                  </select>
                  <span className="field-hint" style={{ fontSize: "0.75rem" }}>
                    Captures which employee completed the work so hours attribute accurately in reports.
                  </span>
                </div>
              )}

              {/* Task Binding Selector */}
              <div className="field">
                <label>Attached Task (Task Card Binding)</label>
                <select
                  value={logTaskId}
                  onChange={(e) => {
                    const tid = e.target.value;
                    setLogTaskId(tid);
                    if (tid) {
                      const t = tasks.find((tk) => tk.id === tid);
                      if (t && !logDesc) {
                        setLogDesc(`Worked on: ${t.title}`);
                      }
                    }
                  }}
                >
                  <option value="">-- General Project Work (Unlinked) --</option>
                  {canManage || isProjectLead ? (
                    <>
                      <optgroup label="My Assigned Tasks">
                        {tasks
                          .filter((t) => user?.employee?.id && t.assigned_to === user.employee.id)
                          .map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.title} ({t.status.toUpperCase()})
                            </option>
                          ))}
                      </optgroup>
                      <optgroup label="Team Member Tasks">
                        {tasks
                          .filter((t) => !user?.employee?.id || t.assigned_to !== user.employee.id)
                          .map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.title} — {t.assigned_to_name || "Unassigned"} ({t.status.toUpperCase()})
                            </option>
                          ))}
                      </optgroup>
                    </>
                  ) : (
                    tasks
                      .filter((t) => user?.employee?.id && t.assigned_to === user.employee.id)
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.title} ({t.status.toUpperCase()})
                        </option>
                      ))
                  )}
                </select>
                <span className="field-hint" style={{ fontSize: "0.75rem" }}>
                  {!canManage && !isProjectLead && tasks.every((t) => !user?.employee?.id || t.assigned_to !== user.employee.id)
                    ? "ℹ️ You have no assigned tasks in this project yet. Log time as general project work."
                    : "Binds logged hours directly to the task card to synchronize progress."}
                </span>
              </div>

              <div className="field">
                <label>Log Date *</label>
                <input
                  type="date"
                  value={logDate}
                  onChange={(e) => setLogDate(e.target.value)}
                  required
                />
              </div>

              {/* Mode 1: Duration */}
              {timeInputMode === "duration" && (
                <div className="field">
                  <label>Hours Spent * (e.g. 7, 7.5)</label>
                  <input
                    type="number"
                    step="any"
                    min="0.1"
                    max="24"
                    placeholder="e.g. 7 or 7.5"
                    value={logHours}
                    onChange={(e) => setLogHours(e.target.value)}
                    required
                  />
                </div>
              )}

              {/* Mode 2: Start / End Range */}
              {timeInputMode === "range" && (
                <div className="stack gap-3" style={{ background: "#f8fafc", padding: "12px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                  <div className="grid-2">
                    <div className="field">
                      <label style={{ fontSize: "12px" }}>Start Time</label>
                      <input
                        type="time"
                        value={logStartTime}
                        onChange={(e) => {
                          setLogStartTime(e.target.value);
                          // Calculate diff
                          const [sh, sm] = e.target.value.split(":").map(Number);
                          const [eh, em] = logEndTime.split(":").map(Number);
                          const startM = sh * 60 + sm;
                          const endM = eh * 60 + em;
                          const breakM = parseInt(logBreakMinutes) || 0;
                          const diff = Math.max(0, (endM - startM - breakM) / 60);
                          setLogHours(diff.toFixed(2));
                        }}
                      />
                    </div>
                    <div className="field">
                      <label style={{ fontSize: "12px" }}>End Time</label>
                      <input
                        type="time"
                        value={logEndTime}
                        onChange={(e) => {
                          setLogEndTime(e.target.value);
                          const [sh, sm] = logStartTime.split(":").map(Number);
                          const [eh, em] = e.target.value.split(":").map(Number);
                          const startM = sh * 60 + sm;
                          const endM = eh * 60 + em;
                          const breakM = parseInt(logBreakMinutes) || 0;
                          const diff = Math.max(0, (endM - startM - breakM) / 60);
                          setLogHours(diff.toFixed(2));
                        }}
                      />
                    </div>
                  </div>
                  <div className="grid-2">
                    <div className="field">
                      <label style={{ fontSize: "12px" }}>Break Deduction (minutes)</label>
                      <input
                        type="number"
                        min="0"
                        max="240"
                        value={logBreakMinutes}
                        onChange={(e) => {
                          setLogBreakMinutes(e.target.value);
                          const [sh, sm] = logStartTime.split(":").map(Number);
                          const [eh, em] = logEndTime.split(":").map(Number);
                          const startM = sh * 60 + sm;
                          const endM = eh * 60 + em;
                          const breakM = parseInt(e.target.value) || 0;
                          const diff = Math.max(0, (endM - startM - breakM) / 60);
                          setLogHours(diff.toFixed(2));
                        }}
                      />
                    </div>
                    <div className="field">
                      <label style={{ fontSize: "12px", fontWeight: 700 }}>Calculated Hours</label>
                      <input
                        type="text"
                        readOnly
                        value={`${logHours || "0.00"} hrs`}
                        style={{ background: "#e2e8f0", fontWeight: 700, color: "#1e293b" }}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Mode 3: Live Stopwatch */}
              {timeInputMode === "stopwatch" && (
                <div className="stack gap-3 text-center" style={{ background: "#0f172a", color: "#fff", padding: "16px", borderRadius: "8px" }}>
                  <div style={{ fontSize: "12px", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "1px" }}>
                    Live Task Stopwatch
                  </div>
                  <div style={{ fontSize: "2rem", fontFamily: "monospace", fontWeight: 800, color: "#34d399", letterSpacing: "2px" }}>
                    ⏱️ {formatTime(elapsedSeconds)}
                  </div>
                  <div className="flex gap-2 justify-center">
                    {activeTimer ? (
                      <button
                        type="button"
                        style={{ background: "#ef4444", color: "#fff", border: "none", padding: "8px 16px", borderRadius: "6px", fontWeight: 700, cursor: "pointer" }}
                        onClick={() => {
                          const stopped = stopTimer();
                          if (stopped) {
                            const hrs = Math.max(0.1, +(elapsedSeconds / 3600).toFixed(2));
                            setLogHours(hrs.toString());
                            setTimeInputMode("duration");
                          }
                        }}
                      >
                        ⏹ Stop & Use {Math.max(0.1, +(elapsedSeconds / 3600).toFixed(2))}h
                      </button>
                    ) : (
                      <button
                        type="button"
                        style={{ background: "#10b981", color: "#fff", border: "none", padding: "8px 16px", borderRadius: "6px", fontWeight: 700, cursor: "pointer" }}
                        onClick={() => {
                          if (!id) return;
                          startTimer({
                            id: logTaskId || "general",
                            title: logTaskId ? (tasks.find(t => t.id === logTaskId)?.title || "Task") : `${project.name} General Work`,
                            projectId: id,
                            projectName: project.name,
                          });
                        }}
                      >
                        ▶ Start Timer Now
                      </button>
                    )}
                  </div>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>
                    Hours Spent: <b>{logHours || "0.00"} hrs</b>
                  </div>
                </div>
              )}

              <div className="field">
                <label>Work Description *</label>
                <textarea
                  rows={3}
                  placeholder="Summarize what was worked on today..."
                  value={logDesc}
                  onChange={(e) => setLogDesc(e.target.value)}
                  required
                />
              </div>

              <div className="field">
                <label className="flex items-center gap-2" style={{ cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={logBillable}
                    onChange={(e) => setLogBillable(e.target.checked)}
                  />
                  <span>Billable Hours (Count towards client invoice)</span>
                </label>
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowTimeModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingTime}>
                  {submittingTime ? "Logging..." : "Log Time"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* DOCUMENT UPLOAD MODAL */}
      {showDocModal && (
        <div className="modal-backdrop" onClick={() => setShowDocModal(false)}>
          <div className="modal card" style={{ maxWidth: "480px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Upload Project Document</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowDocModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleUploadDocument} className="stack gap-4 my-2">
              <div className="field">
                <label>Select File *</label>
                <input
                  type="file"
                  accept=".pdf,.docx,.doc,.png,.jpg,.jpeg,.xlsx,.xls,.zip"
                  onChange={(e) => {
                    const file = e.target.files?.[0] || null;
                    if (file && file.size > 25 * 1024 * 1024) {
                      notify("File size exceeds the 25MB limit.", "error");
                      e.target.value = "";
                      setUploadFile(null);
                      return;
                    }
                    setUploadFile(file);
                  }}
                  required
                />
                <span className="field-hint" style={{ fontSize: "0.75rem", display: "block", marginTop: "3px" }}>
                  Supported formats: <strong>PDF, DOCX, PNG, JPG, XLSX, ZIP</strong> up to <strong>25MB</strong>.
                </span>
              </div>
              <div className="field">
                <label>Document Description / Notes (Optional)</label>
                <textarea
                  rows={2}
                  placeholder="e.g. System architecture diagram, Client contract, PRD..."
                  value={docDesc}
                  onChange={(e) => setDocDesc(e.target.value)}
                />
              </div>
              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowDocModal(false)} disabled={uploadingDoc}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={uploadingDoc || !uploadFile}>
                  {uploadingDoc ? (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                      <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true" style={{ width: "14px", height: "14px", border: "2px solid #fff", borderRightColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.75s linear infinite" }} />
                      Uploading File...
                    </span>
                  ) : (
                    "Upload Document"
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
