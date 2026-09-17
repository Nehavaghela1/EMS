import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { useDebounce } from "../../../shared/hooks/useDebounce";
import { useHasRole } from "../../../shared/hooks/useRole";
import { parseApiError } from "../../../shared/api/errors";
import { listDepartments, listEmployees, updateEmployee, type Employee } from "../api";
import { listCompanies } from "../../identity/api";
import { formatDate } from "../../../shared/utils/date";
import { getPositionsForDepartment, toTitleCase } from "../constants/departmentPositions";

export function EmployeeListPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const isSuperAdmin = useHasRole("super_admin");
  const canCreate = useHasRole("hr_admin", "super_admin");
  const { page, limit, setPage } = usePagination();
  const [q, setQ] = useState("");
  const debouncedQ = useDebounce(q);
  const [companyId, setCompanyId] = useState(searchParams.get("companyId") || "");
  const [departmentId, setDepartmentId] = useState("");
  const [sort, setSort] = useState<string | null>(null);

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
    queryKey: ["employees", { q: debouncedQ, companyId, departmentId, sort, page, limit }],
    queryFn: () =>
      listEmployees({
        q: debouncedQ || undefined,
        company_id: (isSuperAdmin && companyId) ? companyId : undefined,
        department_id: departmentId || undefined,
        sort: sort ?? undefined,
        page,
        limit,
      }),
    placeholderData: (prev) => prev,
  });

  const [quickEditEmp, setQuickEditEmp] = useState<Employee | null>(null);
  const [quickPositionMode, setQuickPositionMode] = useState("");
  const [quickCustomPosition, setQuickCustomPosition] = useState("");
  const [quickSaving, setQuickSaving] = useState(false);
  const [quickError, setQuickError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  // Open quick edit modal and configure dropdown vs custom
  function handleOpenQuickEdit(emp: Employee) {
    setQuickEditEmp(emp);
    setQuickError(null);
    const deptName = departmentsQuery.data?.items.find((d) => d.id === emp.department_id)?.name;
    const stdPositions = getPositionsForDepartment(deptName);
    if (emp.position && stdPositions.includes(emp.position)) {
      setQuickPositionMode(emp.position);
      setQuickCustomPosition("");
    } else if (emp.position) {
      setQuickPositionMode("__other__");
      setQuickCustomPosition(emp.position);
    } else {
      setQuickPositionMode("");
      setQuickCustomPosition("");
    }
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
    if (quickPositionMode === "__other__" && !quickCustomPosition.trim()) {
      setQuickError("Please specify the designation title.");
      return;
    }

    const finalPos =
      quickPositionMode === "__other__"
        ? toTitleCase(quickCustomPosition.trim())
        : quickPositionMode.trim();

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

  const columns: DataTableColumn<Employee>[] = [
    { key: "employee_code", label: "Code", render: (e) => e.employee_code },
    {
      key: "first_name",
      label: "Name",
      sortable: true,
      render: (e) => `${e.first_name}${e.last_name ? " " + e.last_name : ""}`,
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
      </div>

      <DataTable
        columns={columns}
        page={employeesQuery.data}
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
        emptyMessage="No employees match your search."
        rowKey={(e) => e.id}
        onRowClick={(e) => navigate(`/employees/${e.id}`)}
        onRowDoubleClick={(e) => navigate(`/employees/${e.id}`)}
      />

      {/* Quick Edit Position Modal */}
      {quickEditEmp && (
        <div className="modal-backdrop" onClick={() => setQuickEditEmp(null)}>
          <div className="modal stack" onClick={(evt) => evt.stopPropagation()} style={{ maxWidth: "420px" }}>
            <div className="modal-header">
              <h3>Edit Position: {quickEditEmp.first_name} {quickEditEmp.last_name || ""}</h3>
              <button type="button" className="modal-close-btn" onClick={() => setQuickEditEmp(null)}>
                ✕
              </button>
            </div>
            {quickError && <div className="alert alert-error">{quickError}</div>}
            <div className="field">
              <div className="row-between align-center mb-1">
                <label style={{ margin: 0 }}>Designation / Position</label>
                {quickEditEmp.department_id && (
                  <span className="text-xs text-muted">
                    {departmentsQuery.data?.items.find((d) => d.id === quickEditEmp.department_id)?.name || "Department"} Roles
                  </span>
                )}
              </div>
              <div className="stack gap-2">
                <select
                  value={quickPositionMode}
                  onChange={(e) => {
                    const val = e.target.value;
                    setQuickPositionMode(val);
                    if (val !== "__other__") {
                      setQuickCustomPosition("");
                    }
                  }}
                >
                  <option value="">— Select Designation —</option>
                  {getPositionsForDepartment(
                    departmentsQuery.data?.items.find((d) => d.id === quickEditEmp.department_id)?.name
                  ).map((pos) => (
                    <option key={pos} value={pos}>
                      {pos}
                    </option>
                  ))}
                  <option value="__other__">Other (Specify)...</option>
                </select>

                {quickPositionMode === "__other__" && (
                  <div className="stack gap-1" style={{ animation: "fadeIn 0.2s ease-in-out" }}>
                    <label style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text, #334155)" }}>
                      Specify Designation *
                    </label>
                    <input
                      value={quickCustomPosition}
                      onChange={(evt) => setQuickCustomPosition(evt.target.value)}
                      onBlur={() => {
                        setQuickCustomPosition(toTitleCase(quickCustomPosition));
                      }}
                      placeholder="e.g. Prompt Engineer, Data Architect"
                      autoFocus
                    />
                    <span className="field-hint" style={{ fontSize: "0.75rem" }}>
                      Auto-formatted to Title Case upon saving.
                    </span>
                  </div>
                )}
              </div>
            </div>
            <div className="row-end mt-4">
              <button type="button" className="btn" onClick={() => setQuickEditEmp(null)} disabled={quickSaving}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleSaveQuickPosition}
                disabled={quickSaving}
              >
                {quickSaving ? "Saving…" : "Save Position"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
