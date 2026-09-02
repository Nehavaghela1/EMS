import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog";
import { usePagination } from "../../../shared/hooks/usePagination";
import { parseApiError } from "../../../shared/api/errors";
import { useToast } from "../../../app/toast-context";
import { listEmployees } from "../../hr/api";
import { assignShift, createShift, deleteShift, listShifts, updateShift, type Shift } from "../api";

/** Page 15 (Spec 14.3, HR only) — carried over from WP-09's deliverable
 * list since no frontend existed then. Shift CRUD and assignment. */
export function ShiftsPage() {
  const { page, limit, setPage } = usePagination();
  const queryClient = useQueryClient();
  const { notify } = useToast();

  const shiftsQuery = useQuery({
    queryKey: ["shifts", { page, limit }],
    queryFn: () => listShifts(page, limit),
    placeholderData: (prev) => prev,
  });
  const employeesQuery = useQuery({
    queryKey: ["employees", "all-for-shifts"],
    queryFn: () => listEmployees({ page: 1, limit: 100 }),
  });

  const [editing, setEditing] = useState<Shift | "new" | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Shift | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<Shift | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["shifts"] });
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
    { key: "start_time", label: "Start", render: (s) => s.start_time },
    { key: "end_time", label: "End", render: (s) => s.end_time },
    { key: "break_minutes", label: "Break (min)", render: (s) => s.break_minutes },
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

  return (
    <div>
      <PageHeader
        title="Shifts"
        breadcrumb="Time & leave"
        action={
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            + New shift
          </button>
        }
      />

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
        emptyMessage="No shifts yet."
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
        <h3>Assign "{shift.name}"</h3>
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
