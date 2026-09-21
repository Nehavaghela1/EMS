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

  const [moreActionsOpen, setMoreActionsOpen] = useState(false);

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

      {/* Unified Zoho-grade Profile Hero Banner */}
      <div
        className="card"
        style={{
          padding: 0,
          overflow: "hidden",
          border: "1px solid var(--color-border, #e2e8f0)",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
        }}
      >
        {/* Banner Top Area */}
        <div
          style={{
            background: "linear-gradient(180deg, #f8fafc 0%, #ffffff 100%)",
            padding: "1.5rem 1.75rem 1.25rem",
            borderBottom: "1px solid var(--color-border, #e2e8f0)",
          }}
        >
          <div className="flex justify-between items-start" style={{ flexWrap: "wrap", gap: "1.25rem" }}>
            <div className="flex items-center gap-4">
              <div
                style={{
                  width: "68px",
                  height: "68px",
                  borderRadius: "14px",
                  background: "linear-gradient(135deg, #2563eb, #1d4ed8)",
                  color: "#ffffff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1.5rem",
                  fontWeight: 700,
                  boxShadow: "0 4px 12px rgba(37, 99, 235, 0.25)",
                  flexShrink: 0,
                }}
              >
                {e.first_name.charAt(0).toUpperCase()}
                {(e.last_name || "").charAt(0).toUpperCase()}
              </div>
              <div>
                <div className="flex items-center gap-2" style={{ flexWrap: "wrap" }}>
                  <h1 style={{ margin: 0, fontSize: "1.45rem", fontWeight: 700, color: "var(--color-heading, #0f172a)" }}>
                    {e.first_name} {e.last_name || ""}
                  </h1>
                  <span
                    className="font-mono"
                    style={{
                      fontSize: "0.82rem",
                      fontWeight: 600,
                      background: "#f1f5f9",
                      padding: "2px 8px",
                      borderRadius: "4px",
                      color: "#475569",
                      border: "1px solid #e2e8f0",
                    }}
                  >
                    {e.employee_code}
                  </span>
                  <span className={"badge " + (e.is_active ? "badge-success" : "badge-muted")}>
                    {e.is_active ? "● Active" : "Inactive"}
                  </span>
                </div>
                {/* Metadata Badges Row */}
                <div className="flex items-center gap-2 mt-2" style={{ flexWrap: "wrap", fontSize: "0.82rem", color: "#64748b" }}>
                  <span style={{ fontWeight: 500 }}>{e.position || "Staff"}</span>
                  <span>•</span>
                  <span className="badge badge-outline" style={{ textTransform: "capitalize" }}>{e.level || "L1"}</span>
                  <span>•</span>
                  <span style={{ textTransform: "capitalize" }}>{e.employment_type.replace("_", " ")}</span>
                  {e.company_name && (
                    <>
                      <span>•</span>
                      <span>🏢 {e.company_name}</span>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Action Buttons: Primary + Tucked Ellipsis */}
            {isHr && (
              <div className="flex items-center gap-2">
                {e.invitation_status !== "activated" && (
                  <button className="btn btn-sm btn-ghost" onClick={handleResendInvite} disabled={resendBusy}>
                    {resendBusy ? "Resending…" : "Resend Invite"}
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  onClick={() => navigate(`/employees/${e.id}/edit`)}
                  style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}
                >
                  <span>✏️</span> Edit Profile
                </button>

                {/* More Actions Dropdown (Tucking Deactivate safely) */}
                <div style={{ position: "relative" }}>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline"
                    style={{ padding: "0.4rem 0.65rem", fontWeight: 700 }}
                    onClick={() => setMoreActionsOpen(!moreActionsOpen)}
                    title="More actions"
                  >
                    •••
                  </button>
                  {moreActionsOpen && (
                    <div
                      style={{
                        position: "absolute",
                        right: 0,
                        top: "115%",
                        background: "#ffffff",
                        border: "1px solid var(--color-border, #e2e8f0)",
                        borderRadius: "8px",
                        boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1)",
                        zIndex: 50,
                        minWidth: "180px",
                        padding: "6px 0",
                      }}
                      onMouseLeave={() => setMoreActionsOpen(false)}
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
                          color: e.is_active ? "#dc2626" : "#2563eb",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          gap: "8px",
                        }}
                        onClick={() => {
                          setMoreActionsOpen(false);
                          setConfirmOpen(true);
                        }}
                      >
                        <span>{e.is_active ? "🛑" : "✅"}</span>
                        <span>{e.is_active ? "Deactivate Employee" : "Reactivate Employee"}</span>
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Segmented Tabs Anchored to Hero Bottom */}
        <div
          className="flex gap-2"
          style={{
            background: "#ffffff",
            padding: "0 1.5rem",
            overflowX: "auto",
          }}
        >
          {[
            { id: "overview", label: "Overview", icon: "👤" },
            { id: "salary", label: "Salary Details", icon: "💳" },
            { id: "payslips", label: "Payslips", icon: "📄" },
            { id: "exit", label: "Resignation & FnF", icon: "📑" },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              className="btn-ghost"
              style={{
                border: "none",
                background: "transparent",
                padding: "0.75rem 1rem",
                fontSize: "0.88rem",
                fontWeight: activeTab === tab.id ? 600 : 500,
                color: activeTab === tab.id ? "var(--color-primary, #2563eb)" : "var(--color-text-muted, #64748b)",
                borderBottom: activeTab === tab.id ? "2.5px solid var(--color-primary, #2563eb)" : "2.5px solid transparent",
                borderRadius: 0,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
              }}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </div>
      </div>

      {invite && (
        <div className="alert alert-success">
          Invitation sent to <strong>{invite.sent_to}</strong>, expires {formatDateTime(invite.expires_at)}.
        </div>
      )}

      {/* TAB 1: OVERVIEW - TWO-COLUMN ASYMMETRIC (30% / 70%) */}
      {activeTab === "overview" && (
        <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: "1.25rem", alignItems: "start" }}>
          {/* Left Column (30%): Quick Summary & Contact Sticky Card */}
          <div className="stack gap-4">
            <div className="card" style={{ padding: "1.25rem" }}>
              <div className="text-xs font-semibold uppercase text-muted mb-3" style={{ letterSpacing: "0.05em" }}>
                Contact Details
              </div>
              <div className="stack gap-3">
                <div>
                  <label className="text-xs text-muted block mb-1">Work Email</label>
                  <div className="text-sm font-semibold text-primary" style={{ wordBreak: "break-all" }}>
                    <a href={`mailto:${e.email}`} style={{ textDecoration: "none" }}>{e.email}</a>
                  </div>
                </div>
                <div>
                  <label className="text-xs text-muted block mb-1">Personal Email</label>
                  <div className="text-sm font-medium" style={{ wordBreak: "break-all" }}>
                    {e.personal_email || "—"}
                  </div>
                </div>
                <div>
                  <label className="text-xs text-muted block mb-1">Phone Number</label>
                  <div className="text-sm font-medium">
                    {e.phone ? <a href={`tel:${e.phone}`} style={{ textDecoration: "none" }}>{e.phone}</a> : "—"}
                  </div>
                </div>
                <div>
                  <label className="text-xs text-muted block mb-1">Account Activation</label>
                  <span className="badge badge-outline text-xs">
                    {e.invitation_status.replace("_", " ")}
                  </span>
                </div>
              </div>
            </div>

            {/* Direct Reporting Manager Card */}
            <div className="card" style={{ padding: "1.25rem" }}>
              <div className="text-xs font-semibold uppercase text-muted mb-3" style={{ letterSpacing: "0.05em" }}>
                Reporting Hierarchy
              </div>
              <div className="flex items-center gap-3">
                <div
                  style={{
                    width: "40px",
                    height: "40px",
                    borderRadius: "50%",
                    background: "#e2e8f0",
                    color: "#475569",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 700,
                    fontSize: "0.9rem",
                  }}
                >
                  👔
                </div>
                <div>
                  <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "var(--color-heading, #1e293b)" }}>
                    Direct Manager
                  </div>
                  <div className="text-xs text-muted">
                    {e.reporting_manager_id ? "Assigned in Team Hierarchy" : "Reports to Organization Head"}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right Column (70%): Clean Grouped Sections */}
          <div className="stack gap-4">
            <div className="card" style={{ padding: "1.25rem" }}>
              <h3 style={{ fontSize: "0.95rem", fontWeight: 700, marginBottom: "1rem", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
                Job & Organization Information
              </h3>
              <div className="form-grid">
                <Field label="Full Name" value={`${e.first_name} ${e.last_name || ""}`} />
                <Field label="Employee Code" value={e.employee_code} />
                <Field label="Designation / Position" value={e.position ?? "—"} />
                <Field label="Band / Grade Level" value={e.level ?? "—"} />
                <Field label="Employment Type" value={e.employment_type.replace("_", " ")} />
                <Field label="Primary Department" value={e.department_id ? "Assigned Department" : "General Organization"} />
              </div>
            </div>

            <div className="card" style={{ padding: "1.25rem" }}>
              <h3 style={{ fontSize: "0.95rem", fontWeight: 700, marginBottom: "1rem", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
                Work Timings & Shift Schedule
              </h3>
              <div className="form-grid">
                <Field
                  label="Assigned Shift Schedule"
                  value={
                    assignedShiftQuery.data?.shift
                      ? `${assignedShiftQuery.data.shift.name} (${assignedShiftQuery.data.shift.start_time.slice(0, 5)} - ${assignedShiftQuery.data.shift.end_time.slice(0, 5)})`
                      : "General Shift (09:00 - 18:00)"
                  }
                />
                <Field label="Official Joining Date" value={formatDate(e.hire_date)} />
                <Field label="Probation End Date" value={e.probation_end_date ? formatDate(e.probation_end_date) : "Completed / None"} />
                <Field label="Contractual Notice Period" value={`${e.notice_period_days ?? 30} days`} />
              </div>
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
  editable,
}: {
  label: string;
  value: React.ReactNode;
  isLocked?: boolean;
  editable?: boolean;
}) {
  return (
    <div className="field" style={{ marginBottom: "0.85rem" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "4px" }}>
        <label
          style={{
            margin: 0,
            fontSize: "0.72rem",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: "var(--color-text-muted, #64748b)",
          }}
        >
          {label}
        </label>
        {editable && (
          <span
            style={{
              fontSize: "0.72rem",
              color: "#3b82f6",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: "2px",
            }}
            title="Field editable by employee"
          >
            ✏️
          </span>
        )}
      </div>
      <div
        style={{
          fontWeight: 600,
          color: "var(--color-heading, #1e293b)",
          fontSize: "0.92rem",
          background: "var(--color-bg, #f8fafc)",
          border: "1px solid var(--color-border, #e2e8f0)",
          borderRadius: "6px",
          padding: "6px 10px",
          minHeight: "34px",
          display: "flex",
          alignItems: "center",
        }}
      >
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
  const [showReleaseModal, setShowReleaseModal] = useState(false);
  const [releaseConfirmInput, setReleaseConfirmInput] = useState("");

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

  async function executeReleaseSettlement() {
    if (releaseConfirmInput.trim().toUpperCase() !== "CONFIRM") {
      notify('Please type "CONFIRM" to release the settlement.', "error");
      return;
    }

    setUpdatingClearance(true);
    try {
      await updateFnFClearance(employee.id, { mark_settled: true });
      notify("FnF Settlement released successfully! Employee account finalized.", "success");
      setShowReleaseModal(false);
      setReleaseConfirmInput("");
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
              <div className="card" style={{ background: "#ffffff", border: "1px solid var(--color-border)", borderRadius: "12px", padding: "20px" }}>
                {/* Meta stats bar */}
                <div style={{ display: "flex", flexWrap: "wrap", gap: "16px", padding: "12px 16px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0", marginBottom: "20px" }}>
                  <div>
                    <span style={{ fontSize: "11px", color: "#64748b", textTransform: "uppercase", fontWeight: 600, display: "block" }}>Monthly Gross Pay</span>
                    <strong style={{ fontSize: "14px", color: "#1e293b" }}>₹{Number(fnfQuery.data.monthly_gross_salary || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
                  </div>
                  <div style={{ width: "1px", background: "#cbd5e1" }} />
                  <div>
                    <span style={{ fontSize: "11px", color: "#64748b", textTransform: "uppercase", fontWeight: 600, display: "block" }}>Per-Day Rate (30d Base)</span>
                    <strong style={{ fontSize: "14px", color: "#1e293b" }}>₹{Number(fnfQuery.data.per_day_salary || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })} / day</strong>
                  </div>
                  <div style={{ width: "1px", background: "#cbd5e1" }} />
                  <div>
                    <span style={{ fontSize: "11px", color: "#64748b", textTransform: "uppercase", fontWeight: 600, display: "block" }}>Unpaid Salary Days</span>
                    <strong style={{ fontSize: "14px", color: "#1e293b" }}>{fnfQuery.data.unpaid_salary_days} days</strong>
                  </div>
                  <div style={{ width: "1px", background: "#cbd5e1" }} />
                  <div>
                    <span style={{ fontSize: "11px", color: "#64748b", textTransform: "uppercase", fontWeight: 600, display: "block" }}>Notice Shortfall</span>
                    <strong style={{ fontSize: "14px", color: "#1e293b" }}>{fnfQuery.data.notice_recovery_days} days</strong>
                  </div>
                </div>

                {/* Two-Sided Audited Ledger Card */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
                  {/* Left Column: Credits / Additions */}
                  <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: "8px", padding: "16px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #bbf7d0", paddingBottom: "10px", marginBottom: "12px" }}>
                      <span style={{ fontWeight: 700, fontSize: "13px", color: "#15803d", textTransform: "uppercase", letterSpacing: "0.03em" }}>
                        ➕ Payable Credits (Additions)
                      </span>
                      <span style={{ fontSize: "11px", color: "#166534", fontWeight: 600 }}>Earnings & Accruals</span>
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px" }}>
                        <span style={{ color: "#334155" }}>Prorated Unpaid Salary ({fnfQuery.data.unpaid_salary_days}d)</span>
                        <strong style={{ color: "#166534" }}>+ ₹{Number(fnfQuery.data.unpaid_salary_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px" }}>
                        <span style={{ color: "#334155" }}>Leave Encashment ({fnfQuery.data.encashable_leave_days}d)</span>
                        <strong style={{ color: "#166534" }}>+ ₹{Number(fnfQuery.data.leave_encashment_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px" }}>
                        <span style={{ color: "#334155" }}>Severance / Notice in Lieu</span>
                        <strong style={{ color: "#166534" }}>+ ₹{Number(fnfQuery.data.severance_pay).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px" }}>
                        <span style={{ color: "#334155" }}>Pending Approved Reimbursements</span>
                        <strong style={{ color: "#166534" }}>+ ₹{Number(fnfQuery.data.pending_reimbursements).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px" }}>
                        <span style={{ color: "#334155" }}>Gratuity / Performance Bonus</span>
                        <strong style={{ color: "#166534" }}>+ ₹{Number(fnfQuery.data.gratuity_bonus).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
                      </div>
                    </div>

                    <div style={{ marginTop: "14px", paddingTop: "10px", borderTop: "1px dashed #86efac", display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: "13px", color: "#14532d" }}>
                      <span>Total Gross Credits</span>
                      <span>
                        ₹{(
                          Number(fnfQuery.data.unpaid_salary_amount) +
                          Number(fnfQuery.data.leave_encashment_amount) +
                          Number(fnfQuery.data.severance_pay) +
                          Number(fnfQuery.data.pending_reimbursements) +
                          Number(fnfQuery.data.gratuity_bonus)
                        ).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </span>
                    </div>
                  </div>

                  {/* Right Column: Debits / Deductions */}
                  <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "8px", padding: "16px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #fecaca", paddingBottom: "10px", marginBottom: "12px" }}>
                      <span style={{ fontWeight: 700, fontSize: "13px", color: "#b91c1c", textTransform: "uppercase", letterSpacing: "0.03em" }}>
                        ➖ Deductions & Recoveries
                      </span>
                      <span style={{ fontSize: "11px", color: "#991b1b", fontWeight: 600 }}>Payable by Employee</span>
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px" }}>
                        <div>
                          <span style={{ color: "#334155", display: "block" }}>Notice Shortfall Deduction</span>
                          <span style={{ fontSize: "11px", color: "#64748b" }}>({fnfQuery.data.notice_recovery_days} days shortfall)</span>
                        </div>
                        <strong style={{ color: "#b91c1c" }}>- ₹{Number(fnfQuery.data.notice_recovery_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px" }}>
                        <span style={{ color: "#334155" }}>Asset Damage / Penalty Deductions</span>
                        <strong style={{ color: "#b91c1c" }}>- ₹{Number(fnfQuery.data.asset_deductions).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
                      </div>
                    </div>

                    <div style={{ marginTop: "38px", paddingTop: "10px", borderTop: "1px dashed #fca5a5", display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: "13px", color: "#7f1d1d" }}>
                      <span>Total Recoveries / Deductions</span>
                      <span>
                        - ₹{(
                          Number(fnfQuery.data.notice_recovery_amount) +
                          Number(fnfQuery.data.asset_deductions)
                        ).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </span>
                    </div>
                  </div>
                </div>

                {/* HR Adjustment inputs if not settled */}
                {isHr && !employee.fnf_settled_at && (
                  <div style={{ background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0", padding: "14px", marginBottom: "16px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                      <strong style={{ fontSize: "12px", color: "#475569", textTransform: "uppercase", letterSpacing: "0.03em" }}>⚙️ Adjust Clearance Ledger Line Items</strong>
                      <span style={{ fontSize: "11px", color: "#64748b" }}>Update manually approved exceptions</span>
                    </div>
                    <div className="grid grid-3 gap-3">
                      <div className="field">
                        <label style={{ fontSize: "11px", fontWeight: 600 }}>Pending Reimbursements (₹)</label>
                        <input
                          type="number"
                          step="0.01"
                          value={editReimbursements}
                          onChange={(e) => setEditReimbursements(e.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label style={{ fontSize: "11px", fontWeight: 600 }}>Gratuity / Bonus (₹)</label>
                        <input
                          type="number"
                          step="0.01"
                          value={editGratuity}
                          onChange={(e) => setEditGratuity(e.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label style={{ fontSize: "11px", fontWeight: 600 }}>Asset Damage / Deductions (₹)</label>
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
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        padding: "16px 20px",
                        background: isPositive ? "#f0fdf4" : "#fef2f2",
                        borderRadius: "10px",
                        border: isPositive ? "1px solid #86efac" : "1px solid #fca5a5",
                        marginTop: "16px",
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 700, fontSize: "15px", color: isPositive ? "#15803d" : "#b91c1c" }}>
                          {isPositive ? "Total Net FnF Payout (Payable to Employee)" : "Total Net Recovery (Payable by Employee to Company)"}
                        </div>
                        <div style={{ fontSize: "12px", color: "#64748b", marginTop: "2px" }}>
                          {isPositive
                            ? "Gross Credits minus Total Deductions & Recoveries. Processed via Bank Transfer."
                            : "Notice shortfall & damages exceed earnings. To be collected before Relieving Letter."}
                        </div>
                      </div>
                      <div style={{ textAlign: "right" }}>
                        <div style={{ fontSize: "11px", textTransform: "uppercase", color: "#64748b", fontWeight: 600 }}>Final Net Settlement</div>
                        <div style={{ fontSize: "24px", fontWeight: 800, color: isPositive ? "#166534" : "#b91c1c", letterSpacing: "-0.02em" }}>
                          {isPositive
                            ? `₹${netAmount.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`
                            : `-₹${Math.abs(netAmount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                        </div>
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
                      onClick={() => {
                        if (!fnfQuery.data.can_release_settlement) {
                          notify("All department clearances (IT, HR, Finance) must be signed off before release.", "error");
                          return;
                        }
                        setReleaseConfirmInput("");
                        setShowReleaseModal(true);
                      }}
                      title={
                        fnfQuery.data.can_release_settlement
                          ? "Release and lock FnF Settlement"
                          : "Requires IT, HR, and Finance clearance sign-off"
                      }
                      style={{ padding: "9px 20px", fontWeight: 600 }}
                    >
                      {fnfQuery.data.can_release_settlement
                        ? "🚀 Release Full & Final Settlement"
                        : "🔒 Clearance Sign-off Required"}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* CUSTOM CONFIRMATION MODAL FOR FNF RELEASE */}
      {showReleaseModal && fnfQuery.data && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(15, 23, 42, 0.6)",
            backdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1050,
          }}
        >
          <div
            className="card"
            style={{
              width: "100%",
              maxWidth: "480px",
              padding: "24px",
              background: "#ffffff",
              borderRadius: "14px",
              boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
              <span style={{ fontSize: "24px" }}>⚠️</span>
              <h3 style={{ margin: 0, fontSize: "17px", color: "#0f172a" }}>Confirm FnF Final Settlement Release</h3>
            </div>

            <p style={{ fontSize: "13px", color: "#475569", lineHeight: 1.5, margin: "0 0 16px 0" }}>
              You are about to finalize and lock the settlement of{" "}
              <strong style={{ color: "#0f172a" }}>
                ₹{Number(fnfQuery.data.total_settlement_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </strong>{" "}
              for <strong style={{ color: "#0f172a" }}>{`${employee.first_name} ${employee.last_name || ""}`.trim()}</strong>.
            </p>

            <div style={{ background: "#fef3c7", border: "1px solid #fde68a", borderRadius: "8px", padding: "12px", marginBottom: "18px", fontSize: "12px", color: "#92400e", lineHeight: 1.4 }}>
              <strong>Important:</strong> This action permanently locks the settlement ledger and removes this employee from all recurring monthly payroll runs.
            </div>

            <div className="field mb-4">
              <label style={{ fontSize: "12px", fontWeight: 600, color: "#334155", marginBottom: "6px", display: "block" }}>
                Type <span style={{ color: "#dc2626", fontFamily: "monospace", fontWeight: 700 }}>CONFIRM</span> to proceed:
              </label>
              <input
                type="text"
                value={releaseConfirmInput}
                onChange={(e) => setReleaseConfirmInput(e.target.value)}
                placeholder="Type CONFIRM here"
                style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "14px" }}
                autoFocus
              />
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setShowReleaseModal(false)}
                disabled={updatingClearance}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={executeReleaseSettlement}
                disabled={updatingClearance || releaseConfirmInput.trim().toUpperCase() !== "CONFIRM"}
                style={{
                  background: releaseConfirmInput.trim().toUpperCase() === "CONFIRM" ? "#16a34a" : undefined,
                  borderColor: releaseConfirmInput.trim().toUpperCase() === "CONFIRM" ? "#16a34a" : undefined,
                }}
              >
                {updatingClearance ? "Releasing…" : "Authorize & Release"}
              </button>
            </div>
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

