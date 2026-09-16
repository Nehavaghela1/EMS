import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog";
import { usePagination } from "../../../shared/hooks/usePagination";
import { parseApiError } from "../../../shared/api/errors";
import { useToast } from "../../../app/toast-context";
import { useAuth } from "../../../app/auth-context";
import { listEmployees } from "../../hr/api";
import { assignShift, createShift, deleteShift, getAssignedShift, listShifts, updateShift, type Shift } from "../api";

function formatTimeString(timeStr: string): string {
  const parts = timeStr.split(":");
  let hours = parseInt(parts[0], 10);
  const minutes = parts[1] || "00";
  if (isNaN(hours)) return timeStr;
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12;
  hours = hours ? hours : 12;
  return `${String(hours).padStart(2, "0")}:${minutes} ${ampm}`;
}

const DAYS_OF_WEEK = [
  { key: "mon", label: "Monday", short: "Mon", isWeekend: false },
  { key: "tue", label: "Tuesday", short: "Tue", isWeekend: false },
  { key: "wed", label: "Wednesday", short: "Wed", isWeekend: false },
  { key: "thu", label: "Thursday", short: "Thu", isWeekend: false },
  { key: "fri", label: "Friday", short: "Fri", isWeekend: false },
  { key: "sat", label: "Saturday", short: "Sat", isWeekend: true },
  { key: "sun", label: "Sunday", short: "Sun", isWeekend: true },
];

