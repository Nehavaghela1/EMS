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
    <div className="stack" style={{ gap: "1.5rem" }}>
      {/* Back Link */}
      <div>
        <Link to="/projects" style={{ textDecoration: "none", fontSize: "0.9rem" }}>
          ← Back to Projects
        </Link>
      </div>

      {/* Header Info */}
      <div className="card stack" style={{ gap: "1rem" }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <span className="badge badge-muted">{project.code}</span>
            <h2 style={{ margin: "0.25rem 0" }}>{project.name}</h2>
            {project.client_name && <p className="text-muted" style={{ margin: 0 }}>Client: {project.client_name}</p>}
          </div>
          <span className="badge badge-primary">{project.status.toUpperCase()}</span>
        </div>

        {/* Analytics Stats */}
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "1rem" }}>
          <div className="card text-center" style={{ padding: "0.75rem", background: "var(--bg-subtle, #f8fafc)" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>Tasks Progress</span>
            <h3 style={{ margin: 0 }}>{summary.completion_percentage}%</h3>
            <span style={{ fontSize: "0.75rem" }}>{summary.completed_tasks} / {summary.total_tasks} Done</span>
          </div>
          <div className="card text-center" style={{ padding: "0.75rem", background: "var(--bg-subtle, #f8fafc)" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>Logged Hours</span>
            <h3 style={{ margin: 0 }}>{summary.total_logged_hours} hrs</h3>
            <span style={{ fontSize: "0.75rem" }}>{summary.total_billable_hours} hrs Billable</span>
          </div>
          <div className="card text-center" style={{ padding: "0.75rem", background: "var(--bg-subtle, #f8fafc)" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>Overdue Tasks</span>
            <h3 style={{ margin: 0, color: summary.overdue_tasks > 0 ? "var(--danger, #ef4444)" : "inherit" }}>
              {summary.overdue_tasks}
            </h3>
            <span style={{ fontSize: "0.75rem" }}>Action Needed</span>
          </div>
          <div className="card text-center" style={{ padding: "0.75rem", background: "var(--bg-subtle, #f8fafc)" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>Team Size</span>
            <h3 style={{ margin: 0 }}>{summary.members_count}</h3>
            <span style={{ fontSize: "0.75rem" }}>Members</span>
          </div>
        </div>
      </div>

      {/* Tabs Bar */}
      <div className="row" style={{ borderBottom: "1px solid var(--border-color, #e2e8f0)", gap: "1.5rem" }}>
        <button
          className={`btn btn-ghost ${activeTab === "kanban" ? "border-active" : ""}`}
          style={{ borderBottom: activeTab === "kanban" ? "2px solid var(--primary)" : "none", borderRadius: 0 }}
          onClick={() => setActiveTab("kanban")}
        >
          📋 Kanban Task Board
        </button>
        <button
          className={`btn btn-ghost ${activeTab === "milestones" ? "border-active" : ""}`}
          style={{ borderBottom: activeTab === "milestones" ? "2px solid var(--primary)" : "none", borderRadius: 0 }}
          onClick={() => setActiveTab("milestones")}
        >
          🎯 Milestones ({milestones.length})
        </button>
        <button
          className={`btn btn-ghost ${activeTab === "team" ? "border-active" : ""}`}
          style={{ borderBottom: activeTab === "team" ? "2px solid var(--primary)" : "none", borderRadius: 0 }}
          onClick={() => setActiveTab("team")}
        >
          👥 Team Members ({members.length})
        </button>
      </div>

      {/* TAB 1: KANBAN BOARD */}
      {activeTab === "kanban" && (
        <div className="stack" style={{ gap: "1rem" }}>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-primary btn-sm" onClick={() => setShowTaskModal(true)}>
              + Add Task
            </button>
          </div>

          <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", gap: "1rem", overflowX: "auto" }}>
            {kanbanColumns.map((col) => {
              const colTasks = tasks.filter((t) => t.status === col.key);
              return (
                <div key={col.key} className="card stack" style={{ background: "var(--bg-subtle, #f8fafc)", padding: "0.75rem", minHeight: "450px" }}>
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                    <span style={{ fontWeight: 600, color: col.color }}>{col.title}</span>
                    <span className="badge badge-muted">{colTasks.length}</span>
                  </div>

                  <div className="stack" style={{ gap: "0.75rem", flex: 1 }}>
                    {colTasks.map((task) => (
                      <div key={task.id} className="card stack" style={{ padding: "0.75rem", background: "white", gap: "0.5rem" }}>
                        <div className="row" style={{ justifyContent: "space-between" }}>
                          <span className={`badge ${priorityBadges[task.priority]}`}>{task.priority}</span>
                          <button className="btn btn-ghost btn-sm" style={{ padding: "2px 6px" }} onClick={() => openTaskComments(task)}>
                            💬
                          </button>
                        </div>
                        <h4 style={{ margin: 0, fontSize: "0.95rem" }}>{task.title}</h4>
                        {task.description && <p className="text-muted" style={{ fontSize: "0.8rem", margin: 0 }}>{task.description}</p>}

                        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginTop: "0.5rem", fontSize: "0.75rem" }}>
                          <span className="text-muted">{task.due_date ? `Due ${task.due_date}` : ""}</span>
                          <select
                            value={task.status}
                            className="input"
                            style={{ padding: "2px 4px", fontSize: "0.75rem" }}
                            onChange={(e) => handleStatusChange(task.id, e.target.value as TaskStatus)}
                          >
                            <option value="todo">To Do</option>
                            <option value="in_progress">In Progress</option>
                            <option value="review">Review</option>
                            <option value="done">Done</option>
                          </select>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* TAB 2: MILESTONES */}
      {activeTab === "milestones" && (
        <div className="stack" style={{ gap: "1rem" }}>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-primary btn-sm" onClick={() => setShowMilestoneModal(true)}>
              + Add Milestone
            </button>
          </div>

          {milestones.length === 0 ? (
            <p className="text-muted card text-center">No milestones created yet.</p>
          ) : (
            <div className="stack" style={{ gap: "0.75rem" }}>
              {milestones.map((ms) => (
                <div key={ms.id} className="card row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <h4 style={{ margin: 0 }}>{ms.title}</h4>
                    {ms.description && <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{ms.description}</p>}
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>Due: {ms.due_date || "N/A"}</span>
                  </div>
                  <div className="row" style={{ alignItems: "center", gap: "1rem" }}>
                    <div style={{ width: "120px" }}>
                      <div className="row" style={{ justifyContent: "space-between", fontSize: "0.75rem" }}>
                        <span>Progress</span>
                        <span>{ms.completion_percentage}%</span>
                      </div>
                      <div style={{ width: "100%", height: "6px", background: "#e2e8f0", borderRadius: "3px" }}>
                        <div style={{ width: `${ms.completion_percentage}%`, height: "100%", background: "#10b981", borderRadius: "3px" }} />
                      </div>
                    </div>
                    <span className="badge badge-info">{ms.status}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 3: TEAM MEMBERS */}
      {activeTab === "team" && (
        <div className="stack" style={{ gap: "1rem" }}>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-primary btn-sm" onClick={() => setShowMemberModal(true)}>
              + Assign Member
            </button>
          </div>

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
              <thead>
                <tr style={{ background: "var(--bg-subtle, #f8fafc)", borderBottom: "1px solid var(--border-color, #e2e8f0)" }}>
                  <th style={{ padding: "0.75rem 1rem" }}>Employee ID</th>
                  <th style={{ padding: "0.75rem 1rem" }}>Role</th>
                  <th style={{ padding: "0.75rem 1rem" }}>Joined Date</th>
                  <th style={{ padding: "0.75rem 1rem", textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.id} style={{ borderBottom: "1px solid var(--border-color, #e2e8f0)" }}>
                    <td style={{ padding: "0.75rem 1rem" }}>{m.employee_id}</td>
                    <td style={{ padding: "0.75rem 1rem" }}>
                      <span className={`badge ${m.role === "lead" ? "badge-primary" : "badge-muted"}`}>
                        {m.role.toUpperCase()}
                      </span>
                    </td>
                    <td style={{ padding: "0.75rem 1rem" }}>{m.joined_at}</td>
                    <td style={{ padding: "0.75rem 1rem", textAlign: "right" }}>
                      <button className="btn btn-ghost btn-sm text-danger" onClick={() => handleRemoveMember(m.employee_id)}>
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

      {/* CREATE TASK MODAL */}
      {showTaskModal && (
        <div className="modal-backdrop" onClick={() => setShowTaskModal(false)}>
          <div className="modal card stack" style={{ maxWidth: "450px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
              <h3>Create Project Task</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowTaskModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateTask} className="stack" style={{ gap: "1rem" }}>
              <div className="form-group">
                <label>Task Title *</label>
                <input type="text" className="input" value={taskTitle} onChange={(e) => setTaskTitle(e.target.value)} required />
              </div>
              <div className="row" style={{ gap: "1rem" }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Priority</label>
                  <select className="input" value={taskPriority} onChange={(e) => setTaskPriority(e.target.value as TaskPriority)}>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Est. Hours</label>
                  <input type="number" step="0.5" className="input" value={taskEstHours} onChange={(e) => setTaskEstHours(e.target.value)} />
                </div>
              </div>
              <div className="form-group">
                <label>Due Date</label>
                <input type="date" className="input" value={taskDueDate} onChange={(e) => setTaskDueDate(e.target.value)} />
              </div>
              <div className="form-group">
                <label>Description</label>
                <textarea className="input" rows={3} value={taskDesc} onChange={(e) => setTaskDesc(e.target.value)} />
              </div>
              <div className="row" style={{ justifyContent: "flex-end", gap: "0.5rem" }}>
                <button type="button" className="btn btn-ghost" onClick={() => setShowTaskModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submittingTask}>Create Task</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* COMMENTS MODAL */}
      {activeCommentTask && (
        <div className="modal-backdrop" onClick={() => setActiveCommentTask(null)}>
          <div className="modal card stack" style={{ maxWidth: "500px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
              <h3>Comments: {activeCommentTask.title}</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setActiveCommentTask(null)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <div className="stack" style={{ gap: "0.75rem", maxHeight: "250px", overflowY: "auto", padding: "0.5rem" }}>
              {loadingComments ? (
                <p className="text-muted">Loading comments...</p>
              ) : comments.length === 0 ? (
                <p className="text-muted">No comments yet. Start the conversation!</p>
              ) : (
                comments.map((c) => (
                  <div key={c.id} className="card" style={{ padding: "0.5rem 0.75rem", background: "var(--bg-subtle, #f8fafc)" }}>
                    <p style={{ margin: 0, fontSize: "0.9rem" }}>{c.comment}</p>
                    <span className="text-muted" style={{ fontSize: "0.75rem" }}>{new Date(c.created_at).toLocaleString()}</span>
                  </div>
                ))
              )}
            </div>
            <form onSubmit={handlePostComment} className="row" style={{ gap: "0.5rem" }}>
              <input
                type="text"
                className="input"
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
          <div className="modal card stack" style={{ maxWidth: "450px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
              <h3>Create Milestone</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowMilestoneModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateMilestone} className="stack" style={{ gap: "1rem" }}>
              <div className="form-group">
                <label>Milestone Title *</label>
                <input type="text" className="input" value={msTitle} onChange={(e) => setMsTitle(e.target.value)} required />
              </div>
              <div className="row" style={{ gap: "1rem" }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Completion %</label>
                  <input type="number" min="0" max="100" className="input" value={msPct} onChange={(e) => setMsPct(e.target.value)} />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Due Date</label>
                  <input type="date" className="input" value={msDueDate} onChange={(e) => setMsDueDate(e.target.value)} />
                </div>
              </div>
              <div className="form-group">
                <label>Description</label>
                <textarea className="input" rows={2} value={msDesc} onChange={(e) => setMsDesc(e.target.value)} />
              </div>
              <div className="row" style={{ justifyContent: "flex-end", gap: "0.5rem" }}>
                <button type="button" className="btn btn-ghost" onClick={() => setShowMilestoneModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submittingMs}>Save Milestone</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ADD MEMBER MODAL */}
      {showMemberModal && (
        <div className="modal-backdrop" onClick={() => setShowMemberModal(false)}>
          <div className="modal card stack" style={{ maxWidth: "400px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
              <h3>Assign Team Member</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowMemberModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleAddMember} className="stack" style={{ gap: "1rem" }}>
              <div className="form-group">
                <label>Employee ID (UUID) *</label>
                <input type="text" className="input" value={memberEmployeeId} onChange={(e) => setMemberEmployeeId(e.target.value)} required />
              </div>
              <div className="form-group">
                <label>Role</label>
                <select className="input" value={memberRole} onChange={(e) => setMemberRole(e.target.value as any)}>
                  <option value="member">Member</option>
                  <option value="lead">Project Lead</option>
                </select>
              </div>
              <div className="row" style={{ justifyContent: "flex-end", gap: "0.5rem" }}>
                <button type="button" className="btn btn-ghost" onClick={() => setShowMemberModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submittingMember}>Assign</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
