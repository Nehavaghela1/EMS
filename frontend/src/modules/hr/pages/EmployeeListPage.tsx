import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { useDebounce } from "../../../shared/hooks/useDebounce";
import { useHasRole } from "../../../shared/hooks/useRole";
import { listDepartments, listEmployees, type Employee } from "../api";
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
    { key: "position", label: "Position", render: (e) => e.position ?? "—" },
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
    </div>
  );
}
