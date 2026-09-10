import { useEffect, useState } from "react";
import {
  fetchTimeEntries, createTimeEntry, approveRejectTimeEntry,
  fetchProjects, fetchTasks
} from "../api";
import type { TimeEntry, Project, Task } from "../types";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { PageHeader } from "../../../shared/components/PageHeader";

export function TimesheetsPage() {
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"log" | "approval">("log");

  // Form State
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [logDate, setLogDate] = useState(new Date().toISOString().slice(0, 10));
  const [hours, setHours] = useState("");
  const [description, setDescription] = useState("");
  const [isBillable, setIsBillable] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const { user } = useAuth();
  const { notify } = useToast();
  const isManagerOrAdmin = user?.role === "super_admin" || user?.role === "hr_admin" || user?.role === "manager";

  async function loadData() {
    try {
      setLoading(true);
      const [entryData, projectData] = await Promise.all([
        fetchTimeEntries(),
        fetchProjects("active")
      ]);
      setEntries(entryData);
      setProjects(projectData);
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to load timesheets", "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      setTasks([]);
      return;
    }
    fetchTasks(selectedProjectId)
      .then(setTasks)
      .catch(() => setTasks([]));
  }, [selectedProjectId]);

  async function handleLogTime(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedProjectId || !hours || !logDate) {
      notify("Project, date and hours are required", "error");
      return;
    }
    const parsedHours = parseFloat(hours);
    if (parsedHours <= 0 || parsedHours > 24) {
      notify("Hours must be between 0.1 and 24", "error");
      return;
    }
    try {
      setSubmitting(true);
      await createTimeEntry({
        project_id: selectedProjectId,
        task_id: selectedTaskId || undefined,
        date: logDate,
        hours: parsedHours,
        description: description || undefined,
        is_billable: isBillable,
      });
      notify("Time entry logged successfully!", "success");
      setHours("");
      setDescription("");
      loadData();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to log time entry", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleApproveReject(entryId: string, statusAction: "approved" | "rejected") {
    try {
      await approveRejectTimeEntry(entryId, statusAction);
      notify(`Time entry ${statusAction}!`, "success");
      loadData();
    } catch (err: any) {
      notify(`Failed to ${statusAction} entry`, "error");
    }
  }

  const statusBadges: Record<string, string> = {
    approved: "badge-success",
    submitted: "badge-warning",
    draft: "badge-muted",
    rejected: "badge-danger",
  };

  const pendingEntries = entries.filter((e) => e.status === "draft" || e.status === "submitted");

  // Summary calculations
  const totalHours = entries.reduce((acc, curr) => acc + (Number(curr.hours) || 0), 0);
  const billableHours = entries.filter(e => e.is_billable).reduce((acc, curr) => acc + (Number(curr.hours) || 0), 0);
  const approvedHours = entries.filter(e => e.status === "approved").reduce((acc, curr) => acc + (Number(curr.hours) || 0), 0);

  return (
    <div>
      <PageHeader
        title="Timesheets"
        breadcrumb="Projects & Work"
      />

      {/* KPI Stats Overview */}
      <div className="stat-grid mb-6">
        <div className="card">
          <div className="stat-label">Total Logged</div>
          <div className="stat-value">{totalHours.toFixed(1)} hrs</div>
        </div>
        <div className="card">
          <div className="stat-label">Billable Hours</div>
          <div className="stat-value" style={{ color: "var(--color-primary)" }}>{billableHours.toFixed(1)} hrs</div>
        </div>
        <div className="card">
          <div className="stat-label">Approved Hours</div>
          <div className="stat-value" style={{ color: "var(--color-success)" }}>{approvedHours.toFixed(1)} hrs</div>
        </div>
        <div className="card">
          <div className="stat-label">Pending Approval</div>
          <div className="stat-value" style={{ color: pendingEntries.length > 0 ? "var(--color-warning-text)" : "inherit" }}>
            {pendingEntries.length} entries
          </div>
        </div>
      </div>

      {/* Navigation Tab Bar */}
      <div className="tab-bar">
        <button
          type="button"
          className={`tab-item ${activeTab === "log" ? "active" : ""}`}
          onClick={() => setActiveTab("log")}
        >
          <span>⏱️ My Time Logs</span>
        </button>
        {isManagerOrAdmin && (
          <button
            type="button"
            className={`tab-item ${activeTab === "approval" ? "active" : ""}`}
            onClick={() => setActiveTab("approval")}
          >
            <span>📋 Approvals Queue</span>
            {pendingEntries.length > 0 && (
              <span className="badge badge-warning">{pendingEntries.length}</span>
            )}
          </button>
        )}
      </div>

      {/* TAB 1: TIME LOG FORM + HISTORY */}
      {activeTab === "log" && (
        <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: "var(--space-5)", alignItems: "start" }}>
          {/* Time Entry Form */}
          <div className="card">
            <h3>Log Time Worked</h3>
            <p className="text-muted text-xs mb-4">Record hours spent on assigned projects and tasks</p>
            <form onSubmit={handleLogTime} className="stack">
              <div className="field">
                <label>Select Project *</label>
                <select
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                  required
                >
                  <option value="">-- Choose Project --</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.code} — {p.name}</option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label>Select Task (Optional)</label>
                <select
                  value={selectedTaskId}
                  onChange={(e) => setSelectedTaskId(e.target.value)}
                  disabled={!selectedProjectId}
                >
                  <option value="">-- No specific task --</option>
                  {tasks.map((t) => (
                    <option key={t.id} value={t.id}>{t.title}</option>
                  ))}
                </select>
              </div>

              <div className="form-grid">
                <div className="field">
                  <label>Date *</label>
                  <input
                    type="date"
                    value={logDate}
                    onChange={(e) => setLogDate(e.target.value)}
                    required
                  />
                </div>
                <div className="field">
                  <label>Hours *</label>
                  <input
                    type="number"
                    step="0.25"
                    min="0.1"
                    max="24"
                    value={hours}
                    onChange={(e) => setHours(e.target.value)}
                    placeholder="e.g. 7.5"
                    required
                  />
                </div>
              </div>

              <div className="row" style={{ gap: "var(--space-2)", margin: "var(--space-1) 0" }}>
                <input
                  type="checkbox"
                  id="billable"
                  checked={isBillable}
                  onChange={(e) => setIsBillable(e.target.checked)}
                  style={{ width: "16px", height: "16px", cursor: "pointer" }}
                />
                <label htmlFor="billable" style={{ cursor: "pointer", fontSize: "var(--text-sm)", userSelect: "none" }}>
                  Billable Hours
                </label>
              </div>

              <div className="field">
                <label>Work Description</label>
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Summary of deliverables, tasks, or meetings performed..."
                />
              </div>

              <button type="submit" className="btn btn-primary" style={{ width: "100%", marginTop: "var(--space-2)" }} disabled={submitting}>
                {submitting ? "Submitting..." : "Submit Time Entry"}
              </button>
            </form>
          </div>

          {/* Log History */}
          <div className="stack">
            <div className="row-between">
              <div>
                <h3 className="mb-0">Logged History</h3>
                <span className="text-xs text-muted">All submitted time logs for your tenant</span>
              </div>
              <span className="text-xs text-muted">{entries.length} records</span>
            </div>

            <div className="table-wrap">
              {loading ? (
                <div className="empty-state">Loading logs...</div>
              ) : entries.length === 0 ? (
                <div className="empty-state">No time entries recorded yet. Use the form on the left to submit hours.</div>
              ) : (
                <table className="data-table">
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
                    {entries.map((entry) => (
                      <tr key={entry.id}>
                        <td className="font-medium">{entry.date}</td>
                        <td className="font-semibold">{entry.hours} hrs</td>
                        <td>
                          {entry.is_billable ? (
                            <span className="badge badge-success">Billable</span>
                          ) : (
                            <span className="badge badge-muted">Non-billable</span>
                          )}
                        </td>
                        <td style={{ maxWidth: "260px", whiteSpace: "normal", wordBreak: "break-word" }}>
                          {entry.description || <span className="text-faint">—</span>}
                        </td>
                        <td>
                          <span className={`badge ${statusBadges[entry.status] || "badge-muted"}`}>
                            {entry.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: APPROVALS QUEUE */}
      {activeTab === "approval" && isManagerOrAdmin && (
        <div className="stack">
          <div className="row-between">
            <div>
              <h3 className="mb-0">Manager Approval Queue</h3>
              <span className="text-xs text-muted">Review, approve, or reject team member timesheet submissions</span>
            </div>
            <span className="text-xs text-muted">{pendingEntries.length} pending requests</span>
          </div>

          <div className="table-wrap">
            {pendingEntries.length === 0 ? (
              <div className="empty-state">No pending timesheet entries awaiting approval.</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Hours</th>
                    <th>Billable</th>
                    <th>Description</th>
                    <th style={{ textAlign: "right" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingEntries.map((entry) => (
                    <tr key={entry.id}>
                      <td className="font-medium">{entry.date}</td>
                      <td className="font-semibold">{entry.hours} hrs</td>
                      <td>
                        {entry.is_billable ? (
                          <span className="badge badge-success">Billable</span>
                        ) : (
                          <span className="badge badge-muted">Non-billable</span>
                        )}
                      </td>
                      <td style={{ maxWidth: "300px", whiteSpace: "normal", wordBreak: "break-word" }}>
                        {entry.description || <span className="text-faint">—</span>}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <div className="row-end">
                          <button
                            type="button"
                            className="btn btn-sm btn-success"
                            onClick={() => handleApproveReject(entry.id, "approved")}
                          >
                            Approve
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm btn-danger"
                            onClick={() => handleApproveReject(entry.id, "rejected")}
                          >
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

