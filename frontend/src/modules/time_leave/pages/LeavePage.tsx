import { useMemo, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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
import { formatDate } from "../../../shared/utils/date";

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
  const navigate = useNavigate();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const canDecide = user?.role === "hr_admin" || user?.role === "manager" || user?.role === "super_admin";
  const canPickEmployee = user?.role === "hr_admin" || user?.role === "manager" || user?.role === "super_admin";

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

  const [searchParams, setSearchParams] = useSearchParams();
  const employeeIdParam = searchParams.get("employee_id");
  const employeeNameParam = searchParams.get("employee_name");

  const [filterEmployee, setFilterEmployee] = useState<{ id: string; name: string } | null>(
    employeeIdParam ? { id: employeeIdParam, name: employeeNameParam || "Selected Employee" } : null
  );

  const [statusFilter, setStatusFilter] = useState<LeaveStatus | "">("");
  const { page, limit, setPage } = usePagination();
  const leavesQuery = useQuery({
    queryKey: ["leaves", { status: statusFilter, employee_id: filterEmployee?.id, page, limit }],
    queryFn: () => listLeaves({ status: statusFilter || undefined, employee_id: filterEmployee?.id, page, limit }),
    placeholderData: (prev) => prev,
  });

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
            render: (l: Leave) => {
              const empName = employeeNameById.get(l.employee_id) ?? l.employee_id;
              const isSelected = filterEmployee?.id === l.employee_id;
              return (
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <div
                    style={{ cursor: "pointer" }}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleSelectEmployee(l.employee_id, empName);
                    }}
                    title="Click to view this employee's leave records"
                  >
                    <strong
                      style={{
                        color: "var(--color-primary, #2563eb)",
                        textDecoration: isSelected ? "underline" : "none",
                      }}
                    >
                      {empName}
                    </strong>
                  </div>
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
                      navigate(`/employees/${l.employee_id}`);
                    }}
                  >
                    Profile ↗
                  </button>
                </div>
              );
            },
          } satisfies DataTableColumn<Leave>,
        ]
      : []),
    { key: "leave_type", label: "Type", render: (l) => leaveTypeNameById.get(l.leave_type_id) ?? "—" },
    { key: "dates", label: "Dates", render: (l) => `${formatDate(l.start_date)} → ${formatDate(l.end_date)}` },
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
        currentUser={user}
        onApplied={refreshAll}
      />

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          marginTop: "2rem",
          marginBottom: "1rem",
        }}
      >
        <h2 style={{ fontSize: "1.25rem", margin: 0 }}>
          {filterEmployee ? `Leave Requests: ${filterEmployee.name}` : "Requests"}
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
            <span>Showing leaves for <strong>{filterEmployee.name}</strong></span>
            <button
              type="button"
              className="btn btn-xs btn-ghost"
              style={{ padding: "0 4px", fontWeight: "bold" }}
              onClick={handleClearEmployeeFilter}
              title="Show all leave records"
            >
              ✕ Clear Filter
            </button>
          </div>
        )}
      </div>

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
        emptyMessage={filterEmployee ? `No leave requests found for ${filterEmployee.name}.` : "No leave requests."}
        rowKey={(l) => l.id}
        onRowClick={(l) => {
          if (l.employee_id && canPickEmployee) {
            const empName = employeeNameById.get(l.employee_id) ?? l.employee_id;
            handleSelectEmployee(l.employee_id, empName);
          }
        }}
        onRowDoubleClick={(l) => {
          if (canDecide && l.status === "pending") {
            setDecisionTarget({ leave: l, status: "approved" });
          } else if (l.employee_id && canPickEmployee) {
            const empName = employeeNameById.get(l.employee_id) ?? l.employee_id;
            handleSelectEmployee(l.employee_id, empName);
          }
        }}
      />

      {decisionTarget && (
        <div className="modal-backdrop" onClick={() => setDecisionTarget(null)}>
          <div className="modal stack" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
              <h3>{decisionTarget.status === "approved" ? "Approve" : "Reject"} this leave request?</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setDecisionTarget(null)}
                title="Close"
              >
                ✕
              </button>
            </div>
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
  currentUser,
  onApplied,
}: {
  canPickEmployee: boolean;
  employees: { id: string; first_name: string; last_name: string | null }[];
  leaveTypes: { id: string; name: string }[];
  currentUser?: { email: string; employee?: { id: string } | null } | null;
  onApplied: () => void;
}) {
  const { notify } = useToast();
  // If user is admin without employee record, default to requiring selecting an employee
  const hasLinkedEmployee = Boolean(currentUser?.employee?.id);
  const [targetType, setTargetType] = useState<"myself" | "other">(hasLinkedEmployee ? "myself" : "other");
  const [employeeId, setEmployeeId] = useState(hasLinkedEmployee ? currentUser!.employee!.id : "");
  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [isHalfDay, setIsHalfDay] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Sync end date automatically whenever start date changes if end date is empty or was same as previous start date
  function handleStartDateChange(val: string) {
    setStartDate(val);
    if (!endDate || endDate === startDate || endDate < val) {
      setEndDate(val);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!leaveTypeId || !startDate || !endDate || !reason.trim()) {
      setError("Leave type, dates, and a reason are all required.");
      return;
    }

    const effectiveEmployeeId = targetType === "myself"
      ? (currentUser?.employee?.id || undefined)
      : (employeeId || undefined);

    if (targetType === "other" && !effectiveEmployeeId) {
      setError("Please select the employee name when applying on behalf of someone else.");
      return;
    }

    if (targetType === "myself" && !hasLinkedEmployee) {
      setError("Your admin account is not linked to an employee profile. Please select an employee from the directory.");
      return;
    }

    setSubmitting(true);
    try {
      await applyLeave({
        employee_id: effectiveEmployeeId,
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
      if (targetType === "other") {
        setEmployeeId("");
      }
      onApplied();
    } catch (err) {
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
            <label>Applicant</label>
            <div style={{ display: "flex", gap: "8px", marginBottom: "6px" }}>
              <button
                type="button"
                className={`btn btn-sm ${targetType === "myself" ? "btn-primary" : "btn-outline"}`}
                onClick={() => {
                  setTargetType("myself");
                  if (currentUser?.employee?.id) {
                    setEmployeeId(currentUser.employee.id);
                  }
                }}
                disabled={!hasLinkedEmployee}
                title={!hasLinkedEmployee ? "Admin account has no linked employee profile" : undefined}
              >
                👤 Myself {hasLinkedEmployee ? "(Linked)" : "(No Profile)"}
              </button>
              <button
                type="button"
                className={`btn btn-sm ${targetType === "other" ? "btn-primary" : "btn-outline"}`}
                onClick={() => {
                  setTargetType("other");
                  if (employeeId === currentUser?.employee?.id) {
                    setEmployeeId("");
                  }
                }}
              >
                👥 On Behalf of Employee
              </button>
            </div>
            {targetType === "other" && (
              <select
                value={employeeId}
                onChange={(e) => setEmployeeId(e.target.value)}
                required
              >
                <option value="">— Select Employee * —</option>
                {employees.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.first_name}
                    {e.last_name ? ` ${e.last_name}` : ""}
                  </option>
                ))}
              </select>
            )}
            {targetType === "myself" && (
              <div className="text-xs text-muted">
                {hasLinkedEmployee
                  ? "Automatically locked to your logged-in employee record."
                  : "No employee record linked to this admin account."}
              </div>
            )}
          </div>
        )}
        <div className="field">
          <label>Leave type *</label>
          <select value={leaveTypeId} onChange={(e) => setLeaveTypeId(e.target.value)} required>
            <option value="">— Select —</option>
            {leaveTypes.map((lt) => (
              <option key={lt.id} value={lt.id}>
                {lt.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Start date *</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => handleStartDateChange(e.target.value)}
            required
          />
        </div>
        <div className="field">
          <label>End date *</label>
          <input
            type="date"
            value={endDate}
            min={startDate || undefined}
            onChange={(e) => setEndDate(e.target.value)}
            required
          />
        </div>
      </div>
      <label className="row text-sm">
        <input type="checkbox" checked={isHalfDay} onChange={(e) => setIsHalfDay(e.target.checked)} />
        Half day
      </label>
      <div className="field">
        <label>Reason *</label>
        <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} required />
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
