import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog";
import { usePagination } from "../../../shared/hooks/usePagination";
import { parseApiError } from "../../../shared/api/errors";
import { useToast } from "../../../app/toast-context";
import {
  createDepartment,
  deleteDepartment,
  listDepartments,
  updateDepartment,
  type Department,
} from "../api";
import { departmentFormSchema } from "../schemas";

export function DepartmentListPage() {
  const { page, limit, setPage } = usePagination();
  const [sort, setSort] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { notify } = useToast();

  const departmentsQuery = useQuery({
    queryKey: ["departments", { page, limit, sort }],
    queryFn: () => listDepartments({ page, limit, sort: sort ?? undefined }),
    placeholderData: (prev) => prev,
  });

  const [editing, setEditing] = useState<Department | "new" | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Department | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["departments"] });
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await deleteDepartment(deleteTarget.id);
      notify("Department deleted.");
      setDeleteTarget(null);
      await refresh();
    } catch (err) {
      setDeleteError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  }

  const columns: DataTableColumn<Department>[] = [
    { key: "name", label: "Name", sortable: true, render: (d) => d.name },
    { key: "description", label: "Description", render: (d) => d.description ?? "—" },
    { key: "employee_count", label: "Employees", render: (d) => d.employee_count },
    {
      key: "actions",
      label: "",
      render: (d) => (
        <div className="row">
          <button className="btn btn-sm" onClick={() => setEditing(d)}>
            Edit
          </button>
          <button className="btn btn-sm btn-danger" onClick={() => setDeleteTarget(d)}>
            Delete
          </button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Departments"
        breadcrumb="HR"
        action={
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            + New department
          </button>
        }
      />

      {editing && (
        <DepartmentForm
          initial={editing === "new" ? null : editing}
          onDone={async () => {
            setEditing(null);
            await refresh();
          }}
          onCancel={() => setEditing(null)}
        />
      )}

      <DataTable
        columns={columns}
        page={departmentsQuery.data}
        isLoading={departmentsQuery.isLoading}
        isError={departmentsQuery.isError}
        error={departmentsQuery.error}
        currentPage={page}
        onPageChange={setPage}
        sort={sort}
        onSortChange={setSort}
        emptyMessage="No departments yet."
        rowKey={(d) => d.id}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete department?"
        message={
          deleteError ??
          `This cannot be undone if it succeeds. A department with active employees assigned cannot be deleted.`
        }
        confirmLabel="Delete"
        danger
        busy={busy}
        onConfirm={handleDelete}
        onCancel={() => {
          setDeleteTarget(null);
          setDeleteError(null);
        }}
      />
    </div>
  );
}

function DepartmentForm({
  initial,
  onDone,
  onCancel,
}: {
  initial: Department | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { notify } = useToast();
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setFieldError(null);

    const parsed = departmentFormSchema.safeParse({ name, description });
    if (!parsed.success) {
      setFieldError(parsed.error.issues[0]?.message ?? "Invalid input");
      return;
    }

    setSubmitting(true);
    try {
      if (initial) {
        await updateDepartment(initial.id, { name, description: description || null });
        notify("Department updated.");
      } else {
        await createDepartment({ name, description: description || undefined });
        notify("Department created.");
      }
      onDone();
    } catch (err) {
      setError(parseApiError(err).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card stack mb-4" onSubmit={handleSubmit} style={{ maxWidth: 480 }}>
      {error && <div className="alert alert-error">{error}</div>}
      <div className={"field" + (fieldError ? " has-error" : "")}>
        <label>Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        {fieldError && <span className="field-error">{fieldError}</span>}
      </div>
      <div className="field">
        <label>Description</label>
        <textarea rows={2} value={description ?? ""} onChange={(e) => setDescription(e.target.value)} />
      </div>
      <div className="row">
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Saving…" : initial ? "Save changes" : "Create department"}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
