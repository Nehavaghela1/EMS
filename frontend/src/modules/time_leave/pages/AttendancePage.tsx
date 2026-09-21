import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { parseApiError } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { TodayAttendanceCard } from "../components/TodayAttendanceCard";
import { AttendanceCalendar } from "../components/AttendanceCalendar";
import { listAttendance, regularizeAttendance, type Attendance, type AttendanceStatus } from "../api";
import { formatDate, todayIso } from "../../../shared/utils/date";

const STATUS_OPTIONS: AttendanceStatus[] = ["present", "absent", "half_day", "wfh", "on_leave"];

function formatHoursWorked(a: Attendance): React.ReactNode {
  const isPastDate = a.date < todayIso();

  if (a.check_in && a.check_out) {
    const diffMs = new Date(a.check_out).getTime() - new Date(a.check_in).getTime();
    if (diffMs > 0) {
      const totalMinutes = Math.floor(diffMs / (1000 * 60));
      const hours = Math.floor(totalMinutes / 60);
      const minutes = totalMinutes % 60;
      return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
    }
  }
  if (a.hours_worked) {
    const val = parseFloat(a.hours_worked);
    if (!isNaN(val) && val > 0) {
      const hours = Math.floor(val);
      const minutes = Math.round((val - hours) * 60);
      return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
    }
  }
  if (a.check_in && !a.check_out) {
    // Enterprise Rule A: Unclosed sessions on PAST calendar dates MUST NOT run live timers (+95h)
    if (isPastDate) {
      return (
        <span
          className="badge"
          style={{
            backgroundColor: "#fffbeb",
            color: "#b45309",
            border: "1px solid #fde68a",
            fontSize: "0.75rem",
            fontWeight: 600,
            display: "inline-flex",
            alignItems: "center",
            gap: "5px",
          }}
          title={`Shift not closed on ${formatDate(a.date)}. Requires Attendance Regularization.`}
        >
          <span>⚠️</span> Missing Out-Punch
        </span>
      );
    }

    const elapsedMs = Date.now() - new Date(a.check_in).getTime();
    if (elapsedMs > 0) {
      const totalMinutes = Math.floor(elapsedMs / (1000 * 60));
      const hours = Math.floor(totalMinutes / 60);
      const minutes = totalMinutes % 60;
      return (
        <span
          className="badge"
          style={{
            backgroundColor: "#ecfdf5",
            color: "#047857",
            border: "1px solid #a7f3d0",
            fontSize: "0.75rem",
            fontWeight: 600,
            display: "inline-flex",
            alignItems: "center",
            gap: "4px",
          }}
          title={`Checked in today: running elapsed time ${hours}h ${minutes}m`}
        >
          <span style={{ width: "6px", height: "6px", borderRadius: "50%", backgroundColor: "#10b981", display: "inline-block" }} />
          {hours > 0 ? `${hours}h ${minutes}m (Active)` : "In Progress"}
        </span>
      );
    }
    return (
      <span
        className="badge badge-warning"
        style={{ fontSize: "0.75rem", fontWeight: 600 }}
      >
        In Progress
      </span>
    );
  }
  return "—";
}


/**
 * Page 11 (Spec 14.3): check-in/check-out with today's state visible (via
 * TodayAttendanceCard — the same widget the dashboard uses, Part 2), plus
 * the role-scoped history — own for an employee, team for a manager,
 * everyone for HR (all three via the same `GET /attendance` call; the
 * backend resolves the scope from the caller's role, Spec 10.4). HR gets
 * the regularize action.
 */
