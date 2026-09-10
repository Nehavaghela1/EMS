import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  fetchProjectSummary, fetchTasks, createTask, updateTask,
  fetchProjectMembers, addProjectMember, removeProjectMember,
  fetchMilestones, createMilestone,
  fetchTaskComments, addTaskComment
} from "../api";
import type {
  ProjectSummary, Task, TaskStatus, TaskPriority,
  ProjectMember, Milestone, TaskComment
} from "../types";
import { useToast } from "../../../app/toast-context";

export function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"kanban" | "milestones" | "team">("kanban");

  // Task Modal
  const [showTaskModal, setShowTaskModal] = useState(false);
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDesc, setTaskDesc] = useState("");
  const [taskPriority, setTaskPriority] = useState<TaskPriority>("medium");
  const [taskDueDate, setTaskDueDate] = useState("");
  const [taskEstHours, setTaskEstHours] = useState("");
  const [submittingTask, setSubmittingTask] = useState(false);

  // Milestone Modal
  const [showMilestoneModal, setShowMilestoneModal] = useState(false);
  const [msTitle, setMsTitle] = useState("");
  const [msDesc, setMsDesc] = useState("");
  const [msDueDate, setMsDueDate] = useState("");
  const [msPct, setMsPct] = useState("0");
  const [submittingMs, setSubmittingMs] = useState(false);

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
      const [sumRes, taskRes, memRes, msRes] = await Promise.all([
        fetchProjectSummary(id),
        fetchTasks(id),
        fetchProjectMembers(id),
        fetchMilestones(id)
      ]);
      setSummary(sumRes);
      setTasks(taskRes);
      setMembers(memRes);
      setMilestones(msRes);
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to load project details", "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, [id]);

  // Task Kanban Actions
  async function handleCreateTask(e: React.FormEvent) {
    e.preventDefault();
    if (!id || !taskTitle) return;
    try {
      setSubmittingTask(true);
      await createTask(id, {
        title: taskTitle,
        description: taskDesc || undefined,
        priority: taskPriority,
        due_date: taskDueDate || undefined,
        estimated_hours: taskEstHours ? parseFloat(taskEstHours) : undefined,
      });
      notify("Task created!", "success");
      setShowTaskModal(false);
      setTaskTitle("");
      setTaskDesc("");
      setTaskPriority("medium");
      setTaskDueDate("");
      setTaskEstHours("");
      loadData();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to create task", "error");
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

  // Milestone Actions
  async function handleCreateMilestone(e: React.FormEvent) {
    e.preventDefault();
    if (!id || !msTitle) return;
    try {
      setSubmittingMs(true);
      await createMilestone(id, {
        title: msTitle,
        description: msDesc || undefined,
        due_date: msDueDate || undefined,
        completion_percentage: parseFloat(msPct),
      });
      notify("Milestone created!", "success");
      setShowMilestoneModal(false);
      setMsTitle("");
      setMsDesc("");
      setMsDueDate("");
      setMsPct("0");
      loadData();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to create milestone", "error");
    } finally {
      setSubmittingMs(false);
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
          </div>
          <h1 style={{ margin: 0, fontSize: "1.75rem", fontWeight: 700, letterSpacing: "-0.02em" }}>{project.name}</h1>
          {project.client_name && (
            <p className="text-muted text-sm mt-1" style={{ margin: 0 }}>
              Client: <strong style={{ color: "var(--color-text)" }}>{project.client_name}</strong>
            </p>
          )}
        </div>

        <div>
          <button className="btn btn-primary" onClick={() => setShowTaskModal(true)}>
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

      {/* Tabs Bar */}
      <div className="tab-bar">
        <button
          type="button"
          className={`tab-item ${activeTab === "kanban" ? "active" : ""}`}
          onClick={() => setActiveTab("kanban")}
        >
          📋 Kanban Task Board
        </button>
        <button
          type="button"
          className={`tab-item ${activeTab === "milestones" ? "active" : ""}`}
          onClick={() => setActiveTab("milestones")}
        >
          🎯 Milestones ({milestones.length})
        </button>
        <button
          type="button"
          className={`tab-item ${activeTab === "team" ? "active" : ""}`}
          onClick={() => setActiveTab("team")}
        >
          👥 Team Members ({members.length})
        </button>
      </div>

      {/* TAB 1: KANBAN BOARD */}
      {activeTab === "kanban" && (
        <div className="kanban-board">
            {kanbanColumns.map((col) => {
              const colTasks = tasks.filter((t) => t.status === col.key);
              return (
                <div key={col.key} className="kanban-col">
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

                  <div className="stack gap-3" style={{ flex: 1, overflowY: "auto" }}>
                    {colTasks.length === 0 ? (
                      <div
                        className="text-center text-muted text-xs p-4"
                        style={{
                          border: "1px dashed #cbd5e1",
                          borderRadius: "var(--radius-sm)",
                          background: "rgba(255, 255, 255, 0.6)",
                        }}
                      >
                        No tasks
                      </div>
                    ) : (
                      colTasks.map((task) => (
                        <div key={task.id} className="kanban-task-card">
                          <div className="row-between align-center">
                            <span className={`badge ${priorityBadges[task.priority]}`} style={{ textTransform: "uppercase", fontSize: "10px", letterSpacing: "0.5px" }}>
                              {task.priority}
                            </span>
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

                          <div className="kanban-task-body">
                            <h4 className="kanban-task-title">{task.title}</h4>
                            {task.description && (
                              <p className="kanban-task-desc">{task.description}</p>
                            )}
                          </div>

                          <div className="kanban-task-footer">
                            <span className="text-muted text-xs">
                              {task.due_date ? `📅 Due ${task.due_date}` : "No due date"}
                            </span>
                            <select
                              value={task.status}
                              className="status-select-sm"
                              onChange={(e) => handleStatusChange(task.id, e.target.value as TaskStatus)}
                            >
                              <option value="todo">To Do</option>
                              <option value="in_progress">In Progress</option>
                              <option value="review">Review</option>
                              <option value="done">Done</option>
                            </select>
                          </div>
                        </div>
                      ))
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
          <div className="flex justify-end">
            <button className="btn btn-primary btn-sm" onClick={() => setShowMilestoneModal(true)}>
              + Add Milestone
            </button>
          </div>

          {milestones.length === 0 ? (
            <div className="card text-center p-8">
              <p className="text-muted text-sm">No milestones created yet for this project.</p>
            </div>
          ) : (
            <div className="stack gap-3">
              {milestones.map((ms) => (
                <div key={ms.id} className="card row-between align-center p-4">
                  <div>
                    <div className="row gap-2 align-center mb-1">
                      <h4 style={{ margin: 0 }}>{ms.title}</h4>
                      <span className={`badge ${ms.status === "completed" ? "badge-success" : "badge-info"}`}>
                        {ms.status.toUpperCase()}
                      </span>
                    </div>
                    {ms.description && <p className="text-muted text-sm mb-1">{ms.description}</p>}
                    <span className="text-muted text-xs">Target Date: <strong>{ms.due_date || "Not set"}</strong></span>
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
          <div className="flex justify-end">
            <button className="btn btn-primary btn-sm" onClick={() => setShowMemberModal(true)}>
              + Assign Member
            </button>
          </div>

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Employee ID</th>
                  <th>Role</th>
                  <th>Joined Date</th>
                  <th style={{ textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.id}>
                    <td className="font-mono text-xs">{m.employee_id}</td>
                    <td>
                      <span className={`badge ${m.role === "lead" ? "badge-primary" : "badge-muted"}`}>
                        {m.role.toUpperCase()}
                      </span>
                    </td>
                    <td>{m.joined_at}</td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm text-danger"
                        onClick={() => handleRemoveMember(m.employee_id)}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ADD TASK MODAL */}
      {showTaskModal && (
        <div className="modal-backdrop" onClick={() => setShowTaskModal(false)}>
          <div className="modal card" style={{ maxWidth: "480px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Create Task</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowTaskModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateTask} className="stack gap-4 my-2">
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
                  <label>Est. Hours</label>
                  <input type="number" step="0.5" value={taskEstHours} onChange={(e) => setTaskEstHours(e.target.value)} />
                </div>
              </div>
              <div className="field">
                <label>Due Date</label>
                <input type="date" value={taskDueDate} onChange={(e) => setTaskDueDate(e.target.value)} />
              </div>
              <div className="field">
                <label>Description</label>
                <textarea rows={3} value={taskDesc} onChange={(e) => setTaskDesc(e.target.value)} />
              </div>
              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowTaskModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submittingTask}>
                  {submittingTask ? "Saving..." : "Save"}
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
                    <span className="text-muted text-xs">{new Date(c.created_at).toLocaleString()}</span>
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

      {/* CREATE MILESTONE MODAL */}
      {showMilestoneModal && (
        <div className="modal-backdrop" onClick={() => setShowMilestoneModal(false)}>
          <div className="modal card" style={{ maxWidth: "480px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Create Milestone</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowMilestoneModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateMilestone} className="stack gap-4 my-2">
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
                  <label>Due Date</label>
                  <input type="date" value={msDueDate} onChange={(e) => setMsDueDate(e.target.value)} />
                </div>
              </div>
              <div className="field">
                <label>Description</label>
                <textarea rows={2} value={msDesc} onChange={(e) => setMsDesc(e.target.value)} />
              </div>
              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowMilestoneModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submittingMs}>
                  {submittingMs ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ADD MEMBER MODAL */}
      {showMemberModal && (
        <div className="modal-backdrop" onClick={() => setShowMemberModal(false)}>
          <div className="modal card" style={{ maxWidth: "440px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
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
                <label>Employee ID (UUID) *</label>
                <input type="text" value={memberEmployeeId} onChange={(e) => setMemberEmployeeId(e.target.value)} required />
              </div>
              <div className="field">
                <label>Role</label>
                <select value={memberRole} onChange={(e) => setMemberRole(e.target.value as any)}>
                  <option value="member">Member</option>
                  <option value="lead">Project Lead</option>
                </select>
              </div>
              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowMemberModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submittingMember}>
                  {submittingMember ? "Saving..." : "Assign"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
