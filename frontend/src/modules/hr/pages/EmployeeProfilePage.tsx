import { useState } from "react";
import { useLocation, useNavigate, useParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog";
import { parseApiError } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
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

      <PageHeader
        title={`${e.first_name}${e.last_name ? " " + e.last_name : ""}`}
        breadcrumb="HR / Employees"
        action={
          isHr && (
            <div className="row">
              {e.invitation_status !== "activated" && (
                <button className="btn" onClick={handleResendInvite} disabled={resendBusy}>
                  {resendBusy ? "Resending…" : "Resend invitation"}
                </button>
              )}
              <button className="btn" onClick={() => navigate(`/employees/${e.id}/edit`)}>
                Edit
              </button>
              <button
                className={e.is_active ? "btn btn-danger" : "btn btn-primary"}
                onClick={() => setConfirmOpen(true)}
              >
                {e.is_active ? "Deactivate" : "Reactivate"}
              </button>
            </div>
          )
        }
      />

      {invite && (
        <div className="alert alert-success mb-4">
          Invitation sent to <strong>{invite.sent_to}</strong>, expires{" "}
          {new Date(invite.expires_at).toLocaleString()}.
        </div>
      )}

      <div className="card mb-4">
        <div className="form-grid">
          <Field label="Employee code" value={e.employee_code} />
          <Field
            label="Status"
            value={
              <span className={"badge " + (e.is_active ? "badge-success" : "badge-muted")}>
                {e.is_active ? "Active" : "Inactive"}
              </span>
            }
          />
          <Field label="Work email" value={e.email} />
          <Field label="Personal email" value={e.personal_email ?? "—"} />
          <Field label="Phone" value={e.phone ?? "—"} />
          <Field label="Position" value={e.position ?? "—"} />
          <Field label="Level" value={e.level ?? "—"} />
          <Field label="Employment type" value={e.employment_type.replace("_", " ")} />
          <Field label="Hire date" value={e.hire_date} />
          <Field label="Probation end date" value={e.probation_end_date ?? "—"} />
          <Field label="Notice period" value={`${e.notice_period_days ?? 30} days`} />
          <Field label="Invitation status" value={e.invitation_status.replace("_", " ")} />
        </div>
      </div>

      <ResignationAndFnFCard employee={e} isHr={isHr} onRefresh={() => queryClient.invalidateQueries({ queryKey: ["employee", id] })} />

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
            <Field label="Resignation date" value={employee.resignation_date ?? "—"} />
            <Field label="Last working date" value={employee.last_working_date ?? "—"} />
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

