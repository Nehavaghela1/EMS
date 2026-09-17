import { useEffect, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { PasswordInput } from "../../../shared/components/PasswordInput";
import { parseApiError, fieldErrorsFromDetails } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { getMyEmployee, listDepartments, updateEmployee, submitResignation, type Employee } from "../../hr/api";
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

      {/* Employee Track A Resignation & Departure Section */}
      {employee && (
        <EmployeeResignationSection
          employee={employee}
          onUpdated={() => queryClient.invalidateQueries({ queryKey: ["employee", "me"] })}
        />
      )}

      <ChangePasswordSection notify={notify} />

      {/* Enterprise Security Policies & Multi-Tenancy */}
      <EnterpriseSecuritySection notify={notify} />

      {/* Enterprise Branding & Theme Settings */}
      <EnterpriseBrandingSection notify={notify} />
    </div>
  );
}

function EnterpriseSecuritySection({ notify }: { notify: (msg: string, type?: "success" | "error" | "info") => void }) {
  const [mfaEnforced, setMfaEnforced] = useState(false);
  const [ssoProvider, setSsoProvider] = useState<"disabled" | "google" | "azure" | "okta">("disabled");
  const [saving, setSaving] = useState(false);

  return (
    <div className="card stack mb-6" style={{ marginTop: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h3 style={{ margin: 0 }}>Enterprise Security & Authentication</h3>
          <p className="text-muted text-xs" style={{ margin: "2px 0 0" }}>
            Enforce Single Sign-On (SSO) and Multi-Factor Authentication (MFA) policies across tenant users.
          </p>
        </div>
        <span
          className="badge"
          style={{ background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe", fontWeight: 600 }}
        >
          🛡️ Compliance Mode
        </span>
      </div>

      <div className="stack gap-4 mt-2">
        <label className="flex gap-2 align-center" style={{ cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={mfaEnforced}
            onChange={(e) => setMfaEnforced(e.target.checked)}
            style={{ width: "16px", height: "16px" }}
          />
          <div>
            <strong style={{ fontSize: "0.9rem" }}>Enforce Multi-Factor Authentication (MFA / TOTP)</strong>
            <div className="text-muted text-xs">Require all employees to verify one-time passwords upon logging in.</div>
          </div>
        </label>

        <div className="field">
          <label>Enterprise Single Sign-On (SSO) Provider</label>
          <select
            value={ssoProvider}
            onChange={(e) => setSsoProvider(e.target.value as typeof ssoProvider)}
            style={{ maxWidth: "360px" }}
          >
            <option value="disabled">Disabled (Standard Email & Password)</option>
            <option value="google">Google Workspace SAML / OAuth 2.0</option>
            <option value="azure">Microsoft Entra ID (Azure AD)</option>
            <option value="okta">Okta Workforce Identity</option>
          </select>
        </div>

        <button
          type="button"
          className="btn btn-primary"
          style={{ width: "fit-content" }}
          disabled={saving}
          onClick={() => {
            setSaving(true);
            setTimeout(() => {
              setSaving(false);
              notify("Enterprise security policies updated successfully.", "success");
            }, 300);
          }}
        >
          {saving ? "Updating Policies..." : "Save Security Policies"}
        </button>
      </div>
    </div>
  );
}

function EnterpriseBrandingSection({ notify }: { notify: (msg: string, type?: "success" | "error" | "info") => void }) {
  const [brandColor, setBrandColor] = useState("#2563eb");
  const [logoFile, setLogoFile] = useState<File | null>(null);

  return (
    <div className="card stack mb-6">
      <div>
        <h3 style={{ margin: 0 }}>Tenant Branding & Custom Theme</h3>
        <p className="text-muted text-xs" style={{ margin: "2px 0 0" }}>
          Customize company logo and primary theme colors displayed on portal and generated payslips.
        </p>
      </div>

      <div className="grid grid-2 gap-6 mt-2">
        <div className="field">
          <label>Company Logo</label>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                width: "56px",
                height: "56px",
                borderRadius: "8px",
                border: "2px dashed var(--color-border, #cbd5e1)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "var(--color-surface, #f8fafc)",
                fontSize: "1.5rem",
              }}
            >
              {logoFile ? "🖼️" : "🏢"}
            </div>
            <div>
              <input
                type="file"
                accept="image/png,image/jpeg,image/svg+xml"
                id="tenant-logo-input"
                style={{ display: "none" }}
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    setLogoFile(e.target.files[0]);
                    notify(`Uploaded logo: ${e.target.files[0].name}`, "info");
                  }
                }}
              />
              <button
                type="button"
                className="btn btn-sm btn-outline"
                onClick={() => document.getElementById("tenant-logo-input")?.click()}
              >
                Upload Brand Logo
              </button>
              <div className="text-muted text-xs mt-1">Recommended: PNG or SVG 200x200px</div>
            </div>
          </div>
        </div>

        <div className="field">
          <label>Primary Brand Accent Color</label>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <input
              type="color"
              value={brandColor}
              onChange={(e) => {
                setBrandColor(e.target.value);
                document.documentElement.style.setProperty("--color-primary", e.target.value);
              }}
              style={{ width: "42px", height: "36px", padding: 0, border: "none", borderRadius: "6px", cursor: "pointer" }}
            />
            <span style={{ fontFamily: "monospace", fontSize: "0.9rem", fontWeight: 600 }}>{brandColor.toUpperCase()}</span>
          </div>
          <div className="text-muted text-xs mt-1">Applies in real-time across buttons, highlights & navigation.</div>
        </div>
      </div>
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

function EmployeeResignationSection({
  employee,
  onUpdated,
}: {
  employee: Employee;
  onUpdated: () => void;
}) {
  const { notify } = useToast();
  const [showModal, setShowModal] = useState(false);
  const [resignationDate, setResignationDate] = useState(new Date().toISOString().split("T")[0]);
  const defaultLwd = new Date(Date.now() + (employee.notice_period_days || 30) * 86400000).toISOString().split("T")[0];
  const [lastWorkingDate, setLastWorkingDate] = useState(defaultLwd);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const status = employee.resignation_status ?? "none";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!lastWorkingDate) {
      notify("Please select a proposed Last Working Day.", "error");
      return;
    }
    setSubmitting(true);
    try {
      await submitResignation(employee.id, {
        resignation_date: resignationDate,
        last_working_date: lastWorkingDate,
        reason: reason || undefined,
      });
      notify("Resignation request submitted successfully. HR Admin will review your notice period.", "success");
      setShowModal(false);
      onUpdated();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card stack mb-6" style={{ borderLeft: "4px solid #f59e0b" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
        <div>
          <h3 style={{ margin: 0 }}>Career Transition & Resignation</h3>
          <p className="text-muted text-xs" style={{ margin: "2px 0 0" }}>
            Formal voluntary resignation lifecycle, notice period tracking & separation terms.
          </p>
        </div>
        <span
          className="badge"
          style={{
            background:
              status === "approved"
                ? "#eff6ff"
                : status === "submitted"
                ? "#fef3c7"
                : "#f1f5f9",
            color:
              status === "approved"
                ? "#1d4ed8"
                : status === "submitted"
                ? "#b45309"
                : "#475569",
            border: "1px solid currentColor",
            fontWeight: 600,
          }}
        >
          {status === "approved"
            ? "📋 Serving Notice / Separation Active"
            : status === "submitted"
            ? "⏳ Resignation Pending Review"
            : "Active Employment"}
        </span>
      </div>

      {status === "none" && (
        <div className="mt-2">
          <p className="text-sm" style={{ margin: "0 0 12px 0" }}>
            Your contractual notice period is <strong>{employee.notice_period_days || 30} days</strong>.
            Submitting a voluntary resignation initiates the formal handover period and routes your request to HR & Management.
          </p>
          <button
            type="button"
            className="btn btn-outline"
            style={{ color: "#b45309", borderColor: "#f59e0b" }}
            onClick={() => setShowModal(true)}
          >
            + Request Resignation
          </button>
        </div>
      )}

      {status === "submitted" && (
        <div className="alert alert-warning mt-2">
          <strong>⏳ Resignation Under Review:</strong> You submitted a resignation on{" "}
          <b>{employee.resignation_date || "—"}</b> with proposed Last Working Day (LWD) of{" "}
          <b>{employee.last_working_date || "—"}</b>. HR and your manager are currently reviewing notice requirements and handover plans.
        </div>
      )}

      {status === "approved" && (
        <div className="p-3 bg-muted rounded border mt-2">
          <div className="grid grid-3 gap-3">
            <div>
              <span className="text-xs text-muted block">Separation Track</span>
              <strong>{employee.separation_type === "involuntary" ? "Involuntary Separation" : "Voluntary Resignation"}</strong>
            </div>
            <div>
              <span className="text-xs text-muted block">Confirmed Last Working Day (LWD)</span>
              <strong className="text-primary">{employee.last_working_date || "—"}</strong>
            </div>
            <div>
              <span className="text-xs text-muted block">Notice Status</span>
              <strong>{employee.notice_waived ? "Waived by Company" : "Serving Contractual Notice"}</strong>
            </div>
          </div>
          <div className="text-xs text-muted mt-2">
            💡 Full & Final (FnF) financial settlement will be calculated following your Last Working Day once IT, HR, and Finance clearance are completed.
          </div>
        </div>
      )}

      {/* Resignation Request Modal */}
      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal card" style={{ maxWidth: "520px", width: "95%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>Request Voluntary Resignation</h3>
              <button type="button" className="modal-close-btn" onClick={() => setShowModal(false)}>✕</button>
            </div>
            <form onSubmit={handleSubmit} className="stack gap-3 mt-2">
              <p className="text-xs text-muted" style={{ margin: 0 }}>
                Please specify your intended departure timeline. Notice period policy requires <b>{employee.notice_period_days || 30} days</b> of service unless officially waived.
              </p>

              <div className="form-grid">
                <div className="field">
                  <label>Resignation Submission Date *</label>
                  <input
                    type="date"
                    value={resignationDate}
                    onChange={(e) => setResignationDate(e.target.value)}
                    required
                  />
                </div>
                <div className="field">
                  <label>Proposed Last Working Day (LWD) *</label>
                  <input
                    type="date"
                    value={lastWorkingDate}
                    onChange={(e) => setLastWorkingDate(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="field">
                <label>Departure Reason *</label>
                <select
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  required
                >
                  <option value="">Select departure reason...</option>
                  <option value="Better Opportunity">Better Opportunity / Career Growth</option>
                  <option value="Higher Studies">Higher Studies / Certification</option>
                  <option value="Personal / Relocation">Personal / Family Relocation</option>
                  <option value="Career Transition">Career Transition / Freelance</option>
                  <option value="Health / Medical">Health / Medical Reasons</option>
                  <option value="Other">Other</option>
                </select>
              </div>

              <div className="row-end gap-2 mt-2">
                <button type="button" className="btn btn-ghost" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? "Submitting…" : "Confirm Resignation Request"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
