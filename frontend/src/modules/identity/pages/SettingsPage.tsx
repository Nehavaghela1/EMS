import { useEffect, useState, useRef, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { PasswordInput } from "../../../shared/components/PasswordInput";
import { parseApiError, fieldErrorsFromDetails } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { getMyEmployee, listDepartments, updateEmployee, submitResignation, listEmployees, type Employee } from "../../hr/api";
import { changePassword, listAdministrators, updateUserRole, getMyCompany, updateMyCompany, type AdminUser } from "../api";
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

      {/* ── Admins & Access Control (Owner only) ─────────────── */}
      {user?.role === "owner" && <AdminDelegationSection />}

      {/* Profile Section: If linked employee exists, show full employee profile; if owner without employee record, show Owner Profile */}
      {user?.employee ? (
        employeeQuery.isLoading ? (
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
            onSaved={() => {
              queryClient.invalidateQueries({ queryKey: ["employee", "me"] });
              queryClient.invalidateQueries({ queryKey: ["company", "me"] });
            }}
          />
        ) : null
      ) : user?.role === "owner" ? (
        <OwnerProfileSection user={user} notify={notify} />
      ) : (
        <div className="card mb-6">
          <span className="text-muted">
            This account has no employee record linked — there's no profile to show here.
          </span>
        </div>
      )}

      {/* Employee Track A Resignation & Departure Section (Only for standard employees, not workspace owners) */}
      {employee && user?.role !== "owner" && (
        <EmployeeResignationSection
          employee={employee}
          onUpdated={() => queryClient.invalidateQueries({ queryKey: ["employee", "me"] })}
        />
      )}

      <ChangePasswordSection notify={notify} />

      {/* Enterprise Branding & Theme Settings (Owner, HR Admin, Super Admin only) */}
      {(user?.role === "owner" || user?.role === "hr_admin" || user?.role === "super_admin") && (
        <EnterpriseBrandingSection notify={notify} />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// AdminDelegationSection — Zoho-style admin management hub (owner-only)
// ─────────────────────────────────────────────────────────────────────────────
function AdminDelegationSection() {
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [empSearch, setEmpSearch] = useState("");
  const [selectedEmp, setSelectedEmp] = useState<Employee | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState<AdminUser | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [revoking, setRevoking] = useState(false);

  const adminQuery = useQuery({
    queryKey: ["administrators"],
    queryFn: listAdministrators,
  });

  const empQuery = useQuery({
    queryKey: ["employees-search-admin", empSearch],
    queryFn: () => listEmployees({ q: empSearch || undefined, page: 1, limit: 10 }),
    enabled: showModal,
    placeholderData: (prev) => prev,
  });

  async function handlePromote() {
    if (!selectedEmp?.user_id) {
      notify("Selected employee has no linked user account.", "error");
      return;
    }
    setPromoting(true);
    try {
      await updateUserRole(selectedEmp.user_id, "hr_admin");
      await queryClient.invalidateQueries({ queryKey: ["administrators"] });
      notify(`${selectedEmp.first_name} promoted to HR Admin.`, "success");
      setShowModal(false);
      setSelectedEmp(null);
      setEmpSearch("");
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setPromoting(false);
    }
  }

  async function handleRevoke(admin: AdminUser) {
    setRevoking(true);
    try {
      await updateUserRole(admin.id, "employee");
      // Drop the row at once, then refetch to confirm against the server.
      queryClient.setQueryData<AdminUser[]>(["administrators"], (prev) =>
        (prev ?? []).filter((a) => a.id !== admin.id),
      );
      await queryClient.invalidateQueries({ queryKey: ["administrators"] });
      notify(`${admin.first_name ?? admin.email}'s admin access revoked.`, "success");
      setConfirmRevoke(null);
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setRevoking(false);
    }
  }

  const admins = adminQuery.data ?? [];

  return (
    <>
      {/* ── Main Card ─────────────────────────── */}
      <div
        style={{
          background: "#ffffff",
          borderRadius: "16px",
          border: "1px solid #e2e8f0",
          boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
          marginBottom: "1.5rem",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "20px 24px 16px",
            borderBottom: "1px solid #f1f5f9",
            background: "linear-gradient(135deg, #f8faff 0%, #f0f4ff 100%)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                width: 40, height: 40, borderRadius: "10px",
                background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "1.1rem",
              }}
            >
              👑
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700, color: "#0f172a" }}>
                Administrators & Access Control
              </h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.78rem", color: "#64748b" }}>
                Manage who can configure HR, run payroll, and govern the workspace
              </p>
            </div>
          </div>
          <button
            id="btn-assign-hr-admin"
            onClick={() => setShowModal(true)}
            style={{
              display: "flex", alignItems: "center", gap: "6px",
              padding: "8px 16px", borderRadius: "8px", border: "none",
              background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
              color: "#fff", fontWeight: 600, fontSize: "0.82rem",
              cursor: "pointer", boxShadow: "0 2px 8px rgba(99,102,241,0.3)",
              transition: "all 0.2s",
            }}
          >
            <span style={{ fontSize: "1rem" }}>+</span> Assign HR Admin
          </button>
        </div>

        {/* Zoho-style data table */}
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
            <thead>
              <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                {["Administrator", "Email", "Designation", "Member Since", "Role", "Action"].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "10px 16px", textAlign: "left", fontWeight: 700,
                      color: "#64748b", fontSize: "0.74rem", textTransform: "uppercase",
                      letterSpacing: "0.06em", whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {adminQuery.isLoading ? (
                <tr>
                  <td colSpan={6} style={{ padding: "28px 16px", textAlign: "center", color: "#94a3b8" }}>
                    Loading administrators…
                  </td>
                </tr>
              ) : admins.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ padding: "28px 16px", textAlign: "center", color: "#94a3b8" }}>
                    No administrators found.
                  </td>
                </tr>
              ) : (
                admins.map((admin, i) => {
                  const displayName = admin.first_name
                    ? `${admin.first_name}${admin.last_name ? " " + admin.last_name : ""}`
                    : admin.email;
                  const initials = admin.first_name
                    ? `${admin.first_name[0]}${admin.last_name?.[0] ?? ""}`.toUpperCase()
                    : admin.email[0].toUpperCase();
                  const isOwner = admin.role === "owner";
                  const memberSince = admin.hire_date
                    ? new Date(admin.hire_date).toLocaleDateString("en-IN", { day: "2-digit", month: "2-digit", year: "numeric" })
                    : "—";

                  return (
                    <tr
                      key={admin.id}
                      style={{
                        borderBottom: i < admins.length - 1 ? "1px solid #f1f5f9" : "none",
                        transition: "background 0.12s",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "#fafbff")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                    >
                      {/* Administrator */}
                      <td style={{ padding: "14px 16px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          <div
                            style={{
                              width: 32, height: 32, borderRadius: "50%", flexShrink: 0,
                              background: isOwner
                                ? "linear-gradient(135deg, #f59e0b, #d97706)"
                                : "linear-gradient(135deg, #6366f1, #8b5cf6)",
                              display: "flex", alignItems: "center", justifyContent: "center",
                              fontWeight: 700, fontSize: "0.72rem", color: "#fff",
                            }}
                          >
                            {initials}
                          </div>
                          <span style={{ fontWeight: 600, color: "#0f172a" }}>{displayName}</span>
                        </div>
                      </td>

                      {/* Email */}
                      <td style={{ padding: "14px 16px", color: "#475569" }}>{admin.email}</td>

                      {/* Designation */}
                      <td style={{ padding: "14px 16px", color: "#475569" }}>
                        {admin.position ?? <span style={{ color: "#94a3b8" }}>—</span>}
                      </td>

                      {/* Member Since */}
                      <td style={{ padding: "14px 16px", color: "#475569", whiteSpace: "nowrap" }}>
                        {memberSince}
                      </td>

                      {/* Role badge */}
                      <td style={{ padding: "14px 16px" }}>
                        <span
                          style={{
                            padding: "3px 10px", borderRadius: "20px", fontSize: "0.69rem",
                            fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em",
                            whiteSpace: "nowrap",
                            ...(isOwner
                              ? { background: "#fffbeb", color: "#b45309", border: "1px solid #fcd34d" }
                              : { background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }),
                          }}
                        >
                          {isOwner ? "👑 Primary Owner" : "🛡️ HR Admin"}
                        </span>
                      </td>

                      {/* Action */}
                      <td style={{ padding: "14px 16px" }}>
                        {!isOwner ? (
                          <button
                            onClick={() => setConfirmRevoke(admin)}
                            style={{
                              padding: "5px 12px", borderRadius: "6px",
                              border: "1px solid #fecaca", background: "#fff5f5",
                              color: "#dc2626", fontSize: "0.75rem", fontWeight: 600,
                              cursor: "pointer", whiteSpace: "nowrap", transition: "all 0.15s",
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.background = "#fee2e2"; }}
                            onMouseLeave={(e) => { e.currentTarget.style.background = "#fff5f5"; }}
                          >
                            Revoke Admin Access
                          </button>
                        ) : (
                          <span style={{ color: "#94a3b8", fontSize: "0.75rem" }}>Primary Owner</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Assign HR Admin Modal ─────────────── */}
      {showModal && (
        <div
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            backgroundColor: "rgba(15, 23, 42, 0.7)",
            backdropFilter: "blur(4px)",
            display: "flex", alignItems: "center", justifyContent: "center", padding: "16px",
          }}
          onClick={() => { setShowModal(false); setSelectedEmp(null); setEmpSearch(""); }}
        >
          <div
            style={{
              background: "#ffffff", borderRadius: "16px", width: "100%", maxWidth: "480px",
              boxShadow: "0 25px 50px -12px rgba(0,0,0,0.35)", border: "1px solid #e2e8f0",
              overflow: "hidden",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div
              style={{
                padding: "20px 24px", borderBottom: "1px solid #f1f5f9",
                background: "linear-gradient(135deg, #f8faff 0%, #f0f4ff 100%)",
                display: "flex", alignItems: "center", justifyContent: "space-between",
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700, color: "#0f172a" }}>
                  Assign HR Admin
                </h3>
                <p style={{ margin: "2px 0 0", fontSize: "0.78rem", color: "#64748b" }}>
                  Search and select an employee to grant HR Admin access
                </p>
              </div>
              <button
                onClick={() => { setShowModal(false); setSelectedEmp(null); setEmpSearch(""); }}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1.2rem", color: "#64748b", padding: "4px" }}
              >
                ✕
              </button>
            </div>

            {/* Modal Body */}
            <div style={{ padding: "20px 24px" }}>
              <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#374151", display: "block", marginBottom: "6px" }}>
                Search Employee
              </label>
              <input
                id="admin-emp-search"
                type="text"
                placeholder="Type name or email…"
                value={empSearch}
                onChange={(e) => { setEmpSearch(e.target.value); setSelectedEmp(null); }}
                style={{
                  width: "100%", padding: "10px 12px", borderRadius: "8px",
                  border: "1px solid #e2e8f0", fontSize: "0.875rem", outline: "none",
                  boxSizing: "border-box",
                }}
                autoFocus
              />

              {/* Results */}
              {empQuery.data && empQuery.data.items.length > 0 && !selectedEmp && (
                <div
                  style={{
                    marginTop: "8px", borderRadius: "8px", border: "1px solid #e2e8f0",
                    overflow: "hidden", maxHeight: "200px", overflowY: "auto",
                  }}
                >
                  {empQuery.data.items
                    .filter((e) => !admins.find((a) => a.employee_id === e.id))
                    .map((emp) => (
                      <button
                        key={emp.id}
                        type="button"
                        onClick={() => { setSelectedEmp(emp); setEmpSearch(`${emp.first_name} ${emp.last_name ?? ""}`); }}
                        style={{
                          width: "100%", textAlign: "left", padding: "10px 14px",
                          border: "none", borderBottom: "1px solid #f8fafc",
                          background: "#fff", cursor: "pointer", fontSize: "0.875rem",
                          display: "flex", alignItems: "center", gap: "10px",
                          transition: "background 0.1s",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "#f8fafc")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "#fff")}
                      >
                        <div
                          style={{
                            width: 30, height: 30, borderRadius: "50%",
                            background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
                            color: "#fff", fontWeight: 700, fontSize: "0.75rem",
                            display: "flex", alignItems: "center", justifyContent: "center",
                            flexShrink: 0,
                          }}
                        >
                          {emp.first_name[0]}{emp.last_name?.[0] ?? ""}
                        </div>
                        <div>
                          <div style={{ fontWeight: 600, color: "#0f172a" }}>
                            {emp.first_name} {emp.last_name ?? ""}
                          </div>
                          <div style={{ fontSize: "0.75rem", color: "#64748b" }}>{emp.email}</div>
                        </div>
                      </button>
                    ))}
                </div>
              )}

              {/* Selection confirmation */}
              {selectedEmp && (
                <div
                  style={{
                    marginTop: "12px", padding: "12px 14px", borderRadius: "10px",
                    background: "#f0fdf4", border: "1px solid #bbf7d0",
                    display: "flex", alignItems: "center", gap: "10px",
                  }}
                >
                  <span style={{ fontSize: "1.2rem" }}>✅</span>
                  <div>
                    <p style={{ margin: 0, fontWeight: 600, fontSize: "0.875rem", color: "#166534" }}>
                      {selectedEmp.first_name} {selectedEmp.last_name ?? ""}
                    </p>
                    <p style={{ margin: "1px 0 0", fontSize: "0.75rem", color: "#15803d" }}>
                      Will be granted <strong>HR Admin</strong> privileges
                    </p>
                  </div>
                </div>
              )}

              {/* Warning */}
              <div
                style={{
                  marginTop: "16px", padding: "10px 12px", borderRadius: "8px",
                  background: "#fffbeb", border: "1px solid #fde68a",
                  fontSize: "0.78rem", color: "#92400e",
                }}
              >
                ⚠️ HR Admins can view all employee records, configure payroll, and manage leave policies.
              </div>
            </div>

            {/* Modal Footer */}
            <div
              style={{
                padding: "16px 24px", borderTop: "1px solid #f1f5f9",
                background: "#fafafa", display: "flex", justifyContent: "flex-end", gap: "8px",
              }}
            >
              <button
                onClick={() => { setShowModal(false); setSelectedEmp(null); setEmpSearch(""); }}
                style={{
                  padding: "8px 18px", borderRadius: "8px", border: "1px solid #e2e8f0",
                  background: "#fff", color: "#64748b", fontWeight: 600,
                  fontSize: "0.85rem", cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                id="btn-confirm-promote"
                onClick={handlePromote}
                disabled={!selectedEmp || promoting}
                style={{
                  padding: "8px 18px", borderRadius: "8px", border: "none",
                  background: selectedEmp ? "linear-gradient(135deg, #6366f1, #8b5cf6)" : "#e2e8f0",
                  color: selectedEmp ? "#fff" : "#94a3b8",
                  fontWeight: 600, fontSize: "0.85rem",
                  cursor: selectedEmp ? "pointer" : "not-allowed",
                  boxShadow: selectedEmp ? "0 2px 8px rgba(99,102,241,0.3)" : "none",
                }}
              >
                {promoting ? "Granting…" : "Grant HR Admin Access"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Confirm Revoke Modal ─────────────── */}
      {confirmRevoke && (
        <div
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            backgroundColor: "rgba(15, 23, 42, 0.7)",
            backdropFilter: "blur(4px)",
            display: "flex", alignItems: "center", justifyContent: "center", padding: "16px",
          }}
          onClick={() => setConfirmRevoke(null)}
        >
          <div
            style={{
              background: "#ffffff", borderRadius: "16px", width: "100%", maxWidth: "420px",
              boxShadow: "0 25px 50px -12px rgba(0,0,0,0.35)", border: "1px solid #e2e8f0",
              padding: "28px 28px 24px",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ textAlign: "center", marginBottom: "20px" }}>
              <div style={{ fontSize: "2.5rem", marginBottom: "12px" }}>🔒</div>
              <h3 style={{ margin: "0 0 6px", fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>
                Revoke Admin Access?
              </h3>
              <p style={{ margin: 0, fontSize: "0.85rem", color: "#64748b", lineHeight: 1.5 }}>
                <strong style={{ color: "#0f172a" }}>
                  {confirmRevoke.first_name
                    ? `${confirmRevoke.first_name} ${confirmRevoke.last_name ?? ""}`
                    : confirmRevoke.email}
                </strong>{" "}
                will lose all HR Admin privileges and revert to a regular employee.
              </p>
            </div>
            <div style={{ display: "flex", gap: "10px", justifyContent: "center" }}>
              <button
                onClick={() => setConfirmRevoke(null)}
                style={{
                  padding: "9px 22px", borderRadius: "8px", border: "1px solid #e2e8f0",
                  background: "#fff", color: "#64748b", fontWeight: 600,
                  fontSize: "0.875rem", cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                id="btn-confirm-revoke"
                onClick={() => handleRevoke(confirmRevoke)}
                disabled={revoking}
                style={{
                  padding: "9px 22px", borderRadius: "8px", border: "none",
                  background: "linear-gradient(135deg, #dc2626, #b91c1c)",
                  color: "#fff", fontWeight: 600, fontSize: "0.875rem",
                  cursor: revoking ? "not-allowed" : "pointer",
                  boxShadow: "0 2px 8px rgba(220,38,38,0.3)",
                }}
              >
                {revoking ? "Revoking…" : "Yes, Revoke Access"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function EnterpriseBrandingSection({ notify }: { notify: (msg: string, type?: "success" | "error" | "info") => void }) {
  const queryClient = useQueryClient();
  const [brandColor, setBrandColor] = useState("#2563eb");
  const [logoPreview, setLogoPreview] = useState<string | null>(null);
  const [logoWidth, setLogoWidth] = useState<number>(140);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getMyCompany().then((comp) => {
      setLogoPreview(comp.logo_url || null);
      if (comp.brand_color) {
        setBrandColor(comp.brand_color);
        document.documentElement.style.setProperty("--color-primary", comp.brand_color);
      }
    }).catch(() => {});
    const savedWidth = localStorage.getItem("ems_brand_logo_width");
    if (savedWidth) setLogoWidth(Number(savedWidth));
  }, []);

  async function handleSaveBranding() {
    setSaving(true);
    try {
      await updateMyCompany({
        brand_color: brandColor,
        logo_url: logoPreview !== undefined ? logoPreview : null,
      });
      localStorage.setItem("ems_brand_logo_width", String(logoWidth));
      document.documentElement.style.setProperty("--color-primary", brandColor);
      notify("Branding preferences and accent color saved successfully.", "success");
      await queryClient.invalidateQueries({ queryKey: ["company", "me"] });
      await queryClient.invalidateQueries({ queryKey: ["user-workspaces"] });
    } catch (err) {
      notify(parseApiError(err).message || "Failed to save branding preferences", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card stack mb-6">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h3 style={{ margin: 0 }}>Company Branding & Theme Customization</h3>
          <p className="text-muted text-xs" style={{ margin: "2px 0 0" }}>
            Customize your company logo, top workspace branding, payslip layout, and primary theme colors.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={handleSaveBranding}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save Branding"}
        </button>
      </div>

      <div className="grid grid-2 gap-6 mt-2">
        <div className="field">
          <label>Company Brand Logo (Workspace & Payslips)</label>
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <div
              style={{
                width: "80px",
                height: "64px",
                borderRadius: "8px",
                border: "1px solid var(--color-border, #cbd5e1)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "var(--color-surface, #ffffff)",
                overflow: "hidden",
                padding: "4px",
              }}
            >
              {logoPreview ? (
                <img
                  src={logoPreview}
                  alt="Company Logo"
                  style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }}
                />
              ) : (
                <span style={{ fontSize: "1.75rem" }}>🏢</span>
              )}
            </div>
            <div>
              <input
                type="file"
                accept="image/png,image/jpeg,image/jpg,image/webp"
                id="tenant-logo-input"
                style={{ display: "none" }}
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    const file = e.target.files[0];
                    e.target.value = "";
                    const allowedTypes = ["image/png", "image/jpeg", "image/jpg", "image/webp"];
                    if (!allowedTypes.includes(file.type)) {
                      notify("Logo must be a PNG, JPEG or WebP image.", "error");
                      return;
                    }
                    if (file.size > 500 * 1024) {
                      notify("Logo must be smaller than 500 KB.", "error");
                      return;
                    }
                    const reader = new FileReader();
                    reader.onload = (ev) => {
                      const dataUrl = ev.target?.result as string;
                      setLogoPreview(dataUrl);
                      notify(`Logo loaded: ${file.name}. Click "Save Branding" to apply.`, "info");
                    };
                    reader.readAsDataURL(file);
                  }
                }}
              />
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  type="button"
                  className="btn btn-sm btn-outline"
                  onClick={() => document.getElementById("tenant-logo-input")?.click()}
                >
                  Upload Brand Logo
                </button>
                {logoPreview && (
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={() => {
                      setLogoPreview(null);
                      notify("Logo cleared. Save branding to apply changes.", "info");
                    }}
                    style={{ color: "#dc2626" }}
                  >
                    Remove
                  </button>
                )}
              </div>
              <div className="text-muted text-xs mt-1">Accepts PNG, JPG, or WebP. Displays in top navigation header and on payslip PDFs.</div>
            </div>
          </div>

          {/* Logo sizing controls */}
          {logoPreview && (
            <div style={{ marginTop: "14px", background: "#f8fafc", padding: "10px 14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                <label style={{ fontSize: "0.78rem", fontWeight: 600, color: "#334155", margin: 0 }}>
                  Payslip Logo Width: <strong>{logoWidth}px</strong>
                </label>
                <span className="text-muted text-xs">(Adjust to fit your logo aspect ratio)</span>
              </div>
              <input
                type="range"
                min="80"
                max="260"
                step="5"
                value={logoWidth}
                onChange={(e) => setLogoWidth(Number(e.target.value))}
                style={{ width: "100%", accentColor: "var(--color-primary, #2563eb)", cursor: "pointer" }}
              />
            </div>
          )}
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

function OwnerProfileSection({
  user,
  notify,
}: {
  user: { email: string; company_name?: string | null; company_code?: string | null };
  notify: (msg: string, type?: "success" | "error" | "info") => void;
}) {
  const queryClient = useQueryClient();
  const companyQuery = useQuery({
    queryKey: ["company", "me"],
    queryFn: getMyCompany,
  });

  const company = companyQuery.data;
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (company) {
      setPhone(company.phone ?? "");
      setAddress(company.address ?? "");
    }
  }, [company]);

  async function handleSaveContact(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await updateMyCompany({
        phone: phone.trim() || undefined,
        address: address.trim() || undefined,
      });
      notify("Owner profile & contact details updated.", "success");
      queryClient.invalidateQueries({ queryKey: ["company", "me"] });
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card stack mb-6" style={{ background: "#ffffff", borderRadius: "12px", border: "1px solid #e2e8f0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #f1f5f9", paddingBottom: "12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: "50%",
              background: "linear-gradient(135deg, #f59e0b, #d97706)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 800,
              fontSize: "1.1rem",
              color: "#fff",
              boxShadow: "0 2px 8px rgba(245, 158, 11, 0.3)",
            }}
          >
            {user.email[0].toUpperCase()}
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <h3 style={{ margin: 0, fontSize: "1.05rem", fontWeight: 700, color: "#0f172a" }}>My Profile</h3>
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                  padding: "2px 8px",
                  borderRadius: "12px",
                  fontSize: "0.72rem",
                  fontWeight: 700,
                  background: "#fffbeb",
                  color: "#b45309",
                  border: "1px solid #fde68a",
                }}
              >
                👑 Primary Owner
              </span>
            </div>
            <p className="text-muted text-xs" style={{ margin: "2px 0 0" }}>
              Workspace Owner & Organization Administrator
            </p>
          </div>
        </div>
      </div>

      <div className="form-grid" style={{ marginTop: "8px" }}>
        <div className="field">
          <label>Sign-in / Primary Email</label>
          <div style={{ fontWeight: 600, color: "#0f172a", fontSize: "0.9rem" }}>{user.email}</div>
          <span className="field-hint">Primary account identity for workspace management.</span>
        </div>
        <div className="field">
          <label>System Role</label>
          <div style={{ fontWeight: 600, color: "#0f172a", fontSize: "0.9rem" }}>Workspace Owner (Superuser)</div>
          <span className="field-hint">Full administrative rights over organization & billing.</span>
        </div>
        <div className="field">
          <label>Company / Organization</label>
          <div style={{ fontWeight: 600, color: "#0f172a", fontSize: "0.9rem" }}>
            {company?.name || user.company_name || "Primary Organization"}
          </div>
        </div>
        <div className="field">
          <label>Company Code</label>
          <div style={{ fontWeight: 600, color: "#0f172a", fontSize: "0.9rem" }}>
            {company?.code || user.company_code || "—"}
          </div>
        </div>
      </div>

      <form onSubmit={handleSaveContact} style={{ marginTop: "12px", borderTop: "1px solid #f1f5f9", paddingTop: "14px" }}>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="owner-phone">Contact Phone</label>
            <input
              id="owner-phone"
              type="text"
              placeholder="+91 98765 43210"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="owner-address">Office / Business Address</label>
            <input
              id="owner-address"
              type="text"
              placeholder="e.g. 402 Business Tower, Silicon Park"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
          </div>
        </div>
        <div className="row-end mt-2">
          <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>
            {saving ? "Saving…" : "Save Contact Info"}
          </button>
        </div>
      </form>
    </div>
  );
}

// User Profile Photo Modal (Zoho Style)
function ProfilePhotoModal({
  isOpen,
  onClose,
  imageSrc,
  initialScale = 1,
  initialRotate = 0,
  initialPos = { x: 0, y: 0 },
  currentVisibility,
  onSave,
  onChooseNewImage,
  saving,
}: {
  isOpen: boolean;
  onClose: () => void;
  imageSrc: string;
  initialScale?: number;
  initialRotate?: number;
  initialPos?: { x: number; y: number };
  currentVisibility: string;
  onSave: (croppedDataUrl: string, rawDataUrl: string, cropData: { scale: number; rotate: number; pos: { x: number; y: number } }, visibility: string) => Promise<void>;
  onChooseNewImage?: () => void;
  saving: boolean;
}) {
  const [scale, setScale] = useState(initialScale);
  const [rotate, setRotate] = useState(initialRotate);
  const [pos, setPos] = useState(initialPos);
  const [visibility, setVisibility] = useState(currentVisibility || "only_me");
  const [isDragging, setIsDragging] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);
  const dragStartRef = useRef<{ startX: number; startY: number; initialPosX: number; initialPosY: number }>({
    startX: 0,
    startY: 0,
    initialPosX: 0,
    initialPosY: 0,
  });

  useEffect(() => {
    if (isOpen) {
      setScale(initialScale ?? 1);
      setRotate(initialRotate ?? 0);
      setPos(initialPos ?? { x: 0, y: 0 });
      setVisibility(currentVisibility || "only_me");
    }
  }, [isOpen, initialScale, initialRotate, initialPos, currentVisibility]);

  if (!isOpen || !imageSrc) return null;

  function handleMouseDown(e: React.MouseEvent) {
    e.preventDefault();
    setIsDragging(true);
    dragStartRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      initialPosX: pos.x,
      initialPosY: pos.y,
    };
  }

  function handleMouseMove(e: React.MouseEvent) {
    if (!isDragging) return;
    e.preventDefault();
    const dx = e.clientX - dragStartRef.current.startX;
    const dy = e.clientY - dragStartRef.current.startY;
    setPos({
      x: dragStartRef.current.initialPosX + dx,
      y: dragStartRef.current.initialPosY + dy,
    });
  }

  function handleMouseUp() {
    setIsDragging(false);
  }

  async function handleUpdate() {
    try {
      const img = new Image();
      img.crossOrigin = "anonymous";
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = reject;
        img.src = imageSrc;
      });

      // Target canvas dimensions for highest fidelity
      const targetSize = 400;
      const canvas = document.createElement("canvas");
      canvas.width = targetSize;
      canvas.height = targetSize;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      // Draw circular clip path matching the 260px circle in modal
      ctx.beginPath();
      ctx.arc(targetSize / 2, targetSize / 2, targetSize / 2, 0, Math.PI * 2);
      ctx.closePath();
      ctx.clip();

      // The circular mask inside viewport is 260px in diameter (280px container with 10px margins)
      const circleDiameterInView = 260;
      const ratio = targetSize / circleDiameterInView;

      // Rendered unscaled size of image inside the 280x280 viewport container
      const renderedW = imgRef.current?.offsetWidth || 280;
      const renderedH = imgRef.current?.offsetHeight || 280;

      ctx.save();
      // Translate to canvas center, apply scaled user pan offset, rotate, then scale
      ctx.translate(targetSize / 2 + pos.x * ratio, targetSize / 2 + pos.y * ratio);
      ctx.rotate((rotate * Math.PI) / 180);
      ctx.scale(scale, scale);

      // Draw image precisely matching its displayed proportions
      const drawW = renderedW * ratio;
      const drawH = renderedH * ratio;
      ctx.drawImage(img, -drawW / 2, -drawH / 2, drawW, drawH);
      ctx.restore();

      const cropped = canvas.toDataURL("image/png");
      await onSave(cropped, imageSrc, { scale, rotate, pos }, visibility);
    } catch (err) {
      console.error(err);
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: "rgba(15, 23, 42, 0.45)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9999,
        padding: "16px",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        style={{
          background: "#ffffff",
          borderRadius: "16px",
          boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
          width: "100%",
          maxWidth: "460px",
          padding: "24px 28px",
          display: "flex",
          flexDirection: "column",
          gap: "20px",
          position: "relative",
          userSelect: isDragging ? "none" : "auto",
        }}
      >
        {/* Title & Change Photo Button */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <h3 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700, color: "#1e293b" }}>
              User Profile Photo
            </h3>
            {onChooseNewImage && (
              <button
                type="button"
                onClick={onChooseNewImage}
                style={{
                  background: "#f1f5f9",
                  border: "1px solid #cbd5e1",
                  borderRadius: "6px",
                  padding: "4px 10px",
                  fontSize: "0.76rem",
                  fontWeight: 600,
                  color: "#0284c7",
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                }}
                title="Choose a new photo from gallery/computer"
              >
                📁 Choose from gallery
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              fontSize: "1.2rem",
              color: "#94a3b8",
              cursor: "pointer",
              padding: "4px",
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>

        {/* Viewport with circular mask */}
        <div
          style={{
            position: "relative",
            width: "280px",
            height: "280px",
            margin: "0 auto",
            borderRadius: "12px",
            overflow: "hidden",
            background: "#f1f5f9",
            cursor: isDragging ? "grabbing" : "grab",
          }}
          onMouseDown={handleMouseDown}
        >
          {/* Underlying movable image */}
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transform: `translate(${pos.x}px, ${pos.y}px) rotate(${rotate}deg) scale(${scale})`,
              transformOrigin: "center center",
              transition: isDragging ? "none" : "transform 0.05s ease-out",
            }}
          >
            <img
              ref={imgRef}
              src={imageSrc}
              alt="Profile crop preview"
              draggable={false}
              style={{
                maxWidth: "100%",
                maxHeight: "100%",
                objectFit: "contain",
                pointerEvents: "none",
              }}
            />
          </div>

          {/* Zoho circular mask overlay */}
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              pointerEvents: "none",
              boxShadow: "0 0 0 9999px rgba(255, 255, 255, 0.72)",
              borderRadius: "50%",
              margin: "10px",
              border: "2px solid #00b374",
            }}
          />
        </div>

        {/* Controls row: Rotate CCW, - (zoom out), Slider, + (zoom in), Rotate CW */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "12px",
            width: "100%",
          }}
        >
          {/* Rotate CCW */}
          <button
            type="button"
            onClick={() => setRotate((prev) => (prev - 90) % 360)}
            style={{
              width: "36px",
              height: "36px",
              borderRadius: "50%",
              border: "1px solid #e2e8f0",
              background: "#ffffff",
              color: "#64748b",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              fontSize: "1.1rem",
              boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
            }}
            title="Rotate counter-clockwise"
          >
            ↺
          </button>

          {/* Zoom Slider container with - and + */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              flex: 1,
              background: "#ffffff",
              border: "1px solid #e2e8f0",
              borderRadius: "24px",
              padding: "4px 12px",
              boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
            }}
          >
            <button
              type="button"
              onClick={() => setScale((prev) => Math.max(0.5, Number((prev - 0.1).toFixed(2))))}
              style={{
                background: "none",
                border: "none",
                color: "#94a3b8",
                fontSize: "1.2rem",
                cursor: "pointer",
                padding: "0 4px",
                lineHeight: 1,
              }}
              title="Zoom out"
            >
              −
            </button>
            <input
              type="range"
              min="0.5"
              max="3"
              step="0.05"
              value={scale}
              onChange={(e) => setScale(parseFloat(e.target.value))}
              style={{
                flex: 1,
                accentColor: "#00b374",
                cursor: "pointer",
                height: "4px",
              }}
            />
            <button
              type="button"
              onClick={() => setScale((prev) => Math.min(3, Number((prev + 0.1).toFixed(2))))}
              style={{
                background: "none",
                border: "none",
                color: "#94a3b8",
                fontSize: "1.2rem",
                cursor: "pointer",
                padding: "0 4px",
                lineHeight: 1,
              }}
              title="Zoom in"
            >
              +
            </button>
          </div>

          {/* Rotate CW */}
          <button
            type="button"
            onClick={() => setRotate((prev) => (prev + 90) % 360)}
            style={{
              width: "36px",
              height: "36px",
              borderRadius: "50%",
              border: "1px solid #e2e8f0",
              background: "#ffffff",
              color: "#64748b",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              fontSize: "1.1rem",
              boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
            }}
            title="Rotate clockwise"
          >
            ↻
          </button>
        </div>

        {/* Who can view your profile picture? */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.85rem", color: "#475569" }}>
          <span>Who can view your profile picture?</span>
          <select
            value={visibility}
            onChange={(e) => setVisibility(e.target.value)}
            style={{
              border: "none",
              color: "#0284c7",
              fontWeight: 600,
              background: "transparent",
              cursor: "pointer",
              outline: "none",
              padding: "2px 4px",
              fontSize: "0.85rem",
            }}
          >
            <option value="only_me">Only myself ▾</option>
            <option value="company">Employees of my organization ▾</option>
            <option value="everyone">Anyone ▾</option>
          </select>
        </div>

        {/* Action Buttons: Green Update and Cancel */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "4px" }}>
          <button
            type="button"
            onClick={handleUpdate}
            disabled={saving}
            style={{
              background: "#00b374",
              color: "#ffffff",
              border: "none",
              borderRadius: "6px",
              padding: "8px 24px",
              fontWeight: 600,
              fontSize: "0.88rem",
              cursor: saving ? "not-allowed" : "pointer",
              opacity: saving ? 0.7 : 1,
              boxShadow: "0 2px 4px rgba(0, 179, 116, 0.25)",
            }}
          >
            {saving ? "Updating…" : "Update"}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            style={{
              background: "#f1f5f9",
              color: "#475569",
              border: "none",
              borderRadius: "6px",
              padding: "8px 20px",
              fontWeight: 600,
              fontSize: "0.88rem",
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
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
  const { user, refreshMe } = useAuth();
  const { notify } = useToast();
  const [isEditing, setIsEditing] = useState(false);
  const [firstName, setFirstName] = useState(employee.first_name ?? "");
  const [lastName, setLastName] = useState(employee.last_name ?? "");
  const [personalEmail, setPersonalEmail] = useState(employee.personal_email ?? "");
  const [phone, setPhone] = useState(employee.phone ?? "");
  const [gender, setGender] = useState(employee.gender ?? "I'd prefer not to say");
  const [avatarUrl, setAvatarUrl] = useState(employee.avatar_url ?? "");
  const [avatarRawUrl, setAvatarRawUrl] = useState(employee.avatar_raw_url ?? employee.avatar_url ?? "");
  const [avatarCropData, setAvatarCropData] = useState<{ scale: number; rotate: number; pos: { x: number; y: number } } | null>(
    employee.avatar_crop_data ?? null
  );
  const [avatarVisibility, setAvatarVisibility] = useState(employee.avatar_visibility ?? "company");

  // Zoho Photo Modal state
  const [photoModalOpen, setPhotoModalOpen] = useState(false);
  const [editingImageSrc, setEditingImageSrc] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [savingPhoto, setSavingPhoto] = useState(false);

  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setFirstName(employee.first_name ?? "");
    setLastName(employee.last_name ?? "");
    setPersonalEmail(employee.personal_email ?? "");
    setPhone(employee.phone ?? "");
    setGender(employee.gender ?? "I'd prefer not to say");
    setAvatarUrl(employee.avatar_url ?? "");
    setAvatarRawUrl(employee.avatar_raw_url ?? employee.avatar_url ?? "");
    setAvatarCropData(employee.avatar_crop_data ?? null);
    setAvatarVisibility(employee.avatar_visibility ?? "company");
  }, [employee]);

  // Handle ESC key to cancel edit mode or photo modal
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (photoModalOpen) {
          setPhotoModalOpen(false);
        } else if (isEditing) {
          setIsEditing(false);
          setFirstName(employee.first_name ?? "");
          setLastName(employee.last_name ?? "");
          setPersonalEmail(employee.personal_email ?? "");
          setPhone(employee.phone ?? "");
          setGender(employee.gender ?? "I'd prefer not to say");
          setAvatarUrl(employee.avatar_url ?? "");
          setAvatarRawUrl(employee.avatar_raw_url ?? employee.avatar_url ?? "");
          setAvatarCropData(employee.avatar_crop_data ?? null);
          setAvatarVisibility(employee.avatar_visibility ?? "company");
          setFormError(null);
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isEditing, photoModalOpen, employee]);

  function openPhotoEditor(imageSrc: string) {
    setEditingImageSrc(imageSrc);
    setPhotoModalOpen(true);
  }

  function handleImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      notify("Image size should be less than 5 MB.", "error");
      return;
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      const base64 = event.target?.result as string;
      // When a new image file is chosen, reset crop data
      setAvatarCropData(null);
      openPhotoEditor(base64);
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  }

  async function handleSavePhoto(
    croppedDataUrl: string,
    rawDataUrl: string,
    cropData: { scale: number; rotate: number; pos: { x: number; y: number } },
    visibility: string
  ) {
    setSavingPhoto(true);
    try {
      await updateEmployee(employee.id, {
        avatar_url: croppedDataUrl,
        avatar_raw_url: rawDataUrl,
        avatar_crop_data: cropData,
        avatar_visibility: visibility,
      });
      setAvatarUrl(croppedDataUrl);
      setAvatarRawUrl(rawDataUrl);
      setAvatarCropData(cropData);
      setAvatarVisibility(visibility);
      setPhotoModalOpen(false);
      notify("Profile photo updated successfully.");
      if (refreshMe) {
        await refreshMe();
      }
      onSaved();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setSavingPhoto(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      const payload: Record<string, any> = {
        first_name: firstName.trim() || employee.first_name,
        last_name: lastName.trim() || null,
        personal_email: personalEmail.trim() || null,
        phone: phone.trim() || null,
        gender: gender || null,
        avatar_url: avatarUrl || null,
        avatar_visibility: avatarVisibility || "company",
      };
      await updateEmployee(employee.id, payload);
      notify("Profile updated successfully.");
      setIsEditing(false);
      if (refreshMe) {
        await refreshMe();
      }
      onSaved();
    } catch (err) {
      setFormError(parseApiError(err).message);
    } finally {
      setSubmitting(false);
    }
  }

  // Calculate remaining notice period days if on notice period
  const isOnNotice = employee.resignation_status === "submitted" || employee.resignation_status === "approved" || employee.pending_separation;
  const noticeDaysRemaining = employee.last_working_date
    ? Math.max(0, Math.ceil((new Date(employee.last_working_date).getTime() - new Date().setHours(0,0,0,0)) / (1000 * 60 * 60 * 24)))
    : employee.notice_period_days ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem", marginBottom: "1.5rem" }}>
      {/* ── Main Zoho-style Profile Card ────────────────────────────── */}
      <div
        style={{
          background: "#ffffff",
          borderRadius: "14px",
          border: "1px solid #e2e8f0",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
          padding: "24px",
          position: "relative",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "20px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            {/* Avatar with click to open editor and upload */}
            <div style={{ position: "relative" }}>
              <div
                onClick={() => {
                  if (avatarRawUrl || avatarUrl) {
                    openPhotoEditor(avatarRawUrl || avatarUrl);
                  } else {
                    fileInputRef.current?.click();
                  }
                }}
                style={{
                  width: "64px",
                  height: "64px",
                  borderRadius: "50%",
                  background: avatarUrl ? "transparent" : "linear-gradient(135deg, #2563eb, #1d4ed8)",
                  color: "#ffffff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1.5rem",
                  fontWeight: 700,
                  boxShadow: "0 2px 8px rgba(37,99,235,0.2)",
                  overflow: "hidden",
                  border: "2px solid #e2e8f0",
                  cursor: "pointer",
                  transition: "transform 0.15s ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = "scale(1.05)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = "scale(1)";
                }}
                title={avatarUrl ? "Click to view / adjust profile photo" : "Click to upload photo"}
              >
                {avatarUrl ? (
                  <img src={avatarUrl} alt={employee.first_name} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                ) : (
                  `${employee.first_name.charAt(0).toUpperCase()}${(employee.last_name || "").charAt(0).toUpperCase()}`
                )}
              </div>
              <label
                style={{
                  position: "absolute",
                  bottom: "-2px",
                  right: "-2px",
                  background: "#0f172a",
                  color: "#ffffff",
                  borderRadius: "50%",
                  width: "24px",
                  height: "24px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: "pointer",
                  fontSize: "0.72rem",
                  border: "2px solid #ffffff",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
                }}
                title="Upload new profile picture"
              >
                📷
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={handleImageUpload}
                  style={{ display: "none" }}
                />
              </label>
            </div>

            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                <h3 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700, color: "#0f172a" }}>
                  {employee.first_name} {employee.last_name || ""}
                </h3>
                <span
                  style={{
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    fontFamily: "monospace",
                    background: "#f1f5f9",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    color: "#475569",
                  }}
                >
                  {employee.employee_code}
                </span>

                {/* Status Badges */}
                <span
                  style={{
                    fontSize: "0.72rem",
                    fontWeight: 600,
                    padding: "2px 8px",
                    borderRadius: "12px",
                    background: employee.is_active ? "#ecfdf5" : "#f1f5f9",
                    color: employee.is_active ? "#059669" : "#64748b",
                    border: `1px solid ${employee.is_active ? "#a7f3d0" : "#cbd5e1"}`,
                  }}
                >
                  {employee.is_active ? "● Active" : "Inactive"}
                </span>

                {isOnNotice && (
                  <span
                    style={{
                      fontSize: "0.72rem",
                      fontWeight: 700,
                      padding: "2px 8px",
                      borderRadius: "12px",
                      background: "#fef2f2",
                      color: "#dc2626",
                      border: "1px solid #fecaca",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "4px",
                    }}
                  >
                    ⚠️ On Notice Period
                    {noticeDaysRemaining !== null && (
                      <span>({noticeDaysRemaining} days remaining)</span>
                    )}
                  </span>
                )}

                {user?.role === "owner" && (
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "4px",
                      padding: "2px 8px",
                      borderRadius: "12px",
                      fontSize: "0.72rem",
                      fontWeight: 700,
                      background: "#fffbeb",
                      color: "#b45309",
                      border: "1px solid #fde68a",
                    }}
                  >
                    👑 Primary Owner
                  </span>
                )}
              </div>
              <div style={{ fontSize: "0.82rem", color: "#64748b", marginTop: "4px" }}>
                {employee.position || "Staff"} • {departmentName || "General"} • {employee.email}
              </div>
            </div>
          </div>

          {/* Zoho-style Edit / Pencil Button */}
          {!isEditing ? (
            <button
              type="button"
              onClick={() => setIsEditing(true)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                padding: "6px 14px",
                borderRadius: "8px",
                background: "#00b374",
                border: "none",
                fontSize: "0.8rem",
                fontWeight: 600,
                color: "#ffffff",
                cursor: "pointer",
                transition: "all 0.15s ease",
                boxShadow: "0 2px 4px rgba(0, 179, 116, 0.25)",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "#059669")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "#00b374")}
              title="Click or double-click fields to edit"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
              </svg>
              Edit
            </button>
          ) : (
            <div style={{ display: "flex", gap: "8px" }}>
              <button
                type="button"
                onClick={() => {
                  setIsEditing(false);
                  setFirstName(employee.first_name ?? "");
                  setLastName(employee.last_name ?? "");
                  setPersonalEmail(employee.personal_email ?? "");
                  setPhone(employee.phone ?? "");
                  setGender(employee.gender ?? "I'd prefer not to say");
                  setAvatarUrl(employee.avatar_url ?? "");
                  setAvatarVisibility(employee.avatar_visibility ?? "company");
                }}
                style={{
                  padding: "6px 14px",
                  borderRadius: "8px",
                  background: "#f8fafc",
                  border: "1px solid #cbd5e1",
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  color: "#64748b",
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={submitting}
                style={{
                  padding: "6px 16px",
                  borderRadius: "8px",
                  background: "#00b374",
                  border: "none",
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  color: "#ffffff",
                  cursor: "pointer",
                  boxShadow: "0 2px 4px rgba(0, 179, 116, 0.25)",
                }}
              >
                {submitting ? "Saving…" : "Save"}
              </button>
            </div>
          )}
        </div>

        {formError && <div className="alert alert-error mb-4">{formError}</div>}

        {/* Profile Info Grid: Double-click enabled */}
        <div
          onDoubleClick={() => {
            if (!isEditing) setIsEditing(true);
          }}
          title={!isEditing ? "Double-click any field to edit" : undefined}
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "16px 24px",
            fontSize: "0.83rem",
          }}
        >
          {/* First Name */}
          <div>
            <label style={{ display: "block", color: "#64748b", fontSize: "0.74rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "4px" }}>
              First Name *
            </label>
            {isEditing ? (
              <input
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                style={{ width: "100%", padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.83rem" }}
                required
              />
            ) : (
              <div style={{ fontWeight: 600, color: "#1e293b" }}>{employee.first_name}</div>
            )}
          </div>

          {/* Last Name */}
          <div>
            <label style={{ display: "block", color: "#64748b", fontSize: "0.74rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "4px" }}>
              Last Name
            </label>
            {isEditing ? (
              <input
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                style={{ width: "100%", padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.83rem" }}
              />
            ) : (
              <div style={{ fontWeight: 600, color: "#1e293b" }}>{employee.last_name || "—"}</div>
            )}
          </div>

          {/* Gender */}
          <div>
            <label style={{ display: "block", color: "#64748b", fontSize: "0.74rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "4px" }}>
              Gender
            </label>
            {isEditing ? (
              <select
                value={gender}
                onChange={(e) => setGender(e.target.value)}
                style={{ width: "100%", padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.83rem" }}
              >
                <option value="I'd prefer not to say">I'd prefer not to say</option>
                <option value="Female">Female</option>
                <option value="Male">Male</option>
                <option value="Non-binary">Non-binary</option>
              </select>
            ) : (
              <div style={{ fontWeight: 600, color: "#1e293b" }}>{gender || "—"}</div>
            )}
          </div>

          {/* Photo Visibility */}
          <div>
            <label style={{ display: "block", color: "#64748b", fontSize: "0.74rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "4px" }}>
              Profile Photo Visibility
            </label>
            {isEditing ? (
              <select
                value={avatarVisibility}
                onChange={(e) => setAvatarVisibility(e.target.value)}
                style={{ width: "100%", padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.83rem" }}
              >
                <option value="company">Employees of my organization</option>
                <option value="everyone">Everyone (Public)</option>
                <option value="only_me">Only myself</option>
              </select>
            ) : (
              <div style={{ fontWeight: 600, color: "#1e293b" }}>
                {avatarVisibility === "everyone"
                  ? "Anyone"
                  : avatarVisibility === "only_me"
                  ? "Only myself"
                  : "Employees of my organization"}
              </div>
            )}
          </div>

          {/* Department */}
          <div>
            <label style={{ display: "block", color: "#64748b", fontSize: "0.74rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "4px" }}>
              Department
            </label>
            <div style={{ fontWeight: 600, color: "#1e293b" }}>{departmentName || "—"}</div>
          </div>

          {/* Position */}
          <div>
            <label style={{ display: "block", color: "#64748b", fontSize: "0.74rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "4px" }}>
              Position / Role
            </label>
            <div style={{ fontWeight: 600, color: "#1e293b" }}>{employee.position || "—"}</div>
          </div>

          {/* Employment Type */}
          <div>
            <label style={{ display: "block", color: "#64748b", fontSize: "0.74rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "4px" }}>
              Employment Type
            </label>
            <div style={{ fontWeight: 600, color: "#1e293b", textTransform: "capitalize" }}>
              {employee.employment_type.replace("_", " ")}
            </div>
          </div>

          {/* Date of Joining */}
          <div>
            <label style={{ display: "block", color: "#64748b", fontSize: "0.74rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "4px" }}>
              Date of Joining (DOJ)
            </label>
            <div style={{ fontWeight: 600, color: "#1e293b" }}>{employee.hire_date}</div>
          </div>
        </div>
      </div>

      {/* ── Zoho Card 2: My Email Addresses ─────────────────────────── */}
      <div
        style={{
          background: "#ffffff",
          borderRadius: "14px",
          border: "1px solid #e2e8f0",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
          padding: "20px 24px",
        }}
      >
        <h4 style={{ margin: "0 0 4px", fontSize: "0.95rem", fontWeight: 700, color: "#0f172a" }}>
          My Email Addresses
        </h4>
        <p style={{ margin: "0 0 16px", fontSize: "0.76rem", color: "#64748b" }}>
          View and manage the email addresses associated with your account.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          {/* Work Email (Primary) */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 14px",
              borderRadius: "8px",
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <div
                style={{
                  width: "32px",
                  height: "32px",
                  borderRadius: "50%",
                  background: "#eff6ff",
                  color: "#2563eb",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1rem",
                }}
              >
                ✉️
              </div>
              <div>
                <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#0f172a" }}>
                  {employee.email}
                </div>
                <div style={{ fontSize: "0.72rem", color: "#64748b" }}>Work Email (Primary identity)</div>
              </div>
            </div>
            <span
              style={{
                fontSize: "0.72rem",
                fontWeight: 600,
                color: "#2563eb",
                background: "#eff6ff",
                padding: "2px 8px",
                borderRadius: "12px",
                border: "1px solid #bfdbfe",
              }}
            >
              Primary
            </span>
          </div>

          {/* Personal Email */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 14px",
              borderRadius: "8px",
              background: "#ffffff",
              border: "1px solid #e2e8f0",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "12px", flex: 1 }}>
              <div
                style={{
                  width: "32px",
                  height: "32px",
                  borderRadius: "50%",
                  background: "#f1f5f9",
                  color: "#64748b",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1rem",
                }}
              >
                ✉️
              </div>
              <div style={{ flex: 1 }}>
                {isEditing ? (
                  <input
                    type="email"
                    value={personalEmail}
                    onChange={(e) => setPersonalEmail(e.target.value)}
                    placeholder="Enter personal email address"
                    style={{ width: "100%", maxWidth: "340px", padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.83rem" }}
                  />
                ) : (
                  <>
                    <div style={{ fontSize: "0.85rem", fontWeight: 600, color: personalEmail ? "#0f172a" : "#94a3b8" }}>
                      {personalEmail || "No personal email added"}
                    </div>
                    <div style={{ fontSize: "0.72rem", color: "#64748b" }}>Personal Email</div>
                  </>
                )}
              </div>
            </div>

            {/* Hover Delete Action Icon (Zoho style) */}
            {personalEmail && (
              <button
                type="button"
                onClick={async () => {
                  if (confirm("Remove personal email?")) {
                    setPersonalEmail("");
                    try {
                      await updateEmployee(employee.id, { personal_email: null });
                      notify("Personal email removed.");
                      onSaved();
                    } catch (err) {
                      notify(parseApiError(err).message, "error");
                    }
                  }
                }}
                style={{
                  background: "none",
                  border: "none",
                  color: "#94a3b8",
                  cursor: "pointer",
                  padding: "6px",
                  borderRadius: "4px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = "#ef4444";
                  e.currentTarget.style.background = "#fee2e2";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = "#94a3b8";
                  e.currentTarget.style.background = "none";
                }}
                title="Remove personal email"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Zoho Card 3: My Mobile Numbers ───────────────────────────── */}
      <div
        style={{
          background: "#ffffff",
          borderRadius: "14px",
          border: "1px solid #e2e8f0",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
          padding: "20px 24px",
        }}
      >
        <h4 style={{ margin: "0 0 4px", fontSize: "0.95rem", fontWeight: 700, color: "#0f172a" }}>
          My Mobile Numbers
        </h4>
        <p style={{ margin: "0 0 16px", fontSize: "0.76rem", color: "#64748b" }}>
          View and manage contact numbers associated with your account.
        </p>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "10px 14px",
            borderRadius: "8px",
            background: "#ffffff",
            border: "1px solid #e2e8f0",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px", flex: 1 }}>
            <div
              style={{
                width: "32px",
                height: "32px",
                borderRadius: "50%",
                background: "#fff7ed",
                color: "#ea580c",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "1rem",
              }}
            >
              📞
            </div>
            <div style={{ flex: 1 }}>
              {isEditing ? (
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="Enter phone number"
                  style={{ width: "100%", maxWidth: "340px", padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.83rem" }}
                />
              ) : (
                <>
                  <div style={{ fontSize: "0.85rem", fontWeight: 600, color: phone ? "#0f172a" : "#94a3b8" }}>
                    {phone || "No mobile number added"}
                  </div>
                  <div style={{ fontSize: "0.72rem", color: "#64748b" }}>Primary contact number</div>
                </>
              )}
            </div>
          </div>

          {/* Hover Delete Action Icon (Zoho style) */}
          {phone && (
            <button
              type="button"
              onClick={async () => {
                if (confirm("Remove phone number?")) {
                  setPhone("");
                  try {
                    await updateEmployee(employee.id, { phone: null });
                    notify("Phone number removed.");
                    onSaved();
                  } catch (err) {
                    notify(parseApiError(err).message, "error");
                  }
                }
              }}
              style={{
                background: "none",
                border: "none",
                color: "#94a3b8",
                cursor: "pointer",
                padding: "6px",
                borderRadius: "4px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                transition: "all 0.15s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "#ef4444";
                e.currentTarget.style.background = "#fee2e2";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "#94a3b8";
                e.currentTarget.style.background = "none";
              }}
              title="Remove phone number"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Zoho User Profile Photo Modal */}
      <ProfilePhotoModal
        isOpen={photoModalOpen}
        onClose={() => setPhotoModalOpen(false)}
        imageSrc={editingImageSrc}
        initialScale={avatarCropData?.scale ?? 1}
        initialRotate={avatarCropData?.rotate ?? 0}
        initialPos={avatarCropData?.pos ?? { x: 0, y: 0 }}
        currentVisibility={avatarVisibility}
        onSave={handleSavePhoto}
        onChooseNewImage={() => fileInputRef.current?.click()}
        saving={savingPhoto}
      />
    </div>
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

  const noticeDays = employee.notice_period_days || 30;

  function calculateExpectedLwd(resDateStr: string, days: number): string {
    if (!resDateStr) return "";
    const [y, m, d] = resDateStr.split("-").map(Number);
    const dateObj = new Date(y, m - 1, d);
    dateObj.setDate(dateObj.getDate() + days);
    return dateObj.toISOString().split("T")[0];
  }

  function formatDisplayDate(dateStr: string): string {
    if (!dateStr) return "—";
    const [y, m, d] = dateStr.split("-");
    if (!y || !m || !d) return dateStr;
    return `${d}/${m}/${y}`;
  }

  // Calculate served days and shortfall dynamically
  let servedDays = 0;
  let shortfallDays = 0;
  const expectedLwd = calculateExpectedLwd(resignationDate, noticeDays);

  if (resignationDate && lastWorkingDate) {
    const rDate = new Date(resignationDate);
    const lDate = new Date(lastWorkingDate);
    servedDays = Math.max(0, Math.round((lDate.getTime() - rDate.getTime()) / (1000 * 60 * 60 * 24)));
    shortfallDays = Math.max(0, noticeDays - servedDays);
  }

  function handleResignationDateChange(newDate: string) {
    setResignationDate(newDate);
    // If lastWorkingDate was matching old default, update it to the new expected LWD
    const oldExpected = calculateExpectedLwd(resignationDate, noticeDays);
    if (!lastWorkingDate || lastWorkingDate === oldExpected) {
      setLastWorkingDate(calculateExpectedLwd(newDate, noticeDays));
    }
  }

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
            onClick={() => {
              const today = new Date().toISOString().split("T")[0];
              setResignationDate(today);
              setLastWorkingDate(calculateExpectedLwd(today, noticeDays));
              setShowModal(true);
            }}
          >
            + Request Resignation
          </button>
        </div>
      )}

      {status === "submitted" && (
        <div className="alert alert-warning mt-2">
          <strong>⏳ Resignation Under Review:</strong> You submitted a resignation on{" "}
          <b>{employee.resignation_date ? formatDisplayDate(employee.resignation_date) : "—"}</b> with proposed Last Working Day (LWD) of{" "}
          <b>{employee.last_working_date ? formatDisplayDate(employee.last_working_date) : "—"}</b>.
          {(employee.notice_recovery_days ?? 0) > 0 ? (
            <span style={{ display: "block", marginTop: "4px" }}>
              ⚠️ Early release requested with <b>{employee.notice_recovery_days} unserved notice days</b> shortfall. HR and your manager are currently reviewing notice requirements and buyout terms.
            </span>
          ) : (
            <span> HR and your manager are currently reviewing notice requirements and handover plans.</span>
          )}
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
              <strong className="text-primary">{employee.last_working_date ? formatDisplayDate(employee.last_working_date) : "—"}</strong>
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
                Please specify your intended departure timeline. Your contractual notice period is <b>{noticeDays} days</b> (Expected LWD: <b>{formatDisplayDate(expectedLwd)}</b>).
              </p>

              <div className="form-grid">
                <div className="field">
                  <label>Resignation Submission Date *</label>
                  <input
                    type="date"
                    value={resignationDate}
                    onChange={(e) => handleResignationDateChange(e.target.value)}
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

              {/* Amber Warning Banner on Notice Shortfall */}
              {shortfallDays > 0 && (
                <div
                  style={{
                    backgroundColor: "#fffbeb",
                    border: "1px solid #fde68a",
                    borderLeft: "4px solid #f59e0b",
                    borderRadius: "6px",
                    padding: "10px 12px",
                    color: "#92400e",
                    fontSize: "0.82rem",
                    lineHeight: 1.45,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ fontSize: "1rem" }}>⚠️</span>
                    <div>
                      <strong>Notice Shortfall Warning:</strong> Your contractual notice period is{" "}
                      <b>{noticeDays} days</b> (Expected LWD: <b>{formatDisplayDate(expectedLwd)}</b>). Requesting{" "}
                      <b>{formatDisplayDate(lastWorkingDate)}</b> ({servedDays} days served) creates a{" "}
                      <b>{shortfallDays}-day notice shortfall</b> that may be deducted from your Full & Final settlement unless approved or waived by HR.
                    </div>
                  </div>
                </div>
              )}

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
