import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { useDebounce } from "../../../shared/hooks/useDebounce";
import { useToast } from "../../../app/toast-context";
import { useAuth } from "../../../app/auth-context";
import { useHasRole } from "../../../shared/hooks/useRole";
import { parseApiError } from "../../../shared/api/errors";
import { listDepartments, listEmployees, updateEmployee, type Employee } from "../api";
import { listCompanies } from "../../identity/api";
import { updateUserRole } from "../../identity/api";
import { formatDate } from "../../../shared/utils/date";
import { getPositionsForDepartment, toTitleCase } from "../constants/departmentPositions";

export function EmployeeListPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const isSuperAdmin = useHasRole("super_admin");
  const isOwner = user?.role === "owner";
  const canCreate = useHasRole("hr_admin", "super_admin");
  const { page, limit, setPage } = usePagination();
  const [q, setQ] = useState("");
  const debouncedQ = useDebounce(q);
  const [companyId, setCompanyId] = useState(searchParams.get("companyId") || "");
  const [departmentId, setDepartmentId] = useState("");
  const [roleFilter, setRoleFilter] = useState(""); // "" | "owner" | "hr_admin" | "employee"
  const [sort, setSort] = useState<string | null>(null);

  // Role promotion / revoke confirmation state
  const [roleConfirm, setRoleConfirm] = useState<{ emp: Employee; action: "promote" | "demote" } | null>(null);
  const [roleChanging, setRoleChanging] = useState(false);

  useEffect(() => {
    const cid = searchParams.get("companyId");
    if (cid) {
      setCompanyId(cid);
    }
  }, [searchParams]);

  const companiesQuery = useQuery({
    queryKey: ["companies", "all-filter"],
    queryFn: () => listCompanies({ page: 1, limit: 100 }),
    enabled: isSuperAdmin,
  });

  const departmentsQuery = useQuery({
    queryKey: ["departments", "all-for-filter"],
    queryFn: () => listDepartments({ page: 1, limit: 100 }),
    enabled: !isSuperAdmin,
  });

  const employeesQuery = useQuery({
    queryKey: ["employees", { q: debouncedQ, companyId, departmentId, role: roleFilter, sort, page, limit }],
    queryFn: () =>
      listEmployees({
        q: debouncedQ || undefined,
        company_id: (isSuperAdmin && companyId) ? companyId : undefined,
        department_id: departmentId || undefined,
        role: roleFilter || undefined,
        sort: sort ?? undefined,
        page,
        limit,
      }),
    placeholderData: (prev) => prev,
  });

  const [quickEditEmp, setQuickEditEmp] = useState<Employee | null>(null);
  const [quickPositionValue, setQuickPositionValue] = useState("");
  const [quickSaving, setQuickSaving] = useState(false);
  const [quickError, setQuickError] = useState<string | null>(null);
  const [actionMenuOpen, setActionMenuOpen] = useState<string | null>(null);
  const { notify } = useToast();

  const queryClient = useQueryClient();

  // Open quick edit modal — pre-fill with current position
  function handleOpenQuickEdit(emp: Employee) {
    setQuickEditEmp(emp);
    setQuickError(null);
    setQuickPositionValue(emp.position ?? "");
  }

  // Color generator for positions / roles
  function getPositionBadgeStyle(pos: string | null | undefined) {
    if (!pos) return { bg: "#f1f5f9", color: "#475569", border: "#cbd5e1" };
    const p = pos.toLowerCase();
    if (p.includes("dev") || p.includes("engineer") || p.includes("tech")) {
      return { bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" };
    }
    if (p.includes("sales") || p.includes("marketing") || p.includes("growth")) {
      return { bg: "#ecfdf5", color: "#047857", border: "#a7f3d0" };
    }
    if (p.includes("lead") || p.includes("head") || p.includes("manager") || p.includes("dir")) {
      return { bg: "#fdf4ff", color: "#86198f", border: "#f5d0fe" };
    }
    if (p.includes("hr") || p.includes("admin") || p.includes("people")) {
      return { bg: "#fff7ed", color: "#c2410c", border: "#fed7aa" };
    }
    if (p.includes("design") || p.includes("ui") || p.includes("ux")) {
      return { bg: "#f5f3ff", color: "#6d28d9", border: "#ddd6fe" };
    }
    return { bg: "#f8fafc", color: "#334155", border: "#e2e8f0" };
  }

  async function handleSaveQuickPosition() {
    if (!quickEditEmp) return;
    if (!quickPositionValue.trim()) {
      setQuickError("Please enter a designation title.");
      return;
    }

    const finalPos = toTitleCase(quickPositionValue.trim());

    setQuickSaving(true);
    setQuickError(null);
    try {
      await updateEmployee(quickEditEmp.id, {
        position: finalPos || undefined,
      });
      await queryClient.invalidateQueries({ queryKey: ["employees"] });
      setQuickEditEmp(null);
    } catch (err) {
      setQuickError(parseApiError(err).message);
    } finally {
      setQuickSaving(false);
    }
  }

  async function handleRoleChange() {
    if (!roleConfirm?.emp.user_id) {
      notify("Employee has no linked user account.", "error");
      return;
    }
    setRoleChanging(true);
    const newRole = roleConfirm.action === "promote" ? "hr_admin" : "employee";
    const name = `${roleConfirm.emp.first_name} ${roleConfirm.emp.last_name ?? ""}`;
    try {
      await updateUserRole(roleConfirm.emp.user_id, newRole);
      await queryClient.invalidateQueries({ queryKey: ["employees"] });
      notify(
        roleConfirm.action === "promote"
          ? `${name} promoted to HR Admin.`
          : `${name} demoted to Employee.`,
        "success"
      );
      setRoleConfirm(null);
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setRoleChanging(false);
    }
  }

  const columns: DataTableColumn<Employee>[] = [
    { key: "employee_code", label: "Code", render: (e) => e.employee_code },
    {
      key: "first_name",
      label: "Name",
      sortable: true,
      render: (e) => (
        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
          <span style={{ fontWeight: 500 }}>
            {e.first_name}{e.last_name ? " " + e.last_name : ""}
          </span>
          {e.system_role === "owner" && (
            <span
              style={{
                display: "inline-flex", alignItems: "center", gap: "3px",
                padding: "1px 7px", borderRadius: "20px", fontSize: "0.67rem",
                fontWeight: 700, letterSpacing: "0.02em",
                background: "#fffbeb", color: "#b45309", border: "1px solid #fcd34d",
                whiteSpace: "nowrap",
              }}
              title="Workspace Owner"
            >
              👑 Owner
            </span>
          )}
          {e.system_role === "hr_admin" && (
            <span
              style={{
                display: "inline-flex", alignItems: "center", gap: "3px",
                padding: "1px 7px", borderRadius: "20px", fontSize: "0.67rem",
                fontWeight: 700, letterSpacing: "0.02em",
                background: "#f5f3ff", color: "#6d28d9", border: "1px solid #ddd6fe",
                whiteSpace: "nowrap",
              }}
              title="HR Admin — administrative access"
            >
              🛡️ HR Admin
            </span>
          )}
        </div>
      ),
    },
    ...(isSuperAdmin
      ? [
          {
            key: "company_name" as keyof Employee,
            label: "Company",
            render: (e: Employee) => (
              <span className="badge badge-outline" style={{ fontWeight: 600 }}>
                {e.company_name || "—"}
              </span>
            ),
          },
        ]
      : []),
    { key: "email", label: "Email", render: (e) => e.email },
    {
      key: "position",
      label: "Position",
      render: (e) => {
        const style = getPositionBadgeStyle(e.position);
        return (
          <div style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <span
              className="badge"
              style={{
                backgroundColor: style.bg,
                color: style.color,
                border: `1px solid ${style.border}`,
                fontWeight: 600,
                fontSize: "0.75rem",
              }}
            >
              {e.position ?? "Staff"}
            </span>
            {canCreate && (
              <button
                className="btn btn-ghost btn-xs"
                style={{ padding: "0 4px", fontSize: "0.7rem", color: "var(--color-muted, #64748b)" }}
                title="Quick edit position"
                onClick={(evt) => {
                  evt.stopPropagation();
                  handleOpenQuickEdit(e);
                }}
              >
                ✎
              </button>
            )}
          </div>
        );
      },
    },
    {
      key: "hire_date",
      label: "Hire date",
      sortable: true,
      render: (e) => formatDate(e.hire_date),
    },
    {
      key: "is_active",
      label: "Status",
      render: (e) => (
        <span className={"badge " + (e.is_active ? "badge-success" : "badge-muted")}>
          {e.is_active ? "Active" : "Inactive"}
        </span>
      ),
    },
    {
      key: "actions",
      label: "",
      render: (e) => (
        <div style={{ position: "relative", textAlign: "right" }}>
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            style={{ padding: "0.2rem 0.5rem" }}
            onClick={(evt) => {
              evt.stopPropagation();
              setActionMenuOpen(actionMenuOpen === e.id ? null : e.id);
            }}
          >
            •••
          </button>
          {actionMenuOpen === e.id && (
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
                minWidth: "200px",
                padding: "6px 0",
                textAlign: "left"
              }}
              onMouseLeave={() => setActionMenuOpen(null)}
            >
              <button
                type="button"
                style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                onClick={(evt) => { evt.stopPropagation(); navigate(`/employees/${e.id}`); }}
              >
                <span>👁️</span> <span>View Full Profile</span>
              </button>
              {canCreate && (
                <button
                  type="button"
                  style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                  onClick={(evt) => { evt.stopPropagation(); handleOpenQuickEdit(e); setActionMenuOpen(null); }}
                >
                  <span>✎</span> <span>Quick Edit Position</span>
                </button>
              )}
              {e.invitation_status !== "activated" && (
                <button
                  type="button"
                  style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                  onClick={(evt) => { evt.stopPropagation(); notify("Resend Invite flow triggered"); setActionMenuOpen(null); }}
                >
                  <span>✉️</span> <span>Resend Invite</span>
                </button>
              )}
              <button
                type="button"
                style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                onClick={(evt) => { evt.stopPropagation(); navigate(`/employees/${e.id}`); notify("Redirected to profile to print dossier"); }}
              >
                <span>📄</span> <span>Download Dossier</span>
              </button>
              {/* Owner-only: security role actions — separate from job designation */}
              {isOwner && e.user_id && e.user_id !== user?.id && (
                <>
                  <div style={{ height: "1px", background: "#e2e8f0", margin: "4px 0" }} />
                  {e.system_role !== "hr_admin" && e.system_role !== "owner" && (
                    <button
                      type="button"
                      style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#6366f1", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                      onClick={(evt) => { evt.stopPropagation(); setRoleConfirm({ emp: e, action: "promote" }); setActionMenuOpen(null); }}
                    >
                      <span>👑</span> <span>Make HR Admin</span>
                    </button>
                  )}
                  {e.system_role === "hr_admin" && (
                    <button
                      type="button"
                      style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#dc2626", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                      onClick={(evt) => { evt.stopPropagation(); setRoleConfirm({ emp: e, action: "demote" }); setActionMenuOpen(null); }}
                    >
                      <span>⬇️</span> <span>Demote to Employee</span>
                    </button>
                  )}
                </>
              )}
              <div style={{ height: "1px", background: "#e2e8f0", margin: "4px 0" }} />
              <button
                type="button"
                style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#dc2626", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                onClick={(evt) => { evt.stopPropagation(); notify("Deactivate flow initiated."); setActionMenuOpen(null); }}
              >
                <span>🚫</span> <span>Deactivate / Archive</span>
              </button>
            </div>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title={isSuperAdmin ? "Platform Employees Directory" : "Employees"}
        breadcrumb={isSuperAdmin ? "Super Admin / Directory" : "HR"}
        action={
          canCreate && (
            <button className="btn btn-primary" onClick={() => navigate("/employees/new")}>
              + New employee
            </button>
          )
        }
      />

      <div className="row mb-4" style={{ gap: "var(--space-3)", flexWrap: "wrap" }}>
        <input
          placeholder="Search by name, email or code…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
          style={{ minWidth: 240 }}
        />
        {isSuperAdmin && (
          <select
            value={companyId}
            onChange={(e) => {
              const val = e.target.value;
              setCompanyId(val);
              setPage(1);
              if (val) {
                setSearchParams({ companyId: val });
              } else {
                setSearchParams({});
              }
            }}
            style={{ minWidth: 200 }}
          >
            <option value="">All Companies (Platform-wide)</option>
            {companiesQuery.data?.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.code})
              </option>
            ))}
          </select>
        )}
        {!isSuperAdmin && (
          <select
            value={departmentId}
            onChange={(e) => {
              setDepartmentId(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All departments</option>
            {departmentsQuery.data?.items.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        )}
        {/* Role filter — client-side scan; shows admins in 1 click */}
        <select
          id="dir-role-filter"
          value={roleFilter}
          onChange={(e) => {
            setRoleFilter(e.target.value);
            setPage(1);
          }}
          style={{
            borderRadius: "8px",
            border: "1px solid #e2e8f0",
            padding: "6px 10px",
            fontSize: "0.84rem",
            color: "#374151",
            background: roleFilter ? "#f0f4ff" : undefined,
            fontWeight: roleFilter ? 600 : undefined,
          }}
        >
          <option value="">All roles</option>
          <option value="owner">👑 Owner</option>
          <option value="hr_admin">🛡️ HR Admin</option>
          <option value="employee">Employee</option>
          <option value="manager">Manager</option>
        </select>
      </div>

      <DataTable
        columns={columns}
        page={(() => {
          const raw = employeesQuery.data;
          if (!raw || !roleFilter) return raw;
          const cleanRole = roleFilter.toLowerCase();
          const filtered = raw.items.filter(
            (e) => !e.system_role || e.system_role.toLowerCase() === cleanRole
          );
          return { ...raw, items: filtered };
        })()}
        isLoading={employeesQuery.isLoading}
        isError={employeesQuery.isError}
        error={employeesQuery.error}
        currentPage={page}
        onPageChange={setPage}
        sort={sort}
        onSortChange={(s) => {
          setSort(s);
          setPage(1);
        }}
        emptyMessage={roleFilter ? `No employees with role "${roleFilter}" found.` : "No employees match your search."}
        rowKey={(e) => e.id}
        onRowClick={(e) => navigate(`/employees/${e.id}`)}
        onRowDoubleClick={(e) => navigate(`/employees/${e.id}`)}
      />

      {/* Quick Edit Position Modal — single creatable combobox, no two-tier friction */}
      {quickEditEmp && (
        <div className="modal-backdrop" onClick={() => setQuickEditEmp(null)}>
          <div className="modal stack" onClick={(evt) => evt.stopPropagation()} style={{ maxWidth: "440px" }}>
            <div className="modal-header">
              <h3>Edit Designation — {quickEditEmp.first_name} {quickEditEmp.last_name || ""}</h3>
              <button type="button" className="modal-close-btn" onClick={() => setQuickEditEmp(null)}>✕</button>
            </div>

            <p style={{ fontSize: "0.78rem", color: "#64748b", margin: "0 0 14px", padding: "0 2px" }}>
              Type a job title or pick from the smart suggestions below. This does not affect system access or security roles.
            </p>

            {quickError && <div className="alert alert-error">{quickError}</div>}

            <div className="field">
              <div className="row-between align-center mb-1">
                <label style={{ margin: 0 }}>Designation / Position</label>
                {quickEditEmp.department_id && (
                  <span className="text-xs text-muted">
                    Suggestions from:{" "}
                    <strong>{departmentsQuery.data?.items.find((d) => d.id === quickEditEmp.department_id)?.name || "department"}</strong>
                  </span>
                )}
              </div>

              {/* Single creatable combobox — type anything OR pick a suggestion */}
              <input
                id="quick-position-input"
                list="quick-position-suggestions"
                value={quickPositionValue}
                onChange={(e) => setQuickPositionValue(e.target.value)}
                onBlur={() => setQuickPositionValue(toTitleCase(quickPositionValue))}
                placeholder="e.g. Senior Python Developer, Prompt Engineer…"
                autoFocus
                autoComplete="off"
                style={{ width: "100%" }}
              />
              <datalist id="quick-position-suggestions">
                {getPositionsForDepartment(
                  departmentsQuery.data?.items.find((d) => d.id === quickEditEmp.department_id)?.name
                ).map((pos) => (
                  <option key={pos} value={pos} />
                ))}
              </datalist>
              <span className="field-hint" style={{ fontSize: "0.74rem", marginTop: "4px", display: "block" }}>
                Auto-formatted to Title Case on save. Pick a suggestion or type your own.
              </span>
            </div>

            <div className="row-end mt-4">
              <button type="button" className="btn" onClick={() => setQuickEditEmp(null)} disabled={quickSaving}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleSaveQuickPosition}
                disabled={quickSaving || !quickPositionValue.trim()}
              >
                {quickSaving ? "Saving…" : "Save Designation"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Security Role Confirmation Modal — owner-only */}
      {roleConfirm && (
        <div
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            backgroundColor: "rgba(15, 23, 42, 0.7)",
            backdropFilter: "blur(4px)",
            display: "flex", alignItems: "center", justifyContent: "center", padding: "16px",
          }}
          onClick={() => setRoleConfirm(null)}
        >
          <div
            style={{
              background: "#ffffff", borderRadius: "16px", width: "100%", maxWidth: "440px",
              boxShadow: "0 25px 50px -12px rgba(0,0,0,0.35)", border: "1px solid #e2e8f0",
              padding: "32px 28px 24px",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ textAlign: "center", marginBottom: "20px" }}>
              <div style={{ fontSize: "2.5rem", marginBottom: "12px" }}>
                {roleConfirm.action === "promote" ? "👑" : "⬇️"}
              </div>
              <h3 style={{ margin: "0 0 8px", fontSize: "1.05rem", fontWeight: 700, color: "#0f172a" }}>
                {roleConfirm.action === "promote" ? "Grant Administrative Access?" : "Revoke Admin Access?"}
              </h3>
              <p style={{ margin: 0, fontSize: "0.875rem", color: "#64748b", lineHeight: 1.6 }}>
                You are about to{" "}
                {roleConfirm.action === "promote" ? (
                  <>
                    grant{" "}
                    <strong style={{ color: "#0f172a" }}>
                      {roleConfirm.emp.first_name} {roleConfirm.emp.last_name ?? ""}
                    </strong>{" "}
                    full <strong style={{ color: "#6366f1" }}>HR Admin</strong> privileges. They will be able to
                    view employee records, configure leave & attendance, and process payroll.
                  </>
                ) : (
                  <>
                    remove HR Admin privileges from{" "}
                    <strong style={{ color: "#0f172a" }}>
                      {roleConfirm.emp.first_name} {roleConfirm.emp.last_name ?? ""}
                    </strong>.
                    They will revert to a regular employee.
                  </>
                )}
              </p>
            </div>
            <div style={{ display: "flex", gap: "10px", justifyContent: "center" }}>
              <button
                onClick={() => setRoleConfirm(null)}
                style={{
                  padding: "9px 22px", borderRadius: "8px", border: "1px solid #e2e8f0",
                  background: "#fff", color: "#64748b", fontWeight: 600,
                  fontSize: "0.875rem", cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                id="btn-confirm-role-change"
                onClick={handleRoleChange}
                disabled={roleChanging}
                style={{
                  padding: "9px 22px", borderRadius: "8px", border: "none",
                  background: roleConfirm.action === "promote"
                    ? "linear-gradient(135deg, #6366f1, #8b5cf6)"
                    : "linear-gradient(135deg, #dc2626, #b91c1c)",
                  color: "#fff", fontWeight: 600, fontSize: "0.875rem",
                  cursor: roleChanging ? "not-allowed" : "pointer",
                  boxShadow: roleConfirm.action === "promote"
                    ? "0 2px 8px rgba(99,102,241,0.3)"
                    : "0 2px 8px rgba(220,38,38,0.3)",
                }}
              >
                {roleChanging
                  ? roleConfirm.action === "promote" ? "Promoting…" : "Revoking…"
                  : roleConfirm.action === "promote" ? "Confirm Promotion" : "Confirm Revoke"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
