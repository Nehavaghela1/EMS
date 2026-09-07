import { useEffect, useState } from "react";
import {
  fetchTimeEntries, createTimeEntry, approveRejectTimeEntry,
  fetchProjects, fetchTasks
} from "../api";
import type { TimeEntry, Project, Task } from "../types";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";

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

  return (
    <div className="stack" style={{ gap: "1.5rem" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h2>Timesheets</h2>
          <p className="text-muted">Track billable work hours, task activity logs, and manager approvals</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="row" style={{ borderBottom: "1px solid var(--border-color, #e2e8f0)", gap: "1.5rem" }}>
        <button
          className={`btn btn-ghost ${activeTab === "log" ? "border-active" : ""}`}
          style={{ borderBottom: activeTab === "log" ? "2px solid var(--primary)" : "none", borderRadius: 0 }}
          onClick={() => setActiveTab("log")}
        >
          ⏱️ My Time Logs
        </button>
        {isManagerOrAdmin && (
          <button
            className={`btn btn-ghost ${activeTab === "approval" ? "border-active" : ""}`}
            style={{ borderBottom: activeTab === "approval" ? "2px solid var(--primary)" : "none", borderRadius: 0 }}
            onClick={() => setActiveTab("approval")}
          >
            📋 Approvals Queue ({pendingEntries.length})
          </button>
        )}
      </div>

      {/* TAB 1: TIME LOG FORM + HISTORY */}
      {activeTab === "log" && (
        <div className="grid" style={{ gridTemplateColumns: "1fr 2fr", gap: "1.5rem" }}>
          {/* Form */}
          <div className="card stack" style={{ gap: "1rem" }}>
            <h3>Log Time Worked</h3>
            <form onSubmit={handleLogTime} className="stack" style={{ gap: "1rem" }}>
              <div className="form-group">
                <label>Select Project *</label>
                <select
                  className="input"
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                  required
                >
                  <option value="">-- Choose Project --</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.code} - {p.name}</option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Select Task (Optional)</label>
                <select
                  className="input"
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

              <div className="row" style={{ gap: "1rem" }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Date *</label>
                  <input type="date" className="input" value={logDate} onChange={(e) => setLogDate(e.target.value)} required />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Hours *</label>
                  <input
                    type="number"
                    step="0.25"
                    min="0.1"
                    max="24"
                    className="input"
                    value={hours}
                    onChange={(e) => setHours(e.target.value)}
                    placeholder="e.g. 7.5"
                    required
                  />
                </div>
              </div>

              <div className="row" style={{ alignItems: "center", gap: "0.5rem" }}>
                <input
                  type="checkbox"
                  id="billable"
                  checked={isBillable}
                  onChange={(e) => setIsBillable(e.target.checked)}
                />
                <label htmlFor="billable">Billable Hours</label>
              </div>

              <div className="form-group">
                <label>Work Description</label>
                <textarea
                  className="input"
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Summary of work performed..."
                />
              </div>

              <button type="submit" className="btn btn-primary" disabled={submitting}>
                {submitting ? "Submitting..." : "Submit Time Entry"}
              </button>
            </form>
          </div>

          {/* Log History */}
          <div className="card stack" style={{ gap: "1rem" }}>
            <h3>Logged History</h3>
            {loading ? (
              <p className="text-muted">Loading logs...</p>
            ) : entries.length === 0 ? (
              <p className="text-muted">No time entries recorded yet.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                  <thead>
                    <tr style={{ background: "var(--bg-subtle, #f8fafc)", borderBottom: "1px solid var(--border-color, #e2e8f0)" }}>
                      <th style={{ padding: "0.75rem" }}>Date</th>
                      <th style={{ padding: "0.75rem" }}>Hours</th>
                      <th style={{ padding: "0.75rem" }}>Billable</th>
                      <th style={{ padding: "0.75rem" }}>Description</th>
                      <th style={{ padding: "0.75rem" }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => (
                      <tr key={entry.id} style={{ borderBottom: "1px solid var(--border-color, #e2e8f0)" }}>
                        <td style={{ padding: "0.75rem", fontSize: "0.9rem" }}>{entry.date}</td>
                        <td style={{ padding: "0.75rem", fontWeight: 600 }}>{entry.hours} hrs</td>
                        <td style={{ padding: "0.75rem" }}>
                          {entry.is_billable ? <span className="badge badge-success">Yes</span> : <span className="badge badge-muted">No</span>}
                        </td>
                        <td style={{ padding: "0.75rem", fontSize: "0.85rem" }}>{entry.description || "N/A"}</td>
                        <td style={{ padding: "0.75rem" }}>
                          <span className={`badge ${statusBadges[entry.status] || "badge-muted"}`}>
                            {entry.status.toUpperCase()}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: APPROVALS QUEUE */}
      {activeTab === "approval" && isManagerOrAdmin && (
        <div className="card stack" style={{ gap: "1rem" }}>
          <h3>Manager Approval Queue</h3>
          {pendingEntries.length === 0 ? (
            <p className="text-muted">No pending timesheet entries awaiting approval.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                <thead>
                  <tr style={{ background: "var(--bg-subtle, #f8fafc)", borderBottom: "1px solid var(--border-color, #e2e8f0)" }}>
                    <th style={{ padding: "0.75rem" }}>Employee ID</th>
                    <th style={{ padding: "0.75rem" }}>Date</th>
                    <th style={{ padding: "0.75rem" }}>Hours</th>
                    <th style={{ padding: "0.75rem" }}>Billable</th>
                    <th style={{ padding: "0.75rem" }}>Description</th>
                    <th style={{ padding: "0.75rem", textAlign: "right" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingEntries.map((entry) => (
                    <tr key={entry.id} style={{ borderBottom: "1px solid var(--border-color, #e2e8f0)" }}>
                      <td style={{ padding: "0.75rem", fontSize: "0.85rem" }}>{entry.employee_id}</td>
                      <td style={{ padding: "0.75rem" }}>{entry.date}</td>
                      <td style={{ padding: "0.75rem", fontWeight: 600 }}>{entry.hours} hrs</td>
                      <td style={{ padding: "0.75rem" }}>{entry.is_billable ? "Yes" : "No"}</td>
                      <td style={{ padding: "0.75rem", fontSize: "0.85rem" }}>{entry.description || "N/A"}</td>
                      <td style={{ padding: "0.75rem", textAlign: "right" }}>
                        <div className="row" style={{ justifyContent: "flex-end", gap: "0.5rem" }}>
                          <button className="btn btn-success btn-sm" onClick={() => handleApproveReject(entry.id, "approved")}>
                            Approve
                          </button>
                          <button className="btn btn-danger btn-sm" onClick={() => handleApproveReject(entry.id, "rejected")}>
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
