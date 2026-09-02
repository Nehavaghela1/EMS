import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog";
import { parseApiError } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { deactivateEmployee, getEmployee, reactivateEmployee } from "../api";

interface InviteState {
  invite?: { activation_token: string; expires_at: string };
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

  const employeeQuery = useQuery({
    queryKey: ["employee", id],
    queryFn: () => getEmployee(id as string),
    enabled: Boolean(id),
  });

  const invite = (location.state as InviteState | null)?.invite;
  const isHr = user?.role === "hr_admin";

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
    <div>
      <PageHeader
        title={`${e.first_name}${e.last_name ? " " + e.last_name : ""}`}
        breadcrumb="HR / Employees"
        action={
          isHr && (
            <div className="row">
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
          Invite created — activation token (shown once, share it with the employee):{" "}
          <code>{invite.activation_token}</code>, expires{" "}
          {new Date(invite.expires_at).toLocaleString()}.
        </div>
      )}

      <div className="card">
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
          <Field label="Notice period" value={`${e.notice_period_days} days`} />
          <Field label="Invitation status" value={e.invitation_status.replace("_", " ")} />
        </div>
      </div>

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
