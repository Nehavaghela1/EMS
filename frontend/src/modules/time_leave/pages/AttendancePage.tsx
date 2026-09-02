import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { parseApiError } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { TodayAttendanceCard } from "../components/TodayAttendanceCard";
import { listAttendance, regularizeAttendance, type Attendance, type AttendanceStatus } from "../api";

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
  const queryClient = useQueryClient();
  const isHr = user?.role === "hr_admin";

  async function refreshAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["attendance"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    ]);
  }

  const { page, limit, setPage } = usePagination();
  const historyQuery = useQuery({
    queryKey: ["attendance", "history", { page, limit }],
    queryFn: () => listAttendance({ page, limit }),
    placeholderData: (prev) => prev,
  });

  const [regularizing, setRegularizing] = useState<Attendance | null>(null);

  const columns: DataTableColumn<Attendance>[] = [
    { key: "date", label: "Date", render: (a) => a.date },
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

      <PageHeader
        title={isHr ? "All attendance" : user?.role === "manager" ? "Team attendance" : "My attendance"}
      />
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
        emptyMessage="No attendance records."
        rowKey={(a) => a.id}
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
        <h3>Regularize attendance — {record.date}</h3>
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
