import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  fetchProjectSummary, fetchTasks, createTask, updateTask,
  fetchProjectMembers, addProjectMember, removeProjectMember,
  fetchMilestones, createMilestone, updateMilestone, updateProject,
  fetchTaskComments, addTaskComment,
  fetchTimeEntries, createTimeEntry
} from "../api";
import type {
  ProjectSummary, ProjectStatus, Task, TaskStatus, TaskPriority,
  ProjectMember, Milestone, MilestoneStatus, TaskComment, TimeEntry
} from "../types";
import { listEmployees, type Employee } from "../../hr/api";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { formatDate, formatDateTime } from "../../../shared/utils/date";

export function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const canManage = user?.role === "hr_admin" || user?.role === "super_admin" || user?.role === "manager";

  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [timeLogs, setTimeLogs] = useState<TimeEntry[]>([]);
  const [employeeList, setEmployeeList] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"kanban" | "milestones" | "team" | "timelogs" | "settings">("kanban");

  // Drag-and-drop State
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null);
  const [dragOverCol, setDragOverCol] = useState<TaskStatus | null>(null);

  // Log Time Modal in Project
  const [showTimeModal, setShowTimeModal] = useState(false);
  const [logDate, setLogDate] = useState(new Date().toISOString().slice(0, 10));
  const [logHours, setLogHours] = useState("");
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
      const [sumRes, taskRes, memRes, msRes, timeRes, empRes] = await Promise.all([
        fetchProjectSummary(id),
        fetchTasks(id),
        fetchProjectMembers(id),
        fetchMilestones(id),
        fetchTimeEntries({ projectId: id }).catch(() => []),
        listEmployees({ page: 1, limit: 100 }).catch(() => ({ items: [] }))
      ]);
      setSummary(sumRes);
      setTasks(taskRes);
      setMembers(memRes);
      setMilestones(msRes);
      setTimeLogs(timeRes);
      setEmployeeList(empRes.items || []);
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
    setMsPct("0");
    setMsStatus("pending");
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
                style={{ padding: "4px 8px", fontSize: "14px", color: "#64748b" }}
                onClick={openEditProjectModal}
                title="Edit Project Details (✏️)"
              >
                ✏️
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
              onClick={openEditProjectModal}
              title="Edit Project"
            >
              ✏️ Edit Project
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
          <div className="text-muted text-xs mt-2">
            {summary.overdue_tasks > 0 ? "⚠️ Needs Attention" : "✓ On Track"}
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
        <div className="kanban-board">
            {kanbanColumns.map((col) => {
              const colTasks = tasks.filter((t) => t.status === col.key);
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
                      return (
                        <div
                          key={task.id}
                          className={`kanban-task-card ${isDraggingThis ? "is-dragging" : ""}`}
                          draggable
                          onDragStart={(e) => {
                            setDraggedTaskId(task.id);
                            e.dataTransfer.setData("text/plain", task.id);
                            e.dataTransfer.effectAllowed = "move";
                          }}
                          onDragEnd={() => {
                            setDraggedTaskId(null);
                            setDragOverCol(null);
                          }}
                          onDoubleClick={() => openEditTaskModal(task)}
                          onContextMenu={(e) => {
                            e.preventDefault();
                            if (task.status !== "done") {
                              handleStatusChange(task.id, "done");
                              notify("Task marked as Done!", "success");
                            } else {
                              handleStatusChange(task.id, "in_progress");
                              notify("Task reopened to In Progress", "info");
                            }
                          }}
                          title="Drag to move • Double-click to edit ✏️ • Right-click to toggle Done"
                        >
                          <div className="row-between align-center">
                            <span className={`badge ${priorityBadges[task.priority]}`} style={{ textTransform: "uppercase", fontSize: "10px", letterSpacing: "0.5px" }}>
                              {task.priority}
                            </span>
                            <div className="flex items-center gap-1">
                              <span
                                style={{
                                  fontSize: "12px",
                                  color: "#94a3b8",
                                  cursor: "grab",
                                  padding: "0 2px",
                                  userSelect: "none"
                                }}
                                title="Drag card"
                              >
                                ⠿
                              </span>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                style={{ padding: "2px 6px", fontSize: "12px", color: "#64748b" }}
                                onClick={() => openEditTaskModal(task)}
                                title="Edit Task (✏️)"
                              >
                                ✏️
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                style={{ padding: "2px 6px", fontSize: "13px" }}
                                onClick={() => openTaskComments(task)}
                                title="Task comments"
                              >
                                💬
                              </button>
                            </div>
                          </div>

                          <div className="kanban-task-body">
                            <h4 className="kanban-task-title">{task.title}</h4>
                            {task.description && (
                              <p className="kanban-task-desc">{task.description}</p>
                            )}
                          </div>

                          <div className="kanban-task-footer">
                            <span className="text-muted text-xs">
                              {task.due_date ? `📅 ${formatDate(task.due_date)}` : "No due date"}
                            </span>
                            
                            {task.status !== "done" ? (
                              <button
                                type="button"
                                className="btn btn-sm"
                                style={{
                                  padding: "2px 8px",
                                  fontSize: "11px",
                                  fontWeight: 600,
                                  background: "#ecfdf5",
                                  color: "#059669",
                                  border: "1px solid #a7f3d0",
                                  borderRadius: "4px",
                                  display: "flex",
                                  alignItems: "center",
                                  gap: "3px",
                                  cursor: "pointer"
                                }}
                                onClick={() => {
                                  handleStatusChange(task.id, "done");
                                }}
                                title="Mark as Done"
                              >
                                ✓ Done
                              </button>
                            ) : (
                              <span
                                style={{
                                  fontSize: "11px",
                                  fontWeight: 600,
                                  color: "#10b981",
                                  display: "flex",
                                  alignItems: "center",
                                  gap: "3px"
                                }}
                              >
                                ✓ Completed
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
                  title="Double-click to edit milestone ✏️"
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
                          style={{ padding: "2px 6px", fontSize: "12px", color: "#64748b" }}
                          onClick={(e) => {
                            e.stopPropagation();
                            openEditMilestoneModal(ms);
                          }}
                          title="Edit Milestone (✏️)"
                        >
                          ✏️
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
                    const empName = emp ? `${emp.first_name} ${emp.last_name || ""}`.trim() : m.employee_id.substring(0, 8);
                    const empEmail = emp?.email;
                    return (
                      <tr key={m.id}>
                        <td>
                          <div className="flex items-center gap-2">
                            <div
                              style={{
                                width: "32px",
                                height: "32px",
                                borderRadius: "50%",
                                background: "#eff6ff",
                                color: "#2563eb",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontWeight: 700,
                                fontSize: "0.8rem",
                              }}
                            >
                              {empName.charAt(0).toUpperCase()}
                            </div>
                            <div>
                              <div style={{ fontWeight: 600 }}>{empName}</div>
                              {empEmail && <div className="text-muted text-xs">{empEmail}</div>}
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className={`badge ${m.role === "lead" ? "badge-primary" : "badge-muted"}`}>
                            {m.role === "lead" ? "👑 Project Lead" : "Contributor"}
                          </span>
                        </td>
                        <td>{emp?.position || "Engineering / Staff"}</td>
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
                  <th>Hours</th>
                  <th>Billable</th>
                  <th>Description</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {timeLogs.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="text-center text-muted p-4">
                      No time entries recorded for this project yet.
                    </td>
                  </tr>
                ) : (
                  timeLogs.map((entry) => (
                    <tr key={entry.id}>
                      <td>{formatDate(entry.date)}</td>
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
              <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.4rem" }}>
                Financial & Budget Summary
              </h3>
              <div className="form-grid">
                <div className="field">
                  <label>Total Budget</label>
                  <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--color-primary)" }}>
                    ₹{project.budget ? Number(project.budget).toLocaleString("en-IN", { minimumFractionDigits: 2 }) : "Not defined"}
                  </div>
                </div>
                <div className="field">
                  <label>Billable Hours</label>
                  <div style={{ fontWeight: 600 }}>{summary.total_billable_hours} hrs</div>
                </div>
                <div className="field">
                  <label>Total Logged Hours</label>
                  <div style={{ fontWeight: 600 }}>{summary.total_logged_hours} hrs</div>
                </div>
                <div className="field">
                  <label>Delivery Health</label>
                  <div style={{ fontWeight: 600, color: summary.overdue_tasks > 0 ? "#dc2626" : "#16a34a" }}>
                    {summary.overdue_tasks > 0 ? `⚠️ ${summary.overdue_tasks} Overdue Task(s)` : "✓ On Schedule"}
                  </div>
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
              <h2>{editingTaskId ? "✏️ Edit Task" : "+ Create Task"}</h2>
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
              <div className="grid-2">
                <div className="field">
                  <label>Est. Hours</label>
                  <input type="number" step="0.5" value={taskEstHours} onChange={(e) => setTaskEstHours(e.target.value)} />
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
              <h2>{editingMsId ? "✏️ Edit Milestone" : "+ Create Milestone"}</h2>
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
                  <label>Completion %</label>
                  <input type="number" min="0" max="100" value={msPct} onChange={(e) => setMsPct(e.target.value)} />
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
              <h2>✏️ Edit Project Workspace</h2>
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
            <form onSubmit={handleLogTime} className="stack gap-4 my-2">
              <div className="grid-2">
                <div className="field">
                  <label>Log Date *</label>
                  <input
                    type="date"
                    value={logDate}
                    onChange={(e) => setLogDate(e.target.value)}
                    required
                  />
                </div>
                <div className="field">
                  <label>Hours Spent *</label>
                  <input
                    type="number"
                    step="0.5"
                    min="0.1"
                    max="24"
                    placeholder="e.g. 7.5"
                    value={logHours}
                    onChange={(e) => setLogHours(e.target.value)}
                    required
                  />
                </div>
              </div>

              {tasks.length > 0 && (
                <div className="field">
                  <label>Link to Task (Optional)</label>
                  <select
                    value={logTaskId}
                    onChange={(e) => setLogTaskId(e.target.value)}
                  >
                    <option value="">-- General Project Work --</option>
                    {tasks.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.title} ({t.status.toUpperCase()})
                      </option>
                    ))}
                  </select>
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
    </div>
  );
}
