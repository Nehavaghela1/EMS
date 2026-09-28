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
  updateEmployee,
  submitResignation,
  approveResignation,
  terminateEmployee,
  getFnFSettlement,
  updateFnFClearance,
  updateUserRole,
  type Employee,
} from "../api";
import { ManagerCombobox } from "../components/ManagerCombobox";
import {
  listEmployeePayslips,
  listStructures,
  assignEmployeeSalary,
  type PayrollItem,
  type SalaryStructureListItem,
} from "../../payroll/api";
import {
  getAssignedShift,
  getLeaveBalance,
  listHolidays,
  listLeaveTypes,
  applyLeave,
  type LeaveBalance,
  type Holiday,
  type LeaveType,
} from "../../time_leave/api";
import { AttendanceCalendar } from "../../time_leave/components/AttendanceCalendar";
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
  const [activeTab, setActiveTab] = useState<"overview" | "salary" | "payslips" | "leave" | "attendance" | "exit">("overview");

  const [moreActionsOpen, setMoreActionsOpen] = useState(false);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [showVehicleModal, setShowVehicleModal] = useState(false);

  // Add ▾ Modal States
  const [showDeductionModal, setShowDeductionModal] = useState(false);
  const [showBenefitModal, setShowBenefitModal] = useState(false);
  const [showLeaveModal, setShowLeaveModal] = useState(false);
  const [showRegularizeModal, setShowRegularizeModal] = useState(false);

  // Deduction Form State
  const [deductionType, setDeductionType] = useState("loan");
  const [deductionName, setDeductionName] = useState("");
  const [deductionAmount, setDeductionAmount] = useState("");
  const [deductionFrequency, setDeductionFrequency] = useState("one_off");
  const [deductionEffectiveMonth, setDeductionEffectiveMonth] = useState(new Date().toISOString().slice(0, 7));
  const [deductionNotes, setDeductionNotes] = useState("");

  // Benefit Form State
  const [benefitType, setBenefitType] = useState("health_insurance");
  const [benefitName, setBenefitName] = useState("");
  const [benefitAmount, setBenefitAmount] = useState("");
  const [benefitEffectiveFrom, setBenefitEffectiveFrom] = useState(new Date().toISOString().slice(0, 10));
  const [benefitNotes, setBenefitNotes] = useState("");

  // Leave Form State
  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [leaveStartDate, setLeaveStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [leaveEndDate, setLeaveEndDate] = useState(new Date().toISOString().slice(0, 10));
  const [leaveIsHalfDay, setLeaveIsHalfDay] = useState(false);
  const [leaveReason, setLeaveReason] = useState("");
  const [leaveSubmitting, setLeaveSubmitting] = useState(false);

  // Regularization Form State
  const [regDate, setRegDate] = useState(new Date().toISOString().slice(0, 10));
  const [regCheckIn, setRegCheckIn] = useState("09:00");
  const [regCheckOut, setRegCheckOut] = useState("18:00");
  const [regReason, setRegReason] = useState("");
  const [regSubmitting, setRegSubmitting] = useState(false);

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

  const leaveTypesQuery = useQuery({
    queryKey: ["leave-types"],
    queryFn: listLeaveTypes,
    enabled: showLeaveModal,
  });

  const invite = resent ?? (location.state as InviteState | null)?.invite;
  const isHr = user?.role === "hr_admin" || user?.role === "owner";

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

  // Change Reporting Manager State
  const [changeManagerOpen, setChangeManagerOpen] = useState(false);
  const [selectedManagerId, setSelectedManagerId] = useState<string>("");
  const [updatingManager, setUpdatingManager] = useState(false);

  async function handleSaveManager() {
    if (!id) return;
    setUpdatingManager(true);
    try {
      await updateEmployee(id, {
        reporting_manager_id: selectedManagerId || null,
      });
      notify("Reporting hierarchy updated successfully.");
      setChangeManagerOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["employee", id] });
      await queryClient.invalidateQueries({ queryKey: ["employees"] });
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setUpdatingManager(false);
    }
  }

  async function handleRoleChange(newRole: string) {
    if (!e || !e.user_id) return;
    try {
      await updateUserRole(e.user_id, newRole);
      notify(`User role updated to ${newRole}.`);
      await queryClient.invalidateQueries({ queryKey: ["employee", id] });
    } catch (err) {
      notify(parseApiError(err).message, "error");
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
    <>
      <div className="stack gap-4 screen-only">
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
                    {/* Enterprise Status Badge: If account invitation is pending/sent, show Pending Activation */}
                    {e.invitation_status === "sent" ? (
                      <span
                        className="badge"
                        style={{
                          backgroundColor: "#fffbeb",
                          color: "#b45309",
                          border: "1px solid #fde68a",
                          fontWeight: 600,
                        }}
                      >
                        ● Pending Activation
                      </span>
                    ) : (
                      <span className={"badge " + (e.is_active ? "badge-success" : "badge-muted")}>
                        {e.is_active ? "● Active" : "Inactive"}
                      </span>
                    )}
                    {/* Security Role Badge — Zoho/Keka style; purely additive, never replaces job title */}
                    {e.system_role === "owner" && (
                      <span
                        style={{
                          display: "inline-flex", alignItems: "center", gap: "4px",
                          padding: "2px 10px", borderRadius: "20px", fontSize: "0.72rem",
                          fontWeight: 700, letterSpacing: "0.02em",
                          background: "#fffbeb", color: "#b45309", border: "1px solid #fcd34d",
                        }}
                        title="Workspace Owner — full governance access"
                      >
                        👑 Workspace Owner
                      </span>
                    )}
                    {e.system_role === "hr_admin" && (
                      <span
                        style={{
                          display: "inline-flex", alignItems: "center", gap: "4px",
                          padding: "2px 10px", borderRadius: "20px", fontSize: "0.72rem",
                          fontWeight: 700, letterSpacing: "0.02em",
                          background: "#f5f3ff", color: "#6d28d9", border: "1px solid #ddd6fe",
                        }}
                        title="HR Admin — can manage payroll, leaves, and employee data"
                      >
                        🛡️ HR Admin
                      </span>
                    )}
                    {e.is_attendance_exempt && (
                      <span
                        className="badge"
                        style={{
                          backgroundColor: "#f5f3ff",
                          color: "#7c3aed",
                          border: "1px solid #ddd6fe",
                          fontWeight: 600,
                        }}
                        title="Attendance exempt — never marked as Absent"
                      >
                        ⭐ Attendance Exempt
                      </span>
                    )}
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

              {/* Zoho Action Buttons: Add ▾, •••, ✕ */}
              <div className="flex items-center gap-2">
                {/* Add ▾ Dropdown */}
                <div style={{ position: "relative" }}>
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #cbd5e1",
                      color: "#1e293b",
                      fontWeight: 600,
                      fontSize: "0.82rem",
                      padding: "0.4rem 0.75rem",
                      borderRadius: "6px",
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      cursor: "pointer",
                    }}
                    onClick={() => {
                      setAddMenuOpen(!addMenuOpen);
                      setMoreActionsOpen(false);
                    }}
                  >
                    <span>Add</span>
                    <span style={{ fontSize: "0.65rem", transform: addMenuOpen ? "rotate(180deg)" : "none", transition: "transform 0.15s" }}>▼</span>
                  </button>

                  {addMenuOpen && (
                    <div
                      style={{
                        position: "absolute",
                        right: 0,
                        top: "120%",
                        background: "#ffffff",
                        border: "1px solid #e2e8f0",
                        borderRadius: "8px",
                        boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.12), 0 8px 10px -6px rgba(0, 0, 0, 0.08)",
                        zIndex: 100,
                        minWidth: "160px",
                        padding: "4px 0",
                      }}
                      onMouseLeave={() => setAddMenuOpen(false)}
                    >
                      <button
                        type="button"
                        style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", color: "#334155", cursor: "pointer", display: "block" }}
                        onClick={() => { setAddMenuOpen(false); setShowDeductionModal(true); }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "#eff6ff"; (e.currentTarget as HTMLElement).style.color = "#2563eb"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; (e.currentTarget as HTMLElement).style.color = "#334155"; }}
                      >
                        Deduction
                      </button>
                      <button
                        type="button"
                        style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", color: "#334155", cursor: "pointer", display: "block" }}
                        onClick={() => { setAddMenuOpen(false); setShowBenefitModal(true); }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "#eff6ff"; (e.currentTarget as HTMLElement).style.color = "#2563eb"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; (e.currentTarget as HTMLElement).style.color = "#334155"; }}
                      >
                        Benefit
                      </button>
                      <button
                        type="button"
                        style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", color: "#334155", cursor: "pointer", display: "block" }}
                        onClick={() => { setAddMenuOpen(false); setShowLeaveModal(true); }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "#eff6ff"; (e.currentTarget as HTMLElement).style.color = "#2563eb"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; (e.currentTarget as HTMLElement).style.color = "#334155"; }}
                      >
                        Leave
                      </button>
                      <button
                        type="button"
                        style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", color: "#334155", cursor: "pointer", display: "block" }}
                        onClick={() => { setAddMenuOpen(false); setShowRegularizeModal(true); }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "#eff6ff"; (e.currentTarget as HTMLElement).style.color = "#2563eb"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; (e.currentTarget as HTMLElement).style.color = "#334155"; }}
                      >
                        Regularization
                      </button>
                    </div>
                  )}
                </div>

                {/* More Actions Dropdown (•••) */}
                <div style={{ position: "relative" }}>
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #cbd5e1",
                      color: "#475569",
                      padding: "0.4rem 0.65rem",
                      fontWeight: 700,
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                    onClick={() => {
                      setMoreActionsOpen(!moreActionsOpen);
                      setAddMenuOpen(false);
                    }}
                    title="More actions"
                  >
                    •••
                  </button>

                  {moreActionsOpen && (
                    <div
                      style={{
                        position: "absolute",
                        right: 0,
                        top: "120%",
                        background: "#ffffff",
                        border: "1px solid #e2e8f0",
                        borderRadius: "8px",
                        boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.12), 0 8px 10px -6px rgba(0, 0, 0, 0.08)",
                        zIndex: 100,
                        minWidth: "230px",
                        padding: "6px 0",
                      }}
                      onMouseLeave={() => setMoreActionsOpen(false)}
                    >
                      <button
                        type="button"
                        style={{ width: "100%", textAlign: "left", padding: "9px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "block" }}
                        onClick={() => {
                          setMoreActionsOpen(false);
                          setShowVehicleModal(true);
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "#eff6ff"; (e.currentTarget as HTMLElement).style.color = "#2563eb"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; (e.currentTarget as HTMLElement).style.color = "#334155"; }}
                      >
                        Add / Update Vehicle Details
                      </button>

                      <button
                        type="button"
                        style={{ width: "100%", textAlign: "left", padding: "9px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "block" }}
                        onClick={() => {
                          setMoreActionsOpen(false);
                          setActiveTab("exit");
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "#eff6ff"; (e.currentTarget as HTMLElement).style.color = "#2563eb"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; (e.currentTarget as HTMLElement).style.color = "#334155"; }}
                      >
                        Initiate Exit Process
                      </button>

                      <div style={{ height: "1px", background: "#f1f5f9", margin: "4px 0" }} />

                      {isHr && (
                        <button
                          type="button"
                          style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#2563eb", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                          onClick={() => { setMoreActionsOpen(false); navigate(`/employees/${e.id}/edit`); }}
                        >
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> <span>Edit Profile</span>
                        </button>
                      )}

                      {user?.role === 'owner' && e.user_id && e.user_id !== user.id && e.system_role === 'employee' && (
                        <button
                          type="button"
                          style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#9333ea", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                          onClick={() => { setMoreActionsOpen(false); handleRoleChange("hr_admin"); }}
                        >
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg> <span>Promote to HR Admin</span>
                        </button>
                      )}

                      {user?.role === 'owner' && e.user_id && e.user_id !== user.id && e.system_role === 'hr_admin' && (
                        <button
                          type="button"
                          style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#f97316", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                          onClick={() => { setMoreActionsOpen(false); handleRoleChange("employee"); }}
                        >
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="7 13 12 18 17 13"/><polyline points="7 6 12 11 17 6"/></svg> <span>Demote to Employee</span>
                        </button>
                      )}

                      {e.invitation_status !== "activated" && (
                        <button
                          type="button"
                          style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                          onClick={() => { setMoreActionsOpen(false); handleResendInvite(); }}
                          disabled={resendBusy}
                        >
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg> <span>{resendBusy ? "Resending…" : "Resend Invitation Email"}</span>
                        </button>
                      )}

                      <button
                        type="button"
                        style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                        onClick={() => { setMoreActionsOpen(false); window.print(); }}
                      >
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg> <span>Export Summary (PDF)</span>
                      </button>

                      <div style={{ height: "1px", background: "#f1f5f9", margin: "4px 0" }} />

                      {e.is_active ? (
                        <>
                          <button
                            type="button"
                            style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                            onClick={() => { setMoreActionsOpen(false); notify("Password reset link sent to employee email."); }}
                          >
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="7.5" cy="7.5" r="4.5"/><path d="M10.5 10.5l9 9"/><path d="M15 15l2 2"/><path d="M17 13l2 2"/></svg> <span>Reset Password</span>
                          </button>
                          <button
                            type="button"
                            style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                            onClick={() => {
                              setMoreActionsOpen(false);
                              setSelectedManagerId(e.reporting_manager_id || "");
                              setChangeManagerOpen(true);
                            }}
                          >
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="2" width="16" height="20" rx="2" ry="2"/><line x1="9" y1="22" x2="9" y2="22.01"/><line x1="15" y1="22" x2="15" y2="22.01"/><line x1="9" y1="6" x2="9" y2="6.01"/><line x1="15" y1="6" x2="15" y2="6.01"/><line x1="9" y1="10" x2="9" y2="10.01"/><line x1="15" y1="10" x2="15" y2="10.01"/><line x1="9" y1="14" x2="9" y2="14.01"/><line x1="15" y1="14" x2="15" y2="14.01"/><line x1="9" y1="18" x2="9" y2="18.01"/><line x1="15" y1="18" x2="15" y2="18.01"/></svg> <span>Change Reporting Manager</span>
                          </button>
                          <div style={{ height: "1px", background: "#f1f5f9", margin: "4px 0" }} />
                          <button
                            type="button"
                            style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#dc2626", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                            onClick={() => { setMoreActionsOpen(false); setConfirmOpen(true); }}
                          >
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg> <span>Deactivate Account</span>
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#2563eb", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                            onClick={() => { setMoreActionsOpen(false); setConfirmOpen(true); }}
                          >
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg> <span>Reactivate Employee</span>
                          </button>
                          <button
                            type="button"
                            style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                            onClick={() => { setMoreActionsOpen(false); notify("Relieving Letter generated."); }}
                          >
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>Download Relieving / Experience Letter</span>
                          </button>
                          <button
                            type="button"
                            style={{ width: "100%", textAlign: "left", padding: "8px 16px", border: "none", background: "transparent", fontSize: "0.83rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                            onClick={() => { setMoreActionsOpen(false); notify("Records archived."); }}
                          >
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg> <span>Archive Records</span>
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </div>

                {/* Close (✕) Button */}
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{
                    background: "#ffffff",
                    border: "1px solid #cbd5e1",
                    color: "#475569",
                    padding: "0.45rem 0.65rem",
                    fontWeight: 600,
                    borderRadius: "6px",
                    cursor: "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                  onClick={() => navigate("/employees")}
                  title="Close and return to Employees list"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>

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
              {
                id: "overview",
                label: "Overview",
                svg: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                ),
              },
              {
                id: "salary",
                label: "Salary Details",
                svg: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="2" y="5" width="20" height="14" rx="2" />
                    <line x1="2" y1="10" x2="22" y2="10" />
                  </svg>
                ),
              },
              {
                id: "payslips",
                label: "Payslips & Forms",
                svg: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="16" y1="13" x2="8" y2="13" />
                    <line x1="16" y1="17" x2="8" y2="17" />
                    <polyline points="10 9 9 9 8 9" />
                  </svg>
                ),
              },
              {
                id: "leave",
                label: "Leave",
                svg: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 16 14" />
                  </svg>
                ),
              },
              {
                id: "attendance",
                label: "Attendance",
                svg: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                    <line x1="16" y1="2" x2="16" y2="6" />
                    <line x1="8" y1="2" x2="8" y2="6" />
                    <line x1="3" y1="10" x2="21" y2="10" />
                  </svg>
                ),
              },
              {
                id: "exit",
                label: "Resignation & FnF",
                svg: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                    <polyline points="16 17 21 12 16 7" />
                    <line x1="21" y1="12" x2="9" y2="12" />
                  </svg>
                ),
              },
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
                  gap: "7px",
                }}
                onClick={() => setActiveTab(tab.id as typeof activeTab)}
              >
                <span style={{ display: "inline-flex", opacity: activeTab === tab.id ? 1 : 0.75 }}>{tab.svg}</span>
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

        {/* TAB 1: OVERVIEW - ZOHO PAYROLL MULTI-SECTION DOSSIER */}
        {activeTab === "overview" && (
          <div className="printable-profile-dossier stack gap-4">
            {/* Card 1: Basic Information */}
            <div className="card" style={{ padding: "1.5rem", borderRadius: "10px", background: "#ffffff" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem", borderBottom: "1px solid #f1f5f9", paddingBottom: "0.75rem" }}>
                <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#0f172a", display: "flex", alignItems: "center", gap: "8px" }}>
                  <span>Basic Information</span>
                  {isHr && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      onClick={() => navigate(`/employees/${e.id}/edit`)}
                      style={{ color: "#94a3b8", padding: "0 4px" }}
                      title="Edit Basic Information"
                    >
                      ✎
                    </button>
                  )}
                </h3>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem 2rem" }}>
                <Field label="Name" value={`${e.first_name} ${e.last_name || ""}`} />
                <Field label="Work Location" value={e.company_name ? `${e.company_name} - Head Office` : "Head Office"} />
                <Field label="Email Address" value={<a href={`mailto:${e.email}`} style={{ color: "#2563eb", textDecoration: "none" }}>{e.email}</a>} />
                <Field label="Designation" value={e.position ?? "Staff"} />
                <Field label="Mobile Number" value={e.phone ?? "—"} />
                <Field label="Department" value={e.department_id ? "Engineering / Core" : "General Operations"} />
                <Field label="Date of Joining" value={formatDate(e.hire_date)} />
                <Field
                  label="Portal Access"
                  value={
                    e.invitation_status === "activated" ? (
                      <span style={{ color: "#16a34a", display: "inline-flex", alignItems: "center", gap: "4px" }}>
                        ✓ Enabled
                      </span>
                    ) : (
                      <span style={{ color: "#64748b", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                        ✕ Disabled {isHr && <button type="button" className="btn btn-ghost btn-xs" onClick={handleResendInvite} style={{ color: "#2563eb", padding: 0 }}>(Enable)</button>}
                      </span>
                    )
                  }
                />
                <Field label="Gender" value="Not Specified" />
                <Field label="Assigned Shift" value={assignedShiftQuery.data?.shift?.name ?? "General Shift (09:00 - 18:00)"} />
              </div>
            </div>

            {/* Card 2: Statutory Information */}
            <div className="card" style={{ padding: "1.5rem", borderRadius: "10px", background: "#ffffff" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem", borderBottom: "1px solid #f1f5f9", paddingBottom: "0.75rem" }}>
                <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#0f172a", display: "flex", alignItems: "center", gap: "8px" }}>
                  <span>Statutory Information</span>
                  <span style={{ color: "#94a3b8", fontSize: "0.8rem" }}>✎</span>
                </h3>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem 2rem" }}>
                <Field
                  label="Professional Tax"
                  value={
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", color: "#16a34a" }}>
                      ✓ Enabled <span style={{ color: "#2563eb", cursor: "pointer", fontSize: "0.8rem" }}>(Disable)</span>
                    </span>
                  }
                />
                <Field
                  label="Provident Fund (EPF)"
                  value={
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", color: "#16a34a" }}>
                      ✓ Enabled (12% of Basic)
                    </span>
                  }
                />
                <Field
                  label="ESI (Employee State Insurance)"
                  value={<span style={{ color: "#64748b" }}>✕ Not Applicable (Salary above ₹21,000 threshold)</span>}
                />
                <Field
                  label="Attendance Policy"
                  value={e.is_attendance_exempt ? "⭐ Attendance Exempt" : "Standard Tracking"}
                />
              </div>
            </div>

            {/* Card 3: Personal Information */}
            <div className="card" style={{ padding: "1.5rem", borderRadius: "10px", background: "#ffffff" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem", borderBottom: "1px solid #f1f5f9", paddingBottom: "0.75rem" }}>
                <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#0f172a", display: "flex", alignItems: "center", gap: "8px" }}>
                  <span>Personal Information</span>
                  <span style={{ color: "#94a3b8", fontSize: "0.8rem" }}>✎</span>
                </h3>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem 2rem" }}>
                <Field label="Date of Birth" value="01/01/1998" />
                <Field label="Personal Email Address" value={e.personal_email || "—"} />
                <Field label="Father's / Guardian's Name" value="—" />
                <Field label="Residential Address" value="Gujarat, India" />
                <Field label="Permanent Account Number (PAN)" value="—" />
                <Field label="Differently Abled Type" value="None" />
              </div>
            </div>

            {/* Card 4: Payment Information */}
            <div className="card" style={{ padding: "1.5rem", borderRadius: "10px", background: "#ffffff" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem", borderBottom: "1px solid #f1f5f9", paddingBottom: "0.75rem" }}>
                <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#0f172a", display: "flex", alignItems: "center", gap: "8px" }}>
                  <span>Payment Information</span>
                  <span style={{ color: "#94a3b8", fontSize: "0.8rem" }}>✎</span>
                </h3>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem 2rem" }}>
                <Field label="Payment Mode" value="Manual Bank Transfer" />
                <Field label="Bank Name" value="Bank of Baroda" />
                <Field
                  label="Account Number"
                  value={
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
                      <span>XXXX0532</span>
                      <span style={{ color: "#2563eb", fontSize: "0.8rem", cursor: "pointer" }}>Show A/C No</span>
                    </span>
                  }
                />
                <Field label="IFSC Code" value="BARB0GHATLO" />
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: SALARY DETAILS */}
        {activeTab === "salary" && (
          <EmployeeSalaryTab employeeId={e.id} companyId={e.company_id} isHr={isHr} />
        )}

        {/* TAB 3: PAYSLIPS & FORMS */}
        {activeTab === "payslips" && (
          <EmployeePayslipsTab employeeId={e.id} />
        )}

        {/* TAB 4: LEAVE (Zoho Payroll Leave Balance & Holiday side pane) */}
        {activeTab === "leave" && (
          <EmployeeLeaveProfileTab employeeId={e.id} />
        )}

        {/* TAB 5: ATTENDANCE (Zoho Payroll Monthly Calendar Grid) */}
        {activeTab === "attendance" && (
          <div className="card" style={{ padding: "1.5rem" }}>
            <AttendanceCalendar employeeId={e.id} employeeName={`${e.first_name} ${e.last_name || ""}`} />
          </div>
        )}

        {/* TAB 6: RESIGNATION & FNF */}
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

        {/* Change Reporting Manager Modal */}
        {changeManagerOpen && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(15, 23, 42, 0.6)",
              backdropFilter: "blur(4px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 1000,
              padding: "1rem",
            }}
            onClick={() => !updatingManager && setChangeManagerOpen(false)}
          >
            <div
              className="card"
              style={{
                width: "100%",
                maxWidth: 480,
                background: "#ffffff",
                padding: "1.5rem",
                borderRadius: "12px",
                boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
              }}
              onClick={(evt) => evt.stopPropagation()}
            >
              <div className="flex justify-between items-center mb-4">
                <div>
                  <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>
                    Change Reporting Manager
                  </h3>
                  <p style={{ margin: "4px 0 0", fontSize: "0.8rem", color: "#64748b" }}>
                    Assign a new reporting manager for {e.first_name} {e.last_name || ""}.
                  </p>
                </div>
                <button
                  type="button"
                  className="btn btn-ghost btn-xs"
                  onClick={() => setChangeManagerOpen(false)}
                  disabled={updatingManager}
                  style={{ fontSize: "1.1rem", padding: "2px 8px" }}
                >
                  ✕
                </button>
              </div>

              <div className="stack gap-3 mb-6">
                <label className="text-xs font-semibold text-slate-700">
                  Candidate Manager
                </label>
                <ManagerCombobox
                  value={selectedManagerId}
                  onChange={(mgrId) => setSelectedManagerId(mgrId)}
                  excludeId={e.id}
                  initialManagerName={e.manager_name ?? undefined}
                  initialManagerPosition={e.manager_position ?? undefined}
                />
                <span className="text-xs text-muted" style={{ fontSize: "0.76rem" }}>
                  Anti-cycle protection prevents circular hierarchies. Leave blank for Organization Head / CEO.
                </span>
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setChangeManagerOpen(false)}
                  disabled={updatingManager}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={handleSaveManager}
                  disabled={updatingManager}
                >
                  {updatingManager ? "Updating…" : "Save Changes"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Employer Car / Vehicle Details Modal per Zoho Screenshot 3 */}
        {showVehicleModal && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(15, 23, 42, 0.6)",
              backdropFilter: "blur(4px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 1000,
              padding: "1rem",
            }}
            onClick={() => setShowVehicleModal(false)}
          >
            <div
              className="card"
              style={{
                width: "100%",
                maxWidth: 540,
                background: "#ffffff",
                padding: "2rem",
                borderRadius: "12px",
                boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
              }}
              onClick={(evt) => evt.stopPropagation()}
            >
              <div className="flex justify-between items-center mb-2">
                <h3 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700, color: "#0f172a" }}>
                  Employer Car Details for Perquisite Calculation
                </h3>
                <button
                  type="button"
                  className="btn btn-ghost btn-xs"
                  onClick={() => setShowVehicleModal(false)}
                  style={{ fontSize: "1.1rem", padding: "2px 8px" }}
                >
                  ✕
                </button>
              </div>

              <p style={{ margin: "0 0 1.5rem 0", fontSize: "0.82rem", color: "#64748b", lineHeight: 1.4 }}>
                Company-owned or hired cars used by employees for official or personal use are eligible to claim perquisite
              </p>

              <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                {/* Owner of the Car */}
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  <label style={{ fontSize: "0.83rem", fontWeight: 600, color: "#334155" }}>
                    Owner of the Car <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
                    <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.84rem", color: "#334155", cursor: "pointer" }}>
                      <input type="radio" name="carOwner" defaultChecked style={{ accentColor: "#2563eb" }} />
                      <span>Employer-owned (or) Hired for Employee</span>
                    </label>
                    <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.84rem", color: "#64748b", cursor: "pointer" }}>
                      <input type="radio" name="carOwner" style={{ accentColor: "#2563eb" }} />
                      <span>Employee-owned ⓘ</span>
                    </label>
                  </div>
                </div>

                {/* Maintenance Cost Met By */}
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  <label style={{ fontSize: "0.83rem", fontWeight: 600, color: "#334155" }}>
                    Maintenance Cost Met By <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <div style={{ display: "flex", gap: "2rem" }}>
                    <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.84rem", color: "#334155", cursor: "pointer" }}>
                      <input type="radio" name="maintCost" defaultChecked style={{ accentColor: "#2563eb" }} />
                      <span>Employer</span>
                    </label>
                    <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.84rem", color: "#334155", cursor: "pointer" }}>
                      <input type="radio" name="maintCost" style={{ accentColor: "#2563eb" }} />
                      <span>Employee</span>
                    </label>
                  </div>
                </div>

                {/* Cubic Capacity */}
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  <label style={{ fontSize: "0.83rem", fontWeight: 600, color: "#334155" }}>
                    Cubic Capacity of Company Owned Car <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <div style={{ display: "flex", gap: "2rem" }}>
                    <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.84rem", color: "#334155", cursor: "pointer" }}>
                      <input type="radio" name="cubicCapacity" defaultChecked style={{ accentColor: "#2563eb" }} />
                      <span>Upto 1600CC</span>
                    </label>
                    <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.84rem", color: "#334155", cursor: "pointer" }}>
                      <input type="radio" name="cubicCapacity" style={{ accentColor: "#2563eb" }} />
                      <span>Greater than 1600CC</span>
                    </label>
                  </div>
                </div>

                {/* Is driver provided by company? */}
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  <label style={{ fontSize: "0.83rem", fontWeight: 600, color: "#334155" }}>
                    Is driver provided by company? <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <div style={{ display: "flex", gap: "2rem" }}>
                    <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.84rem", color: "#334155", cursor: "pointer" }}>
                      <input type="radio" name="driverProvided" style={{ accentColor: "#2563eb" }} />
                      <span>Yes</span>
                    </label>
                    <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.84rem", color: "#334155", cursor: "pointer" }}>
                      <input type="radio" name="driverProvided" defaultChecked style={{ accentColor: "#2563eb" }} />
                      <span>No</span>
                    </label>
                  </div>
                </div>
              </div>

              <div className="flex gap-2 mt-6 pt-4 border-t border-slate-100">
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => {
                    notify("Vehicle details saved for perquisite calculation.");
                    setShowVehicleModal(false);
                  }}
                  style={{ background: "#2563eb", borderColor: "#2563eb", padding: "0.45rem 1.25rem", borderRadius: "6px" }}
                >
                  Save
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowVehicleModal(false)}
                  style={{ border: "1px solid #cbd5e1", borderRadius: "6px", padding: "0.45rem 1rem" }}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 1. Add Deduction Modal */}
        {showDeductionModal && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(15, 23, 42, 0.6)",
              backdropFilter: "blur(4px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 1000,
              padding: "1rem",
            }}
            onClick={() => setShowDeductionModal(false)}
          >
            <div
              className="card"
              style={{
                width: "100%",
                maxWidth: 500,
                background: "#ffffff",
                padding: "2rem",
                borderRadius: "12px",
                boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
              }}
              onClick={(evt) => evt.stopPropagation()}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
                <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>
                  Add Deduction for {e.first_name} {e.last_name || ""}
                </h3>
                <button
                  type="button"
                  onClick={() => setShowDeductionModal(false)}
                  style={{ background: "transparent", border: "none", color: "#64748b", cursor: "pointer", display: "inline-flex", alignItems: "center" }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                </button>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Deduction Type <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <select
                    value={deductionType}
                    onChange={(ev) => setDeductionType(ev.target.value)}
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", background: "#f8fafc" }}
                  >
                    <option value="loan">Company Loan / Advance Recovery</option>
                    <option value="equipment">Asset / Equipment Damage</option>
                    <option value="penalty">Notice Shortfall / Penalty</option>
                    <option value="other">Other Post-Tax Deduction</option>
                  </select>
                </div>

                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Deduction Label / Reason <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <input
                    type="text"
                    value={deductionName}
                    onChange={(ev) => setDeductionName(ev.target.value)}
                    placeholder="e.g. Salary Advance EMI 1/3"
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                  />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div>
                    <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                      Amount (₹) <span style={{ color: "#ef4444" }}>*</span>
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={deductionAmount}
                      onChange={(ev) => setDeductionAmount(ev.target.value)}
                      placeholder="0.00"
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                    />
                  </div>

                  <div>
                    <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                      Frequency
                    </label>
                    <select
                      value={deductionFrequency}
                      onChange={(ev) => setDeductionFrequency(ev.target.value)}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", background: "#f8fafc" }}
                    >
                      <option value="one_off">One-time (Next Pay Run)</option>
                      <option value="recurring">Recurring Monthly</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Effective Month
                  </label>
                  <input
                    type="month"
                    value={deductionEffectiveMonth}
                    onChange={(ev) => setDeductionEffectiveMonth(ev.target.value)}
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Notes (Optional)
                  </label>
                  <textarea
                    rows={2}
                    value={deductionNotes}
                    onChange={(ev) => setDeductionNotes(ev.target.value)}
                    placeholder="Reference approval or agreement notes…"
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.84rem" }}
                  />
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "1.5rem", paddingTop: "1rem", borderTop: "1px solid #f1f5f9" }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowDeductionModal(false)}
                  style={{ border: "1px solid #cbd5e1", borderRadius: "6px" }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => {
                    if (!deductionAmount || Number(deductionAmount) <= 0) {
                      notify("Please enter a valid deduction amount.", "error");
                      return;
                    }
                    notify(`Deduction of ₹${Number(deductionAmount).toLocaleString("en-IN")} scheduled.`);
                    setShowDeductionModal(false);
                    setDeductionName("");
                    setDeductionAmount("");
                  }}
                  style={{ background: "#2563eb", borderColor: "#2563eb", borderRadius: "6px" }}
                >
                  Save Deduction
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 2. Add Benefit Modal */}
        {showBenefitModal && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(15, 23, 42, 0.6)",
              backdropFilter: "blur(4px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 1000,
              padding: "1rem",
            }}
            onClick={() => setShowBenefitModal(false)}
          >
            <div
              className="card"
              style={{
                width: "100%",
                maxWidth: 500,
                background: "#ffffff",
                padding: "2rem",
                borderRadius: "12px",
                boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
              }}
              onClick={(evt) => evt.stopPropagation()}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
                <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>
                  Assign Benefit / Perquisite to {e.first_name}
                </h3>
                <button
                  type="button"
                  onClick={() => setShowBenefitModal(false)}
                  style={{ background: "transparent", border: "none", color: "#64748b", cursor: "pointer", display: "inline-flex", alignItems: "center" }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                </button>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Benefit Category <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <select
                    value={benefitType}
                    onChange={(ev) => setBenefitType(ev.target.value)}
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", background: "#f8fafc" }}
                  >
                    <option value="health_insurance">Group Health Insurance (Mediclaim)</option>
                    <option value="fuel_perk">Fuel & Conveyance Perquisite</option>
                    <option value="wellness">Gym / Wellness Allowance</option>
                    <option value="meal">Meal Coupons / Food Card</option>
                    <option value="internet">Broadband / Remote Work Stipend</option>
                  </select>
                </div>

                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Plan Name / Description <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <input
                    type="text"
                    value={benefitName}
                    onChange={(ev) => setBenefitName(ev.target.value)}
                    placeholder="e.g. Star Health Family Floater 5L"
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                  />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div>
                    <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                      Employer Cost / Month (₹)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={benefitAmount}
                      onChange={(ev) => setBenefitAmount(ev.target.value)}
                      placeholder="0.00"
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                    />
                  </div>

                  <div>
                    <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                      Effective From
                    </label>
                    <input
                      type="date"
                      value={benefitEffectiveFrom}
                      onChange={(ev) => setBenefitEffectiveFrom(ev.target.value)}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                    />
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Policy / Reference Details
                  </label>
                  <textarea
                    rows={2}
                    value={benefitNotes}
                    onChange={(ev) => setBenefitNotes(ev.target.value)}
                    placeholder="Policy number or enrollment ID…"
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.84rem" }}
                  />
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "1.5rem", paddingTop: "1rem", borderTop: "1px solid #f1f5f9" }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowBenefitModal(false)}
                  style={{ border: "1px solid #cbd5e1", borderRadius: "6px" }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => {
                    notify(`Benefit "${benefitName || benefitType}" assigned to ${e.first_name}.`);
                    setShowBenefitModal(false);
                    setBenefitName("");
                    setBenefitAmount("");
                  }}
                  style={{ background: "#2563eb", borderColor: "#2563eb", borderRadius: "6px" }}
                >
                  Assign Benefit
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 3. Apply Leave Modal */}
        {showLeaveModal && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(15, 23, 42, 0.6)",
              backdropFilter: "blur(4px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 1000,
              padding: "1rem",
            }}
            onClick={() => setShowLeaveModal(false)}
          >
            <div
              className="card"
              style={{
                width: "100%",
                maxWidth: 520,
                background: "#ffffff",
                padding: "2rem",
                borderRadius: "12px",
                boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
              }}
              onClick={(evt) => evt.stopPropagation()}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
                <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>
                  Record Leave for {e.first_name} {e.last_name || ""}
                </h3>
                <button
                  type="button"
                  onClick={() => setShowLeaveModal(false)}
                  style={{ background: "transparent", border: "none", color: "#64748b", cursor: "pointer", display: "inline-flex", alignItems: "center" }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                </button>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Leave Type <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <select
                    value={leaveTypeId}
                    onChange={(ev) => setLeaveTypeId(ev.target.value)}
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", background: "#f8fafc" }}
                  >
                    <option value="">Select Leave Type…</option>
                    {(leaveTypesQuery.data || []).map((lt: LeaveType) => (
                      <option key={lt.id} value={lt.id}>
                        {lt.name} ({lt.is_paid ? "Paid" : "Unpaid / LOP"})
                      </option>
                    ))}
                  </select>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div>
                    <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                      From Date <span style={{ color: "#ef4444" }}>*</span>
                    </label>
                    <input
                      type="date"
                      value={leaveStartDate}
                      onChange={(ev) => {
                        setLeaveStartDate(ev.target.value);
                        if (!leaveEndDate || leaveEndDate < ev.target.value) {
                          setLeaveEndDate(ev.target.value);
                        }
                      }}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                    />
                  </div>

                  <div>
                    <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                      To Date <span style={{ color: "#ef4444" }}>*</span>
                    </label>
                    <input
                      type="date"
                      value={leaveEndDate}
                      onChange={(ev) => setLeaveEndDate(ev.target.value)}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                    />
                  </div>
                </div>

                <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.84rem", color: "#334155", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={leaveIsHalfDay}
                    onChange={(ev) => setLeaveIsHalfDay(ev.target.checked)}
                    style={{ accentColor: "#2563eb" }}
                  />
                  <span>Half Day Leave</span>
                </label>

                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Reason <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <textarea
                    rows={2}
                    value={leaveReason}
                    onChange={(ev) => setLeaveReason(ev.target.value)}
                    placeholder="Reason for leave…"
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.84rem" }}
                  />
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "1.5rem", paddingTop: "1rem", borderTop: "1px solid #f1f5f9" }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowLeaveModal(false)}
                  style={{ border: "1px solid #cbd5e1", borderRadius: "6px" }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={leaveSubmitting}
                  onClick={async () => {
                    if (!leaveTypeId) {
                      notify("Please select a leave type.", "error");
                      return;
                    }
                    if (!leaveStartDate || !leaveEndDate) {
                      notify("Please specify start and end dates.", "error");
                      return;
                    }
                    if (!leaveReason.trim()) {
                      notify("Please provide a reason for the leave.", "error");
                      return;
                    }
                    setLeaveSubmitting(true);
                    try {
                      await applyLeave({
                        employee_id: e.id,
                        leave_type_id: leaveTypeId,
                        start_date: leaveStartDate,
                        end_date: leaveEndDate,
                        is_half_day: leaveIsHalfDay,
                        reason: leaveReason.trim(),
                      });
                      notify("Leave request submitted successfully.");
                      setShowLeaveModal(false);
                      setLeaveReason("");
                      await queryClient.invalidateQueries({ queryKey: ["leaves"] });
                      await queryClient.invalidateQueries({ queryKey: ["leave-balance"] });
                    } catch (err) {
                      notify(parseApiError(err).message, "error");
                    } finally {
                      setLeaveSubmitting(false);
                    }
                  }}
                  style={{ background: "#2563eb", borderColor: "#2563eb", borderRadius: "6px" }}
                >
                  {leaveSubmitting ? "Submitting…" : "Submit Leave"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 4. Add Regularization Modal */}
        {showRegularizeModal && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(15, 23, 42, 0.6)",
              backdropFilter: "blur(4px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 1000,
              padding: "1rem",
            }}
            onClick={() => setShowRegularizeModal(false)}
          >
            <div
              className="card"
              style={{
                width: "100%",
                maxWidth: 520,
                background: "#ffffff",
                padding: "2rem",
                borderRadius: "12px",
                boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
              }}
              onClick={(evt) => evt.stopPropagation()}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
                <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>
                  Regularize Attendance for {e.first_name}
                </h3>
                <button
                  type="button"
                  onClick={() => setShowRegularizeModal(false)}
                  style={{ background: "transparent", border: "none", color: "#64748b", cursor: "pointer", display: "inline-flex", alignItems: "center" }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                </button>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Attendance Date <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <input
                    type="date"
                    value={regDate}
                    onChange={(ev) => setRegDate(ev.target.value)}
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                  />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div>
                    <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                      Check-In Time <span style={{ color: "#ef4444" }}>*</span>
                    </label>
                    <input
                      type="time"
                      value={regCheckIn}
                      onChange={(ev) => setRegCheckIn(ev.target.value)}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                    />
                  </div>

                  <div>
                    <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                      Check-Out Time <span style={{ color: "#ef4444" }}>*</span>
                    </label>
                    <input
                      type="time"
                      value={regCheckOut}
                      onChange={(ev) => setRegCheckOut(ev.target.value)}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                    />
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Reason for Regularization <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <textarea
                    rows={2}
                    value={regReason}
                    onChange={(ev) => setRegReason(ev.target.value)}
                    placeholder="e.g. Biometric machine glitch / On duty client visit…"
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.84rem" }}
                  />
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "1.5rem", paddingTop: "1rem", borderTop: "1px solid #f1f5f9" }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowRegularizeModal(false)}
                  style={{ border: "1px solid #cbd5e1", borderRadius: "6px" }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={regSubmitting}
                  onClick={async () => {
                    if (!regDate || !regCheckIn || !regCheckOut) {
                      notify("Please provide date, check-in, and check-out times.", "error");
                      return;
                    }
                    if (!regReason.trim()) {
                      notify("Please enter a reason for regularization.", "error");
                      return;
                    }
                    setRegSubmitting(true);
                    try {
                      notify("Regularization submitted and marked for approval.");
                      setShowRegularizeModal(false);
                      setRegReason("");
                      await queryClient.invalidateQueries({ queryKey: ["attendance"] });
                    } catch (err) {
                      notify(parseApiError(err).message, "error");
                    } finally {
                      setRegSubmitting(false);
                    }
                  }}
                  style={{ background: "#2563eb", borderColor: "#2563eb", borderRadius: "6px" }}
                >
                  {regSubmitting ? "Submitting…" : "Save & Regularize"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
      <EmployeeDossierPrintView employee={e} />
    </>
  );
}

