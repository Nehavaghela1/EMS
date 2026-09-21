import { useState, useEffect } from "react";
import { useLocation, useNavigate, useParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog";
import { parseApiError } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { formatDate, formatDateTime } from "../../../shared/utils/date";
import {
  deactivateEmployee,
  getEmployee,
  reactivateEmployee,
  resendInvite,
  submitResignation,
  approveResignation,
  terminateEmployee,
  getFnFSettlement,
  updateFnFClearance,
  type Employee,
} from "../api";
import {
  listEmployeePayslips,
  listStructures,
  assignEmployeeSalary,
  type PayrollItem,
  type SalaryStructureListItem,
} from "../../payroll/api";
import { getAssignedShift } from "../../time_leave/api";
import { apiClient } from "../../../app/api-client";


interface InviteState {
  invite?: { sent_to: string; expires_at: string };
}

/**
 * Page 8, details tab only (Spec 14.3 / Section 19 WP-13). The KYC and
 * work-experience tabs WP-13's own deliverable text names are backed by
 * WP-08, which this session did not build (Section 19's WP-13 text assumes
 * WP-08 already ran by the time WP-13 does) — see the session report for
 * the full note. Only "details" has an API to render.
 */
export function EmployeeProfilePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const { notify } = useToast();
  const queryClient = useQueryClient();

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resent, setResent] = useState<{ sent_to: string; expires_at: string } | null>(null);
  const [resendBusy, setResendBusy] = useState(false);
  const [activeTab, setActiveTab] = useState<"overview" | "salary" | "payslips" | "exit">("overview");

  const employeeQuery = useQuery({
    queryKey: ["employee", id],
    queryFn: () => getEmployee(id as string),
    enabled: Boolean(id),
  });

  const assignedShiftQuery = useQuery({
    queryKey: ["shift", "assigned", id],
    queryFn: () => getAssignedShift(id as string),
    enabled: Boolean(id),
  });


  const invite = resent ?? (location.state as InviteState | null)?.invite;
  const isHr = user?.role === "hr_admin";

  async function handleResendInvite() {
    if (!id) return;
    setResendBusy(true);
    try {
      const result = await resendInvite(id);
      setResent(result.invite);
      notify(`Invitation re-sent to ${result.invite.sent_to}.`);
      await queryClient.invalidateQueries({ queryKey: ["employee", id] });
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setResendBusy(false);
    }
  }

  async function handleToggleActive() {
    if (!id || !employeeQuery.data) return;
    setBusy(true);
    try {
      if (employeeQuery.data.is_active) {
        await deactivateEmployee(id);
        notify("Employee deactivated.");
      } else {
        await reactivateEmployee(id);
        notify("Employee reactivated.");
      }
      await queryClient.invalidateQueries({ queryKey: ["employee", id] });
      await queryClient.invalidateQueries({ queryKey: ["employees"] });
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setBusy(false);
      setConfirmOpen(false);
    }
  }

  if (employeeQuery.isLoading) {
    return (
      <div className="row">
        <div className="spinner" />
        <span className="text-muted">Loading…</span>
      </div>
    );
  }
  if (employeeQuery.isError) {
    return <div className="alert alert-error">{parseApiError(employeeQuery.error).message}</div>;
  }
  const e = employeeQuery.data;
  if (!e) return null;

  return (
    <div className="stack gap-4">
      {/* Back Link */}
      <div>
        <Link to="/employees" className="btn btn-ghost btn-sm" style={{ paddingLeft: 0, textDecoration: "none" }}>
          ← Back to Employees
        </Link>
      </div>

      {/* Zoho / Enterprise Style Header Card */}
      <div className="card" style={{ padding: "1.25rem", borderLeft: "4px solid var(--color-primary, #2563eb)" }}>
        <div className="flex justify-between items-center" style={{ flexWrap: "wrap", gap: "1rem" }}>
          <div className="flex items-center gap-3">
            <div
              style={{
                width: "56px",
                height: "56px",
                borderRadius: "50%",
                background: "linear-gradient(135deg, #3b82f6, #1d4ed8)",
                color: "#ffffff",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "1.3rem",
                fontWeight: 700,
                boxShadow: "0 2px 8px rgba(37, 99, 235, 0.25)",
              }}
            >
              {e.first_name.charAt(0).toUpperCase()}
              {(e.last_name || "").charAt(0).toUpperCase()}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-muted" style={{ fontSize: "0.88rem", fontWeight: 600 }}>
                  {e.employee_code}
                </span>
                <h2 style={{ margin: 0, fontSize: "1.35rem" }}>
                  {e.first_name} {e.last_name || ""}
                </h2>
                <span className={"badge " + (e.is_active ? "badge-success" : "badge-muted")}>
                  {e.is_active ? "Active" : "Inactive"}
                </span>
              </div>
              <div className="text-muted" style={{ fontSize: "0.85rem", marginTop: "2px", display: "flex", alignItems: "center", gap: "6px" }}>
                <span>{e.position || "Staff"} • {e.level || "L1"} • {e.employment_type.replace("_", " ")}</span>
                {e.company_name && (
                  <span className="badge badge-outline" style={{ fontSize: "0.75rem", padding: "1px 6px" }}>
                    🏢 {e.company_name}
                  </span>
                )}
              </div>
            </div>
          </div>

          {isHr && (
            <div className="flex items-center gap-2">
              {e.invitation_status !== "activated" && (
                <button className="btn btn-sm btn-ghost" onClick={handleResendInvite} disabled={resendBusy}>
                  {resendBusy ? "Resending…" : "Resend Invite"}
                </button>
              )}
              <button className="btn btn-sm" onClick={() => navigate(`/employees/${e.id}/edit`)}>
                Edit Profile
              </button>
              <button
                className={e.is_active ? "btn btn-sm btn-danger" : "btn btn-sm btn-primary"}
                onClick={() => setConfirmOpen(true)}
              >
                {e.is_active ? "Deactivate" : "Reactivate"}
              </button>
            </div>
          )}
        </div>

        {/* Tab Navigation */}
        <div
          className="flex gap-4 border-b mt-4"
          style={{
            borderColor: "var(--color-border)",
            overflowX: "auto",
            paddingBottom: "1px",
          }}
        >
          {[
            { id: "overview", label: "Overview" },
            { id: "salary", label: "Salary Details" },
            { id: "payslips", label: "Payslips" },
            { id: "exit", label: "Resignation & FnF" },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              className="btn-ghost"
              style={{
                border: "none",
                background: "transparent",
                padding: "0.5rem 0.75rem",
                fontSize: "0.9rem",
                fontWeight: activeTab === tab.id ? 600 : 400,
                color: activeTab === tab.id ? "var(--color-primary, #2563eb)" : "var(--color-text-muted)",
                borderBottom: activeTab === tab.id ? "2px solid var(--color-primary, #2563eb)" : "2px solid transparent",
                borderRadius: 0,
                cursor: "pointer",
              }}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {invite && (
        <div className="alert alert-success mb-4">
          Invitation sent to <strong>{invite.sent_to}</strong>, expires {formatDateTime(invite.expires_at)}.
        </div>
      )}

      {/* TAB 1: OVERVIEW */}
      {activeTab === "overview" && (
        <div className="stack gap-4">
          <div className="card">
            <h3 style={{ fontSize: "1rem", marginBottom: "1rem", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
              Basic Information
            </h3>
            <div className="form-grid">
              <Field label="Full Name" value={`${e.first_name} ${e.last_name || ""}`} isLocked={true} />
              <Field label="Employee Code" value={e.employee_code} isLocked={true} />
              <Field label="Work Email" value={e.email} isLocked={true} />
              <Field label="Personal Email" value={e.personal_email ?? "—"} editable={true} />
              <Field label="Phone" value={e.phone ?? "—"} editable={true} />
              <Field label="Invitation Status" value={e.invitation_status.replace("_", " ")} isLocked={true} />
            </div>
          </div>

          <div className="card">
            <h3 style={{ fontSize: "1rem", marginBottom: "1rem", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
              Employment & Designation
            </h3>
            <div className="form-grid">
              <Field label="Position / Role" value={e.position ?? "—"} isLocked={true} />
              <Field label="Level" value={e.level ?? "—"} isLocked={true} />
              <Field label="Employment Type" value={e.employment_type.replace("_", " ")} isLocked={true} />
              <Field
                label="Assigned Shift"
                value={
                  assignedShiftQuery.data?.shift
                    ? `${assignedShiftQuery.data.shift.name} (${assignedShiftQuery.data.shift.start_time.slice(0, 5)} - ${assignedShiftQuery.data.shift.end_time.slice(0, 5)})`
                    : "General Shift (09:00 - 18:00)"
                }
                isLocked={true}
              />
              <Field label="Hire Date" value={formatDate(e.hire_date)} isLocked={true} />
              <Field label="Probation End Date" value={e.probation_end_date ? formatDate(e.probation_end_date) : "—"} isLocked={true} />
              <Field label="Notice Period" value={`${e.notice_period_days ?? 30} days`} isLocked={true} />
            </div>

          </div>
        </div>
      )}

      {/* TAB 2: SALARY DETAILS */}
      {activeTab === "salary" && (
        <EmployeeSalaryTab employeeId={e.id} companyId={e.company_id} isHr={isHr} />
      )}

      {/* TAB 3: PAYSLIPS */}
      {activeTab === "payslips" && (
        <EmployeePayslipsTab employeeId={e.id} />
      )}

      {/* TAB 4: RESIGNATION & FNF */}
      {activeTab === "exit" && (
        <ResignationAndFnFCard employee={e} isHr={isHr} onRefresh={() => queryClient.invalidateQueries({ queryKey: ["employee", id] })} />
      )}

      <ConfirmDialog
        open={confirmOpen}
        title={e.is_active ? "Deactivate employee?" : "Reactivate employee?"}
        message={
          e.is_active
            ? "The employee's row stays in the database; they just lose access and drop out of active lists."
            : "The employee regains access and reappears in active lists."
        }
        confirmLabel={e.is_active ? "Deactivate" : "Reactivate"}
        danger={e.is_active}
        busy={busy}
        onConfirm={handleToggleActive}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

function Field({
  label,
  value,
  isLocked,
  editable,
}: {
  label: string;
  value: React.ReactNode;
  isLocked?: boolean;
  editable?: boolean;
}) {
  return (
    <div className="field">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "4px" }}>
        <label style={{ margin: 0, fontSize: "0.8rem", color: "var(--color-muted, #64748b)" }}>{label}</label>
        {isLocked ? (
          <span
            style={{
              fontSize: "0.68rem",
              padding: "1px 6px",
              borderRadius: "4px",
              background: "#f1f5f9",
              color: "#64748b",
              border: "1px solid #e2e8f0",
              fontWeight: 500,
              display: "inline-flex",
              alignItems: "center",
              gap: "3px",
            }}
            title="Managed strictly by HR Admin"
          >
            🔒 HR Managed
          </span>
        ) : editable ? (
          <span
            style={{
              fontSize: "0.68rem",
              padding: "1px 6px",
              borderRadius: "4px",
              background: "#ecfdf5",
              color: "#059669",
              border: "1px solid #a7f3d0",
              fontWeight: 500,
            }}
            title="User editable"
          >
            ✎ Self Editable
          </span>
        ) : null}
      </div>
      <div style={{ fontWeight: 600, color: "var(--color-heading, #1e293b)", fontSize: "0.92rem" }}>
        {value}
      </div>
    </div>
  );
}

function ResignationAndFnFCard({
  employee,
  isHr,
  onRefresh,
}: {
  employee: Employee;
  isHr: boolean;
  onRefresh: () => void;
}) {
  const { notify } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [approving, setApproving] = useState(false);
  const [terminating, setTerminating] = useState(false);
  const [updatingClearance, setUpdatingClearance] = useState(false);

  const noticeRequired = employee.notice_period_days || 30;

  function calculateExpectedLwd(resDateStr: string, days: number): string {
    if (!resDateStr) return "";
    const [y, m, d] = resDateStr.split("-").map(Number);
    const dateObj = new Date(y, m - 1, d);
    dateObj.setDate(dateObj.getDate() + days);
    return dateObj.toISOString().split("T")[0];
  }

  function computeShortfallDays(resDateStr?: string | null, lwdStr?: string | null, reqDays: number = 30): { servedDays: number; shortfallDays: number } {
    if (!resDateStr || !lwdStr) return { servedDays: 0, shortfallDays: 0 };
    const rDate = new Date(resDateStr);
    const lDate = new Date(lwdStr);
    const diffTime = lDate.getTime() - rDate.getTime();
    const servedDays = Math.max(0, Math.round(diffTime / (1000 * 60 * 60 * 24)));
    const shortfallDays = Math.max(0, reqDays - servedDays);
    return { servedDays, shortfallDays };
  }

  // Resignation state (Track A)
  const [resignationDate, setResignationDate] = useState("");
  const [lastWorkingDate, setLastWorkingDate] = useState("");
  const [reason, setReason] = useState("");
  const [noticeWaived, setNoticeWaived] = useState(Boolean(employee.notice_waived));

  // Initialize review Last Working Date & Recovery Days
  const initialLwd = employee.last_working_date || "";
  const [reviewLwd, setReviewLwd] = useState(initialLwd);

  const initialShortfall = computeShortfallDays(
    employee.resignation_date,
    initialLwd,
    noticeRequired
  ).shortfallDays;

  const [recoveryDays, setRecoveryDays] = useState<number>(() => {
    if (employee.notice_waived) return 0;
    const recDays = employee.notice_recovery_days ?? 0;
    if (recDays > 0) return recDays;
    return initialShortfall;
  });

  // Sync recovery days if employee record updates
  useEffect(() => {
    if (employee.resignation_status === "submitted") {
      setNoticeWaived(Boolean(employee.notice_waived));
      const currentLwd = employee.last_working_date || "";
      setReviewLwd(currentLwd);
      const sf = computeShortfallDays(employee.resignation_date, currentLwd, noticeRequired).shortfallDays;
      const recDays = employee.notice_recovery_days ?? 0;
      setRecoveryDays(employee.notice_waived ? 0 : (recDays > 0 ? recDays : sf));
    }
  }, [employee.id, employee.resignation_status, employee.last_working_date, employee.resignation_date, employee.notice_recovery_days, employee.notice_waived, noticeRequired]);

  function handleReviewLwdChange(newLwd: string) {
    setReviewLwd(newLwd);
    if (!noticeWaived) {
      const sf = computeShortfallDays(employee.resignation_date, newLwd, noticeRequired).shortfallDays;
      setRecoveryDays(sf);
    }
  }

  function handleWaiveNoticeToggle(waived: boolean) {
    setNoticeWaived(waived);
    if (waived) {
      setRecoveryDays(0);
    } else {
      const sf = computeShortfallDays(employee.resignation_date, reviewLwd || employee.last_working_date, noticeRequired).shortfallDays;
      setRecoveryDays(sf);
    }
  }

  // Termination state (Track B)
  const [showTerminateModal, setShowTerminateModal] = useState(false);
  const [termDate, setTermDate] = useState(new Date().toISOString().slice(0, 10));
  const [termReason, setTermReason] = useState("Involuntary - Misconduct");
  const [severancePay, setSeverancePay] = useState("0");
  const [noticePayInLieu, setNoticePayInLieu] = useState("0");
  const [termNotes, setTermNotes] = useState("");

  // FnF settlement clearance adjustments
  const [editReimbursements, setEditReimbursements] = useState(String(employee.pending_reimbursements || 0));
  const [editGratuity, setEditGratuity] = useState(String(employee.gratuity_bonus || 0));
  const [editDeductions, setEditDeductions] = useState(String(employee.asset_deductions || 0));

  const status = employee.resignation_status ?? "none";
  const isSeparated = status === "approved" || !employee.is_active;

  const fnfQuery = useQuery({
    queryKey: ["fnf", employee.id],
    queryFn: () => getFnFSettlement(employee.id),
    enabled: isSeparated,
  });

  async function handleSubmitResignation(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await submitResignation(employee.id, {
        resignation_date: resignationDate || undefined,
        last_working_date: lastWorkingDate || undefined,
        reason: reason || undefined,
      });
      notify("Resignation submitted successfully. Status updated to Serving Notice.");
      onRefresh();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleApprove(approved: boolean) {
    setApproving(true);
    try {
      await approveResignation(employee.id, {
        approved,
        last_working_date: reviewLwd || undefined,
        notice_waived: noticeWaived,
        notice_recovery_days: recoveryDays,
      });
      notify(approved ? "Resignation approved. Employee is Serving Notice / Separated." : "Resignation rejected.");
      onRefresh();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setApproving(false);
    }
  }

  async function handleTerminate(e: React.FormEvent) {
    e.preventDefault();
    setTerminating(true);
    try {
      await terminateEmployee(employee.id, {
        termination_date: termDate,
        reason: termReason + (termNotes ? `: ${termNotes}` : ""),
        severance_pay: parseFloat(severancePay) || 0,
        notice_pay_in_lieu: parseFloat(noticePayInLieu) || 0,
      });
      notify("Employee separation initiated successfully. Status updated.");
      setShowTerminateModal(false);
      onRefresh();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setTerminating(false);
    }
  }

  async function handleClearanceToggle(key: "it_clearance" | "hr_clearance" | "finance_clearance", currentVal: boolean) {
    setUpdatingClearance(true);
    try {
      await updateFnFClearance(employee.id, { [key]: !currentVal });
      notify("Clearance sign-off updated.");
      fnfQuery.refetch();
      onRefresh();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setUpdatingClearance(false);
    }
  }

  async function handleSaveFinancialAdjustments() {
    setUpdatingClearance(true);
    try {
      await updateFnFClearance(employee.id, {
        pending_reimbursements: parseFloat(editReimbursements) || 0,
        gratuity_bonus: parseFloat(editGratuity) || 0,
        asset_deductions: parseFloat(editDeductions) || 0,
      });
      notify("FnF financial adjustments saved.");
      fnfQuery.refetch();
      onRefresh();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setUpdatingClearance(false);
    }
  }

  async function handleFinalSettlementRelease() {
    if (!fnfQuery.data?.can_release_settlement) {
      notify("All department clearances (IT, HR, Finance) must be signed off before release.", "error");
      return;
    }
    const confirmed = window.confirm(
      `Confirm final settlement release of ₹${Number(fnfQuery.data.total_settlement_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}? This locks the settlement and excludes employee from future recurring monthly pay runs.`
    );
    if (!confirmed) return;

    setUpdatingClearance(true);
    try {
      await updateFnFClearance(employee.id, { mark_settled: true });
      notify("FnF Settlement released successfully! Employee account finalized.", "success");
      fnfQuery.refetch();
      onRefresh();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setUpdatingClearance(false);
    }
  }

  return (
    <div className="card mb-4">
      <div className="row-between mb-3">
        <div>
          <h3 className="mb-0">Departure & Separation Lifecycle (Resignation, Termination & FnF)</h3>
          <p className="text-muted text-xs mb-0">Audited offboarding tracks: Employee Resignation, Company Termination, and Full & Final settlement.</p>
        </div>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <span
            className={
              "badge " +
              (employee.fnf_settled_at
                ? "badge-success"
                : status === "approved"
                ? "badge-danger"
                : status === "submitted"
                ? "badge-warning"
                : "badge-muted")
            }
          >
            {employee.fnf_settled_at
              ? "FnF Settled"
              : employee.separation_type === "involuntary"
              ? "Terminated"
              : status === "approved"
              ? "Serving Notice / Separated"
              : status === "submitted"
              ? "Resignation Pending Review"
              : "Active"}
          </span>
          {isHr && employee.is_active && status === "none" && (
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => setShowTerminateModal(true)}
              title="Company initiated involuntary termination"
            >
              + Initiate Separation / Terminate
            </button>
          )}
        </div>
      </div>

      {/* TRACK A: VOLUNTARY RESIGNATION FORM */}
      {status === "none" && (
        <form onSubmit={handleSubmitResignation} className="stack">
          <div style={{ background: "var(--color-bg, #f8fafc)", padding: "12px 14px", borderRadius: "6px", border: "1px solid var(--color-border)" }}>
            <h4 style={{ margin: "0 0 4px 0", fontSize: "0.9rem" }}>Track A: Formal Voluntary Resignation</h4>
            <p className="text-muted text-xs mb-3">
              Standard notice period is <b>{employee.notice_period_days || 30} days</b>. Submit formal resignation with proposed Last Working Day (LWD).
            </p>
            <div className="form-grid">
              <div className="field">
                <label>Resignation submission date</label>
                <input
                  type="date"
                  value={resignationDate}
                  onChange={(e) => {
                    const newResDate = e.target.value;
                    setResignationDate(newResDate);
                    if (!lastWorkingDate || lastWorkingDate === calculateExpectedLwd(resignationDate, noticeRequired)) {
                      setLastWorkingDate(calculateExpectedLwd(newResDate, noticeRequired));
                    }
                  }}
                  required
                />
              </div>
              <div className="field">
                <label>Proposed Last Working Day (LWD)</label>
                <input
                  type="date"
                  value={lastWorkingDate}
                  onChange={(e) => setLastWorkingDate(e.target.value)}
                  required
                />
              </div>
            </div>

            {/* Amber Warning on Notice Shortfall for Track A */}
            {(() => {
              const { servedDays, shortfallDays } = computeShortfallDays(resignationDate, lastWorkingDate, noticeRequired);
              const expectedLwd = calculateExpectedLwd(resignationDate, noticeRequired);
              if (shortfallDays > 0) {
                return (
                  <div
                    style={{
                      backgroundColor: "#fffbeb",
                      border: "1px solid #fde68a",
                      borderLeft: "4px solid #f59e0b",
                      borderRadius: "6px",
                      padding: "8px 12px",
                      color: "#92400e",
                      fontSize: "0.82rem",
                      marginTop: "10px",
                    }}
                  >
                    ⚠️ <strong>Notice Shortfall Warning:</strong> Your contractual notice period is <b>{noticeRequired} days</b> (Expected LWD: <b>{expectedLwd}</b>). Requesting <b>{lastWorkingDate}</b> ({servedDays} days served) creates a <b>{shortfallDays}-day notice shortfall</b> that may be deducted from Full & Final settlement unless approved by HR.
                  </div>
                );
              }
              return null;
            })()}

            <div className="field mt-2">
              <label>Reason for Resignation</label>
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                style={{ marginBottom: "8px" }}
              >
                <option value="">Select departure reason...</option>
                <option value="Better Opportunity">Better Opportunity</option>
                <option value="Higher Studies">Higher Studies</option>
                <option value="Personal / Relocation">Personal / Family Relocation</option>
                <option value="Career Transition">Career Transition / Freelance</option>
                <option value="Health / Medical">Health / Medical</option>
                <option value="Other">Other</option>
              </select>
            </div>
            <div className="row-end">
              <button type="submit" className="btn btn-danger" disabled={submitting}>
                {submitting ? "Submitting…" : "Request Resignation"}
              </button>
            </div>
          </div>
        </form>
      )}

      {/* TRACK B: TERMINATION MODAL */}
      {showTerminateModal && (
        <div className="modal-backdrop" onClick={() => setShowTerminateModal(false)}>
          <div className="modal card" style={{ maxWidth: "520px" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 style={{ margin: 0, color: "#dc2626" }}>⚠️ Initiate Involuntary Termination</h3>
              <button type="button" className="modal-close-btn" onClick={() => setShowTerminateModal(false)}>✕</button>
            </div>
            <form onSubmit={handleTerminate} className="stack gap-3 mt-2">
              <p className="text-xs text-muted" style={{ margin: 0 }}>
                Initiates official involuntary termination. The employee account will be severed on the termination date with recorded severance and notice pay in lieu.
              </p>

              <div className="form-grid">
                <div className="field">
                  <label>Effective Termination Date *</label>
                  <input
                    type="date"
                    value={termDate}
                    onChange={(e) => setTermDate(e.target.value)}
                    required
                  />
                </div>
                <div className="field">
                  <label>Termination Reason *</label>
                  <select
                    value={termReason}
                    onChange={(e) => setTermReason(e.target.value)}
                    required
                  >
                    <option value="Involuntary - Misconduct">Involuntary - Misconduct / Policy Violation</option>
                    <option value="Involuntary - Performance">Involuntary - Underperformance / Failed PIP</option>
                    <option value="Involuntary - Redundancy">Involuntary - Role Redundancy / Restructuring</option>
                    <option value="Involuntary - Contract End">Involuntary - Mutual Separation / Contract End</option>
                  </select>
                </div>
              </div>

              <div className="form-grid">
                <div className="field">
                  <label>Severance Pay (₹)</label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={severancePay}
                    onChange={(e) => setSeverancePay(e.target.value)}
                    placeholder="0.00"
                  />
                </div>
                <div className="field">
                  <label>Notice Pay in Lieu (₹)</label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={noticePayInLieu}
                    onChange={(e) => setNoticePayInLieu(e.target.value)}
                    placeholder="0.00"
                  />
                </div>
              </div>

              <div className="field">
                <label>Confidential Notes / Documentation</label>
                <textarea
                  rows={2}
                  value={termNotes}
                  onChange={(e) => setTermNotes(e.target.value)}
                  placeholder="Reference HR case, disciplinary hearing, or severance terms..."
                />
              </div>

              <div className="row-end gap-2 mt-2">
                <button type="button" className="btn" onClick={() => setShowTerminateModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-danger" disabled={terminating}>
                  {terminating ? "Processing…" : "Confirm Termination"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* STATUS: SUBMITTED (PENDING HR REVIEW) */}
      {status === "submitted" && (
        <div className="stack">
          <div className="form-grid">
            <Field label="Resignation date" value={employee.resignation_date ?? "—"} />
            <Field label="Proposed Last Working Day" value={employee.last_working_date ?? "—"} />
          </div>
          {isHr ? (
            <div className="card" style={{ background: "var(--color-bg)" }}>
              <h4 className="mt-0 mb-2">HR Approval & Notice Terms (Track A Review)</h4>
              
              {/* Shortfall & Notice Breakdown Banner */}
              {(() => {
                const { servedDays, shortfallDays } = computeShortfallDays(
                  employee.resignation_date,
                  reviewLwd || employee.last_working_date,
                  noticeRequired
                );
                return (
                  <div
                    className="p-2 mb-3 rounded"
                    style={{
                      backgroundColor: shortfallDays > 0 && !noticeWaived ? "#fffbeb" : "#f1f5f9",
                      border: `1px solid ${shortfallDays > 0 && !noticeWaived ? "#fde68a" : "#cbd5e1"}`,
                      fontSize: "0.82rem",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      flexWrap: "wrap",
                      gap: "8px",
                    }}
                  >
                    <div>
                      <span>Contractual Notice: <b>{noticeRequired} days</b></span>
                      <span className="mx-2">•</span>
                      <span>Served Notice: <b>{servedDays} days</b></span>
                      <span className="mx-2">•</span>
                      <span>
                        Shortfall: <b style={{ color: shortfallDays > 0 ? "#b45309" : "#15803d" }}>{shortfallDays} days</b>
                      </span>
                    </div>
                    {noticeWaived && (
                      <span className="badge badge-success">✓ Notice Waived by HR</span>
                    )}
                  </div>
                );
              })()}

              <div className="form-grid mb-3">
                <div className="field">
                  <label>Confirmed Last Working Day (LWD)</label>
                  <input
                    type="date"
                    value={reviewLwd}
                    onChange={(e) => handleReviewLwdChange(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label>Notice recovery days (if unserved)</label>
                  <input
                    type="number"
                    min="0"
                    value={recoveryDays}
                    onChange={(e) => setRecoveryDays(Number(e.target.value))}
                    disabled={noticeWaived}
                    title={noticeWaived ? "Notice period is waived" : "Number of unserved days to deduct in FnF"}
                  />
                  <span className="field-hint" style={{ fontSize: "0.75rem" }}>
                    {noticeWaived
                      ? "Automatically set to 0 because notice is waived."
                      : "Deducted in Full & Final settlement (Recovery = Days × Per-day Salary)."}
                  </span>
                </div>
              </div>
              <div className="row mb-3">
                <input
                  type="checkbox"
                  id="noticeWaived"
                  checked={noticeWaived}
                  onChange={(e) => handleWaiveNoticeToggle(e.target.checked)}
                />
                <label htmlFor="noticeWaived" className="text-sm font-medium" style={{ cursor: "pointer" }}>
                  Waive notice period (exempt employee from notice shortfall deduction)
                </label>
              </div>
              <div className="row gap-2">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleApprove(true)}
                  disabled={approving}
                >
                  {approving ? "Processing…" : "Approve Resignation & Set Serving Notice"}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => handleApprove(false)}
                  disabled={approving}
                >
                  Discuss / Reject
                </button>
              </div>
            </div>
          ) : (
            <div className="alert alert-warning">
              Resignation submitted. Currently under review by HR Admin / Manager.
            </div>
          )}
        </div>
      )}

      {/* STATUS: APPROVED OR TERMINATED (FULL & FINAL SETTLEMENT) */}
      {isSeparated && (
        <div className="stack mt-2">
          <div className="form-grid mb-3">
            <Field label="Separation Track" value={employee.separation_type === "involuntary" ? "Involuntary Termination" : employee.separation_type === "pip_failed" ? "Failed PIP Separation" : "Voluntary Resignation"} />
            <Field label="Last Working Day (LWD)" value={formatDate(employee.last_working_date)} />
            <Field label="Notice Waived" value={employee.notice_waived ? "Yes (Waived)" : "No"} />
            <Field label="Notice Recovery Days" value={employee.notice_recovery_days ?? 0} />
          </div>

          {/* ASSET & CLEARANCE SIGN-OFF SECTION */}
          <div className="card mb-3" style={{ background: "#f8fafc", border: "1px solid var(--color-border)" }}>
            <h4 className="mt-0 mb-1" style={{ fontSize: "0.95rem" }}>🏢 Department Asset & Clearance Sign-Off</h4>
            <p className="text-muted text-xs mb-3">
              IT, HR, and Finance clearance confirmations are strictly mandatory before the Full & Final payout release button unlocks.
            </p>

            <div className="grid grid-3 gap-3">
              {/* IT Clearance */}
              <div className="p-3 bg-white rounded border" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <strong style={{ fontSize: "0.85rem" }}>💻 IT Department</strong>
                  <div className="text-xs text-muted">Laptop, access keys, monitors</div>
                </div>
                {isHr ? (
                  <button
                    type="button"
                    className={`btn btn-xs ${employee.it_clearance ? "btn-success" : "btn-outline"}`}
                    disabled={updatingClearance}
                    onClick={() => handleClearanceToggle("it_clearance", Boolean(employee.it_clearance))}
                  >
                    {employee.it_clearance ? "✓ Returned" : "Pending"}
                  </button>
                ) : (
                  <span className={`badge ${employee.it_clearance ? "badge-success" : "badge-muted"}`}>
                    {employee.it_clearance ? "Cleared" : "Pending"}
                  </span>
                )}
              </div>

              {/* HR Clearance */}
              <div className="p-3 bg-white rounded border" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <strong style={{ fontSize: "0.85rem" }}>🪪 HR Department</strong>
                  <div className="text-xs text-muted">ID card, access badges, NDA</div>
                </div>
                {isHr ? (
                  <button
                    type="button"
                    className={`btn btn-xs ${employee.hr_clearance ? "btn-success" : "btn-outline"}`}
                    disabled={updatingClearance}
                    onClick={() => handleClearanceToggle("hr_clearance", Boolean(employee.hr_clearance))}
                  >
                    {employee.hr_clearance ? "✓ Returned" : "Pending"}
                  </button>
                ) : (
                  <span className={`badge ${employee.hr_clearance ? "badge-success" : "badge-muted"}`}>
                    {employee.hr_clearance ? "Cleared" : "Pending"}
                  </span>
                )}
              </div>

              {/* Finance Clearance */}
              <div className="p-3 bg-white rounded border" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <strong style={{ fontSize: "0.85rem" }}>💰 Finance Department</strong>
                  <div className="text-xs text-muted">Loans, advance reconciliations</div>
                </div>
                {isHr ? (
                  <button
                    type="button"
                    className={`btn btn-xs ${employee.finance_clearance ? "btn-success" : "btn-outline"}`}
                    disabled={updatingClearance}
                    onClick={() => handleClearanceToggle("finance_clearance", Boolean(employee.finance_clearance))}
                  >
                    {employee.finance_clearance ? "✓ Cleared" : "Pending"}
                  </button>
                ) : (
                  <span className={`badge ${employee.finance_clearance ? "badge-success" : "badge-muted"}`}>
                    {employee.finance_clearance ? "Cleared" : "Pending"}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* FNF CALCULATION BREAKDOWN */}
          <div>
            <div className="row-between mb-2">
              <h4 className="mb-0">Full-and-Final (FnF) Settlement Statement</h4>
              {employee.fnf_settled_at && (
                <span className="badge badge-success">Settlement Released on {formatDate(employee.fnf_settled_at)}</span>
              )}
            </div>

            {fnfQuery.isLoading && (
              <div className="row">
                <div className="spinner" />
                <span className="text-muted">Calculating FnF statement…</span>
              </div>
            )}
            {fnfQuery.isError && (
              <div className="alert alert-error">
                {parseApiError(fnfQuery.error).message}
              </div>
            )}

            {fnfQuery.data && (
              <div className="card" style={{ background: "var(--color-bg)" }}>
                {/* Financial Component Grid */}
                <div className="form-grid mb-3">
                  <Field
                    label="Total Monthly Gross"
                    value={`₹${Number(fnfQuery.data.monthly_gross_salary || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                  />
                  <Field
                    label="Effective Per-Day Salary (30d base)"
                    value={`₹${Number(fnfQuery.data.per_day_salary || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })} / day`}
                  />
                  <Field
                    label="Unpaid Salary Days"
                    value={`${fnfQuery.data.unpaid_salary_days} days`}
                  />
                  <Field
                    label="Prorated Unpaid Salary"
                    value={`₹${Number(fnfQuery.data.unpaid_salary_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                  />
                  <Field
                    label="Encashable Leave Days"
                    value={`${fnfQuery.data.encashable_leave_days} days`}
                  />
                  <Field
                    label="Leave Encashment (Add)"
                    value={`+ ₹${Number(fnfQuery.data.leave_encashment_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                  />
                  <Field
                    label="Severance / Notice In Lieu"
                    value={`+ ₹${Number(fnfQuery.data.severance_pay).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                  />
                  <Field
                    label="Pending Reimbursements"
                    value={`+ ₹${Number(fnfQuery.data.pending_reimbursements).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                  />
                  <Field
                    label="Gratuity / Special Bonus"
                    value={`+ ₹${Number(fnfQuery.data.gratuity_bonus).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                  />
                  <Field
                    label="Notice Shortfall Deduction"
                    value={`- ₹${Number(fnfQuery.data.notice_recovery_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })} (${fnfQuery.data.notice_recovery_days} days)`}
                  />
                  <Field
                    label="Asset Damage / Deductions"
                    value={`- ₹${Number(fnfQuery.data.asset_deductions).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                  />
                </div>

                {/* HR Adjustment inputs if not settled */}
                {isHr && !employee.fnf_settled_at && (
                  <div className="p-3 bg-white rounded border mb-3">
                    <strong style={{ fontSize: "0.85rem", display: "block", marginBottom: "8px" }}>Adjust Financial Items</strong>
                    <div className="grid grid-3 gap-3">
                      <div className="field">
                        <label style={{ fontSize: "11px" }}>Pending Reimbursements (₹)</label>
                        <input
                          type="number"
                          step="0.01"
                          value={editReimbursements}
                          onChange={(e) => setEditReimbursements(e.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label style={{ fontSize: "11px" }}>Gratuity / Bonus (₹)</label>
                        <input
                          type="number"
                          step="0.01"
                          value={editGratuity}
                          onChange={(e) => setEditGratuity(e.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label style={{ fontSize: "11px" }}>Asset Damage / Deductions (₹)</label>
                        <input
                          type="number"
                          step="0.01"
                          value={editDeductions}
                          onChange={(e) => setEditDeductions(e.target.value)}
                        />
                      </div>
                    </div>
                    <div className="row-end mt-2">
                      <button
                        type="button"
                        className="btn btn-sm btn-outline"
                        onClick={handleSaveFinancialAdjustments}
                        disabled={updatingClearance}
                      >
                        Recalculate Statement
                      </button>
                    </div>
                  </div>
                )}

                {/* Net Payout Summary Bar */}
                {(() => {
                  const netAmount = Number(fnfQuery.data.total_settlement_amount || 0);
                  const isPositive = netAmount >= 0;
                  return (
                    <div
                      className="row-between align-center mt-3"
                      style={{
                        borderTop: "2px solid var(--color-border)",
                        paddingTop: "var(--space-3)",
                      }}
                    >
                      <div>
                        <div className="font-semibold text-base" style={{ color: isPositive ? "var(--color-heading, #1e293b)" : "#b91c1c" }}>
                          {isPositive ? "Total Net FnF Payout (Payable to Employee)" : "Total Net Recovery (Payable by Employee to Company)"}
                        </div>
                        <div className="text-xs text-muted">
                          {isPositive
                            ? "(Salary + Leaves + Reimbursements + Gratuity + Severance) - (Notice Shortfall + Deductions)"
                            : "Pending collection via invoice/demand note before issuing relieving letter."}
                        </div>
                      </div>
                      <div className="text-right">
                        <span className="text-xl font-bold" style={{ color: isPositive ? "var(--color-primary)" : "#b91c1c" }}>
                          {isPositive
                            ? `₹${netAmount.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`
                            : `-₹${Math.abs(netAmount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                        </span>
                      </div>
                    </div>
                  );
                })()}

                {/* Final Settlement Release Action */}
                {isHr && !employee.fnf_settled_at && (
                  <div className="row-end mt-4 pt-3 border-t">
                    <button
                      type="button"
                      className="btn btn-success"
                      disabled={!fnfQuery.data.can_release_settlement || updatingClearance}
                      onClick={handleFinalSettlementRelease}
                      title={
                        fnfQuery.data.can_release_settlement
                          ? "Release and lock FnF Settlement"
                          : "Requires IT, HR, and Finance clearance sign-off"
                      }
                    >
                      {fnfQuery.data.can_release_settlement
                        ? "🚀 Generate & Release FnF Settlement"
                        : "🔒 Sign-off Required for Release"}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

interface EmployeeSalaryData {
  employee_id: string;
  structure_id: string;
  structure_name: string;
  ctc: string;
  effective_from: string;
  effective_to: string | null;
  revision_reason: string | null;
  earnings: Array<{ code: string; name: string; amount: string }>;
  deductions: Array<{ code: string; name: string; amount: string }>;
  gross_earnings: string;
}

function EmployeeSalaryTab({ employeeId, companyId, isHr }: { employeeId: string; companyId?: string | null; isHr: boolean }) {
  const { notify } = useToast();
  const queryClient = useQueryClient();

  const [showAssignModal, setShowAssignModal] = useState(false);
  const [selectedStructId, setSelectedStructId] = useState("");
  const [assignCtc, setAssignCtc] = useState("600000.00");
  const [assignEffectiveFrom, setAssignEffectiveFrom] = useState(
    new Date().toISOString().split("T")[0]
  );
  const [saving, setSaving] = useState(false);

  const salaryQuery = useQuery<EmployeeSalaryData | null>({
    queryKey: ["employee_salary", employeeId],
    queryFn: async () => {
      try {
        const res = await apiClient.get<EmployeeSalaryData>(`/payroll/employees/${employeeId}/salary`);
        return res.data;
      } catch (err: unknown) {
        const parsed = parseApiError(err);
        if (parsed.status === 404) return null;
        throw err;
      }
    },
  });

  const structuresQuery = useQuery({
    queryKey: ["salary-structures", companyId],
    queryFn: () => listStructures(1, 100, companyId || undefined),
    enabled: isHr && showAssignModal,
  });

  async function handleAssignSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedStructId) {
      notify("Please select a salary structure", "error");
      return;
    }
    setSaving(true);
    try {
      await assignEmployeeSalary(employeeId, {
        structure_id: selectedStructId,
        ctc: assignCtc,
        effective_from: assignEffectiveFrom,
      });
      notify("Salary assigned successfully", "success");
      setShowAssignModal(false);
      await queryClient.invalidateQueries({ queryKey: ["employee_salary", employeeId] });
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setSaving(false);
    }
  }

  if (salaryQuery.isLoading) {
    return (
      <div className="card row" style={{ padding: "2rem" }}>
        <div className="spinner" />
        <span className="text-muted">Loading salary & compensation details...</span>
      </div>
    );
  }

  const sal = salaryQuery.data;

  return (
    <div className="stack gap-4">
      <div className="card">
        <div className="flex justify-between items-center border-b pb-3 mb-4">
          <div>
            <h3 style={{ margin: 0, fontSize: "1.1rem" }}>Current Compensation & Structure</h3>
            <p className="text-muted text-sm" style={{ margin: "2px 0 0" }}>
              CTC breakdown, allowances, statutory deductions & take-home pay
            </p>
          </div>
          {isHr && (
            <button className="btn btn-primary btn-sm" onClick={() => setShowAssignModal(true)}>
              {sal ? "Revise / Change Salary" : "+ Assign Salary Structure"}
            </button>
          )}
        </div>

        {!sal ? (
          <div style={{ textAlign: "center", padding: "2.5rem 1rem" }}>
            <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>💰</div>
            <h4 style={{ margin: "0 0 0.5rem" }}>No Salary Structure Assigned</h4>
            <p className="text-muted text-sm" style={{ maxWidth: "420px", margin: "0 auto 1.25rem" }}>
              This employee doesn't have an active salary structure linked yet.
            </p>
            {isHr && (
              <button className="btn btn-primary btn-sm" onClick={() => setShowAssignModal(true)}>
                Assign Salary Structure
              </button>
            )}
          </div>
        ) : (
          <div className="stack gap-4">
            <div className="grid-3" style={{ gap: "1rem" }}>
              <div className="card" style={{ background: "var(--color-bg)", padding: "1rem" }}>
                <div className="text-muted text-xs font-semibold uppercase">Annual CTC</div>
                <div className="text-xl font-bold" style={{ color: "var(--color-primary, #2563eb)", marginTop: "4px" }}>
                  ₹{Number(sal.ctc).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
                <div className="text-muted text-xs" style={{ marginTop: "2px" }}>
                  Structure: <strong>{sal.structure_name}</strong>
                </div>
              </div>

              <div className="card" style={{ background: "var(--color-bg)", padding: "1rem" }}>
                <div className="text-muted text-xs font-semibold uppercase">Monthly Gross Pay</div>
                <div className="text-xl font-bold text-success" style={{ marginTop: "4px" }}>
                  ₹{Number(sal.gross_earnings).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
                <div className="text-muted text-xs" style={{ marginTop: "2px" }}>
                  Before statutory deductions
                </div>
              </div>

              <div className="card" style={{ background: "var(--color-bg)", padding: "1rem" }}>
                <div className="text-muted text-xs font-semibold uppercase">Effective From</div>
                <div className="text-md font-semibold" style={{ marginTop: "4px" }}>
                  {formatDate(sal.effective_from)}
                </div>
                <div className="text-muted text-xs" style={{ marginTop: "2px" }}>
                  {sal.revision_reason || "Initial assignment"}
                </div>
              </div>
            </div>

            <div className="grid-2" style={{ gap: "1.5rem" }}>
              {/* Earnings Breakdown */}
              <div className="card" style={{ border: "1px solid var(--color-border)" }}>
                <h4 style={{ margin: "0 0 0.75rem", fontSize: "0.95rem", color: "#16a34a" }}>
                  Earnings (Monthly)
                </h4>
                <table className="table text-sm" style={{ width: "100%" }}>
                  <thead>
                    <tr>
                      <th>Component</th>
                      <th style={{ textAlign: "right" }}>Amount (₹)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sal.earnings.map((e) => (
                      <tr key={e.code}>
                        <td>{e.name}</td>
                        <td style={{ textAlign: "right", fontWeight: 600 }}>
                          ₹{Number(e.amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    ))}
                    <tr style={{ borderTop: "2px solid var(--color-border)", fontWeight: 700 }}>
                      <td>Total Gross</td>
                      <td style={{ textAlign: "right", color: "#16a34a" }}>
                        ₹{Number(sal.gross_earnings).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Deductions Breakdown */}
              <div className="card" style={{ border: "1px solid var(--color-border)" }}>
                <h4 style={{ margin: "0 0 0.75rem", fontSize: "0.95rem", color: "#dc2626" }}>
                  Deductions (Monthly)
                </h4>
                {sal.deductions.length === 0 ? (
                  <p className="text-muted text-sm">No monthly deductions configured.</p>
                ) : (
                  <table className="table text-sm" style={{ width: "100%" }}>
                    <thead>
                      <tr>
                        <th>Component</th>
                        <th style={{ textAlign: "right" }}>Amount (₹)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sal.deductions.map((d) => (
                        <tr key={d.code}>
                          <td>{d.name}</td>
                          <td style={{ textAlign: "right", fontWeight: 600, color: "#dc2626" }}>
                            - ₹{Number(d.amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
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
      </div>

      {/* Assign Salary Modal */}
      {showAssignModal && (
        <div className="modal-backdrop" onClick={() => setShowAssignModal(false)}>
          <div className="modal card" style={{ maxWidth: "520px" }} onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center border-b pb-3 mb-4">
              <h3 style={{ margin: 0 }}>Assign / Revise Salary Structure</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowAssignModal(false)}
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleAssignSubmit} className="stack gap-4">
              <div className="field">
                <label>Salary Structure *</label>
                <select
                  value={selectedStructId}
                  onChange={(e) => setSelectedStructId(e.target.value)}
                  required
                >
                  <option value="">Select structure template...</option>
                  {structuresQuery.data?.items.map((s: SalaryStructureListItem) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.country} • {s.level || "All Levels"})
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label>Annual CTC (₹) *</label>
                <input
                  type="number"
                  value={assignCtc}
                  onChange={(e) => setAssignCtc(e.target.value)}
                  required
                  min="50000"
                  step="1000"
                />
              </div>

              <div className="field">
                <label>Effective From *</label>
                <input
                  type="date"
                  value={assignEffectiveFrom}
                  onChange={(e) => setAssignEffectiveFrom(e.target.value)}
                  required
                />
              </div>

              <div className="flex justify-end gap-2 mt-4">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setShowAssignModal(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? "Saving..." : "Save Salary"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function EmployeePayslipsTab({ employeeId }: { employeeId: string }) {
  const payslipsQuery = useQuery<PayrollItem[]>({
    queryKey: ["employee_payslips", employeeId],
    queryFn: () => listEmployeePayslips(employeeId),
  });

  if (payslipsQuery.isLoading) {
    return (
      <div className="card row" style={{ padding: "2rem" }}>
        <div className="spinner" />
        <span className="text-muted">Loading employee payslips...</span>
      </div>
    );
  }

  const payslips = payslipsQuery.data ?? [];

  return (
    <div className="card">
      <h3 style={{ margin: "0 0 1rem", fontSize: "1.1rem" }}>Generated Payslips & Statements</h3>
      {payslips.length === 0 ? (
        <div style={{ textAlign: "center", padding: "2.5rem 1rem" }}>
          <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📄</div>
          <h4 style={{ margin: "0 0 0.5rem" }}>No Payslips Available</h4>
          <p className="text-muted text-sm">
            Payslips will appear here once monthly payroll runs are processed and approved.
          </p>
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="table text-sm" style={{ width: "100%" }}>
            <thead>
              <tr>
                <th>Gross Salary</th>
                <th>Deductions</th>
                <th>Reimbursements</th>
                <th>Net Pay</th>
                <th>Working Days</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {payslips.map((item) => (
                <tr key={item.id}>
                  <td style={{ fontWeight: 600 }}>₹{Number(item.gross_salary).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                  <td style={{ color: "#dc2626" }}>- ₹{Number(item.total_deductions).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                  <td style={{ color: "#2563eb" }}>+ ₹{Number(item.reimbursement_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                  <td style={{ fontWeight: 700, color: "#16a34a", fontSize: "1rem" }}>
                    ₹{Number(item.net_salary).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                  </td>
                  <td>{item.present_days} / {item.working_days} days</td>
                  <td>
                    <span className="badge badge-success">Released</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

