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
import { listAttendance, regularizeAttendance, type Attendance, type AttendanceStatus } from "../api";
import { formatDate } from "../../../shared/utils/date";

const STATUS_OPTIONS: AttendanceStatus[] = ["present", "absent", "half_day", "wfh", "on_leave"];

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
    { key: "hours_worked", label: "Hours", render: (a) => a.hours_worked ?? "—" },
    {
      key: "status",
      label: "Status",
      render: (a) => <span className="badge badge-muted">{a.status.replace("_", " ")}</span>,
    },
    { key: "source", label: "Source", render: (a) => a.source },
    ...(isHr
      ? [
          {
            key: "actions",
            label: "",
            render: (a: Attendance) => (
              <button className="btn btn-sm" onClick={() => setRegularizing(a)}>
                Regularize
              </button>
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
        <h2 style={{ fontSize: "1.25rem", margin: 0 }}>
          {filterEmployee
            ? `Attendance: ${filterEmployee.name}`
            : isHr || user?.role === "super_admin"
            ? "All Company Attendance"
            : user?.role === "manager"
            ? "Team Attendance"
            : "My Attendance"}
        </h2>
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
  const [status, setStatus] = useState<AttendanceStatus>(record.status);
  const [notes, setNotes] = useState(record.notes ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit() {
    if (!reason.trim()) {
      setError("A reason is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await regularizeAttendance(record.id, { status, notes: notes || undefined, reason: reason.trim() });
      notify("Attendance regularized.");
      onDone();
    } catch (err) {
      setError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal stack" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
          <h3>Regularize attendance — {formatDate(record.date)}</h3>
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
        <div className="field">
          <label>Status</label>
          <select value={status} onChange={(e) => setStatus(e.target.value as AttendanceStatus)}>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Notes</label>
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        <div className="field">
          <label>Reason (required)</label>
          <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
        </div>
        <div className="row-end">
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