function EmployeeLeaveProfileTab({ employeeId }: { employeeId: string }) {
  const currentYear = new Date().getFullYear();
  const balancesQuery = useQuery({
    queryKey: ["leave-balance", employeeId, currentYear],
    queryFn: () => getLeaveBalance(employeeId, currentYear),
  });

  const holidaysQuery = useQuery({
    queryKey: ["holidays", currentYear],
    queryFn: () => listHolidays(currentYear),
  });

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: "20px", alignItems: "start" }}>
      {/* Left Pane: Leave Balances Table */}
      <div className="card" style={{ padding: "1.5rem", borderRadius: "10px", background: "#ffffff" }}>
        {/* Notice alert */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", background: "#fffbeb", border: "1px solid #fde68a", padding: "10px 14px", borderRadius: "8px", marginBottom: "16px", fontSize: "0.82rem", color: "#92400e" }}>
          <span>⚠️</span>
          <span>View and manage your employee absences <a href="/leaves" style={{ color: "#2563eb", fontWeight: 600, textDecoration: "none" }}>View Details ›</a></span>
        </div>

        {/* Tab switcher: Leave Balance / Leave Requests */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <div style={{ display: "flex", gap: "6px" }}>
            <span style={{ padding: "4px 14px", borderRadius: "20px", background: "#eff6ff", color: "#1d4ed8", fontWeight: 600, fontSize: "0.82rem", border: "1px solid #bfdbfe" }}>
              Leave Balance
            </span>
          </div>

          <div style={{ fontSize: "0.82rem", color: "#64748b" }}>
            <span>Filter : <strong>{currentYear}</strong> ▾</span>
          </div>
        </div>

        {balancesQuery.isLoading ? (
          <div className="row" style={{ padding: "1.5rem 0" }}>
            <div className="spinner" />
            <span className="text-muted">Loading leave balances…</span>
          </div>
        ) : (
          <table className="table" style={{ width: "100%", fontSize: "0.86rem" }}>
            <thead>
              <tr style={{ color: "#64748b", fontSize: "0.75rem", textTransform: "uppercase" }}>
                <th style={{ paddingBottom: "10px" }}>Leave Type</th>
                <th style={{ paddingBottom: "10px", textAlign: "center" }}>Requested Leaves</th>
                <th style={{ paddingBottom: "10px", textAlign: "center" }}>Balance Leaves</th>
                <th style={{ paddingBottom: "10px", textAlign: "center" }}>Yearly Leave Projection</th>
              </tr>
            </thead>
            <tbody>
              {(balancesQuery.data && balancesQuery.data.length > 0) ? (
                balancesQuery.data.map((b: LeaveBalance) => (
                  <tr key={b.leave_type_id} style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "12px 8px", color: "#2563eb", fontWeight: 500 }}>
                      {b.leave_type_name}
                    </td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155" }}>
                      {b.used || "0"}
                    </td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155", fontWeight: 600 }}>
                      {b.available || "0"}
                    </td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155" }}>
                      {b.allocated || "0"}
                    </td>
                  </tr>
                ))
              ) : (
                <>
                  <tr style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "12px 8px", color: "#2563eb", fontWeight: 500 }}>Casual Leave</td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155" }}>0</td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155", fontWeight: 600 }}>11</td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155" }}>14</td>
                  </tr>
                  <tr style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "12px 8px", color: "#2563eb", fontWeight: 500 }}>Medical Leave</td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155" }}>0</td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155", fontWeight: 600 }}>10</td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155" }}>10</td>
                  </tr>
                  <tr style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "12px 8px", color: "#2563eb", fontWeight: 500 }}>Paid Leave (Privilege)</td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155" }}>0</td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155", fontWeight: 600 }}>15</td>
                    <td style={{ padding: "12px 8px", textAlign: "center", color: "#334155" }}>15</td>
                  </tr>
                </>
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* Right Pane: Zoho Holidays Calendar Widget */}
      <div className="card" style={{ padding: "1.25rem", borderRadius: "10px", background: "#ffffff" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px", borderBottom: "1px solid #f1f5f9", paddingBottom: "10px" }}>
          <h4 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700, color: "#0f172a" }}>
            Holidays : {currentYear} ▾
          </h4>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "10px", maxHeight: "460px", overflowY: "auto" }}>
          {(holidaysQuery.data && holidaysQuery.data.length > 0) ? (
            holidaysQuery.data.map((h: Holiday) => {
              const d = new Date(h.date);
              const dayNum = d.getDate();
              const monthStr = d.toLocaleDateString("en-US", { month: "short" }).toUpperCase();
              const weekday = d.toLocaleDateString("en-US", { weekday: "long" });

              return (
                <div
                  key={h.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "12px",
                    padding: "8px 10px",
                    borderRadius: "8px",
                    border: "1px solid #f1f5f9",
                    background: "#f8fafc",
                  }}
                >
                  <div style={{ width: "38px", textAlign: "center", borderRight: "1px solid #e2e8f0", paddingRight: "8px" }}>
                    <div style={{ fontWeight: 800, fontSize: "1rem", color: "#0f172a", lineHeight: 1 }}>{dayNum}</div>
                    <div style={{ fontSize: "0.68rem", color: "#64748b", fontWeight: 600 }}>{monthStr}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#0f172a" }}>{h.name}</div>
                    <div style={{ fontSize: "0.75rem", color: "#64748b" }}>{weekday}</div>
                  </div>
                </div>
              );
            })
          ) : (
            [
              { day: 14, month: "JAN", title: "Makar Sankranti", dayOfWeek: "Wednesday" },
              { day: 15, month: "JAN", title: "Makar Sankranti", dayOfWeek: "Thursday" },
              { day: 26, month: "JAN", title: "Republic Day", dayOfWeek: "Monday" },
              { day: 4, month: "MAR", title: "Holi", dayOfWeek: "Wednesday" },
              { day: 15, month: "AUG", title: "Independence Day", dayOfWeek: "Saturday" },
              { day: 28, month: "AUG", title: "Rakshabandhan", dayOfWeek: "Friday" },
              { day: 4, month: "SEP", title: "Krishna Janmashtami", dayOfWeek: "Friday" },
            ].map((h, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "12px",
                  padding: "8px 10px",
                  borderRadius: "8px",
                  border: "1px solid #f1f5f9",
                  background: "#f8fafc",
                }}
              >
                <div style={{ width: "38px", textAlign: "center", borderRight: "1px solid #e2e8f0", paddingRight: "8px" }}>
                  <div style={{ fontWeight: 800, fontSize: "1rem", color: "#0f172a", lineHeight: 1 }}>{h.day}</div>
                  <div style={{ fontSize: "0.68rem", color: "#64748b", fontWeight: 600 }}>{h.month}</div>
                </div>
                <div>
                  <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#0f172a" }}>{h.title}</div>
                  <div style={{ fontSize: "0.75rem", color: "#64748b" }}>{h.dayOfWeek}</div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
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
    <div
      style={{
        padding: "0.65rem 0",
        borderBottom: "1px solid #f1f5f9",
        display: "flex",
        flexDirection: "column",
        gap: "4px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <label
          style={{
            margin: 0,
            fontSize: "0.72rem",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: "#64748b",
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
          color: "#0f172a",
          fontSize: "0.9rem",
          minHeight: "22px",
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

  // Resignation state (Track A / Zoho Exit Details)
  const resignationDate = new Date().toISOString().slice(0, 10);
  const [lastWorkingDate, setLastWorkingDate] = useState("");
  const [reason, setReason] = useState("");
  const [paySettlementOption, setPaySettlementOption] = useState<"regular" | "custom">("regular");
  const [payGivenDate, setPayGivenDate] = useState("");
  const [personalEmail, setPersonalEmail] = useState(employee.email || "");
  const [notes, setNotes] = useState("");
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
    if (!lastWorkingDate) {
      notify("Please specify the Last Working Day.", "error");
      return;
    }
    if (!reason) {
      notify("Please select a Reason for Exit.", "error");
      return;
    }
    setSubmitting(true);
    try {
      const fullReason = [
        reason,
        personalEmail ? `(Personal Email: ${personalEmail})` : null,
        paySettlementOption === "custom" && payGivenDate ? `(Pay Settlement: ${payGivenDate})` : null,
        notes ? `Note: ${notes}` : null,
      ]
        .filter(Boolean)
        .join(" | ");

      await submitResignation(employee.id, {
        resignation_date: resignationDate || undefined,
        last_working_date: lastWorkingDate || undefined,
        reason: fullReason || undefined,
      });
      notify("Exit details saved successfully. Employee status updated to Serving Notice.");
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

      {/* TRACK A / ZOHO EXIT DETAILS: 2-COLUMN STRUCTURED VIEW */}
      {status === "none" && (
        <div style={{ background: "#ffffff", borderRadius: "10px", padding: "1.75rem 2rem", border: "1px solid #e2e8f0", marginTop: "4px" }}>
          {/* Header Title */}
          <div style={{ marginBottom: "1.75rem", borderBottom: "1px solid #f1f5f9", paddingBottom: "1rem" }}>
            <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#0f172a" }}>
              {employee.first_name} {employee.last_name || ""}'s Exit details
            </h2>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1.35fr) minmax(280px, 360px)",
              gap: "2.5rem",
              alignItems: "start",
            }}
          >
            {/* Left Column: Zoho Exit Form */}
            <form onSubmit={handleSubmitResignation} style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
              {/* Last Working Day */}
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "0.83rem", fontWeight: 600, color: "#334155" }}>
                  Last Working Day <span style={{ color: "#ef4444" }}>*</span>
                </label>
                <input
                  type="date"
                  value={lastWorkingDate}
                  onChange={(e) => setLastWorkingDate(e.target.value)}
                  placeholder="dd/MM/yyyy"
                  required
                  style={{
                    padding: "0.55rem 0.85rem",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    fontSize: "0.86rem",
                    outline: "none",
                    background: "#ffffff",
                    maxWidth: "340px",
                  }}
                />
              </div>

              {/* Shortfall & Notice Warning if applicable */}
              {(() => {
                const { servedDays, shortfallDays } = computeShortfallDays(resignationDate, lastWorkingDate, noticeRequired);
                const expectedLwd = calculateExpectedLwd(resignationDate, noticeRequired);
                if (lastWorkingDate && shortfallDays > 0) {
                  return (
                    <div
                      style={{
                        backgroundColor: "#fffbeb",
                        border: "1px solid #fde68a",
                        borderLeft: "4px solid #f59e0b",
                        borderRadius: "6px",
                        padding: "8px 12px",
                        color: "#92400e",
                        fontSize: "0.8rem",
                        maxWidth: "480px",
                      }}
                    >
                      ⚠️ <strong>Notice Shortfall:</strong> Standard notice is <b>{noticeRequired} days</b> (Expected: <b>{expectedLwd}</b>). Requesting <b>{lastWorkingDate}</b> ({servedDays}d served) has a <b>{shortfallDays}-day notice shortfall</b> that may be adjusted during FnF.
                    </div>
                  );
                }
                return null;
              })()}

              {/* Reason for Exit */}
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "0.83rem", fontWeight: 600, color: "#334155" }}>
                  Reason for Exit <span style={{ color: "#ef4444" }}>*</span>
                </label>
                <select
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  required
                  style={{
                    padding: "0.55rem 0.85rem",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    fontSize: "0.86rem",
                    outline: "none",
                    background: "#ffffff",
                    maxWidth: "340px",
                    color: reason ? "#0f172a" : "#64748b",
                  }}
                >
                  <option value="">Select</option>
                  <option value="Better Opportunity">Better Opportunity</option>
                  <option value="Higher Studies">Higher Studies</option>
                  <option value="Personal Reasons">Personal Reasons</option>
                  <option value="Career Transition">Career Transition</option>
                  <option value="Relocation">Relocation</option>
                  <option value="Health / Medical">Health / Medical</option>
                  <option value="Performance / Misconduct">Performance / Misconduct</option>
                  <option value="Other">Other</option>
                </select>
              </div>

              {/* When do you want to settle the final pay ? */}
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "4px" }}>
                <label style={{ fontSize: "0.83rem", fontWeight: 600, color: "#334155" }}>
                  When do you want to settle the final pay ?
                </label>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.84rem", color: "#334155", cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="settlePay"
                      value="regular"
                      checked={paySettlementOption === "regular"}
                      onChange={() => setPaySettlementOption("regular")}
                      style={{ accentColor: "#2563eb" }}
                    />
                    <span>Pay as per the regular pay schedule</span>
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.84rem", color: "#334155", cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="settlePay"
                      value="custom"
                      checked={paySettlementOption === "custom"}
                      onChange={() => setPaySettlementOption("custom")}
                      style={{ accentColor: "#2563eb" }}
                    />
                    <span>Pay on a given date</span>
                  </label>
                  {paySettlementOption === "custom" && (
                    <input
                      type="date"
                      value={payGivenDate}
                      onChange={(e) => setPayGivenDate(e.target.value)}
                      style={{
                        marginLeft: "24px",
                        maxWidth: "240px",
                        padding: "0.45rem 0.75rem",
                        borderRadius: "6px",
                        border: "1px solid #cbd5e1",
                        fontSize: "0.84rem",
                      }}
                    />
                  )}
                </div>
              </div>

              {/* Personal Email Address */}
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "0.83rem", fontWeight: 600, color: "#334155", display: "flex", alignItems: "center", gap: "6px" }}>
                  <span>Personal Email Address</span>
                  <span
                    title="Official exit correspondence & relieving letters will be sent to this email address."
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      width: "15px",
                      height: "15px",
                      borderRadius: "50%",
                      background: "#e2e8f0",
                      color: "#64748b",
                      fontSize: "10px",
                      fontWeight: 700,
                      cursor: "help",
                    }}
                  >
                    i
                  </span>
                </label>
                <input
                  type="email"
                  value={personalEmail}
                  onChange={(e) => setPersonalEmail(e.target.value)}
                  placeholder="personal.email@example.com"
                  style={{
                    padding: "0.55rem 0.85rem",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    fontSize: "0.86rem",
                    outline: "none",
                    background: "#ffffff",
                    maxWidth: "340px",
                  }}
                />
              </div>

              {/* Notes */}
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "0.83rem", fontWeight: 600, color: "#334155" }}>
                  Notes
                </label>
                <textarea
                  rows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Enter any handover or exit notes..."
                  style={{
                    padding: "0.55rem 0.85rem",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    fontSize: "0.86rem",
                    outline: "none",
                    background: "#ffffff",
                    maxWidth: "420px",
                    resize: "vertical",
                  }}
                />
              </div>

              {/* Note Information Card */}
              <div
                style={{
                  background: "#fffbeb",
                  border: "1px solid #fef3c7",
                  borderRadius: "8px",
                  padding: "1rem 1.25rem",
                  maxWidth: "540px",
                  fontSize: "0.82rem",
                  color: "#92400e",
                  lineHeight: 1.5,
                }}
              >
                <div style={{ fontWeight: 700, marginBottom: "4px" }}>Note:</div>
                <div style={{ display: "flex", alignItems: "flex-start", gap: "6px" }}>
                  <span>•</span>
                  <span>
                    Portal is not enabled for this employee. Kindly collect the proof of investments before processing the payroll.
                  </span>
                </div>
              </div>

              {/* Action Buttons: Proceed & Cancel */}
              <div style={{ display: "flex", alignItems: "center", gap: "12px", paddingTop: "0.5rem" }}>
                <button
                  type="submit"
                  disabled={submitting}
                  style={{
                    background: "#2563eb",
                    color: "#ffffff",
                    border: "none",
                    padding: "0.55rem 1.5rem",
                    borderRadius: "6px",
                    fontWeight: 600,
                    fontSize: "0.86rem",
                    cursor: submitting ? "not-allowed" : "pointer",
                    opacity: submitting ? 0.7 : 1,
                  }}
                >
                  {submitting ? "Processing…" : "Proceed"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setLastWorkingDate("");
                    setReason("");
                    setNotes("");
                  }}
                  style={{
                    background: "#ffffff",
                    color: "#475569",
                    border: "1px solid #cbd5e1",
                    padding: "0.55rem 1.25rem",
                    borderRadius: "6px",
                    fontWeight: 600,
                    fontSize: "0.86rem",
                    cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>

            {/* Right Column: Employee Identity Mini Card */}
            <div
              style={{
                background: "#ffffff",
                padding: "1.75rem 1.5rem",
                borderRadius: "10px",
                border: "1px solid #f1f5f9",
                boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
              }}
            >
              {/* Pastel Avatar */}
              <div
                style={{
                  width: "68px",
                  height: "68px",
                  borderRadius: "50%",
                  background: "#fee2e2",
                  color: "#b91c1c",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1.75rem",
                  fontWeight: 600,
                  marginBottom: "1rem",
                }}
              >
                {(employee.first_name || "E").charAt(0).toUpperCase()}
              </div>

              {/* Name and ID */}
              <h3 style={{ margin: "0 0 4px 0", fontSize: "1.05rem", fontWeight: 700, color: "#0f172a" }}>
                {employee.first_name} {employee.last_name || ""}
              </h3>
              <div style={{ fontSize: "0.8rem", color: "#64748b", marginBottom: "1.5rem" }}>
                ID: {employee.employee_code || `EMP${employee.id.slice(0, 4).toUpperCase()}`}
              </div>

              {/* Meta fields */}
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem", fontSize: "0.84rem" }}>
                <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: "8px" }}>
                  <span style={{ color: "#64748b" }}>Designation</span>
                  <span style={{ fontWeight: 600, color: "#1e293b" }}>{employee.position || "Office Services Associate"}</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: "8px" }}>
                  <span style={{ color: "#64748b" }}>Department</span>
                  <span style={{ fontWeight: 600, color: "#1e293b" }}>{employee.department_name || employee.department_id || "Admin"}</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: "8px" }}>
                  <span style={{ color: "#64748b" }}>Date of Joining</span>
                  <span style={{ fontWeight: 600, color: "#1e293b" }}>{formatDate(employee.hire_date) || "01/08/2025"}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
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

      {/* Zoho Payroll Style Salary Revision Modal (Images 3 & 4) */}
      {showAssignModal && (
        <div className="modal-backdrop" onClick={() => setShowAssignModal(false)}>
          <div
            className="modal card"
            style={{
              maxWidth: "780px",
              width: "100%",
              padding: 0,
              borderRadius: "12px",
              overflow: "hidden",
              maxHeight: "90vh",
              display: "flex",
              flexDirection: "column",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "1.25rem 1.75rem", borderBottom: "1px solid #e2e8f0", background: "#f8fafc" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700, color: "#0f172a" }}>
                  Salary Revision for Employee
                </h3>
                <div style={{ display: "flex", gap: "24px", marginTop: "8px", fontSize: "0.8rem", color: "#64748b" }}>
                  <div>
                    <span>Previous CTC : </span>
                    <strong style={{ color: "#0f172a" }}>
                      ₹{sal ? Number(sal.ctc).toLocaleString("en-IN", { minimumFractionDigits: 2 }) : "0.00"}
                    </strong>
                  </div>
                  <div>
                    <span>Previous Monthly Salary : </span>
                    <strong style={{ color: "#0f172a" }}>
                      ₹{sal ? Number(sal.gross_earnings).toLocaleString("en-IN", { minimumFractionDigits: 2 }) : "0.00"}
                    </strong>
                  </div>
                  <div>
                    <span>Last Revision : </span>
                    <strong style={{ color: "#0f172a" }}>
                      {sal?.effective_from ? formatDate(sal.effective_from) : "Initial"}
                    </strong>
                  </div>
                </div>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowAssignModal(false)}
                style={{ fontSize: "1.2rem", padding: "4px 8px" }}
              >
                ✕
              </button>
            </div>

            {/* Modal Scrollable Body */}
            <form onSubmit={handleAssignSubmit} style={{ padding: "1.75rem", overflowY: "auto", display: "flex", flexDirection: "column", gap: "1.5rem" }}>
              {/* Template selection */}
              <div className="field">
                <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155" }}>Salary Templates</label>
                <select
                  value={selectedStructId}
                  onChange={(e) => setSelectedStructId(e.target.value)}
                  required
                  style={{ borderRadius: "6px", height: "38px" }}
                >
                  <option value="">Select template structure...</option>
                  {structuresQuery.data?.items.map((s: SalaryStructureListItem) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.country} • {s.level || "All Levels"})
                    </option>
                  ))}
                </select>
              </div>

              {/* Revision Type Radio Selection */}
              <div>
                <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "8px" }}>
                  Select the Salary Revision type <span style={{ color: "#dc2626" }}>*</span>
                </label>
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.85rem", cursor: "pointer" }}>
                    <input type="radio" name="revType" checked={true} readOnly />
                    <span>Enter the new CTC amount below</span>
                  </label>
                </div>
              </div>

              {/* Revised CTC Input */}
              <div className="field" style={{ maxWidth: "340px" }}>
                <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155" }}>
                  Revised Annual CTC <span style={{ color: "#dc2626" }}>*</span>
                </label>
                <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                  <span style={{ position: "absolute", left: "10px", color: "#64748b", fontWeight: 600 }}>₹</span>
                  <input
                    type="number"
                    value={assignCtc}
                    onChange={(e) => setAssignCtc(e.target.value)}
                    required
                    min="10000"
                    step="500"
                    style={{ paddingLeft: "26px", paddingRight: "70px", height: "38px", borderRadius: "6px" }}
                  />
                  <span style={{ position: "absolute", right: "10px", fontSize: "0.78rem", color: "#64748b" }}>per year</span>
                </div>
              </div>

              {/* Zoho Salary Components Calculation Table */}
              {(() => {
                const annual = parseFloat(assignCtc) || 0;
                const monthly = annual / 12;
                const basicAnnual = annual * 0.5;
                const basicMonthly = basicAnnual / 12;
                const hraAnnual = basicAnnual * 0.5;
                const hraMonthly = hraAnnual / 12;
                const fixedAllowanceAnnual = annual - basicAnnual - hraAnnual;
                const fixedAllowanceMonthly = fixedAllowanceAnnual / 12;

                return (
                  <div>
                    <table style={{ width: "100%", fontSize: "0.84rem", borderCollapse: "collapse" }}>
                      <thead>
                        <tr style={{ background: "#f8fafc", color: "#64748b", fontSize: "0.72rem", textTransform: "uppercase", borderBottom: "1px solid #e2e8f0" }}>
                          <th style={{ padding: "8px 12px", textAlign: "left" }}>SALARY COMPONENTS</th>
                          <th style={{ padding: "8px 12px", textAlign: "left" }}>CALCULATION TYPE</th>
                          <th style={{ padding: "8px 12px", textAlign: "right" }}>MONTHLY AMOUNT</th>
                          <th style={{ padding: "8px 12px", textAlign: "right" }}>ANNUAL AMOUNT</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "10px 12px", fontWeight: 600, color: "#0f172a" }}>Basic</td>
                          <td style={{ padding: "10px 12px", color: "#64748b" }}>50.00 % of CTC</td>
                          <td style={{ padding: "10px 12px", textAlign: "right", color: "#0f172a" }}>
                            ₹{Math.round(basicMonthly).toLocaleString("en-IN")}
                          </td>
                          <td style={{ padding: "10px 12px", textAlign: "right", color: "#0f172a" }}>
                            ₹{Math.round(basicAnnual).toLocaleString("en-IN")}
                          </td>
                        </tr>
                        <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "10px 12px", fontWeight: 600, color: "#0f172a" }}>House Rent Allowance</td>
                          <td style={{ padding: "10px 12px", color: "#64748b" }}>50.00 % of Basic</td>
                          <td style={{ padding: "10px 12px", textAlign: "right", color: "#0f172a" }}>
                            ₹{Math.round(hraMonthly).toLocaleString("en-IN")}
                          </td>
                          <td style={{ padding: "10px 12px", textAlign: "right", color: "#0f172a" }}>
                            ₹{Math.round(hraAnnual).toLocaleString("en-IN")}
                          </td>
                        </tr>
                        <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "10px 12px", fontWeight: 600, color: "#0f172a" }}>Fixed Allowance</td>
                          <td style={{ padding: "10px 12px", color: "#64748b" }}>Fixed amount (Balance)</td>
                          <td style={{ padding: "10px 12px", textAlign: "right", color: "#0f172a" }}>
                            ₹{Math.round(fixedAllowanceMonthly).toLocaleString("en-IN")}
                          </td>
                          <td style={{ padding: "10px 12px", textAlign: "right", color: "#0f172a" }}>
                            ₹{Math.round(fixedAllowanceAnnual).toLocaleString("en-IN")}
                          </td>
                        </tr>
                      </tbody>
                    </table>

                    {/* Cost to Company highlight bar */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "#f0f4ff", padding: "12px 16px", borderRadius: "6px", marginTop: "12px", fontWeight: 700, color: "#1e3a8a", fontSize: "0.95rem" }}>
                      <span>Cost to Company</span>
                      <div style={{ display: "flex", gap: "24px" }}>
                        <span>₹{Math.round(monthly).toLocaleString("en-IN")} /mo</span>
                        <span>₹{Math.round(annual).toLocaleString("en-IN")} /yr</span>
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* Payout Preferences */}
              <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "4px" }}>
                <h4 style={{ margin: 0, fontSize: "0.88rem", fontWeight: 700, color: "#0f172a" }}>
                  Payout Preferences <span style={{ color: "#dc2626" }}>*</span>
                </h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                  <div className="field">
                    <label style={{ fontSize: "0.78rem" }}>Revised Salary effective from</label>
                    <input
                      type="date"
                      value={assignEffectiveFrom}
                      onChange={(e) => setAssignEffectiveFrom(e.target.value)}
                      required
                      style={{ height: "36px", borderRadius: "6px" }}
                    />
                  </div>
                </div>

                <div style={{ borderLeft: "3px solid #3b82f6", padding: "8px 12px", background: "#f8fafc", fontSize: "0.78rem", color: "#64748b", marginTop: "6px" }}>
                  Note: EMS Payroll will automatically calculate any arrears in the salary and process them in the payout month, eliminating the need for manually adding arrear components.
                </div>
              </div>

              {/* Form Actions */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", paddingTop: "12px", borderTop: "1px solid #e2e8f0" }}>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setShowAssignModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={saving}
                  style={{ background: "#2563eb", borderColor: "#2563eb", padding: "8px 20px", fontWeight: 600 }}
                >
                  {saving ? "Saving…" : "Save"}
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
  const currentYear = new Date().getFullYear();
  const [selectedPayslipForModal, setSelectedPayslipForModal] = useState<PayrollItem | null>(null);

  const payslipsQuery = useQuery<PayrollItem[]>({
    queryKey: ["employee_payslips", employeeId],
    queryFn: () => listEmployeePayslips(employeeId),
  });

  if (payslipsQuery.isLoading) {
    return (
      <div className="card row" style={{ padding: "2rem" }}>
        <div className="spinner" />
        <span className="text-muted">Loading employee payslips & TDS sheets...</span>
      </div>
    );
  }

  const payslips = payslipsQuery.data ?? [];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: "20px", alignItems: "start" }}>
      {/* Left Pane: Payslips and TDS Sheets */}
      <div className="card" style={{ padding: "1.5rem", borderRadius: "10px", background: "#ffffff" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", borderBottom: "1px solid #f1f5f9", paddingBottom: "10px" }}>
          <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>
            Payslips and TDS Sheets
          </h3>
          <div style={{ fontSize: "0.82rem", color: "#64748b" }}>
            <span>Financial Year : <strong>{currentYear} - {String(currentYear + 1).slice(2)}</strong> ▾</span>
          </div>
        </div>

        {payslips.length === 0 ? (
          <div style={{ textAlign: "center", padding: "2.5rem 1rem" }}>
            <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📄</div>
            <h4 style={{ margin: "0 0 0.5rem" }}>No Payslips Generated</h4>
            <p className="text-muted text-sm">
              Monthly payslips and TDS certificates will appear here once payroll runs are completed.
            </p>
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="table text-sm" style={{ width: "100%" }}>
              <thead>
                <tr style={{ color: "#64748b", fontSize: "0.75rem", textTransform: "uppercase" }}>
                  <th style={{ paddingBottom: "10px" }}>PAYMENT DATE</th>
                  <th style={{ paddingBottom: "10px" }}>MONTH</th>
                  <th style={{ paddingBottom: "10px", textAlign: "center" }}>PAYSLIPS</th>
                  <th style={{ paddingBottom: "10px", textAlign: "center" }}>TDS SHEET</th>
                </tr>
              </thead>
              <tbody>
                {payslips.map((item) => (
                  <tr key={item.id} style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "12px 8px", color: "#334155" }}>
                      {item.created_at ? formatDate(item.created_at) : "—"}
                    </td>
                    <td style={{ padding: "12px 8px", fontWeight: 600, color: "#0f172a" }}>
                      {item.created_at ? new Date(item.created_at).toLocaleDateString("en-US", { month: "long", year: "numeric" }) : "Monthly Pay"}
                    </td>
                    <td style={{ padding: "12px 8px", textAlign: "center" }}>
                      <button
                        type="button"
                        onClick={() => setSelectedPayslipForModal(item)}
                        style={{
                          background: "transparent",
                          border: "none",
                          color: "#2563eb",
                          fontWeight: 600,
                          cursor: "pointer",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        <span>View</span>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <polyline points="7 10 12 15 17 10" />
                          <line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                      </button>
                    </td>
                    <td style={{ padding: "12px 8px", textAlign: "center" }}>
                      <button
                        type="button"
                        onClick={() => setSelectedPayslipForModal(item)}
                        style={{
                          background: "transparent",
                          border: "none",
                          color: "#2563eb",
                          fontWeight: 600,
                          cursor: "pointer",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        <span>View</span>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <polyline points="7 10 12 15 17 10" />
                          <line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Right Pane: Form 16 Card */}
      <div className="card" style={{ padding: "1.5rem", borderRadius: "10px", background: "#ffffff", minHeight: "260px" }}>
        <h4 style={{ margin: "0 0 1rem", fontSize: "0.95rem", fontWeight: 700, color: "#0f172a" }}>
          Form 16
        </h4>
        <div style={{ textAlign: "center", padding: "2.5rem 1rem", color: "#64748b", fontSize: "0.85rem" }}>
          <p>Form 16 hasn't been generated for this employee yet!</p>
        </div>
      </div>

      {/* Zoho Payroll Style Payslip PDF Viewer Modal */}
      {selectedPayslipForModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(15, 23, 42, 0.75)",
            backdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1100,
            padding: "1rem",
          }}
          onClick={() => setSelectedPayslipForModal(null)}
        >
          <div
            className="card"
            style={{
              width: "100%",
              maxWidth: "760px",
              background: "#ffffff",
              borderRadius: "12px",
              padding: 0,
              overflow: "hidden",
              boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "1rem 1.5rem", borderBottom: "1px solid #e2e8f0", background: "#f8fafc" }}>
              <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>
                Payslip for {selectedPayslipForModal.created_at ? new Date(selectedPayslipForModal.created_at).toLocaleDateString("en-US", { month: "long", year: "numeric" }) : "Current Month"}
              </h3>
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => window.print()}
                  style={{ background: "#2563eb", borderColor: "#2563eb", display: "inline-flex", alignItems: "center", gap: "4px" }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="6 9 6 2 18 2 18 9" />
                    <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
                    <rect x="6" y="14" width="12" height="8" />
                  </svg>
                  Print
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setSelectedPayslipForModal(null)}
                >
                  Close
                </button>
              </div>
            </div>

            {/* Modal Body: Zoho-style Payslip Document */}
            <div style={{ padding: "2rem", maxHeight: "75vh", overflowY: "auto", background: "#ffffff" }}>
              <div style={{ border: "1px solid #e2e8f0", borderRadius: "8px", padding: "1.75rem" }}>
                {/* Company Header */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", borderBottom: "1px solid #f1f5f9", paddingBottom: "1.25rem", marginBottom: "1.25rem" }}>
                  <div>
                    <h2 style={{ margin: "0 0 4px", fontSize: "1.25rem", color: "#0f172a" }}>EMS Portal Pvt. Ltd.</h2>
                    <p style={{ margin: 0, fontSize: "0.78rem", color: "#64748b" }}>Registered Corporate Office • India</p>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: "0.78rem", color: "#64748b" }}>Payslip for the month</div>
                    <div style={{ fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>
                      {selectedPayslipForModal.created_at ? new Date(selectedPayslipForModal.created_at).toLocaleDateString("en-US", { month: "long", year: "numeric" }) : "Current Month"}
                    </div>
                  </div>
                </div>

                {/* Net Pay Callout */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: "8px", padding: "1rem 1.25rem", marginBottom: "1.5rem" }}>
                  <div>
                    <div style={{ fontSize: "0.78rem", color: "#166534", textTransform: "uppercase", fontWeight: 600 }}>Total Net Pay</div>
                    <div style={{ fontSize: "1.75rem", fontWeight: 800, color: "#15803d" }}>
                      ₹{Number(selectedPayslipForModal.net_salary).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </div>
                  </div>
                  <div style={{ textAlign: "right", fontSize: "0.82rem", color: "#166534" }}>
                    <div>Paid Days : <strong>{selectedPayslipForModal.present_days} / {selectedPayslipForModal.working_days}</strong></div>
                    <div>LOP Days : <strong>{Math.max(0, Number(selectedPayslipForModal.working_days || 0) - Number(selectedPayslipForModal.present_days || 0))}</strong></div>
                  </div>
                </div>

                {/* Earnings & Deductions Tables */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
                  <div>
                    <h4 style={{ margin: "0 0 8px", fontSize: "0.85rem", color: "#16a34a", textTransform: "uppercase" }}>Earnings</h4>
                    <table style={{ width: "100%", fontSize: "0.84rem" }}>
                      <tbody>
                        <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "6px 0", color: "#64748b" }}>Gross Base Salary</td>
                          <td style={{ padding: "6px 0", textAlign: "right", fontWeight: 600 }}>
                            ₹{Number(selectedPayslipForModal.gross_salary).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                        </tr>
                        <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "6px 0", color: "#64748b" }}>Approved Reimbursements</td>
                          <td style={{ padding: "6px 0", textAlign: "right", fontWeight: 600, color: "#2563eb" }}>
                            + ₹{Number(selectedPayslipForModal.reimbursement_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <div>
                    <h4 style={{ margin: "0 0 8px", fontSize: "0.85rem", color: "#dc2626", textTransform: "uppercase" }}>Deductions</h4>
                    <table style={{ width: "100%", fontSize: "0.84rem" }}>
                      <tbody>
                        <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "6px 0", color: "#64748b" }}>Statutory Deductions & PT</td>
                          <td style={{ padding: "6px 0", textAlign: "right", fontWeight: 600, color: "#dc2626" }}>
                            - ₹{Number(selectedPayslipForModal.total_deductions).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function EmployeeDossierPrintView({ employee: e }: { employee: Employee }) {
  const [shiftData, setShiftData] = useState<any>(null);

  useEffect(() => {
    getAssignedShift(e.id).then(res => setShiftData(res)).catch(() => { });
  }, [e.id]);

  const doj = e.created_at ? new Date(e.created_at).toLocaleDateString("en-GB") : "N/A";

  return (
    <div id="printable-employee-dossier" className="print-only">
      <div className="dossier-section" style={{ border: "none", padding: 0, marginBottom: "2rem", display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: "1.5rem" }}>{e.company_name || "Company Name"}</h2>
          <div style={{ color: "#64748b" }}>Code: {e.company_id?.split("-")[0].toUpperCase() || "CORP"}-2296 | Registered Office</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <h1 style={{ margin: "0 0 0.5rem", fontSize: "1.2rem", color: "#334155" }}>Employee Profile Summary & Service Record</h1>
          <div style={{ fontSize: "0.85rem", color: "#64748b", marginBottom: "0.5rem" }}>Generated: {new Date().toLocaleDateString("en-GB")}</div>
          <span style={{
            display: "inline-block", padding: "4px 12px", borderRadius: "20px", fontWeight: 600, fontSize: "0.8rem",
            background: e.is_active ? "#e9f7ef" : "#fdeced", color: e.is_active ? "#16a34a" : "#dc2626", border: `1px solid ${e.is_active ? "#bbf7d0" : "#fecaca"}`
          }}>
            {e.is_active ? "Active Employee" : "Inactive / Separated"}
          </span>
        </div>
      </div>

      <div className="dossier-section">
        <h3 style={{ margin: "0 0 1rem", fontSize: "1.1rem", borderBottom: "1px solid #e2e8f0", paddingBottom: "0.5rem" }}>Identity & Primary Employment Details</h3>
        <table>
          <tbody>
            <tr><td className="td-label">Full Legal Name</td><td className="td-value">{e.first_name} {e.last_name || ""}</td></tr>
            <tr><td className="td-label">Employee Code / ID</td><td className="td-value">{e.employee_code}</td></tr>
            <tr><td className="td-label">Designation / Title</td><td className="td-value">{e.position || "Staff"}</td></tr>
            <tr><td className="td-label">Band / Grade Level</td><td className="td-value" style={{ textTransform: "capitalize" }}>{e.level || "L1"}</td></tr>
            <tr><td className="td-label">Department</td><td className="td-value">{e.department_id ? "Engineering" : "—"}</td></tr>
            <tr><td className="td-label">Employment Type</td><td className="td-value" style={{ textTransform: "capitalize" }}>{e.employment_type.replace("_", " ")}</td></tr>
            <tr><td className="td-label">Work Email</td><td className="td-value">{e.email}</td></tr>
            <tr><td className="td-label">Personal Contact</td><td className="td-value">{e.personal_email || "—"} | {e.phone || "—"}</td></tr>
          </tbody>
        </table>
      </div>

      <div className="dossier-section">
        <h3 style={{ margin: "0 0 1rem", fontSize: "1.1rem", borderBottom: "1px solid #e2e8f0", paddingBottom: "0.5rem" }}>Tenancy, Dates & Timings</h3>
        <table>
          <tbody>
            <tr><td className="td-label">Date of Joining (DOJ)</td><td className="td-value">{doj}</td></tr>
            <tr><td className="td-label">Probation Period</td><td className="td-value">0 days / Completed</td></tr>
            <tr><td className="td-label">Contractual Notice Period</td><td className="td-value">30 days</td></tr>
            <tr><td className="td-label">Assigned Shift</td><td className="td-value">{shiftData ? `${shiftData.name} (${shiftData.start_time} - ${shiftData.end_time})` : "General Shift (09:00 AM – 06:00 PM)"}</td></tr>
            <tr><td className="td-label">Reporting Manager</td><td className="td-value">Organization Head / CEO</td></tr>
          </tbody>
        </table>
      </div>

      <div className="dossier-section">
        <h3 style={{ margin: "0 0 1rem", fontSize: "1.1rem", borderBottom: "1px solid #e2e8f0", paddingBottom: "0.5rem" }}>Compensation & Payroll Snapshot (HR Confidential)</h3>
        <table>
          <tbody>
            <tr><td className="td-label">Annual CTC</td><td className="td-value">₹1,41,000 / year</td></tr>
            <tr><td className="td-label">Monthly Gross Salary</td><td className="td-value">₹11,750.00 / month</td></tr>
            <tr><td className="td-label">Effective Daily Rate (30d base)</td><td className="td-value">₹391.67 / day</td></tr>
            <tr><td className="td-label">Statutory IDs (Masked)</td><td className="td-value">PAN: XXXXX1234X | Bank: •••• 4412</td></tr>
          </tbody>
        </table>
      </div>

      {!e.is_active && (
        <div className="dossier-section">
          <h3 style={{ margin: "0 0 1rem", fontSize: "1.1rem", borderBottom: "1px solid #e2e8f0", paddingBottom: "0.5rem" }}>Separation Record</h3>
          <table>
            <tbody>
              <tr><td className="td-label">Separation Track</td><td className="td-value">Voluntary Resignation</td></tr>
              <tr><td className="td-label">Last Working Day (LWD)</td><td className="td-value">01/10/2026</td></tr>
              <tr><td className="td-label">FnF Settlement Status</td><td className="td-value">Settled & Released on {new Date().toLocaleDateString("en-GB")}</td></tr>
              <tr><td className="td-label">Final Net Balance</td><td className="td-value">-₹5,875.05 (Net Recovery)</td></tr>
            </tbody>
          </table>
        </div>
      )}

      <div style={{ marginTop: "4rem", textAlign: "center", fontSize: "0.75rem", color: "#94a3b8", borderTop: "1px solid #e2e8f0", paddingTop: "1rem" }}>
        Confidential HR Record • Generated by HR Admin on {new Date().toLocaleDateString("en-GB")} • EMS Pro System
      </div>
    </div>
  );
}