export function AttendancePage() {
  const { user } = useAuth();
  const { notify } = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isHr = user?.role === "hr_admin" || user?.role === "super_admin";

  async function refreshAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["attendance"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    ]);
  }

  const [searchParams, setSearchParams] = useSearchParams();
  const employeeIdParam = searchParams.get("employee_id");
  const employeeNameParam = searchParams.get("employee_name");

  const [filterEmployee, setFilterEmployee] = useState<{ id: string; name: string } | null>(
    employeeIdParam ? { id: employeeIdParam, name: employeeNameParam || "Selected Employee" } : null
  );

  const { page, limit, setPage } = usePagination();
  const historyQuery = useQuery({
    queryKey: ["attendance", "history", { page, limit, employee_id: filterEmployee?.id }],
    queryFn: () => listAttendance({ page, limit, employee_id: filterEmployee?.id }),
    placeholderData: (prev) => prev,
  });

  const [regularizing, setRegularizing] = useState<Attendance | null>(null);
  const [actionMenuOpen, setActionMenuOpen] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"list" | "calendar">("list");

  function handleSelectEmployee(empId: string, empName: string) {
    setFilterEmployee({ id: empId, name: empName });
    setPage(1);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("employee_id", empId);
      next.set("employee_name", empName);
      return next;
    });
  }

  function handleClearEmployeeFilter() {
    setFilterEmployee(null);
    setPage(1);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("employee_id");
      next.delete("employee_name");
      return next;
    });
  }

  const showEmployeeCol = user?.role === "hr_admin" || user?.role === "super_admin" || user?.role === "manager";

  const columns: DataTableColumn<Attendance>[] = [
    ...(showEmployeeCol
      ? [
          {
            key: "employee",
            label: "Employee",
            render: (a: Attendance) => {
              const empName = a.employee_name ?? a.employee_code ?? "Employee";
              const isSelected = filterEmployee?.id === a.employee_id;
              return (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                  }}
                >
                  <div
                    style={{
                      cursor: a.employee_id && (isHr || user?.role === "manager") ? "pointer" : "default",
                    }}
                    onClick={(e) => {
                      if (a.employee_id && (isHr || user?.role === "manager")) {
                        e.stopPropagation();
                        handleSelectEmployee(a.employee_id, empName);
                      }
                    }}
                    title={a.employee_id ? "Click to view this employee's attendance records" : undefined}
                  >
                    <strong
                      style={{
                        color: isSelected
                          ? "var(--color-primary, #2563eb)"
                          : a.employee_id && (isHr || user?.role === "manager")
                          ? "var(--color-primary, #2563eb)"
                          : "inherit",
                        textDecoration: isSelected ? "underline" : "none",
                      }}
                    >
                      {a.employee_name ?? "—"}
                    </strong>
                    {a.employee_code && (
                      <span className="text-xs text-muted block" style={{ fontFamily: "monospace" }}>
                        {a.employee_code}
                      </span>
                    )}
                  </div>
                  {a.employee_id && (isHr || user?.role === "manager") && (
                    <button
                      type="button"
                      className="btn btn-xs"
                      style={{
                        padding: "1px 6px",
                        fontSize: "0.72rem",
                        color: "var(--color-muted, #6b7280)",
                        background: "transparent",
                        border: "1px solid var(--color-border, #e5e7eb)",
                        borderRadius: "4px",
                      }}
                      title="View full profile"
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate(`/employees/${a.employee_id}`);
                      }}
                    >
                      Profile ↗
                    </button>
                  )}
                </div>
              );
            },
          } satisfies DataTableColumn<Attendance>,
          {
            key: "department",
            label: "Department",
            render: (a: Attendance) => a.department_name ?? "—",
          } satisfies DataTableColumn<Attendance>,
        ]
      : []),
    { key: "date", label: "Date", render: (a) => formatDate(a.date) },
    { key: "check_in", label: "Check in", render: (a) => (a.check_in ? new Date(a.check_in).toLocaleTimeString() : "—") },
    { key: "check_out", label: "Check out", render: (a) => (a.check_out ? new Date(a.check_out).toLocaleTimeString() : "—") },
    { key: "hours_worked", label: "Hours", render: (a) => formatHoursWorked(a) },
    {
      key: "status",
      label: "Status",
      render: (a) => {
        const isRegularized = a.notes && a.notes.includes("[Regularized");
        const statusClass =
          a.status === "present"
            ? "badge-success"
            : a.status === "half_day"
            ? "badge-warning"
            : a.status === "absent"
            ? "badge-danger"
            : "badge-muted";

        return (
          <div style={{ display: "inline-flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
            <span className={`badge ${statusClass}`}>{a.status.replace("_", " ")}</span>
            {isRegularized && (
              <span
                style={{
                  fontSize: "0.68rem",
                  fontWeight: 600,
                  padding: "1px 5px",
                  borderRadius: "4px",
                  backgroundColor: "#f5f3ff",
                  color: "#7c3aed",
                  border: "1px solid #ddd6fe",
                }}
                title={a.notes || "Regularized"}
              >
                Regularized
              </span>
            )}
          </div>
        );
      },
    },
    { key: "source", label: "Source", render: (a) => a.source },
    ...(isHr
      ? [
          {
            key: "actions",
            label: "",
            render: (a: Attendance) => (
              <div style={{ position: "relative", textAlign: "right" }}>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  style={{ padding: "0.2rem 0.5rem" }}
                  onClick={(evt) => {
                    evt.stopPropagation();
                    setActionMenuOpen(actionMenuOpen === a.id ? null : a.id);
                  }}
                >
                  •••
                </button>
                {actionMenuOpen === a.id && (
                  <div
                    style={{
                      position: "absolute",
                      right: 0,
                      top: "100%",
                      background: "#ffffff",
                      border: "1px solid var(--color-border, #e2e8f0)",
                      borderRadius: "8px",
                      boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
                      zIndex: 50,
                      minWidth: "200px",
                      padding: "6px 0",
                      textAlign: "left"
                    }}
                    onMouseLeave={() => setActionMenuOpen(null)}
                  >
                    <button
                      type="button"
                      style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                      onClick={(evt) => { evt.stopPropagation(); notify("Audit history logic placeholder"); setActionMenuOpen(null); }}
                    >
                      <span>🔍</span> <span>View Audit History</span>
                    </button>
                    <button
                      type="button"
                      style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                      onClick={(evt) => { evt.stopPropagation(); setRegularizing(a); setActionMenuOpen(null); }}
                    >
                      <span>✏️</span> <span>Admin Override (Regularize)</span>
                    </button>
                    <div style={{ height: "1px", background: "#e2e8f0", margin: "4px 0" }} />
                    <button
                      type="button"
                      style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#dc2626", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                      onClick={(evt) => { evt.stopPropagation(); notify("Reject action triggered."); setActionMenuOpen(null); }}
                    >
                      <span>❌</span> <span>Reject with Note</span>
                    </button>
                  </div>
                )}
              </div>
            ),
          } satisfies DataTableColumn<Attendance>,
        ]
      : []),
  ];

  return (
    <div>
      <PageHeader title="Attendance" breadcrumb="Time & leave" />

      <TodayAttendanceCard />

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          marginTop: "1.5rem",
          marginBottom: "0.75rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <h2 style={{ fontSize: "1.25rem", margin: 0 }}>
            {filterEmployee
              ? `Attendance: ${filterEmployee.name}`
              : isHr || user?.role === "super_admin"
              ? "All Company Attendance"
              : user?.role === "manager"
              ? "Team Attendance"
              : "My Attendance"}
          </h2>

          {/* View Toggle */}
          <div
            style={{
              display: "inline-flex",
              backgroundColor: "var(--color-surface, #f1f5f9)",
              borderRadius: "8px",
              padding: "2px",
              border: "1px solid var(--color-border, #e2e8f0)",
            }}
          >
            <button
              type="button"
              onClick={() => setViewMode("list")}
              style={{
                padding: "4px 10px",
                fontSize: "0.8rem",
                fontWeight: 600,
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
                backgroundColor: viewMode === "list" ? "#ffffff" : "transparent",
                color: viewMode === "list" ? "var(--color-primary, #2563eb)" : "var(--color-muted, #64748b)",
                boxShadow: viewMode === "list" ? "0 1px 2px rgba(0,0,0,0.05)" : "none",
              }}
            >
              ☰ List View
            </button>
            <button
              type="button"
              onClick={() => setViewMode("calendar")}
              style={{
                padding: "4px 10px",
                fontSize: "0.8rem",
                fontWeight: 600,
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
                backgroundColor: viewMode === "calendar" ? "#ffffff" : "transparent",
                color: viewMode === "calendar" ? "var(--color-primary, #2563eb)" : "var(--color-muted, #64748b)",
                boxShadow: viewMode === "calendar" ? "0 1px 2px rgba(0,0,0,0.05)" : "none",
              }}
            >
              📅 Monthly Calendar
            </button>
          </div>
        </div>

        {filterEmployee && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "4px 12px",
              borderRadius: "9999px",
              backgroundColor: "var(--color-primary-subtle, #eff6ff)",
              border: "1px solid var(--color-primary-border, #bfdbfe)",
              fontSize: "0.875rem",
            }}
          >
            <span>Showing attendance for <strong>{filterEmployee.name}</strong></span>
            <button
              type="button"
              className="btn btn-xs btn-ghost"
              style={{ padding: "0 4px", fontWeight: "bold" }}
              onClick={handleClearEmployeeFilter}
              title="Show all attendance records"
            >
              ✕ Clear Filter
            </button>
          </div>
        )}
      </div>

      {viewMode === "calendar" ? (
        <AttendanceCalendar
          employeeId={filterEmployee?.id || (user?.employee?.id ?? undefined)}
          employeeName={filterEmployee?.name || (user?.employee ? `${user.employee.first_name} ${user.employee.last_name || ""}`.trim() : undefined)}
        />
      ) : (
        <DataTable
          columns={columns}
          page={historyQuery.data}
          isLoading={historyQuery.isLoading}
          isError={historyQuery.isError}
          error={historyQuery.error}
          currentPage={page}
          onPageChange={setPage}
          sort={null}
          onSortChange={() => {}}
          emptyMessage={filterEmployee ? `No attendance records found for ${filterEmployee.name}.` : "No attendance records."}
          rowKey={(a) => a.id}
          onRowClick={(a) => {
            if (a.employee_id && (isHr || user?.role === "manager")) {
              const empName = a.employee_name ?? a.employee_code ?? "Employee";
              handleSelectEmployee(a.employee_id, empName);
            }
          }}
          onRowDoubleClick={(a) => {
            if (isHr) {
              setRegularizing(a);
            } else if (a.employee_id && user?.role === "manager") {
              const empName = a.employee_name ?? a.employee_code ?? "Employee";
              handleSelectEmployee(a.employee_id, empName);
            }
          }}
        />
      )}

      {regularizing && (
        <RegularizeDialog
          record={regularizing}
          onClose={() => setRegularizing(null)}
          onDone={async () => {
            setRegularizing(null);
            await refreshAll();
          }}
        />
      )}
    </div>
  );
}

