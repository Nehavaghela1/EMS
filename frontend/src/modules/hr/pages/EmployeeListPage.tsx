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
  const [quickPosition, setQuickPosition] = useState("");
  const [quickSaving, setQuickSaving] = useState(false);
  const [quickError, setQuickError] = useState<string | null>(null);

  const queryClient = useQueryClient();

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
    setQuickSaving(true);
    setQuickError(null);
    try {
      await updateEmployee(quickEditEmp.id, {
        position: quickPosition.trim() || undefined,
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
                  setQuickEditEmp(e);
                  setQuickPosition(e.position ?? "");
                  setQuickError(null);
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
              <label>Designation / Position</label>
              <input
                value={quickPosition}
                onChange={(evt) => setQuickPosition(evt.target.value)}
                placeholder="e.g. Developer, Senior Engineer, Sales Executive"
                autoFocus
              />
              <span className="field-hint">Quickly correct typos or update role titles.</span>
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
