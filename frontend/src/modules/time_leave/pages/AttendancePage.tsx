import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { TodayAttendanceCard } from "../components/TodayAttendanceCard";
import { AttendanceCalendar } from "../components/AttendanceCalendar";
import { RegularizeAttendanceModal } from "../components/RegularizeAttendanceModal";
import {
  listAttendance,
  submitRegularizationRequest,
  approveRegularizationRequest,
  type Attendance,
} from "../api";
import { formatDate, todayIso } from "../../../shared/utils/date";

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
    const hours = Math.floor(elapsedMs / (1000 * 60 * 60));
    const minutes = Math.floor((elapsedMs % (1000 * 60 * 60)) / (1000 * 60));
    return (
      <span className="badge badge-outline" title="Session currently ongoing">
        Live: {String(hours).padStart(2, "0")}:{String(minutes).padStart(2, "0")}
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
              const empName = a.employee_name ?? a.employee_code ?? "—";
              const isSelected = filterEmployee?.id === a.employee_id;
              return (
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
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
        const isPendingReg = a.status === "pending_regularization" || a.active_regularization?.status === "pending";
        const statusClass =
          a.status === "present"
            ? "badge-success"
            : a.status === "half_day"
            ? "badge-warning"
            : a.status === "absent"
            ? "badge-danger"
            : a.status === "pending_regularization"
            ? "badge-warning"
            : "badge-muted";

        return (
          <div style={{ display: "inline-flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
            <span className={`badge ${statusClass}`}>{a.status.replace("_", " ")}</span>
            {isPendingReg && (
              <span
                style={{
                  fontSize: "0.68rem",
                  fontWeight: 600,
                  padding: "1px 5px",
                  borderRadius: "4px",
                  backgroundColor: "#fef3c7",
                  color: "#b45309",
                  border: "1px solid #fde68a",
                }}
                title="Regularization awaiting manager/admin approval"
              >
                ⏳ Pending Approval
              </span>
            )}
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
    {
      key: "actions",
      label: "",
      render: (a: Attendance) => {
        const isOwnRecord = Boolean(user?.employee?.id && a.employee_id === user.employee.id);
        const canReview = (isHr || user?.role === "manager") && !isOwnRecord;
        const canApply = isOwnRecord && (a.status === "absent" || a.status === "mispunch" || (!a.check_out && a.date < todayIso()));

        return (
          <div style={{ position: "relative", textAlign: "right" }}>
            {canReview && a.status === "pending_regularization" ? (
              <button
                type="button"
                className="btn btn-xs btn-primary"
                style={{ fontSize: "0.75rem", padding: "2px 8px" }}
                onClick={(e) => {
                  e.stopPropagation();
                  setRegularizing(a);
                }}
              >
                Review Request ↗
              </button>
            ) : canApply ? (
              <button
                type="button"
                className="btn btn-xs"
                style={{ fontSize: "0.75rem", padding: "2px 8px", color: "#2563eb", borderColor: "#bfdbfe" }}
                onClick={(e) => {
                  e.stopPropagation();
                  setRegularizing(a);
                }}
              >
                Regularize
              </button>
            ) : isHr ? (
              <>
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
                      minWidth: "210px",
                      padding: "6px 0",
                      textAlign: "left",
                    }}
                    onMouseLeave={() => setActionMenuOpen(null)}
                  >
                    <button
                      type="button"
                      style={{
                        width: "100%",
                        textAlign: "left",
                        padding: "8px 14px",
                        border: "none",
                        background: "transparent",
                        fontSize: "0.84rem",
                        fontWeight: 500,
                        color: "#334155",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                      }}
                      onClick={(evt) => {
                        evt.stopPropagation();
                        setRegularizing(a);
                        setActionMenuOpen(null);
                      }}
                    >
                      <span>🛡️</span> <span>Review / Regularize</span>
                    </button>
                  </div>
                )}
              </>
            ) : null}
          </div>
        );
      },
    } satisfies DataTableColumn<Attendance>,
  ];

  // Determine whether current user opens modal in Admin Review mode vs Employee Application mode
  const isTargetOwnRecord = Boolean(user?.employee?.id && regularizing?.employee_id === user.employee.id);
  const isModalAdminMode = (isHr || user?.role === "manager") && !isTargetOwnRecord;

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
            setRegularizing(a);
          }}
        />
      )}

      {regularizing && (
        <RegularizeAttendanceModal
          isOpen={Boolean(regularizing)}
          onClose={() => setRegularizing(null)}
          isAdmin={isModalAdminMode}
          employeeName={regularizing.employee_name || "Employee"}
          attendanceDate={regularizing.date}
          currentStatus={regularizing.status}
          initialCheckIn={regularizing.active_regularization?.requested_check_in ?? regularizing.check_in}
          initialCheckOut={regularizing.active_regularization?.requested_check_out ?? regularizing.check_out}
          existingReason={regularizing.active_regularization?.reason ?? regularizing.notes}
          existingAttachmentUrl={regularizing.active_regularization?.attachment_url ?? undefined}
          onSubmit={async (formData) => {
            await submitRegularizationRequest(regularizing.id, formData);
            notify("Regularization request submitted successfully.");
            setRegularizing(null);
            await refreshAll();
          }}
          onApprove={async (adjustedCheckIn, adjustedCheckOut, adminNotes) => {
            if (regularizing.active_regularization) {
              await approveRegularizationRequest(regularizing.active_regularization.id, {
                status: "approved",
                adjusted_check_in: adjustedCheckIn,
                adjusted_check_out: adjustedCheckOut,
                admin_notes: adminNotes,
              });
            } else {
              // Direct override if no pending request
              const inIso = adjustedCheckIn ? new Date(adjustedCheckIn).toISOString() : undefined;
              const outIso = adjustedCheckOut ? new Date(adjustedCheckOut).toISOString() : undefined;
              await submitRegularizationRequest(regularizing.id, (() => {
                const fd = new FormData();
                if (inIso) fd.append("check_in", inIso);
                if (outIso) fd.append("check_out", outIso);
                if (adminNotes) fd.append("admin_notes", adminNotes);
                fd.append("reason", "Admin direct regularize");
                return fd;
              })());
            }
            notify("Attendance regularized and approved.");
            setRegularizing(null);
            await refreshAll();
          }}
          onReject={async (rejectionReason) => {
            if (regularizing.active_regularization) {
              await approveRegularizationRequest(regularizing.active_regularization.id, {
                status: "rejected",
                rejection_reason: rejectionReason,
              });
            }
            notify("Regularization request rejected.");
            setRegularizing(null);
            await refreshAll();
          }}
        />
      )}
    </div>
  );
}