function RegularizeDialog({
  record,
  onClose,
  onDone,
}: {
  record: Attendance;
  onClose: () => void;
  onDone: () => void;
}) {
  const { notify } = useToast();

  // Helper to format ISO to datetime-local value (YYYY-MM-DDTHH:mm)
  function toDateTimeLocalValue(isoStr: string | null | undefined, fallbackDate: string, defaultHour: string): string {
    if (isoStr) {
      try {
        const d = new Date(isoStr);
        const pad = (n: number) => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
      } catch {
        // fallback
      }
    }
    return `${fallbackDate}T${defaultHour}`;
  }

  const [checkInTime, setCheckInTime] = useState(
    toDateTimeLocalValue(record.check_in, record.date, "09:00")
  );
  const [checkOutTime, setCheckOutTime] = useState(
    record.check_out
      ? toDateTimeLocalValue(record.check_out, record.date, "18:00")
      : `${record.date}T18:00`
  );
  const [status, setStatus] = useState<AttendanceStatus>(
    record.status === "absent" && !record.check_out ? "present" : record.status
  );
  const [notes, setNotes] = useState(record.notes ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Live computed hours difference
  let computedHours = 0;
  if (checkInTime && checkOutTime) {
    const tIn = new Date(checkInTime).getTime();
    const tOut = new Date(checkOutTime).getTime();
    if (tOut > tIn) {
      computedHours = Math.round(((tOut - tIn) / (1000 * 3600)) * 100) / 100;
    }
  }

  async function handleSubmit() {
    if (!reason.trim()) {
      setError("A reason is required for attendance regularization.");
      return;
    }
    if (checkInTime && checkOutTime && new Date(checkOutTime) <= new Date(checkInTime)) {
      setError("Check-out time must be strictly after Check-in time.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const inIso = checkInTime ? new Date(checkInTime).toISOString() : undefined;
      const outIso = checkOutTime ? new Date(checkOutTime).toISOString() : undefined;

      await regularizeAttendance(record.id, {
        check_in: inIso,
        check_out: outIso,
        status,
        notes: notes || undefined,
        reason: reason.trim(),
      });
      notify("Attendance regularized successfully.");
      onDone();
    } catch (err) {
      setError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal stack" style={{ maxWidth: "520px" }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "1.1rem" }}>
              Regularize Attendance — {record.employee_name || "Employee"}
            </h3>
            <div className="text-xs text-muted mt-1">
              Date: <strong>{formatDate(record.date)}</strong> • Current Status:{" "}
              <span className="badge badge-outline text-xs">{record.status.replace("_", " ")}</span>
            </div>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            disabled={busy}
            title="Close"
          >
            ✕
          </button>
        </div>

        {error && <div className="alert alert-error">{error}</div>}

        <div style={{ background: "#f8fafc", padding: "12px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
            <div className="field">
              <label style={{ fontSize: "0.78rem", fontWeight: 600 }}>Actual Check-In Time</label>
              <input
                type="datetime-local"
                value={checkInTime}
                onChange={(e) => setCheckInTime(e.target.value)}
                style={{ fontSize: "0.85rem" }}
              />
            </div>
            <div className="field">
              <label style={{ fontSize: "0.78rem", fontWeight: 600 }}>Actual Check-Out Time</label>
              <input
                type="datetime-local"
                value={checkOutTime}
                onChange={(e) => setCheckOutTime(e.target.value)}
                style={{ fontSize: "0.85rem" }}
              />
            </div>
          </div>

          <div className="flex justify-between items-center mt-2 pt-2" style={{ borderTop: "1px dashed #cbd5e1", fontSize: "0.82rem" }}>
            <span className="text-muted">Calculated Work Duration:</span>
            <span style={{ fontWeight: 700, color: computedHours >= 7.5 ? "#047857" : computedHours >= 4.0 ? "#b45309" : "#dc2626" }}>
              {computedHours > 0 ? `${computedHours} hours` : "0.00 hours"}
              {computedHours >= 7.5 ? " (Full Day)" : computedHours >= 4.0 ? " (Half Day)" : computedHours > 0 ? " (Under Minimum)" : ""}
            </span>
          </div>
        </div>

        <div className="field">
          <label style={{ fontSize: "0.82rem", fontWeight: 600 }}>Corrected Attendance Status</label>
          <select value={status} onChange={(e) => setStatus(e.target.value as AttendanceStatus)}>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ").toUpperCase()}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label style={{ fontSize: "0.82rem", fontWeight: 600 }}>HR Admin Notes (Optional)</label>
          <input
            type="text"
            placeholder="e.g., Client site visit confirmed by manager"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        <div className="field">
          <label style={{ fontSize: "0.82rem", fontWeight: 600 }}>Reason for Regularization (Mandatory Audit Trail) *</label>
          <textarea
            rows={2}
            placeholder="e.g., Laptop battery died before out-punch, or biometric device malfunction"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            autoFocus
          />
        </div>

        <div className="row-end" style={{ gap: "10px", marginTop: "0.5rem" }}>
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={busy}>
            {busy ? "Applying Correction…" : "Approve & Regularize"}
          </button>
        </div>
      </div>
    </div>
  );
}
