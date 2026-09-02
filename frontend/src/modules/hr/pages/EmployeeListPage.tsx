import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { useDebounce } from "../../../shared/hooks/useDebounce";
import { useHasRole } from "../../../shared/hooks/useRole";
import { listDepartments, listEmployees, type Employee } from "../api";

const columns: DataTableColumn<Employee>[] = [
  { key: "employee_code", label: "Code", render: (e) => e.employee_code },
  {
    key: "first_name",
    label: "Name",
    sortable: true,
    render: (e) => `${e.first_name}${e.last_name ? " " + e.last_name : ""}`,
  },
  { key: "email", label: "Email", render: (e) => e.email },
  { key: "position", label: "Position", render: (e) => e.position ?? "—" },
  {
    key: "hire_date",
    label: "Hire date",
    sortable: true,
    render: (e) => e.hire_date,
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

export function EmployeeListPage() {
  const navigate = useNavigate();
  const isHr = useHasRole("hr_admin");
  const { page, limit, setPage } = usePagination();
  const [q, setQ] = useState("");
  const debouncedQ = useDebounce(q);
  const [departmentId, setDepartmentId] = useState("");
  const [sort, setSort] = useState<string | null>(null);

  const departmentsQuery = useQuery({
    queryKey: ["departments", "all-for-filter"],
    queryFn: () => listDepartments({ page: 1, limit: 100 }),
  });

  const employeesQuery = useQuery({
    queryKey: ["employees", { q: debouncedQ, departmentId, sort, page, limit }],
    queryFn: () =>
      listEmployees({
        q: debouncedQ || undefined,
        department_id: departmentId || undefined,
        sort: sort ?? undefined,
        page,
        limit,
      }),
    placeholderData: (prev) => prev,
  });

  return (
    <div>
      <PageHeader
        title="Employees"
        breadcrumb="HR"
        action={
          isHr && (
            <button className="btn btn-primary" onClick={() => navigate("/employees/new")}>
              + New employee
            </button>
          )
        }
      />

      <div className="row mb-4">
        <input
          placeholder="Search by name, email or code…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
          style={{ minWidth: 240 }}
        />
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
      />
    </div>
  );
}
