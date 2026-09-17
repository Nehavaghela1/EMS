import { useEffect, useState, useMemo } from "react";
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
import { formatDate, formatDateTime } from "../../../shared/utils/date";

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

  // Approvals Queue: drawer + reject reason prompt + bulk selection
  const [drawerEntry, setDrawerEntry] = useState<TimeEntry | null>(null);
  const [selectedEntryIds, setSelectedEntryIds] = useState<Set<string>>(new Set());
  const [rejectTarget, setRejectTarget] = useState<TimeEntry | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectBusy, setRejectBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState<Record<string, boolean>>({});
  const [bulkBusy, setBulkBusy] = useState(false);

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

    // 1. Check existing logged hours on that date for this employee
    const currentEmpId = user?.employee?.id;
    const sameDayEntries = entries.filter((ent) => {
      if (ent.date !== logDate) return false;
      if (currentEmpId && ent.employee_id) {
        return ent.employee_id === currentEmpId;
      }
      return true;
    });
    const currentDaySum = sameDayEntries.reduce((acc, curr) => acc + (Number(curr.hours) || 0), 0);
    if (currentDaySum + parsedHours > 14.0) {
      notify(
        `Total logged time across all projects cannot exceed 14 hours per day. (Currently logged: ${currentDaySum.toFixed(1)}h, trying to add: ${parsedHours}h)`,
        "error"
      );
      return;
    }

    // 2. Prompt confirmation if single entry exceeds 10 hours
    if (parsedHours > 10) {
      const confirmed = window.confirm(
        `This single entry is ${parsedHours} hours (longer than a standard shift). Are you sure you want to log this duration?`
      );
      if (!confirmed) return;
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

  async function handleApproveReject(
    entryId: string,
    statusAction: "approved" | "rejected",
    rejectionReason?: string,
  ) {
    // Optimistic update: flip the badge immediately
    setEntries((prev) =>
      prev.map((e) => (e.id === entryId ? { ...e, status: statusAction } : e))
    );
    setActionBusy((prev) => ({ ...prev, [entryId]: true }));
    try {
      await approveRejectTimeEntry(entryId, statusAction, rejectionReason);
      notify(
        statusAction === "approved" ? "Time entry approved ✅" : "Time entry rejected.",
        statusAction === "approved" ? "success" : "info",
      );
      // Deselect from bulk set if present
      setSelectedEntryIds((prev) => {
        const next = new Set(prev);
        next.delete(entryId);
        return next;
      });
      // Close drawer/modal if the acted-on entry is open
      setDrawerEntry((prev) => (prev?.id === entryId ? null : prev));
      setRejectTarget(null);
      setRejectReason("");
    } catch (err: any) {
      // Roll back the optimistic update on failure
      notify(err?.response?.data?.error?.message || `Failed to ${statusAction} entry`, "error");
      loadData();
    } finally {
      setActionBusy((prev) => ({ ...prev, [entryId]: false }));
    }
  }

  async function handleBulkApprove() {
    if (selectedEntryIds.size === 0) return;
    const idsToApprove = Array.from(selectedEntryIds);
    setBulkBusy(true);
    let successCount = 0;
    try {
      for (const id of idsToApprove) {
        try {
          await approveRejectTimeEntry(id, "approved");
          successCount++;
        } catch (e) {
          console.error(`Failed to approve ${id}`, e);
        }
      }
      notify(`Successfully approved ${successCount} timesheet entries!`, "success");
      setSelectedEntryIds(new Set());
      await loadData();
    } finally {
      setBulkBusy(false);
    }
  }

  const statusBadges: Record<string, string> = {
    approved: "badge-success",
    submitted: "badge-warning",
    draft: "badge-muted",
    rejected: "badge-danger",
  };

  const pendingEntries = entries.filter((e) => e.status === "draft" || e.status === "submitted");

  // Overtime helper: Calculate Monday-Sunday total approved/submitted hours for employee in that date's week
  function isWeeklyOvertime(entry: TimeEntry): boolean {
    if (!entry.date) return false;
    const d = new Date(entry.date);
    const day = d.getDay(); // 0 is Sunday, 1 is Monday...
    const diffToMonday = day === 0 ? -6 : 1 - day;
    const monday = new Date(d);
    monday.setDate(d.getDate() + diffToMonday);
    monday.setHours(0, 0, 0, 0);

    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    sunday.setHours(23, 59, 59, 999);

    const mondayStr = monday.toISOString().slice(0, 10);
    const sundayStr = sunday.toISOString().slice(0, 10);

    const empId = entry.employee_id;
    const weekTotal = entries
      .filter((e) => e.employee_id === empId && e.date >= mondayStr && e.date <= sundayStr)
      .reduce((acc, curr) => acc + (Number(curr.hours) || 0), 0);

    return weekTotal > 40;
  }

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
          <div className="stat-label">{isManagerOrAdmin ? "Pending Approval" : "My Pending Submissions"}</div>
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
                  <option value="">-- No specific task (General work / Meeting) --</option>
                  {isManagerOrAdmin ? (
                    <>
                      {/* For managers/admins: Group by My Tasks vs Team Tasks */}
                      <optgroup label="My Tasks">
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
                    /* For regular employees: Strictly filter to their own assigned tasks */
                    tasks
                      .filter((t) => user?.employee?.id && t.assigned_to === user.employee.id)
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.title} ({t.status.toUpperCase()})
                        </option>
                      ))
                  )}
                </select>
                {!isManagerOrAdmin && tasks.length > 0 && tasks.every((t) => !user?.employee?.id || t.assigned_to !== user.employee.id) && (
                  <span className="field-hint text-warning" style={{ fontSize: "0.75rem", display: "block", marginTop: "3px" }}>
                    ℹ️ You have no assigned tasks in this project yet. You can log time as general project work.
                  </span>
                )}
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
                <span className="text-xs text-muted">Your recorded and approved time entries (click row to inspect)</span>
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
                      <th>Project / Task</th>
                      <th>Description</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => {
                      const isOT = isWeeklyOvertime(entry);
                      const projName = entry.project_name || projects.find(p => p.id === entry.project_id)?.name || entry.project_id;
                      return (
                        <tr
                          key={entry.id}
                          onClick={() => setDrawerEntry(entry)}
                          style={{
                            cursor: "pointer",
                            background: drawerEntry?.id === entry.id ? "var(--color-primary-subtle, #eff6ff)" : undefined
                          }}
                          title="Click to inspect time entry details"
                        >
                          <td className="font-medium">{formatDate(entry.date)}</td>
                          <td>
                            <span className="font-semibold">{entry.hours} hrs</span>
                            {isOT && (
                              <span
                                className="badge"
                                style={{ marginLeft: "6px", background: "#fef3c7", color: "#b45309", fontSize: "10px", padding: "1px 6px" }}
                                title="Approved hours exceed 40h in this calendar week"
                              >
                                Overtime
                              </span>
                            )}
                          </td>
                          <td>
                            {entry.is_billable ? (
                              <span className="badge badge-success">Billable</span>
                            ) : (
                              <span className="badge badge-muted">Non-billable</span>
                            )}
                          </td>
                          <td>
                            <div className="font-medium" style={{ fontSize: "0.85rem" }}>{projName}</div>
                            {entry.task_title && (
                              <div className="text-xs text-muted">{entry.task_title}</div>
                            )}
                          </td>
                          <td style={{ maxWidth: "240px", whiteSpace: "normal", wordBreak: "break-word" }}>
                            {entry.description || <span className="text-faint">—</span>}
                          </td>
                          <td>
                            <span className={`badge ${statusBadges[entry.status] || "badge-muted"}`}>
                              {entry.status}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
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
              <span className="text-xs text-muted">Review, inspect logged work, or take action right inside the timesheet module</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <span className="text-xs text-muted">{pendingEntries.length} pending requests</span>
              {selectedEntryIds.size > 0 && (
                <button
                  type="button"
                  className="btn btn-sm btn-success"
                  onClick={handleBulkApprove}
                  disabled={bulkBusy}
                  title="Approve all selected timesheets"
                >
                  {bulkBusy ? "Approving..." : `✅ Approve Selected (${selectedEntryIds.size})`}
                </button>
              )}
              {pendingEntries.length > 0 && (
                <button
                  type="button"
                  className="btn btn-sm btn-outline"
                  onClick={async () => {
                    try {
                      for (const p of pendingEntries) {
                        await handleApproveReject(p.id, "approved");
                      }
                      notify(`Batch approved ${pendingEntries.length} timesheet entries!`, "success");
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
            {entries.length === 0 ? (
              <div className="empty-state">No timesheet entries found.</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: "40px", textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={pendingEntries.length > 0 && pendingEntries.every(p => selectedEntryIds.has(p.id))}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedEntryIds(new Set(pendingEntries.map(p => p.id)));
                          } else {
                            setSelectedEntryIds(new Set());
                          }
                        }}
                        disabled={pendingEntries.length === 0}
                        title="Select all pending"
                        style={{ cursor: "pointer" }}
                      />
                    </th>
                    <th>Employee</th>
                    <th>Date</th>
                    <th>Hours</th>
                    <th>Billable</th>
                    <th>Project / Task</th>
                    <th>Description</th>
                    <th>Status</th>
                    <th style={{ textAlign: "right" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry) => {
                    const emp = employeeMap.get(entry.employee_id);
                    const empName =
                      entry.employee_name ||
                      (emp ? `${emp.first_name} ${emp.last_name || ""}`.trim() : "Team Member");
                    const empCode = entry.employee_code || emp?.employee_code || null;
                    const isPending = entry.status === "draft" || entry.status === "submitted";
                    const isBusy = actionBusy[entry.id];
                    const isOT = isWeeklyOvertime(entry);
                    const projName = entry.project_name || projects.find(p => p.id === entry.project_id)?.name || entry.project_id;
                    const isSelected = selectedEntryIds.has(entry.id);

                    return (
                      <tr
                        key={entry.id}
                        style={{
                          cursor: "pointer",
                          background: drawerEntry?.id === entry.id
                            ? "var(--color-primary-subtle, #eff6ff)"
                            : isSelected
                            ? "rgba(59, 130, 246, 0.05)"
                            : undefined
                        }}
                        title="Click to open inspection drawer"
                        onClick={() => setDrawerEntry(entry)}
                      >
                        <td style={{ textAlign: "center" }} onClick={(e) => e.stopPropagation()}>
                          {isPending ? (
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={(e) => {
                                const next = new Set(selectedEntryIds);
                                if (e.target.checked) {
                                  next.add(entry.id);
                                } else {
                                  next.delete(entry.id);
                                }
                                setSelectedEntryIds(next);
                              }}
                              style={{ cursor: "pointer" }}
                            />
                          ) : (
                            <span className="text-faint">—</span>
                          )}
                        </td>
                        <td>
                          <div className="font-semibold">{empName}</div>
                          <div className="text-xs text-muted">
                            {emp?.position || "Staff"}
                            {empCode ? ` · ${empCode}` : ""}
                          </div>
                        </td>
                        <td className="font-medium">{formatDate(entry.date)}</td>
                        <td>
                          <span className="font-semibold">{entry.hours} hrs</span>
                          {isOT && (
                            <span
                              className="badge"
                              style={{ marginLeft: "6px", background: "#fef3c7", color: "#b45309", fontSize: "10px", padding: "1px 6px" }}
                              title="Approved hours exceed 40h in this calendar week"
                            >
                              Overtime
                            </span>
                          )}
                        </td>
                        <td>
                          {entry.is_billable ? (
                            <span className="badge badge-success">Billable</span>
                          ) : (
                            <span className="badge badge-muted">Non-billable</span>
                          )}
                        </td>
                        <td>
                          <div className="font-medium" style={{ fontSize: "0.85rem" }}>{projName}</div>
                          {entry.task_title && (
                            <div className="text-xs text-muted">{entry.task_title}</div>
                          )}
                        </td>
                        <td style={{ maxWidth: "180px", whiteSpace: "normal", wordBreak: "break-word" }}>
                          {entry.description || <span className="text-faint">—</span>}
                        </td>
                        <td>
                          <span className={`badge ${statusBadges[entry.status] || "badge-muted"}`}>
                            {entry.status}
                          </span>
                        </td>
                        <td style={{ textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                          {isPending ? (
                            <div className="row-end" style={{ gap: "6px" }}>
                              <button
                                type="button"
                                className="btn btn-xs btn-success"
                                disabled={isBusy}
                                title="Direct Approve"
                                onClick={() => handleApproveReject(entry.id, "approved")}
                              >
                                {isBusy ? "⏳" : "✓ Approve"}
                              </button>
                              <button
                                type="button"
                                className="btn btn-xs btn-danger"
                                disabled={isBusy}
                                title="Direct Reject (Prompt reason)"
                                onClick={() => {
                                  setRejectTarget(entry);
                                  setRejectReason("");
                                }}
                              >
                                ✕ Reject
                              </button>
                            </div>
                          ) : (
                            <span className="text-xs text-muted">—</span>
                          )}
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

      {/* Reject Reason Modal */}
      {rejectTarget && (
        <div className="modal-backdrop" onClick={() => { setRejectTarget(null); setRejectReason(""); }}>
          <div className="modal card" style={{ maxWidth: "460px" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>Reject Time Entry</h3>
              <button type="button" className="modal-close-btn" onClick={() => { setRejectTarget(null); setRejectReason(""); }}>✕</button>
            </div>
            <div className="stack gap-3 mt-2">
              <div className="p-3 bg-muted rounded border" style={{ fontSize: "0.875rem" }}>
                <div><span className="text-muted text-xs">Employee</span></div>
                <strong>{rejectTarget.employee_name || "Team Member"}</strong>
                <div style={{ marginTop: "4px" }}><span className="text-muted text-xs">Date · Hours</span></div>
                <span>{formatDate(rejectTarget.date)} &nbsp;·&nbsp; {rejectTarget.hours} hrs</span>
                {rejectTarget.description && (
                  <><div style={{ marginTop: "4px" }}><span className="text-muted text-xs">Description</span></div>
                  <p style={{ margin: 0 }}>{rejectTarget.description}</p></>
                )}
              </div>
              <div className="field">
                <label>Rejection Reason <span style={{ color: "#dc2626" }}>*</span></label>
                <textarea
                  rows={3}
                  autoFocus
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="Explain why this time entry is being rejected (e.g. Work description too vague, exceeded budgeted hours)..."
                />
              </div>
            </div>
            <div className="row-end mt-4" style={{ gap: "8px" }}>
              <button
                type="button"
                className="btn"
                onClick={() => { setRejectTarget(null); setRejectReason(""); }}
                disabled={rejectBusy}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-danger"
                disabled={rejectBusy || !rejectReason.trim()}
                onClick={async () => {
                  if (!rejectReason.trim()) return;
                  setRejectBusy(true);
                  try {
                    await handleApproveReject(rejectTarget.id, "rejected", rejectReason.trim());
                  } finally {
                    setRejectBusy(false);
                  }
                }}
              >
                {rejectBusy ? "Rejecting…" : "❌ Confirm Reject"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Slide-out Inspection Drawer */}
      {drawerEntry && (() => {
        const emp = employeeMap.get(drawerEntry.employee_id);
        const empName = drawerEntry.employee_name || (emp ? `${emp.first_name} ${emp.last_name || ""}`.trim() : "Team Member");
        const empRole = emp?.position || "Employee";
        const empCode = drawerEntry.employee_code || emp?.employee_code;
        const initials = empName.split(" ").map((n) => n[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
        const proj = projects.find(p => p.id === drawerEntry.project_id);
        const projName = drawerEntry.project_name || proj?.name || drawerEntry.project_id;
        const taskTitle = drawerEntry.task_title || (drawerEntry.task_id ? tasks.find(t => t.id === drawerEntry.task_id)?.title || drawerEntry.task_id : "General Project Work");
        const isOT = isWeeklyOvertime(drawerEntry);
        const isPending = drawerEntry.status === "draft" || drawerEntry.status === "submitted";

        return (
          <>
            {/* Backdrop */}
            <div
              style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", zIndex: 199, backdropFilter: "blur(2px)" }}
              onClick={() => setDrawerEntry(null)}
            />
            {/* Drawer panel */}
            <div
              style={{
                position: "fixed",
                top: 0,
                right: 0,
                bottom: 0,
                width: "480px",
                maxWidth: "95vw",
                background: "var(--color-surface, #fff)",
                boxShadow: "-4px 0 24px rgba(0,0,0,0.18)",
                zIndex: 200,
                display: "flex",
                flexDirection: "column",
              }}
            >
              {/* Drawer Header with Employee Avatar, Name, Role */}
              <div
                style={{
                  padding: "18px 20px",
                  borderBottom: "1px solid var(--color-border, #e5e7eb)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  background: "var(--color-bg, #f8fafc)"
                }}
              >
                <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                  <div
                    style={{
                      width: "44px",
                      height: "44px",
                      borderRadius: "50%",
                      background: "linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)",
                      color: "#fff",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontWeight: 700,
                      fontSize: "1rem",
                      boxShadow: "0 2px 4px rgba(0,0,0,0.1)"
                    }}
                  >
                    {initials || "EM"}
                  </div>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: "1.05rem", color: "var(--color-text, #0f172a)" }}>{empName}</div>
                    <div className="text-xs text-muted">
                      {empRole} {empCode ? `· ${empCode}` : ""}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="modal-close-btn"
                  onClick={() => setDrawerEntry(null)}
                  title="Close inspection drawer"
                >
                  ✕
                </button>
              </div>

              {/* Drawer Body: Audited details */}
              <div style={{ flex: 1, overflowY: "auto", padding: "20px" }}>
                {/* Rejection Alert if rejected */}
                {drawerEntry.status === "rejected" && drawerEntry.rejection_reason && (
                  <div
                    style={{
                      background: "#fef2f2",
                      border: "1px solid #fecaca",
                      borderRadius: "6px",
                      padding: "12px 14px",
                      marginBottom: "16px",
                      color: "#991b1b"
                    }}
                  >
                    <div style={{ fontWeight: 700, fontSize: "0.85rem", marginBottom: "4px" }}>⚠️ Rejection Reason</div>
                    <div style={{ fontSize: "0.85rem", lineHeight: 1.5 }}>{drawerEntry.rejection_reason}</div>
                  </div>
                )}

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "16px" }}>
                  <div className="card" style={{ padding: "10px 14px", margin: 0, background: "var(--color-bg, #f8fafc)" }}>
                    <div className="text-xs text-muted">Status</div>
                    <div style={{ marginTop: "4px" }}>
                      <span className={`badge ${statusBadges[drawerEntry.status] || "badge-muted"}`}>
                        {drawerEntry.status}
                      </span>
                    </div>
                  </div>
                  <div className="card" style={{ padding: "10px 14px", margin: 0, background: "var(--color-bg, #f8fafc)" }}>
                    <div className="text-xs text-muted">Billing Category</div>
                    <div style={{ marginTop: "4px" }}>
                      {drawerEntry.is_billable ? (
                        <span className="badge badge-success">Billable</span>
                      ) : (
                        <span className="badge badge-muted">Non-billable</span>
                      )}
                    </div>
                  </div>
                </div>

                <dl style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: "12px 10px", fontSize: "0.875rem" }}>
                  <dt className="text-muted">Date Logged</dt>
                  <dd className="font-semibold">{formatDate(drawerEntry.date)}</dd>

                  <dt className="text-muted">Hours</dt>
                  <dd className="font-semibold">
                    {drawerEntry.hours} hrs
                    {isOT && (
                      <span
                        className="badge"
                        style={{ marginLeft: "8px", background: "#fef3c7", color: "#b45309", fontSize: "10px", padding: "1px 6px" }}
                      >
                        Overtime (&gt;40h/wk)
                      </span>
                    )}
                  </dd>

                  <dt className="text-muted">Project</dt>
                  <dd>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <span className="font-semibold">{projName}</span>
                      {drawerEntry.project_id && (
                        <a
                          href={`/projects/${drawerEntry.project_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          title="Open project in new tab"
                          style={{ color: "var(--color-primary, #2563eb)", textDecoration: "none", fontSize: "12px" }}
                        >
                          ↗
                        </a>
                      )}
                    </div>
                    {drawerEntry.project_code && (
                      <span className="text-xs text-muted">Code: {drawerEntry.project_code}</span>
                    )}
                  </dd>

                  <dt className="text-muted">Task</dt>
                  <dd>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <span>{taskTitle}</span>
                      {drawerEntry.project_id && drawerEntry.task_id && (
                        <a
                          href={`/projects/${drawerEntry.project_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          title="Open task in new tab"
                          style={{ color: "var(--color-primary, #2563eb)", textDecoration: "none", fontSize: "12px" }}
                        >
                          ↗
                        </a>
                      )}
                    </div>
                  </dd>

                  <dt className="text-muted" style={{ gridColumn: "1 / -1", paddingTop: "12px", borderTop: "1px solid var(--color-border, #e5e7eb)", marginTop: "4px" }}>
                    Work Notes / Description
                  </dt>
                  <dd style={{ gridColumn: "1 / -1" }}>
                    {drawerEntry.description ? (
                      <div
                        style={{
                          margin: 0,
                          padding: "10px 12px",
                          background: "var(--color-bg, #f8fafc)",
                          borderRadius: "6px",
                          border: "1px solid var(--color-border, #e2e8f0)",
                          lineHeight: 1.6,
                          whiteSpace: "pre-wrap"
                        }}
                      >
                        {drawerEntry.description}
                      </div>
                    ) : (
                      <span className="text-muted">(No work description provided)</span>
                    )}
                  </dd>

                  <dt className="text-muted" style={{ gridColumn: "1 / -1", paddingTop: "14px", borderTop: "1px solid var(--color-border, #e5e7eb)", marginTop: "8px" }}>
                    Activity Audit History
                  </dt>
                  <dd style={{ gridColumn: "1 / -1" }}>
                    <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted, #64748b)", display: "flex", flexDirection: "column", gap: "6px" }}>
                      {drawerEntry.created_at && (
                        <div>📅 Submitted: <b>{formatDateTime(drawerEntry.created_at)}</b></div>
                      )}
                      {drawerEntry.updated_at && drawerEntry.updated_at !== drawerEntry.created_at && (
                        <div>✏️ Last Modified: <b>{formatDateTime(drawerEntry.updated_at)}</b></div>
                      )}
                      {drawerEntry.approved_at && (
                        <div>
                          ✅ Approved at: <b>{formatDateTime(drawerEntry.approved_at)}</b>
                          {drawerEntry.approved_by ? ` (by ${drawerEntry.approved_by})` : ""}
                        </div>
                      )}
                    </div>
                  </dd>
                </dl>
              </div>

              {/* Drawer Footer: Docked Approve (Green) & Reject (Red) Action Buttons */}
              {isManagerOrAdmin && isPending && (
                <div
                  style={{
                    padding: "16px 20px",
                    borderTop: "1px solid var(--color-border, #e5e7eb)",
                    display: "flex",
                    gap: "12px",
                    background: "var(--color-surface, #fff)",
                    boxShadow: "0 -2px 8px rgba(0,0,0,0.05)"
                  }}
                >
                  <button
                    type="button"
                    className="btn btn-success"
                    style={{ flex: 1, padding: "10px", fontWeight: 700 }}
                    disabled={actionBusy[drawerEntry.id]}
                    onClick={() => handleApproveReject(drawerEntry.id, "approved")}
                  >
                    {actionBusy[drawerEntry.id] ? "⏳ Processing…" : "✅ Approve"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-danger"
                    style={{ flex: 1, padding: "10px", fontWeight: 700 }}
                    disabled={actionBusy[drawerEntry.id]}
                    onClick={() => {
                      setRejectTarget(drawerEntry);
                      setRejectReason("");
                    }}
                  >
                    ❌ Reject
                  </button>
                </div>
              )}
            </div>
          </>
        );
      })()}
    </div>
  );
}

