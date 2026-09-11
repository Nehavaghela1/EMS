import { useState } from "react";
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
  getFnFSettlement,
  type Employee,
} from "../api";
import {
  listEmployeePayslips,
  listStructures,
  assignEmployeeSalary,
  type PayrollItem,
  type SalaryStructureListItem,
} from "../../payroll/api";
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
              <div className="text-muted" style={{ fontSize: "0.85rem", marginTop: "2px" }}>
                {e.position || "Staff"} • {e.level || "L1"} • {e.employment_type.replace("_", " ")}
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
              <Field label="Full Name" value={`${e.first_name} ${e.last_name || ""}`} />
              <Field label="Employee Code" value={e.employee_code} />
              <Field label="Work Email" value={e.email} />
              <Field label="Personal Email" value={e.personal_email ?? "—"} />
              <Field label="Phone" value={e.phone ?? "—"} />
              <Field label="Invitation Status" value={e.invitation_status.replace("_", " ")} />
            </div>
          </div>

          <div className="card">
            <h3 style={{ fontSize: "1rem", marginBottom: "1rem", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
              Employment & Designation
            </h3>
            <div className="form-grid">
              <Field label="Position / Role" value={e.position ?? "—"} />
              <Field label="Level" value={e.level ?? "—"} />
              <Field label="Employment Type" value={e.employment_type.replace("_", " ")} />
              <Field label="Hire Date" value={formatDate(e.hire_date)} />
              <Field label="Probation End Date" value={e.probation_end_date ? formatDate(e.probation_end_date) : "—"} />
              <Field label="Notice Period" value={`${e.notice_period_days ?? 30} days`} />
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: SALARY DETAILS */}
      {activeTab === "salary" && (
        <EmployeeSalaryTab employeeId={e.id} isHr={isHr} />
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

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      <div>{value}</div>
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
  const [resignationDate, setResignationDate] = useState("");
  const [lastWorkingDate, setLastWorkingDate] = useState("");
  const [reason, setReason] = useState("");
  const [noticeWaived, setNoticeWaived] = useState(false);
  const [recoveryDays, setRecoveryDays] = useState(0);

  const status = employee.resignation_status ?? "none";

  const fnfQuery = useQuery({
    queryKey: ["fnf", employee.id],
    queryFn: () => getFnFSettlement(employee.id),
    enabled: isHr && (status === "approved" || !employee.is_active),
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
      notify("Resignation submitted successfully.");
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
        last_working_date: lastWorkingDate || undefined,
        notice_waived: noticeWaived,
        notice_recovery_days: recoveryDays,
      });
      notify(approved ? "Resignation approved." : "Resignation rejected.");
      onRefresh();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setApproving(false);
    }
  }

  return (
    <div className="card mb-4">
      <div className="row-between mb-3">
        <h3 className="mb-0">Resignation & Full-and-Final (FnF) Settlement</h3>
        <span
          className={
            "badge " +
            (status === "approved"
              ? "badge-danger"
              : status === "submitted"
              ? "badge-warning"
              : "badge-muted")
          }
        >
          {status === "none" ? "Not Resigned" : `Resignation ${status}`}
        </span>
      </div>

      {status === "none" && (
        <form onSubmit={handleSubmitResignation} className="stack">
          <p className="text-muted text-sm mt-0">
            Submit formal resignation request with effective dates and reason.
          </p>
          <div className="form-grid">
            <div className="field">
              <label>Resignation date</label>
              <input
                type="date"
                value={resignationDate}
                onChange={(e) => setResignationDate(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label>Proposed last working date</label>
              <input
                type="date"
                value={lastWorkingDate}
                onChange={(e) => setLastWorkingDate(e.target.value)}
                required
              />
            </div>
          </div>
          <div className="field">
            <label>Reason for resignation</label>
            <textarea
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="State reason for resignation…"
            />
          </div>
          <div className="row-end">
            <button type="submit" className="btn btn-danger" disabled={submitting}>
              {submitting ? "Submitting…" : "Submit Resignation"}
            </button>
          </div>
        </form>
      )}

      {status === "submitted" && (
        <div className="stack">
          <div className="form-grid">
            <Field label="Resignation date" value={employee.resignation_date ?? "—"} />
            <Field label="Last working date" value={employee.last_working_date ?? "—"} />
          </div>
          {isHr ? (
            <div className="card" style={{ background: "var(--color-bg)" }}>
              <h4 className="mt-0 mb-2">HR Approval & Notice Terms</h4>
              <div className="form-grid mb-3">
                <div className="field">
                  <label>Confirmed last working date</label>
                  <input
                    type="date"
                    defaultValue={employee.last_working_date ?? ""}
                    onChange={(e) => setLastWorkingDate(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label>Notice recovery days (if unserved)</label>
                  <input
                    type="number"
                    min="0"
                    value={recoveryDays}
                    onChange={(e) => setRecoveryDays(Number(e.target.value))}
                  />
                </div>
              </div>
              <div className="row mb-3">
                <input
                  type="checkbox"
                  id="noticeWaived"
                  checked={noticeWaived}
                  onChange={(e) => setNoticeWaived(e.target.checked)}
                />
                <label htmlFor="noticeWaived" className="text-sm font-medium">
                  Waive notice period and notice recovery deduction
                </label>
              </div>
              <div className="row">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleApprove(true)}
                  disabled={approving}
                >
                  {approving ? "Processing…" : "Approve Resignation"}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => handleApprove(false)}
                  disabled={approving}
                >
                  Reject
                </button>
              </div>
            </div>
          ) : (
            <div className="alert alert-warning">
              Resignation submitted. Awaiting HR review and clearance.
            </div>
          )}
        </div>
      )}

      {status === "approved" && (
        <div className="stack">
          <div className="form-grid mb-3">
            <Field label="Resignation date" value={formatDate(employee.resignation_date)} />
            <Field label="Last working date" value={formatDate(employee.last_working_date)} />
            <Field
              label="Notice waived"
              value={employee.notice_waived ? "Yes (Waived)" : "No"}
            />
            <Field
              label="Notice recovery days"
              value={employee.notice_recovery_days ?? 0}
            />
          </div>

          {isHr && (
            <div>
              <h4 className="mb-2">Full-and-Final (FnF) Settlement Calculation</h4>
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
                  <div className="form-grid">
                    <Field
                      label="Unpaid salary days"
                      value={`${fnfQuery.data.unpaid_salary_days} days`}
                    />
                    <Field
                      label="Unpaid salary amount"
                      value={`₹${Number(fnfQuery.data.unpaid_salary_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                    />
                    <Field
                      label="Encashable leave days"
                      value={`${fnfQuery.data.encashable_leave_days} days`}
                    />
                    <Field
                      label="Leave encashment"
                      value={`₹${Number(fnfQuery.data.leave_encashment_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                    />
                    <Field
                      label="Notice recovery days"
                      value={`${fnfQuery.data.notice_recovery_days} days`}
                    />
                    <Field
                      label="Notice recovery deduction"
                      value={`- ₹${Number(fnfQuery.data.notice_recovery_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                    />
                  </div>
                  <div
                    className="row-between mt-3"
                    style={{
                      borderTop: "1px solid var(--color-border)",
                      paddingTop: "var(--space-3)",
                    }}
                  >
                    <span className="font-semibold">Total Net Settlement</span>
                    <span className="text-lg font-semibold" style={{ color: "var(--color-primary)" }}>
                      ₹{Number(fnfQuery.data.total_settlement_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
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

function EmployeeSalaryTab({ employeeId, isHr }: { employeeId: string; isHr: boolean }) {
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
    queryKey: ["salary_structures_list"],
    queryFn: () => listStructures(1, 100),
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

