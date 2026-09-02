import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog";
import { usePagination } from "../../../shared/hooks/usePagination";
import { parseApiError } from "../../../shared/api/errors";
import { fetchDashboard } from "../../platform/api";
import {
  approveCompany,
  listPendingCompanies,
  rejectCompany,
  type CompanyApproveResult,
  type CompanyResponse,
} from "../api";

/**
 * Page 5 (Spec 14.3, super_admin only): platform stats plus the pending
 * companies list with approve/reject — a distinct shape from page 6
 * (`/dashboard`). `GET /dashboard`'s super_admin payload gives the stats
 * half; it has no list of pending companies or any mutation, so this page
 * layers `GET /companies?status=pending` and the approve/reject routes on
 * top of the same dashboard call rather than duplicating the stats
 * elsewhere.
 */
export function AdminDashboardPage() {
  const statsQuery = useQuery({ queryKey: ["dashboard"], queryFn: fetchDashboard });
  const { page, limit, setPage } = usePagination();
  const queryClient = useQueryClient();

  const pendingQuery = useQuery({
    queryKey: ["companies", "pending", { page, limit }],
    queryFn: () => listPendingCompanies(page, limit),
    placeholderData: (prev) => prev,
  });

  const [approveTarget, setApproveTarget] = useState<CompanyResponse | null>(null);
  const [rejectTarget, setRejectTarget] = useState<CompanyResponse | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [approved, setApproved] = useState<CompanyApproveResult | null>(null);

  async function refreshPending() {
    await queryClient.invalidateQueries({ queryKey: ["companies", "pending"] });
  }

  async function handleApprove() {
    if (!approveTarget) return;
    setBusy(true);
    setActionError(null);
    try {
      const result = await approveCompany(approveTarget.id);
      setApproved(result);
      setApproveTarget(null);
      await refreshPending();
    } catch (err) {
      setActionError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleReject() {
    if (!rejectTarget) return;
    if (!rejectReason.trim()) {
      setActionError("A reason is required.");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await rejectCompany(rejectTarget.id, rejectReason.trim());
      setRejectTarget(null);
      setRejectReason("");
      await refreshPending();
    } catch (err) {
      setActionError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  }

  const columns: DataTableColumn<CompanyResponse>[] = [
    { key: "name", label: "Name", render: (c) => c.name },
    { key: "code", label: "Code", render: (c) => c.code },
    { key: "email", label: "Email", render: (c) => c.email },
    { key: "industry", label: "Industry", render: (c) => c.industry ?? "—" },
    { key: "created_at", label: "Registered", render: (c) => new Date(c.created_at).toLocaleDateString() },
    {
      key: "actions",
      label: "",
      render: (c) => (
        <div className="row">
          <button className="btn btn-sm btn-primary" onClick={() => setApproveTarget(c)}>
            Approve
          </button>
          <button className="btn btn-sm btn-danger" onClick={() => setRejectTarget(c)}>
            Reject
          </button>
        </div>
      ),
    },
  ];

  const stats = statsQuery.data?.role === "super_admin" ? statsQuery.data.data : null;

  return (
    <div>
      <PageHeader title="Platform admin" breadcrumb="Super admin" />

      {stats && (
        <div className="stat-grid mb-6">
          <div className="card">
            <div className="stat-label">Pending approvals</div>
            <div className="stat-value">{stats.pending_approvals}</div>
          </div>
          <div className="card">
            <div className="stat-label">Platform users</div>
            <div className="stat-value">{stats.platform_user_count}</div>
          </div>
          {Object.entries(stats.company_counts_by_status).map(([status, count]) => (
            <div className="card" key={status}>
              <div className="stat-label">Companies — {status}</div>
              <div className="stat-value">{count}</div>
            </div>
          ))}
        </div>
      )}

      {approved && (
        <div className="alert alert-success stack mb-4">
          <div>
            Approved <strong>{approved.company.name}</strong>. Login credentials for{" "}
            <code>{approved.hr_admin_email}</code> have been emailed to them directly.
          </div>
          <button
            className="btn btn-sm btn-ghost"
            style={{ width: "fit-content" }}
            onClick={() => setApproved(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      <PageHeader title="Pending companies" />
      <DataTable
        columns={columns}
        page={pendingQuery.data}
        isLoading={pendingQuery.isLoading}
        isError={pendingQuery.isError}
        error={pendingQuery.error}
        currentPage={page}
        onPageChange={setPage}
        sort={null}
        onSortChange={() => {}}
        emptyMessage="No companies awaiting approval."
        rowKey={(c) => c.id}
      />

      <ConfirmDialog
        open={Boolean(approveTarget)}
        title="Approve company?"
        message={
          actionError ??
          `Approving ${approveTarget?.name ?? ""} seeds its departments, leave types and company settings, and creates an HR admin account.`
        }
        confirmLabel="Approve"
        busy={busy}
        onConfirm={handleApprove}
        onCancel={() => {
          setApproveTarget(null);
          setActionError(null);
        }}
      />

      {rejectTarget && (
        <div className="modal-backdrop" onClick={() => setRejectTarget(null)}>
          <div className="modal stack" onClick={(e) => e.stopPropagation()}>
            <h3>Reject {rejectTarget.name}?</h3>
            {actionError && <div className="alert alert-error">{actionError}</div>}
            <div className="field">
              <label htmlFor="reject_reason">Reason</label>
              <textarea
                id="reject_reason"
                rows={3}
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                autoFocus
              />
            </div>
            <div className="row-end">
              <button
                className="btn"
                onClick={() => {
                  setRejectTarget(null);
                  setActionError(null);
                }}
                disabled={busy}
              >
                Cancel
              </button>
              <button className="btn btn-danger" onClick={handleReject} disabled={busy}>
                {busy ? "Working…" : "Reject"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
