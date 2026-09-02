import { useMemo, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { parseApiError } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { listEmployees } from "../../hr/api";
import {
  applyLeave,
  cancelLeave,
  decideLeave,
  getLeaveBalance,
  listLeaveTypes,
  listLeaves,
  type Leave,
  type LeaveStatus,
} from "../api";

const STATUS_FILTERS: { label: string; value: LeaveStatus | "" }[] = [
  { label: "All", value: "" },
  { label: "Pending", value: "pending" },
  { label: "Approved", value: "approved" },
  { label: "Rejected", value: "rejected" },
  { label: "Cancelled", value: "cancelled" },
];

/**
 * Page 12 (Spec 14.3): apply, the role-scoped request list (own/team/
 * everyone, same backend-resolved scoping as attendance), balances, and
 * approve/reject for a manager or HR. The apply form surfaces the
 * backend's own validation messages verbatim (Spec 11.3's eight rules) —
 * this file re-implements none of them, only presence checks for required
 * fields.
 */
export function LeavePage() {
  const { user } = useAuth();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const canDecide = user?.role === "hr_admin" || user?.role === "manager";
  const canPickEmployee = user?.role === "hr_admin" || user?.role === "manager";

  const leaveTypesQuery = useQuery({ queryKey: ["leave-types"], queryFn: listLeaveTypes });
  const employeesQuery = useQuery({
    queryKey: ["employees", "all-for-leave"],
    queryFn: () => listEmployees({ page: 1, limit: 100 }),
    enabled: canPickEmployee,
  });
  const employeeNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of employeesQuery.data?.items ?? []) {
      map.set(e.id, `${e.first_name}${e.last_name ? " " + e.last_name : ""}`);
    }
    return map;
  }, [employeesQuery.data]);
  const leaveTypeNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const lt of leaveTypesQuery.data ?? []) map.set(lt.id, lt.name);
    return map;
  }, [leaveTypesQuery.data]);

  const balancesQuery = useQuery({
    queryKey: ["leave-balance", user?.employee?.id],
    queryFn: () => getLeaveBalance(user!.employee!.id, new Date().getFullYear()),
    enabled: Boolean(user?.employee),
  });

  const [statusFilter, setStatusFilter] = useState<LeaveStatus | "">("");
  const { page, limit, setPage } = usePagination();
  const leavesQuery = useQuery({
    queryKey: ["leaves", { status: statusFilter, page, limit }],
    queryFn: () => listLeaves({ status: statusFilter || undefined, page, limit }),
    placeholderData: (prev) => prev,
  });

  async function refreshAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["leaves"] }),
      queryClient.invalidateQueries({ queryKey: ["leave-balance"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    ]);
  }

  const [decisionTarget, setDecisionTarget] = useState<{ leave: Leave; status: "approved" | "rejected" } | null>(
    null,
  );
  const [rejectionReason, setRejectionReason] = useState("");
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [decisionBusy, setDecisionBusy] = useState(false);

  async function handleDecision() {
    if (!decisionTarget) return;
    if (decisionTarget.status === "rejected" && !rejectionReason.trim()) {
      setDecisionError("A rejection reason is required.");
      return;
    }
    setDecisionBusy(true);
    setDecisionError(null);
    try {
      await decideLeave(decisionTarget.leave.id, decisionTarget.status, rejectionReason.trim() || undefined);
      notify(decisionTarget.status === "approved" ? "Leave approved." : "Leave rejected.");
      setDecisionTarget(null);
      setRejectionReason("");
      await refreshAll();
    } catch (err) {
      setDecisionError(parseApiError(err).message);
    } finally {
      setDecisionBusy(false);
    }
  }

  async function handleCancel(leave: Leave) {
    try {
      await cancelLeave(leave.id);
      notify("Leave cancelled.");
      await refreshAll();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    }
  }

  function canCancel(leave: Leave): boolean {
    const isOwn = user?.employee?.id === leave.employee_id;
    if (leave.status === "pending") return isOwn || user?.role === "hr_admin";
    if (leave.status === "approved") return user?.role === "hr_admin";
    return false;
  }

  const columns: DataTableColumn<Leave>[] = [
    ...(canPickEmployee
      ? [
          {
            key: "employee",
            label: "Employee",
            render: (l: Leave) => employeeNameById.get(l.employee_id) ?? l.employee_id,
          } satisfies DataTableColumn<Leave>,
        ]
      : []),
    { key: "leave_type", label: "Type", render: (l) => leaveTypeNameById.get(l.leave_type_id) ?? "—" },
    { key: "dates", label: "Dates", render: (l) => `${l.start_date} → ${l.end_date}` },
    { key: "total_days", label: "Days", render: (l) => l.total_days },
    {
      key: "status",
      label: "Status",
      render: (l) => (
        <span
          className={
            "badge " +
            (l.status === "approved" ? "badge-success" : l.status === "rejected" ? "badge-warning" : "badge-muted")
          }
        >
          {l.status}
        </span>
      ),
    },
    { key: "reason", label: "Reason", render: (l) => l.reason },
    {
      key: "actions",
      label: "",
      render: (l) => (
        <div className="row">
          {canDecide && l.status === "pending" && (
            <>
              <button
                className="btn btn-sm btn-primary"
                onClick={() => setDecisionTarget({ leave: l, status: "approved" })}
              >
                Approve
              </button>
              <button
                className="btn btn-sm btn-danger"
                onClick={() => setDecisionTarget({ leave: l, status: "rejected" })}
              >
                Reject
              </button>
            </>
          )}
          {canCancel(l) && (
            <button className="btn btn-sm" onClick={() => handleCancel(l)}>
              Cancel
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="Leave" breadcrumb="Time & leave" />

      {user?.employee && (
        <div className="card mb-6">
          <h3>My balances</h3>
          {balancesQuery.isLoading && <span className="text-muted">Loading…</span>}
          {balancesQuery.isError && (
            <div className="alert alert-error">{parseApiError(balancesQuery.error).message}</div>
          )}
          {balancesQuery.data && balancesQuery.data.length === 0 && (
            <span className="text-muted">
              No balances yet — they're created the first time you need one.
            </span>
          )}
          {balancesQuery.data && balancesQuery.data.length > 0 && (
            <div className="stat-grid">
              {balancesQuery.data.map((b) => (
                <div className="card" key={b.leave_type_id}>
                  <div className="stat-label">{b.leave_type_name}</div>
                  <div className="stat-value">{b.available}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <ApplyLeaveForm
        canPickEmployee={canPickEmployee}
        employees={employeesQuery.data?.items ?? []}
        leaveTypes={leaveTypesQuery.data ?? []}
        onApplied={refreshAll}
      />

      <PageHeader title="Requests" />
      <div className="row mb-4">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as LeaveStatus | "")}>
          {STATUS_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </div>
      <DataTable
        columns={columns}
        page={leavesQuery.data}
        isLoading={leavesQuery.isLoading}
        isError={leavesQuery.isError}
        error={leavesQuery.error}
        currentPage={page}
        onPageChange={setPage}
        sort={null}
        onSortChange={() => {}}
        emptyMessage="No leave requests."
        rowKey={(l) => l.id}
      />

      {decisionTarget && (
        <div className="modal-backdrop" onClick={() => setDecisionTarget(null)}>
          <div className="modal stack" onClick={(e) => e.stopPropagation()}>
            <h3>{decisionTarget.status === "approved" ? "Approve" : "Reject"} this leave request?</h3>
            {decisionError && <div className="alert alert-error">{decisionError}</div>}
            {decisionTarget.status === "rejected" && (
              <div className="field">
                <label>Rejection reason</label>
                <textarea
                  rows={2}
                  value={rejectionReason}
                  onChange={(e) => setRejectionReason(e.target.value)}
                  autoFocus
                />
              </div>
            )}
            <div className="row-end">
              <button className="btn" onClick={() => setDecisionTarget(null)} disabled={decisionBusy}>
                Cancel
              </button>
              <button
                className={decisionTarget.status === "approved" ? "btn btn-primary" : "btn btn-danger"}
                onClick={handleDecision}
                disabled={decisionBusy}
              >
                {decisionBusy ? "Working…" : decisionTarget.status === "approved" ? "Approve" : "Reject"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ApplyLeaveForm({
  canPickEmployee,
  employees,
  leaveTypes,
  onApplied,
}: {
  canPickEmployee: boolean;
  employees: { id: string; first_name: string; last_name: string | null }[];
  leaveTypes: { id: string; name: string }[];
  onApplied: () => void;
}) {
  const { notify } = useToast();
  const [employeeId, setEmployeeId] = useState("");
  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [isHalfDay, setIsHalfDay] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!leaveTypeId || !startDate || !endDate || !reason.trim()) {
      setError("Leave type, dates, and a reason are all required.");
      return;
    }
    setSubmitting(true);
    try {
      await applyLeave({
        employee_id: employeeId || undefined,
        leave_type_id: leaveTypeId,
        start_date: startDate,
        end_date: endDate,
        is_half_day: isHalfDay,
        reason: reason.trim(),
      });
      notify("Leave application submitted.");
      setStartDate("");
      setEndDate("");
      setIsHalfDay(false);
      setReason("");
      onApplied();
    } catch (err) {
      // Verbatim: the backend's own message for whichever of the eight
      // Spec 11.3 validations failed — never re-derived here.
      setError(parseApiError(err).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card stack mb-6" onSubmit={handleSubmit}>
      <h3>Apply for leave</h3>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-grid">
        {canPickEmployee && (
          <div className="field">
            <label>For (leave blank for yourself)</label>
            <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
              <option value="">— Myself —</option>
              {employees.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.first_name}
                  {e.last_name ? ` ${e.last_name}` : ""}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label>Leave type</label>
          <select value={leaveTypeId} onChange={(e) => setLeaveTypeId(e.target.value)}>
            <option value="">— Select —</option>
            {leaveTypes.map((lt) => (
              <option key={lt.id} value={lt.id}>
                {lt.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Start date</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </div>
        <div className="field">
          <label>End date</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </div>
      </div>
      <label className="row text-sm">
        <input type="checkbox" checked={isHalfDay} onChange={(e) => setIsHalfDay(e.target.checked)} />
        Half day
      </label>
      <div className="field">
        <label>Reason</label>
        <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <button
        className="btn btn-primary"
        type="submit"
        disabled={submitting}
        style={{ width: "fit-content" }}
      >
        {submitting ? "Submitting…" : "Apply"}
      </button>
    </form>
  );
}