export function ShiftsPage() {
  const { user } = useAuth();
  const isHr = user?.role === "hr_admin" || user?.role === "super_admin";
  const { page, limit, setPage } = usePagination();
  const queryClient = useQueryClient();
  const { notify } = useToast();

  const shiftsQuery = useQuery({
    queryKey: ["shifts", { page, limit }],
    queryFn: () => listShifts(page, limit),
    placeholderData: (prev) => prev,
    enabled: isHr,
  });

  const employeesQuery = useQuery({
    queryKey: ["employees", "all-for-shifts"],
    queryFn: () => listEmployees({ page: 1, limit: 100 }),
    enabled: isHr,
  });

  const myShiftQuery = useQuery({
    queryKey: ["shift", "assigned", user?.employee?.id],
    queryFn: () => getAssignedShift(user!.employee!.id),
    enabled: Boolean(user?.employee?.id),
  });

  const [editing, setEditing] = useState<Shift | "new" | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Shift | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<Shift | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["shifts"] }),
      queryClient.invalidateQueries({ queryKey: ["shift", "assigned"] }),
    ]);
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await deleteShift(deleteTarget.id);
      notify("Shift deleted.");
      setDeleteTarget(null);
      await refresh();
    } catch (err) {
      setDeleteError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  }

  const columns: DataTableColumn<Shift>[] = [
    { key: "name", label: "Name", render: (s) => s.name },
    { key: "start_time", label: "Start", render: (s) => formatTimeString(s.start_time) },
    { key: "end_time", label: "End", render: (s) => formatTimeString(s.end_time) },
    { key: "break_minutes", label: "Break (min)", render: (s) => `${s.break_minutes} min` },
    { key: "night_allowance", label: "Night allowance", render: (s) => s.night_allowance },
    {
      key: "is_active",
      label: "Status",
      render: (s) => (
        <span className={"badge " + (s.is_active ? "badge-success" : "badge-muted")}>
          {s.is_active ? "Active" : "Inactive"}
        </span>
      ),
    },
    {
      key: "actions",
      label: "",
      render: (s) => (
        <div className="row">
          <button className="btn btn-sm" onClick={() => setAssigning(s)}>
            Assign
          </button>
          <button className="btn btn-sm" onClick={() => setEditing(s)}>
            Edit
          </button>
          <button className="btn btn-sm btn-danger" onClick={() => setDeleteTarget(s)}>
            Delete
          </button>
        </div>
      ),
    },
  ];

  // Assigned shift data for weekly calendar grid
  const myAssignedShift = myShiftQuery.data?.shift;
  const activeShiftName = myAssignedShift?.name ?? "General Shift";
  const activeShiftStart = myAssignedShift ? formatTimeString(myAssignedShift.start_time) : "09:00 AM";
  const activeShiftEnd = myAssignedShift ? formatTimeString(myAssignedShift.end_time) : "06:00 PM";
  const breakMinutes = myAssignedShift?.break_minutes ?? 60;

  // Compute dates for the current week (Monday to Sunday)
  const now = new Date();
  const currentDay = now.getDay(); // 0 is Sunday, 1 is Monday...
  const distanceToMonday = (currentDay + 6) % 7;
  const monday = new Date(now);
  monday.setDate(now.getDate() - distanceToMonday);

  const todayIsoString = now.toISOString().slice(0, 10);

  return (
    <div>
      <PageHeader
        title="Shift Schedule"
        breadcrumb="Time & leave"
        action={
          isHr ? (
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              + New shift
            </button>
          ) : undefined
        }
      />

      {/* Weekly Schedule View Grid for Logged-In User */}
      <div className="card mb-6" style={{ padding: "1.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "1rem", marginBottom: "1.25rem" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.25rem" }}>
              <h2 style={{ fontSize: "1.15rem", fontWeight: 600, margin: 0 }}>My Weekly Shift Schedule</h2>
              <span className="badge badge-primary" style={{ fontSize: "0.75rem" }}>Active</span>
            </div>
            <p className="text-muted" style={{ margin: 0, fontSize: "0.875rem" }}>
              Assigned Shift: <strong>{activeShiftName}</strong> ({activeShiftStart} - {activeShiftEnd}, {breakMinutes} min break)
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.85rem", color: "var(--color-text-secondary)" }}>
            <span style={{ display: "inline-block", width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#10b981" }} /> Working Day
            <span style={{ display: "inline-block", width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#94a3b8", marginLeft: "0.75rem" }} /> Weekly Off
          </div>
        </div>

        {/* 7-Day Calendar Grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
            gap: "0.75rem",
          }}
        >
          {DAYS_OF_WEEK.map((day, idx) => {
            const dayDate = new Date(monday);
            dayDate.setDate(monday.getDate() + idx);
            const isToday = dayDate.toISOString().slice(0, 10) === todayIsoString;
            const dateNumber = dayDate.getDate();
            const monthName = dayDate.toLocaleDateString("en-US", { month: "short" });

            return (
              <div
                key={day.key}
                style={{
                  padding: "1rem 0.85rem",
                  borderRadius: "10px",
                  border: isToday
                    ? "2px solid var(--color-primary, #2563eb)"
                    : "1px solid var(--color-border, #e2e8f0)",
                  backgroundColor: isToday
                    ? "var(--color-primary-subtle, #eff6ff)"
                    : day.isWeekend
                    ? "var(--color-bg-secondary, #f8fafc)"
                    : "var(--color-bg, #ffffff)",
                  boxShadow: isToday ? "0 4px 12px rgba(37, 99, 235, 0.12)" : "none",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                  position: "relative",
                  transition: "transform 0.15s ease, box-shadow 0.15s ease",
                }}
              >
                {isToday && (
                  <span
                    style={{
                      position: "absolute",
                      top: "-8px",
                      right: "8px",
                      fontSize: "0.65rem",
                      fontWeight: 700,
                      backgroundColor: "var(--color-primary, #2563eb)",
                      color: "#fff",
                      padding: "1px 6px",
                      borderRadius: "9999px",
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                    }}
                  >
                    Today
                  </span>
                )}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <span style={{ fontWeight: 600, fontSize: "0.95rem" }}>{day.short}</span>
                  <span style={{ fontSize: "0.8rem", color: "var(--color-text-secondary, #64748b)" }}>
                    {dateNumber} {monthName}
                  </span>
                </div>

                {day.isWeekend ? (
                  <div style={{ marginTop: "0.5rem" }}>
                    <div
                      style={{
                        display: "inline-block",
                        padding: "3px 8px",
                        borderRadius: "6px",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        backgroundColor: "#f1f5f9",
                        color: "#64748b",
                      }}
                    >
                      Weekly Off
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginTop: "0.35rem" }}>Weekend</div>
                  </div>
                ) : (
                  <div style={{ marginTop: "0.5rem" }}>
                    <div
                      style={{
                        display: "inline-block",
                        padding: "3px 8px",
                        borderRadius: "6px",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        backgroundColor: "#dcfce7",
                        color: "#15803d",
                      }}
                    >
                      Regular Shift
                    </div>
                    <div style={{ fontSize: "0.8rem", fontWeight: 600, marginTop: "0.4rem", color: "var(--color-text, #1e293b)" }}>
                      {activeShiftStart} - {activeShiftEnd}
                    </div>
                    <div style={{ fontSize: "0.725rem", color: "var(--color-text-secondary, #64748b)" }}>
                      {breakMinutes}m break
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* HR Shift Management Section */}
      {isHr && (
        <div style={{ marginTop: "2rem" }}>
          <div style={{ marginBottom: "1rem" }}>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 600, margin: 0 }}>Company Shift Management</h3>
            <p className="text-muted" style={{ margin: "0.25rem 0 0 0", fontSize: "0.85rem" }}>
              Configure corporate shifts and assign them to employees across departments.
            </p>
          </div>

          {editing && (
            <ShiftForm
              initial={editing === "new" ? null : editing}
              onDone={async () => {
                setEditing(null);
                await refresh();
              }}
              onCancel={() => setEditing(null)}
            />
          )}

          <DataTable
            columns={columns}
            page={shiftsQuery.data}
            isLoading={shiftsQuery.isLoading}
            isError={shiftsQuery.isError}
            error={shiftsQuery.error}
            currentPage={page}
            onPageChange={setPage}
            sort={null}
            onSortChange={() => {}}
            emptyMessage="No shifts configured yet."
            rowKey={(s) => s.id}
          />

          <ConfirmDialog
            open={Boolean(deleteTarget)}
            title="Delete shift?"
            message={deleteError ?? "Blocked if any assignment currently covers today."}
            confirmLabel="Delete"
            danger
            busy={busy}
            onConfirm={handleDelete}
            onCancel={() => {
              setDeleteTarget(null);
              setDeleteError(null);
            }}
          />

          {assigning && (
            <AssignDialog
              shift={assigning}
              employees={employeesQuery.data?.items ?? []}
              onClose={() => setAssigning(null)}
            />
          )}
        </div>
      )}
    </div>
  );
}


function ShiftForm({
  initial,
  onDone,
  onCancel,
}: {
  initial: Shift | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { notify } = useToast();
  const [name, setName] = useState(initial?.name ?? "");
  const [startTime, setStartTime] = useState(initial?.start_time.slice(0, 5) ?? "09:00");
  const [endTime, setEndTime] = useState(initial?.end_time.slice(0, 5) ?? "18:00");
  const [breakMinutes, setBreakMinutes] = useState(String(initial?.break_minutes ?? 60));
  const [nightAllowance, setNightAllowance] = useState(initial?.night_allowance ?? "0");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        name: name.trim(),
        start_time: `${startTime}:00`,
        end_time: `${endTime}:00`,
        break_minutes: Number(breakMinutes) || 0,
        night_allowance: nightAllowance || "0",
      };
      if (initial) {
        await updateShift(initial.id, payload);
        notify("Shift updated.");
      } else {
        await createShift(payload);
        notify("Shift created.");
      }
      onDone();
    } catch (err) {
      setError(parseApiError(err).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card stack mb-4" onSubmit={handleSubmit} style={{ maxWidth: 480 }}>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="field">
        <label>Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </div>
      <div className="form-grid">
        <div className="field">
          <label>Start time</label>
          <input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
        </div>
        <div className="field">
          <label>End time</label>
          <input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
        </div>
        <div className="field">
          <label>Break (minutes)</label>
          <input type="number" min={0} value={breakMinutes} onChange={(e) => setBreakMinutes(e.target.value)} />
        </div>
        <div className="field">
          <label>Night allowance</label>
          <input value={nightAllowance} onChange={(e) => setNightAllowance(e.target.value)} />
        </div>
      </div>
      <div className="row">
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Saving…" : initial ? "Save changes" : "Create shift"}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function AssignDialog({
  shift,
  employees,
  onClose,
}: {
  shift: Shift;
  employees: { id: string; first_name: string; last_name: string | null }[];
  onClose: () => void;
}) {
  const { notify } = useToast();
  const [employeeId, setEmployeeId] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [effectiveTo, setEffectiveTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!employeeId || !effectiveFrom) {
      setError("An employee and a start date are both required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await assignShift(shift.id, {
        employee_id: employeeId,
        effective_from: effectiveFrom,
        effective_to: effectiveTo || undefined,
      });
      notify(`Shift assigned.`);
      onClose();
    } catch (err) {
      setError(parseApiError(err).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal stack" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
          <h3>Assign "{shift.name}"</h3>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            disabled={submitting}
            title="Close"
          >
            ✕
          </button>
        </div>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="field">
          <label>Employee</label>
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            <option value="">— Select —</option>
            {employees.map((e) => (
              <option key={e.id} value={e.id}>
                {e.first_name}
                {e.last_name ? ` ${e.last_name}` : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Effective from</label>
          <input type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
        </div>
        <div className="field">
          <label>Effective to (optional — open-ended if blank)</label>
          <input type="date" value={effectiveTo} onChange={(e) => setEffectiveTo(e.target.value)} />
        </div>
        <div className="row-end">
          <button className="btn" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? "Assigning…" : "Assign"}
          </button>
        </div>
      </div>
    </div>
  );
}
