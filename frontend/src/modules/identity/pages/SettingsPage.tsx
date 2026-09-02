import { useEffect, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { PasswordInput } from "../../../shared/components/PasswordInput";
import { parseApiError, fieldErrorsFromDetails } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { getMyEmployee, listDepartments, updateEmployee, type Employee } from "../../hr/api";
import { changePassword } from "../api";
import { changePasswordSchema } from "../schemas";

/**
 * Page 27 (Spec 14.3): own profile plus change-password, in one page —
 * "Change password, notification preferences" per the spec's own row (no
 * notification-preferences feature exists yet anywhere in the app to
 * expose here, so this page is the profile/security half only).
 *
 * Route 23 (Spec 10.3) is the authority on what's editable, not this page:
 * last_name, personal_email, and phone are the only fields the backend
 * lets an employee change on their own record — enforced in
 * EmployeeService.update_employee, not by which inputs happen to be
 * disabled here. This form only ever sends those three fields, so even if
 * the UI were somehow bypassed, the service layer is still the actual
 * gate (an HR-only field submitted anyway comes back 403, surfaced as-is,
 * never silently accepted or silently dropped).
 */
export function SettingsPage() {
  const { user } = useAuth();
  const { notify } = useToast();
  const queryClient = useQueryClient();

  const employeeQuery = useQuery({
    queryKey: ["employee", "me"],
    queryFn: getMyEmployee,
    enabled: Boolean(user?.employee),
  });
  const employee = employeeQuery.data;

  const departmentsQuery = useQuery({
    queryKey: ["departments", "all-for-settings"],
    queryFn: () => listDepartments({ page: 1, limit: 100 }),
    enabled: Boolean(employee?.department_id),
  });
  const departmentName = departmentsQuery.data?.items.find((d) => d.id === employee?.department_id)?.name;

  return (
    <div>
      <PageHeader title="Settings" breadcrumb="Account" />

      {!user?.employee ? (
        <div className="card mb-6">
          <span className="text-muted">
            This account has no employee record linked — there's no profile to show here.
          </span>
        </div>
      ) : employeeQuery.isLoading ? (
        <div className="row">
          <div className="spinner" />
          <span className="text-muted">Loading…</span>
        </div>
      ) : employeeQuery.isError ? (
        <div className="alert alert-error">{parseApiError(employeeQuery.error).message}</div>
      ) : employee ? (
        <ProfileSection
          employee={employee}
          departmentName={departmentName}
          onSaved={() => queryClient.invalidateQueries({ queryKey: ["employee", "me"] })}
        />
      ) : null}

      <ChangePasswordSection notify={notify} />
    </div>
  );
}

function ProfileSection({
  employee,
  departmentName,
  onSaved,
}: {
  employee: Employee;
  departmentName: string | undefined;
  onSaved: () => void;
}) {
  const { notify } = useToast();
  const [lastName, setLastName] = useState(employee.last_name ?? "");
  const [personalEmail, setPersonalEmail] = useState(employee.personal_email ?? "");
  const [phone, setPhone] = useState(employee.phone ?? "");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setLastName(employee.last_name ?? "");
    setPersonalEmail(employee.personal_email ?? "");
    setPhone(employee.phone ?? "");
  }, [employee]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      // Deliberately only these three keys — matching the backend's own
      // contact-fields allowlist exactly, so there is never a client-sent
      // field the server has to reject (Spec 10.3 route 23).
      await updateEmployee(employee.id, {
        last_name: lastName.trim() || null,
        personal_email: personalEmail.trim() || null,
        phone: phone.trim() || null,
      });
      notify("Profile updated.");
      onSaved();
    } catch (err) {
      setFormError(parseApiError(err).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card stack mb-6" onSubmit={handleSubmit}>
      <h3>My profile</h3>
      {formError && <div className="alert alert-error">{formError}</div>}

      <div className="form-grid">
        <div className="field">
          <label>First name</label>
          <div>{employee.first_name}</div>
          <span className="field-hint">Managed by HR.</span>
        </div>
        <div className="field">
          <label>Employee code</label>
          <div>{employee.employee_code}</div>
        </div>
        <div className="field">
          <label>Work email</label>
          <div>{employee.email}</div>
          <span className="field-hint">Managed by HR.</span>
        </div>
        <div className="field">
          <label>Position</label>
          <div>{employee.position ?? "—"}</div>
        </div>
        <div className="field">
          <label>Level</label>
          <div>{employee.level ?? "—"}</div>
        </div>
        <div className="field">
          <label>Department</label>
          <div>{departmentName ?? "—"}</div>
        </div>
        <div className="field">
          <label>Employment type</label>
          <div>{employee.employment_type.replace("_", " ")}</div>
        </div>
        <div className="field">
          <label>Hire date</label>
          <div>{employee.hire_date}</div>
        </div>
      </div>
      <p className="field-hint mt-0 mb-0">
        The fields above are managed by HR — contact them if any of this needs to change.
      </p>

      <div className="form-grid">
        <div className="field">
          <label htmlFor="last_name">Last name</label>
          <input id="last_name" value={lastName} onChange={(e) => setLastName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="personal_email">Personal email</label>
          <input
            id="personal_email"
            type="email"
            value={personalEmail}
            onChange={(e) => setPersonalEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="phone">Phone</label>
          <input id="phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
      </div>

      <div className="row">
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Saving…" : "Save changes"}
        </button>
      </div>
    </form>
  );
}

function ChangePasswordSection({ notify }: { notify: (message: string, kind?: "success" | "error") => void }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setFieldErrors({});

    const parsed = changePasswordSchema.safeParse({
      current_password: currentPassword,
      new_password: newPassword,
    });
    if (!parsed.success) {
      const errors: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path[0];
        if (typeof key === "string") errors[key] = issue.message;
      }
      setFieldErrors(errors);
      return;
    }

    setSubmitting(true);
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword });
      notify("Password changed. Your other sessions have been signed out.");
      setCurrentPassword("");
      setNewPassword("");
    } catch (err) {
      const parsedErr = parseApiError(err);
      setFormError(parsedErr.message);
      const fromServer = fieldErrorsFromDetails(parsedErr.details);
      if (Object.keys(fromServer).length > 0) setFieldErrors(fromServer);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card stack" onSubmit={handleSubmit}>
      <h3>Change password</h3>
      <p className="text-muted mt-0 mb-0">
        Changing your password signs you out of every other device and browser — this one included,
        the next time your session needs to refresh.
      </p>

      {formError && <div className="alert alert-error">{formError}</div>}

      <PasswordInput
        id="current_password"
        label="Current password"
        value={currentPassword}
        onChange={setCurrentPassword}
        autoComplete="current-password"
        error={fieldErrors.current_password}
      />
      <PasswordInput
        id="new_password"
        label="New password"
        value={newPassword}
        onChange={setNewPassword}
        autoComplete="new-password"
        error={fieldErrors.new_password}
      />

      <div className="row">
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Changing…" : "Change password"}
        </button>
      </div>
    </form>
  );
}
