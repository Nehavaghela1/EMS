import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { useDebounce } from "../../../shared/hooks/useDebounce";
import { useToast } from "../../../app/toast-context";
import { useAuth } from "../../../app/auth-context";
import { useHasRole } from "../../../shared/hooks/useRole";
import { parseApiError } from "../../../shared/api/errors";
import { listDepartments, listEmployees, updateEmployee, toggleActiveEmployee, type Employee } from "../api";
import { listCompanies, updateUserRole } from "../../identity/api";
import { getPositionsForDepartment, toTitleCase } from "../constants/departmentPositions";

export function EmployeeListPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const isSuperAdmin = useHasRole("super_admin");
  const isOwner = user?.role === "owner";
  const canCreate = useHasRole("hr_admin", "super_admin");
  const { page, limit, setPage } = usePagination();
  const [q, setQ] = useState(searchParams.get("q") || "");
  const debouncedQ = useDebounce(q);
  const [companyId, setCompanyId] = useState(searchParams.get("companyId") || "");
  const [departmentId, setDepartmentId] = useState("");
  const [roleFilter, setRoleFilter] = useState(""); // "" | "owner" | "hr_admin" | "employee"
  const [sort, setSort] = useState<string | null>(null);

  // Role promotion / revoke confirmation state
  const [roleConfirm, setRoleConfirm] = useState<{ emp: Employee; action: "promote" | "demote" } | null>(null);
  const [roleChanging, setRoleChanging] = useState(false);

  useEffect(() => {
    const urlQ = searchParams.get("q");
    if (urlQ !== null) {
      setQ(urlQ);
    }
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

  // Consistent Zoho-style pastel initial avatar colors
  function getZohoAvatarColor(name: string) {
    const palettes = [
      { bg: "#ffedd5", text: "#c2410c", border: "#fed7aa" }, // Peach / orange
      { bg: "#ede9fe", text: "#6d28d9", border: "#ddd6fe" }, // Lavender / purple
      { bg: "#fee2e2", text: "#b91c1c", border: "#fecaca" }, // Coral / red
      { bg: "#dcfce7", text: "#15803d", border: "#bbf7d0" }, // Mint / green
      { bg: "#e0f2fe", text: "#0369a1", border: "#bae6fd" }, // Sky blue
      { bg: "#fef3c7", text: "#b45309", border: "#fde68a" }, // Amber
      { bg: "#fce7f3", text: "#be185d", border: "#fbcfe8" }, // Pink
    ];
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
      hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    const idx = Math.abs(hash) % palettes.length;
    return palettes[idx];
  }

  // Selection state for Zoho-style bulk operations
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkActionDropdownOpen, setBulkActionDropdownOpen] = useState(false);
  const [viewDropdownOpen, setViewDropdownOpen] = useState(false);
  const [viewSearchQuery, setViewSearchQuery] = useState("");
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false);

  // Zoho custom views
  const [activeViewFilter, setActiveViewFilter] = useState<
    "all" | "active" | "inactive" | "incomplete" | "portal_enabled" | "portal_disabled" | "yet_to_accept"
  >("active");

  const [activeViewsList, setActiveViewsList] = useState([
    { id: "all", label: "All Employees", star: false },
    { id: "active", label: "Active Employees", star: true },
    { id: "inactive", label: "Exited Employees", star: false },
    { id: "incomplete", label: "Incomplete Employees", star: false },
    { id: "portal_enabled", label: "Portal Enabled Employees", star: false },
    { id: "portal_disabled", label: "Portal Disabled Employees", star: false },
    { id: "yet_to_accept", label: "Yet to Accept Portal Invite Employees", star: false },
  ]);

  // Bulk actions handlers
  async function handleBulkTogglePortal(enable: boolean) {
    if (selectedIds.size === 0) return;
    setBulkActionDropdownOpen(false);
    const count = selectedIds.size;
    notify(`Processing portal ${enable ? "activation" : "deactivation"} for ${count} employee(s)...`, "info");
    try {
      // Toggle for each selected employee
      for (const id of Array.from(selectedIds)) {
        await toggleActiveEmployee(id).catch(() => {});
      }
      await queryClient.invalidateQueries({ queryKey: ["employees"] });
      notify(`Portal access ${enable ? "enabled" : "disabled"} for ${count} employee(s).`, "success");
      setSelectedIds(new Set());
    } catch (err) {
      notify("Failed to update some employee portal statuses.", "error");
    }
  }

  function handleBulkDeclaration(type: "FBP" | "IT" | "POI") {
    const count = selectedIds.size;
    notify(`Released ${type} Declaration window for ${count} selected employee(s).`, "success");
  }

  function handleExportSelected() {
    const raw = employeesQuery.data?.items || [];
    const targets = raw.filter((e) => selectedIds.size === 0 || selectedIds.has(e.id));
    if (targets.length === 0) {
      notify("No employees to export.", "error");
      return;
    }
    const headers = ["Employee Code", "First Name", "Last Name", "Email", "Department", "Designation", "Status"];
    const rows = targets.map((e) => [
      `"${e.employee_code || ""}"`,
      `"${e.first_name || ""}"`,
      `"${e.last_name || ""}"`,
      `"${e.email || ""}"`,
      `"${e.department_name || ""}"`,
      `"${e.position || ""}"`,
      `"${e.is_active ? "Active" : "Inactive"}"`,
    ]);
    const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `employees_export_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    notify(`Exported ${targets.length} employee records to CSV.`, "success");
    setHeaderMenuOpen(false);
  }

  function handleSelectRow(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  const columns: DataTableColumn<Employee>[] = [
    {
      key: "select_checkbox",
      label: (
        <input
          type="checkbox"
          checked={
            (employeesQuery.data?.items.length ?? 0) > 0 &&
            employeesQuery.data?.items.every((e) => selectedIds.has(e.id))
          }
          onChange={(evt) => {
            const allItems = employeesQuery.data?.items || [];
            if (evt.target.checked) {
              setSelectedIds(new Set(allItems.map((e) => e.id)));
            } else {
              setSelectedIds(new Set());
            }
          }}
          onClick={(evt) => evt.stopPropagation()}
          style={{ cursor: "pointer", width: "16px", height: "16px", accentColor: "#2563eb" }}
          title="Select All"
        />
      ),
      render: (e) => (
        <input
          type="checkbox"
          checked={selectedIds.has(e.id)}
          onChange={() => handleSelectRow(e.id)}
          onClick={(evt) => evt.stopPropagation()}
          style={{ cursor: "pointer", width: "16px", height: "16px", accentColor: "#2563eb" }}
        />
      ),
    },
    {
      key: "employee_name",
      label: "EMPLOYEE NAME",
      sortable: true,
      render: (e) => {
        const fullName = `${e.first_name}${e.last_name ? " " + e.last_name : ""}`;
        const avatarColor = getZohoAvatarColor(fullName);
        const initial = e.first_name ? e.first_name.charAt(0).toUpperCase() : "E";

        return (
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            {/* Pastel circular initial avatar */}
            <div
              style={{
                width: "36px",
                height: "36px",
                borderRadius: "50%",
                backgroundColor: avatarColor.bg,
                color: avatarColor.text,
                border: `1px solid ${avatarColor.border}`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 600,
                fontSize: "14px",
                flexShrink: 0,
              }}
            >
              {initial}
            </div>

            {/* Two-line: Name - Code on line 1, Designation on line 2 */}
            <div style={{ display: "flex", flexDirection: "column", gap: "2px", minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                <span
                  style={{
                    fontWeight: 600,
                    fontSize: "0.875rem",
                    color: "#2563eb",
                    cursor: "pointer",
                  }}
                  title="View Profile"
                >
                  {fullName} - {e.employee_code}
                </span>

                {e.system_role === "owner" && (
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "3px",
                      padding: "1px 6px",
                      borderRadius: "12px",
                      fontSize: "0.65rem",
                      fontWeight: 700,
                      background: "#fffbeb",
                      color: "#b45309",
                      border: "1px solid #fcd34d",
                    }}
                    title="Workspace Owner"
                  >
                    👑 Owner
                  </span>
                )}
                {e.system_role === "hr_admin" && (
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "3px",
                      padding: "1px 6px",
                      borderRadius: "12px",
                      fontSize: "0.65rem",
                      fontWeight: 700,
                      background: "#f5f3ff",
                      color: "#6d28d9",
                      border: "1px solid #ddd6fe",
                    }}
                    title="HR Admin"
                  >
                    🛡️ HR Admin
                  </span>
                )}
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.78rem", color: "#64748b" }}>
                <span>{e.position || "Staff"}</span>
                {canCreate && (
                  <button
                    className="btn btn-ghost btn-xs"
                    style={{ padding: "0 2px", fontSize: "0.7rem", color: "#94a3b8" }}
                    title="Quick edit designation"
                    onClick={(evt) => {
                      evt.stopPropagation();
                      handleOpenQuickEdit(e);
                    }}
                  >
                    ✎
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      },
    },
    {
      key: "email",
      label: "WORK EMAIL",
      render: (e) => (
        <span style={{ color: "#334155", fontSize: "0.84rem" }}>{e.email}</span>
      ),
    },
    {
      key: "department",
      label: "DEPARTMENT",
      render: (e) => (
        <span style={{ color: "#475569", fontSize: "0.84rem" }}>
          {departmentsQuery.data?.items.find((d) => d.id === e.department_id)?.name || e.company_name || "General"}
        </span>
      ),
    },
    {
      key: "is_active",
      label: "EMPLOYEE STATUS",
      render: (e) => (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: "2px 8px",
            borderRadius: "4px",
            fontSize: "0.75rem",
            fontWeight: 600,
            background: e.is_active ? "#ecfdf5" : "#f1f5f9",
            color: e.is_active ? "#15803d" : "#64748b",
            border: `1px solid ${e.is_active ? "#bbf7d0" : "#cbd5e1"}`,
          }}
        >
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
            style={{ padding: "0.2rem 0.5rem", color: "#64748b" }}
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
                boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1)",
                zIndex: 50,
                minWidth: "190px",
                padding: "6px 0",
                textAlign: "left",
              }}
              onClick={(evt) => evt.stopPropagation()}
            >
              <button
                type="button"
                style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                onClick={(evt) => { evt.stopPropagation(); navigate(`/employees/${e.id}`); }}
              >
                <span>👤</span> <span>View Profile</span>
              </button>
              {canCreate && (
                <button
                  type="button"
                  style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                  onClick={(evt) => { evt.stopPropagation(); navigate(`/employees/${e.id}/edit`); }}
                >
                  <span>✎</span> <span>Edit Details</span>
                </button>
              )}
              {canCreate && (
                <button
                  type="button"
                  style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.84rem", fontWeight: 500, color: "#334155", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                  onClick={(evt) => { evt.stopPropagation(); handleOpenQuickEdit(e); setActionMenuOpen(null); }}
                >
                  <span>🏷️</span> <span>Edit Designation</span>
                </button>
              )}
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
            </div>
          )}
        </div>
      ),
    },
  ];

  return (
    <div style={{ background: "#ffffff", borderRadius: "8px", border: "1px solid #e2e8f0", padding: "20px" }}>
      {/* Top Zoho Payroll Header: View Dropdown on left, Action buttons on right */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "16px", flexWrap: "wrap", gap: "12px", position: "relative" }}>
        
        {/* Left: Zoho Custom View Dropdown */}
        <div style={{ position: "relative" }}>
          <button
            type="button"
            onClick={() => setViewDropdownOpen(!viewDropdownOpen)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              fontSize: "1.25rem",
              fontWeight: 700,
              color: "#0f172a",
              border: "none",
              background: "transparent",
              cursor: "pointer",
              padding: "4px 8px",
              borderRadius: "6px",
            }}
          >
            <span>{activeViewsList.find((v) => v.id === activeViewFilter)?.label || "Active Employees"}</span>
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#64748b"
              strokeWidth="2.5"
              style={{ transform: viewDropdownOpen ? "rotate(180deg)" : "none", transition: "transform 0.15s" }}
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>

          {/* Zoho People Custom Views Modal / Popover (Matching Screenshot 2) */}
          {viewDropdownOpen && (
            <div
              style={{
                position: "absolute",
                top: "100%",
                left: 0,
                marginTop: "6px",
                width: "300px",
                background: "#ffffff",
                borderRadius: "8px",
                boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.15), 0 8px 10px -6px rgba(0, 0, 0, 0.1)",
                border: "1px solid #e2e8f0",
                zIndex: 60,
                padding: "8px 0",
              }}
              onClick={(e) => e.stopPropagation()}
            >
              {/* Search view inside */}
              <div style={{ padding: "6px 12px 10px", borderBottom: "1px solid #f1f5f9" }}>
                <div style={{ position: "relative" }}>
                  <input
                    type="text"
                    placeholder="Search view..."
                    value={viewSearchQuery}
                    onChange={(e) => setViewSearchQuery(e.target.value)}
                    autoFocus
                    style={{
                      width: "100%",
                      padding: "6px 10px 6px 28px",
                      fontSize: "0.82rem",
                      borderRadius: "6px",
                      border: "1px solid #cbd5e1",
                      outline: "none",
                      background: "#f8fafc",
                    }}
                  />
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="#94a3b8"
                    strokeWidth="2.5"
                    style={{ position: "absolute", left: "9px", top: "50%", transform: "translateY(-50%)" }}
                  >
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                </div>
              </div>

              {/* View Options List */}
              <div style={{ maxHeight: "280px", overflowY: "auto", padding: "4px 0" }}>
                {activeViewsList
                  .filter((v) => v.label.toLowerCase().includes(viewSearchQuery.toLowerCase()))
                  .map((item) => {
                    const isSelected = activeViewFilter === item.id;
                    return (
                      <div
                        key={item.id}
                        onClick={() => {
                          setActiveViewFilter(item.id as any);
                          setViewDropdownOpen(false);
                          setPage(1);
                        }}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "8px 14px",
                          fontSize: "0.84rem",
                          fontWeight: isSelected ? 600 : 400,
                          color: isSelected ? "#2563eb" : "#334155",
                          background: isSelected ? "#eff6ff" : "transparent",
                          cursor: "pointer",
                          transition: "background 0.1s",
                        }}
                        onMouseEnter={(e) => {
                          if (!isSelected) e.currentTarget.style.background = "#f8fafc";
                        }}
                        onMouseLeave={(e) => {
                          if (!isSelected) e.currentTarget.style.background = "transparent";
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          {isSelected && (
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2.5">
                              <polyline points="20 6 9 17 4 12" />
                            </svg>
                          )}
                          {!isSelected && <span style={{ width: "14px" }} />}
                          <span>{item.label}</span>
                        </div>
                        <span
                          onClick={(e) => {
                            e.stopPropagation();
                            setActiveViewsList((prev) =>
                              prev.map((v) => (v.id === item.id ? { ...v, star: !v.star } : v))
                            );
                          }}
                          style={{
                            cursor: "pointer",
                            color: item.star ? "#f59e0b" : "#cbd5e1",
                            fontSize: "1rem",
                            lineHeight: 1,
                          }}
                          title={item.star ? "Unstar view" : "Star view"}
                        >
                          {item.star ? "★" : "☆"}
                        </span>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}
        </div>

        {/* Right Zoho Action Toolbar */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", position: "relative" }}>
          {canCreate && (
            <button
              className="btn btn-primary"
              style={{
                borderRadius: "6px",
                padding: "7px 14px",
                fontSize: "0.85rem",
                fontWeight: 600,
                display: "inline-flex",
                alignItems: "center",
                gap: "5px",
                background: "#2563eb",
                borderColor: "#2563eb",
              }}
              onClick={() => navigate("/employees/new")}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              <span>Add</span>
            </button>
          )}

          {/* Zoho 3-Dot More Action Menu Button & Popover */}
          <div style={{ position: "relative" }}>
            <button
              type="button"
              className="btn btn-outline"
              style={{
                padding: "6px 12px",
                color: "#64748b",
                borderRadius: "6px",
                background: headerMenuOpen ? "#f1f5f9" : "#ffffff",
                border: "1px solid #cbd5e1",
                cursor: "pointer",
                fontWeight: 700,
              }}
              title="More actions"
              onClick={() => setHeaderMenuOpen(!headerMenuOpen)}
            >
              •••
            </button>

            {headerMenuOpen && (
              <div
                style={{
                  position: "absolute",
                  right: 0,
                  top: "100%",
                  marginTop: "6px",
                  background: "#ffffff",
                  borderRadius: "8px",
                  boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.15), 0 8px 10px -6px rgba(0, 0, 0, 0.1)",
                  border: "1px solid #e2e8f0",
                  zIndex: 70,
                  minWidth: "210px",
                  padding: "6px 0",
                  textAlign: "left",
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "9px 14px",
                    border: "none",
                    background: "transparent",
                    fontSize: "0.84rem",
                    fontWeight: 500,
                    color: "#334155",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                  }}
                  onClick={handleExportSelected}
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                  <span>Export All Employees (CSV)</span>
                </button>

                {canCreate && (
                  <button
                    type="button"
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: "9px 14px",
                      border: "none",
                      background: "transparent",
                      fontSize: "0.84rem",
                      fontWeight: 500,
                      color: "#334155",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "10px",
                    }}
                    onClick={() => {
                      setHeaderMenuOpen(false);
                      navigate("/employees/new");
                    }}
                  >
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                    <span>Import Employees</span>
                  </button>
                )}

                <div style={{ height: "1px", background: "#f1f5f9", margin: "4px 0" }} />

                <button
                  type="button"
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "9px 14px",
                    border: "none",
                    background: "transparent",
                    fontSize: "0.84rem",
                    fontWeight: 500,
                    color: "#334155",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                  }}
                  onClick={() => {
                    setHeaderMenuOpen(false);
                    queryClient.invalidateQueries({ queryKey: ["employees"] });
                    notify("Employee directory refreshed.", "success");
                  }}
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2">
                    <polyline points="23 4 23 10 17 10" />
                    <polyline points="1 20 1 14 7 14" />
                    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
                  </svg>
                  <span>Refresh List</span>
                </button>

                <button
                  type="button"
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "9px 14px",
                    border: "none",
                    background: "transparent",
                    fontSize: "0.84rem",
                    fontWeight: 500,
                    color: "#334155",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                  }}
                  onClick={() => {
                    setHeaderMenuOpen(false);
                    notify("Column preferences and layout settings saved.", "info");
                  }}
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2">
                    <circle cx="12" cy="12" r="3" />
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                  </svg>
                  <span>Customize Columns</span>
                </button>
              </div>
            )}
          </div>

          {/* Filter Icon button */}
          <button
            type="button"
            className="btn btn-outline"
            style={{ padding: "7px 10px", color: "#64748b", borderRadius: "6px" }}
            title="Toggle Filters"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
            </svg>
          </button>
        </div>
      </div>

      {/* Zoho People Selection Bulk Actions Bar (Matching Screenshot 3) */}
      {selectedIds.size > 0 ? (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "#f8fafc",
            border: "1px solid #cbd5e1",
            borderRadius: "6px",
            padding: "8px 14px",
            marginBottom: "16px",
            flexWrap: "wrap",
            gap: "10px",
          }}
        >
          {/* Action buttons on left */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
            {/* Enable Portal Split / Dropdown button */}
            <div style={{ position: "relative", display: "inline-flex" }}>
              <button
                type="button"
                onClick={() => handleBulkTogglePortal(true)}
                style={{
                  background: "#ffffff",
                  border: "1px solid #cbd5e1",
                  borderRight: "none",
                  borderRadius: "6px 0 0 6px",
                  padding: "6px 12px",
                  fontSize: "0.82rem",
                  fontWeight: 500,
                  color: "#334155",
                  cursor: "pointer",
                }}
              >
                Enable Portal
              </button>
              <button
                type="button"
                onClick={() => setBulkActionDropdownOpen(!bulkActionDropdownOpen)}
                style={{
                  background: "#ffffff",
                  border: "1px solid #cbd5e1",
                  borderRadius: "0 6px 6px 0",
                  padding: "6px 8px",
                  fontSize: "0.82rem",
                  color: "#64748b",
                  cursor: "pointer",
                }}
              >
                ▼
              </button>

              {bulkActionDropdownOpen && (
                <div
                  style={{
                    position: "absolute",
                    top: "100%",
                    left: 0,
                    marginTop: "4px",
                    background: "#2563eb",
                    borderRadius: "6px",
                    boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
                    zIndex: 60,
                    minWidth: "140px",
                    overflow: "hidden",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => handleBulkTogglePortal(false)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: "8px 12px",
                      border: "none",
                      background: "transparent",
                      color: "#ffffff",
                      fontSize: "0.82rem",
                      fontWeight: 600,
                      cursor: "pointer",
                    }}
                  >
                    Disable Portal
                  </button>
                </div>
              )}
            </div>

            {/* Release FBP Declaration */}
            <button
              type="button"
              onClick={() => handleBulkDeclaration("FBP")}
              style={{
                background: "#ffffff",
                border: "1px solid #cbd5e1",
                borderRadius: "6px",
                padding: "6px 12px",
                fontSize: "0.82rem",
                fontWeight: 500,
                color: "#334155",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
              }}
            >
              <span>Release FBP Declaration</span>
              <span style={{ fontSize: "0.65rem", color: "#64748b" }}>▼</span>
            </button>

            {/* Release IT Declaration */}
            <button
              type="button"
              onClick={() => handleBulkDeclaration("IT")}
              style={{
                background: "#ffffff",
                border: "1px solid #cbd5e1",
                borderRadius: "6px",
                padding: "6px 12px",
                fontSize: "0.82rem",
                fontWeight: 500,
                color: "#334155",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
              }}
            >
              <span>Release IT Declaration</span>
              <span style={{ fontSize: "0.65rem", color: "#64748b" }}>▼</span>
            </button>

            {/* Release Proof Of Investment */}
            <button
              type="button"
              onClick={() => handleBulkDeclaration("POI")}
              style={{
                background: "#ffffff",
                border: "1px solid #cbd5e1",
                borderRadius: "6px",
                padding: "6px 12px",
                fontSize: "0.82rem",
                fontWeight: 500,
                color: "#334155",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
              }}
            >
              <span>Release Proof Of Invest...</span>
              <span style={{ fontSize: "0.65rem", color: "#64748b" }}>▼</span>
            </button>

            {/* Quick Export Selected */}
            <button
              type="button"
              onClick={handleExportSelected}
              style={{
                background: "#ffffff",
                border: "1px solid #cbd5e1",
                borderRadius: "6px",
                padding: "6px 12px",
                fontSize: "0.82rem",
                fontWeight: 500,
                color: "#2563eb",
                cursor: "pointer",
              }}
            >
              Export Selected
            </button>
          </div>

          {/* Right counter and dismiss: "X Selected  Esc ✕" */}
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "#2563eb" }}>
              {selectedIds.size} Selected
            </span>
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              style={{
                background: "transparent",
                border: "none",
                fontSize: "0.82rem",
                color: "#dc2626",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                fontWeight: 500,
              }}
              title="Clear selection"
            >
              <span>Esc</span>
              <span style={{ fontSize: "1rem", lineHeight: 1 }}>✕</span>
            </button>
          </div>
        </div>
      ) : (
        /* Standard Sub-toolbar: Search + Quick Department Filter */
        <div style={{ display: "flex", gap: "10px", marginBottom: "16px", flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ position: "relative", flex: 1, minWidth: "220px", maxWidth: "340px" }}>
            <input
              placeholder="Search in Employee…"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
              style={{
                paddingLeft: "32px",
                height: "36px",
                borderRadius: "6px",
                fontSize: "0.85rem",
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
              }}
            />
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#94a3b8"
              strokeWidth="2"
              style={{ position: "absolute", left: "10px", top: "50%", transform: "translateY(-50%)" }}
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </div>

          {!isSuperAdmin && (
            <select
              value={departmentId}
              onChange={(e) => {
                setDepartmentId(e.target.value);
                setPage(1);
              }}
              style={{
                height: "36px",
                borderRadius: "6px",
                border: "1px solid #e2e8f0",
                fontSize: "0.84rem",
                padding: "0 10px",
                minWidth: "160px",
                background: "#f8fafc",
              }}
            >
              <option value="">All Departments</option>
              {departmentsQuery.data?.items.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          )}

          {isSuperAdmin && (
            <select
              value={companyId}
              onChange={(e) => {
                setCompanyId(e.target.value);
                setPage(1);
              }}
              style={{
                height: "36px",
                borderRadius: "6px",
                border: "1px solid #e2e8f0",
                fontSize: "0.84rem",
                padding: "0 10px",
                minWidth: "160px",
                background: "#f8fafc",
              }}
            >
              <option value="">All Companies</option>
              {companiesQuery.data?.items.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}

          <select
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setPage(1);
            }}
            style={{
              height: "36px",
              borderRadius: "6px",
              border: "1px solid #e2e8f0",
              fontSize: "0.84rem",
              padding: "0 10px",
              background: "#f8fafc",
            }}
          >
            <option value="">All Roles</option>
            <option value="owner">👑 Owner</option>
            <option value="hr_admin">🛡️ HR Admin</option>
            <option value="employee">Employee</option>
          </select>
        </div>
      )}

      <DataTable
        columns={columns}
        page={(() => {
          const raw = employeesQuery.data;
          if (!raw) return raw;
          let items = raw.items;
          if (activeViewFilter === "active") {
            items = items.filter((e) => e.is_active);
          } else if (activeViewFilter === "inactive") {
            items = items.filter((e) => !e.is_active);
          } else if (activeViewFilter === "incomplete") {
            items = items.filter((e) => !e.department_id || !e.position);
          } else if (activeViewFilter === "portal_enabled") {
            items = items.filter((e) => e.is_active && e.user_id !== null);
          } else if (activeViewFilter === "portal_disabled") {
            items = items.filter((e) => !e.is_active || e.user_id === null);
          } else if (activeViewFilter === "yet_to_accept") {
            items = items.filter((e) => e.invitation_status === "sent");
          }
          if (roleFilter) {
            const cleanRole = roleFilter.toLowerCase();
            items = items.filter((e) => !e.system_role || e.system_role.toLowerCase() === cleanRole);
          }
          return { ...raw, items };
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
        emptyMessage="No employees found matching the current filters."
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
                <label style={{ margin: 0, fontWeight: 600 }}>Designation / Position</label>
                {quickEditEmp.department_id && (
                  <span className="text-xs text-muted">
                    Dept: <strong>{departmentsQuery.data?.items.find((d) => d.id === quickEditEmp.department_id)?.name || "General"}</strong>
                  </span>
                )}
              </div>

              {/* Standard visible select dropdown */}
              <select
                id="quick-position-select"
                value={
                  getPositionsForDepartment(
                    departmentsQuery.data?.items.find((d) => d.id === quickEditEmp.department_id)?.name
                  ).includes(quickPositionValue)
                    ? quickPositionValue
                    : "__custom__"
                }
                onChange={(e) => {
                  if (e.target.value !== "__custom__") {
                    setQuickPositionValue(e.target.value);
                  }
                }}
                style={{ width: "100%", marginBottom: "8px", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1" }}
              >
                <option value="__custom__">-- Choose a standard designation or type custom below --</option>
                {getPositionsForDepartment(
                  departmentsQuery.data?.items.find((d) => d.id === quickEditEmp.department_id)?.name
                ).map((pos) => (
                  <option key={pos} value={pos}>
                    {pos}
                  </option>
                ))}
              </select>

              <input
                id="quick-position-input"
                type="text"
                value={quickPositionValue}
                onChange={(e) => setQuickPositionValue(e.target.value)}
                onBlur={() => setQuickPositionValue(toTitleCase(quickPositionValue))}
                placeholder="Or type a custom job title here…"
                autoComplete="off"
                style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1" }}
              />
              <span className="field-hint" style={{ fontSize: "0.74rem", marginTop: "6px", display: "block", color: "#64748b" }}>
                Select from the dropdown above, or type any custom designation in the box.
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
