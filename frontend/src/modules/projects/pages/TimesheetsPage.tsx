import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchTimeEntries, createTimeEntry, approveRejectTimeEntry,
  fetchProjects, fetchTasks
} from "../api";
import type { TimeEntry, Project, Task } from "../types";
import { listEmployees, type Employee } from "../../hr/api";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { useTimer } from "../../../app/timer-context";
import { PageHeader } from "../../../shared/components/PageHeader";
import { formatDate } from "../../../shared/utils/date";

export function TimesheetsPage() {
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"log" | "approval">("log");

  // Form State with 3 Modes: duration, range, stopwatch
  const [timeInputMode, setTimeInputMode] = useState<"duration" | "range" | "stopwatch">("duration");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [logDate, setLogDate] = useState(new Date().toISOString().slice(0, 10));
  const [hours, setHours] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("17:00");
  const [breakMinutes, setBreakMinutes] = useState("60");
  const [description, setDescription] = useState("");
  const [isBillable, setIsBillable] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const navigate = useNavigate();
  const { user } = useAuth();
  const { notify } = useToast();
  const { activeTimer, startTimer, stopTimer, formatTime, elapsedSeconds } = useTimer();
  const isManagerOrAdmin = user?.role === "super_admin" || user?.role === "hr_admin" || user?.role === "manager";

  const employeeMap = useMemo(() => {
    const map = new Map<string, Employee>();
    for (const emp of employees) {
      map.set(emp.id, emp);
    }
    return map;
  }, [employees]);

  async function loadData() {
    try {
      setLoading(true);
      const [entryData, projectData, empData] = await Promise.all([
        fetchTimeEntries(),
        fetchProjects("active"),
        listEmployees({ page: 1, limit: 100 }).catch(() => ({ items: [] }))
      ]);
      setEntries(entryData);
      setProjects(projectData);
      setEmployees(empData.items || []);
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

      {/* Navigation Tab Bar (only if manager/admin has multiple tabs) */}
      {isManagerOrAdmin && (
        <div className="tab-bar">
          <button
            type="button"
            className={`tab-item ${activeTab === "log" ? "active" : ""}`}
            onClick={() => setActiveTab("log")}
          >
            <span>⏱️ My Time Logs</span>
          </button>
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
        </div>
      )}

      {/* TAB 1: TIME LOG FORM + HISTORY */}
      {activeTab === "log" && (
        <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: "var(--space-5)", alignItems: "start" }}>
          {/* Time Entry Form */}
          <div className="card">
            <h3>Log Time Worked</h3>
            <p className="text-muted text-xs mb-4">Record hours spent on assigned projects and tasks</p>

            {/* Quick Actions & 3 Modes Switcher */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
              <button
                type="button"
                className="btn btn-xs btn-outline"
                style={{ fontSize: "0.75rem", padding: "3px 8px" }}
                onClick={() => {
                  if (entries.length > 0) {
                    const last = entries[0];
                    setSelectedProjectId(last.project_id);
                    setSelectedTaskId(last.task_id || "");
                    setHours(last.hours ? String(last.hours) : "4");
                    setDescription(last.description || "Recurring project sprint work");
                    setIsBillable(last.is_billable);
                    notify("Copied previous time entry details!", "info");
                  } else {
                    notify("No previous entries found to copy.", "warning");
                  }
                }}
                title="Copy details from your recent timesheet entry"
              >
                📋 Copy Recent Entry
              </button>
            </div>

            {/* 3 Modes Switcher (Zoho Projects / ClickUp style) */}
            <div style={{ display: "flex", gap: "6px", background: "#f1f5f9", padding: "4px", borderRadius: "6px", marginBottom: "1rem" }}>
              <button
                type="button"
                style={{
                  flex: 1,
                  padding: "6px 4px",
                  fontSize: "11px",
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
                🔢 Duration
              </button>
              <button
                type="button"
                style={{
                  flex: 1,
                  padding: "6px 4px",
                  fontSize: "11px",
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
                  setHours("7.00");
                }}
              >
                🕒 Start / End
              </button>
              <button
                type="button"
                style={{
                  flex: 1,
                  padding: "6px 4px",
                  fontSize: "11px",
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

              <div className="field">
                <label>Date *</label>
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
                  <label>Hours * (e.g. 7 or 7.5)</label>
                  <input
                    type="number"
                    step="any"
                    min="0.1"
                    max="24"
                    value={hours}
                    onChange={(e) => setHours(e.target.value)}
                    placeholder="e.g. 7 or 7.5"
                    required
                  />
                </div>
              )}

              {/* Mode 2: Range */}
              {timeInputMode === "range" && (
                <div className="stack gap-2" style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                  <div className="form-grid">
                    <div className="field">
                      <label style={{ fontSize: "11px" }}>Start Time</label>
                      <input
                        type="time"
                        value={startTime}
                        onChange={(e) => {
                          setStartTime(e.target.value);
                          const [sh, sm] = e.target.value.split(":").map(Number);
                          const [eh, em] = endTime.split(":").map(Number);
                          const startM = sh * 60 + sm;
                          const endM = eh * 60 + em;
                          const breakM = parseInt(breakMinutes) || 0;
                          const diff = Math.max(0, (endM - startM - breakM) / 60);
                          setHours(diff.toFixed(2));
                        }}
                      />
                    </div>
                    <div className="field">
                      <label style={{ fontSize: "11px" }}>End Time</label>
                      <input
                        type="time"
                        value={endTime}
                        onChange={(e) => {
                          setEndTime(e.target.value);
                          const [sh, sm] = startTime.split(":").map(Number);
                          const [eh, em] = e.target.value.split(":").map(Number);
                          const startM = sh * 60 + sm;
                          const endM = eh * 60 + em;
                          const breakM = parseInt(breakMinutes) || 0;
                          const diff = Math.max(0, (endM - startM - breakM) / 60);
                          setHours(diff.toFixed(2));
                        }}
                      />
                    </div>
                  </div>
                  <div className="form-grid">
                    <div className="field">
                      <label style={{ fontSize: "11px" }}>Break (mins)</label>
                      <input
                        type="number"
                        min="0"
                        max="240"
                        value={breakMinutes}
                        onChange={(e) => {
                          setBreakMinutes(e.target.value);
                          const [sh, sm] = startTime.split(":").map(Number);
                          const [eh, em] = endTime.split(":").map(Number);
                          const startM = sh * 60 + sm;
                          const endM = eh * 60 + em;
                          const breakM = parseInt(e.target.value) || 0;
                          const diff = Math.max(0, (endM - startM - breakM) / 60);
                          setHours(diff.toFixed(2));
                        }}
                      />
                    </div>
                    <div className="field">
                      <label style={{ fontSize: "11px", fontWeight: 700 }}>Total</label>
                      <input
                        type="text"
                        readOnly
                        value={`${hours || "0.00"} hrs`}
                        style={{ background: "#e2e8f0", fontWeight: 700 }}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Mode 3: Stopwatch */}
              {timeInputMode === "stopwatch" && (
                <div className="stack gap-2 text-center" style={{ background: "#0f172a", color: "#fff", padding: "12px", borderRadius: "6px" }}>
                  <div style={{ fontSize: "1.5rem", fontFamily: "monospace", fontWeight: 800, color: "#34d399" }}>
                    ⏱️ {formatTime(elapsedSeconds)}
                  </div>
                  <div>
                    {activeTimer ? (
                      <button
                        type="button"
                        style={{ background: "#ef4444", color: "#fff", border: "none", padding: "6px 12px", borderRadius: "4px", fontWeight: 700, cursor: "pointer", fontSize: "12px" }}
                        onClick={() => {
                          const stopped = stopTimer();
                          if (stopped) {
                            const hrs = Math.max(0.1, +(elapsedSeconds / 3600).toFixed(2));
                            setHours(hrs.toString());
                            setTimeInputMode("duration");
                          }
                        }}
                      >
                        ⏹ Stop & Use {Math.max(0.1, +(elapsedSeconds / 3600).toFixed(2))}h
                      </button>
                    ) : (
                      <button
                        type="button"
                        style={{ background: "#10b981", color: "#fff", border: "none", padding: "6px 12px", borderRadius: "4px", fontWeight: 700, cursor: "pointer", fontSize: "12px" }}
                        onClick={() => {
                          if (!selectedProjectId) {
                            notify("Please choose a project first", "error");
                            return;
                          }
                          const proj = projects.find(p => p.id === selectedProjectId);
                          const task = tasks.find(t => t.id === selectedTaskId);
                          startTimer({
                            id: selectedTaskId || "general",
                            title: task ? task.title : (proj ? `${proj.name} Work` : "Work"),
                            projectId: selectedProjectId,
                            projectName: proj?.name,
                          });
                        }}
                      >
                        ▶ Start Timer Now
                      </button>
                    )}
                  </div>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>
                    Hours: <b>{hours || "0.00"} hrs</b>
                  </div>
                </div>
              )}

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
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div className="p-4 border-b row-between align-center" style={{ background: "var(--color-bg)" }}>
              <div>
                <h3 className="mb-0" style={{ fontSize: "1rem" }}>My Submitted Logs</h3>
                <span className="text-xs text-muted">Your recorded and approved time entries</span>
              </div>
              <span className="badge badge-muted">{entries.length} records</span>
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
                      <tr
                        key={entry.id}
                        onDoubleClick={() => {
                          if (entry.project_id) {
                            navigate(`/projects/${entry.project_id}`);
                          }
                        }}
                        style={{ cursor: "pointer" }}
                        title="Double-click to open project details"
                      >
                        <td className="font-medium">{formatDate(entry.date)}</td>
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
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <span className="text-xs text-muted">{pendingEntries.length} pending requests</span>
              {pendingEntries.length > 0 && (
                <button
                  type="button"
                  className="btn btn-sm btn-success"
                  onClick={async () => {
                    try {
                      for (const p of pendingEntries) {
                        await approveRejectTimeEntry(p.id, "approved");
                      }
                      notify(`Batch approved ${pendingEntries.length} timesheet entries!`, "success");
                      loadData();
                    } catch {
                      notify("Failed during batch approval", "error");
                    }
                  }}
                  title="1-Click Approve all pending timesheet submissions"
                >
                  ⚡ Batch Approve All ({pendingEntries.length})
                </button>
              )}
            </div>
          </div>

          <div className="table-wrap">
            {pendingEntries.length === 0 ? (
              <div className="empty-state">No pending timesheet entries awaiting approval.</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Employee</th>
                    <th>Date</th>
                    <th>Hours</th>
                    <th>Billable</th>
                    <th>Description</th>
                    <th style={{ textAlign: "right" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingEntries.map((entry) => {
                    const emp = employeeMap.get(entry.employee_id);
                    const empName =
                      entry.employee_name ||
                      (emp ? `${emp.first_name} ${emp.last_name || ""}`.trim() : "Team Member");
                    const empCode = entry.employee_code || emp?.employee_code || null;

                    return (
                      <tr
                        key={entry.id}
                        onDoubleClick={() => {
                          if (entry.employee_id) {
                            navigate(`/employees/${entry.employee_id}`);
                          }
                        }}
                        style={{ cursor: "pointer" }}
                        title="Double-click to open employee profile"
                      >
                        <td>
                          <div className="font-semibold">{empName}</div>
                          {empCode && <div className="text-xs text-muted">{empCode}</div>}
                        </td>
                        <td className="font-medium">{formatDate(entry.date)}</td>
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
                        <td style={{ textAlign: "right" }}>
                          <div className="row-end">
                            <button
                              type="button"
                              className="btn btn-sm btn-success"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleApproveReject(entry.id, "approved");
                              }}
                            >
                              Approve
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-danger"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleApproveReject(entry.id, "rejected");
                              }}
                            >
                              Reject
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

