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
  listCompanies,
  getCompanyDetail,
  updateCompanyByAdmin,
  rejectCompany,
  type CompanyApproveResult,
  type CompanyResponse,
  type CompanyDetailResponse,
  type AdminCompanyUpdateInput,
} from "../api";
import { formatDate } from "../../../shared/utils/date";

export function AdminDashboardPage() {
  const [activeTab, setActiveTab] = useState<"all" | "pending">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const statsQuery = useQuery({ queryKey: ["dashboard"], queryFn: fetchDashboard });
  const { page, limit, setPage } = usePagination();
  const queryClient = useQueryClient();

  // Pending companies query
  const pendingQuery = useQuery({
    queryKey: ["companies", "pending", { page, limit }],
    queryFn: () => listPendingCompanies(page, limit),
    enabled: activeTab === "pending",
    placeholderData: (prev) => prev,
  });

  // All companies query
  const allCompaniesQuery = useQuery({
    queryKey: ["companies", "all", { page, limit, status: statusFilter, q: searchQuery }],
    queryFn: () => listCompanies({ page, limit, status: statusFilter, q: searchQuery }),
    enabled: activeTab === "all",
    placeholderData: (prev) => prev,
  });

  const [approveTarget, setApproveTarget] = useState<CompanyResponse | null>(null);
  const [rejectTarget, setRejectTarget] = useState<CompanyResponse | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [approved, setApproved] = useState<CompanyApproveResult | null>(null);

  // Edit / Details Modal state
  const [editTargetId, setEditTargetId] = useState<string | null>(null);
  const [editFormData, setEditFormData] = useState<AdminCompanyUpdateInput>({});
  const [editLoading, setEditLoading] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [editSuccess, setEditSuccess] = useState<string | null>(null);
  const [companyDetail, setCompanyDetail] = useState<CompanyDetailResponse | null>(null);

  async function refreshCompanies() {
    await queryClient.invalidateQueries({ queryKey: ["companies"] });
    await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  }

  async function openEditModal(company: CompanyResponse) {
    setEditTargetId(company.id);
    setEditLoading(true);
    setEditError(null);
    setEditSuccess(null);
    try {
      const detail = await getCompanyDetail(company.id);
      setCompanyDetail(detail);
      setEditFormData({
        name: detail.name || "",
        phone: detail.phone || "",
        industry: detail.industry || "",
        status: detail.status || "active",
        address: (detail as any).address || "",
        city: (detail as any).city || "",
        state: (detail as any).state || "",
        pincode: (detail as any).pincode || "",
        website: (detail as any).website || "",
      });
    } catch (err) {
      setEditError(parseApiError(err).message);
    } finally {
      setEditLoading(false);
    }
  }

  async function handleSaveCompany(e: React.FormEvent) {
    e.preventDefault();
    if (!editTargetId) return;
    setBusy(true);
    setEditError(null);
    setEditSuccess(null);
    try {
      await updateCompanyByAdmin(editTargetId, editFormData);
      setEditSuccess("Company updated successfully!");
      await refreshCompanies();
      setTimeout(() => {
        setEditTargetId(null);
        setEditSuccess(null);
      }, 1000);
    } catch (err) {
      setEditError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleApprove() {
    if (!approveTarget) return;
    setBusy(true);
    setActionError(null);
    try {
      const result = await approveCompany(approveTarget.id);
      setApproved(result);
      setApproveTarget(null);
      await refreshCompanies();
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
      await refreshCompanies();
    } catch (err) {
      setActionError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  }

  const allColumns: DataTableColumn<CompanyResponse>[] = [
    { key: "name", label: "Company Name", render: (c) => <strong>{c.name}</strong> },
    {
      key: "code",
      label: "Code",
      render: (c) => <code style={{ fontSize: "11px", padding: "2px 6px" }}>{c.code}</code>,
    },
    { key: "email", label: "Email", render: (c) => c.email },
    { key: "industry", label: "Industry", render: (c) => c.industry ?? "—" },
    {
      key: "status",
      label: "Status",
      render: (c) => {
        let badgeClass = "badge badge-muted";
        if (c.status === "active") badgeClass = "badge badge-success";
        else if (c.status === "pending") badgeClass = "badge badge-warning";
        else if (c.status === "rejected") badgeClass = "badge badge-danger";
        else if (c.status === "suspended") badgeClass = "badge badge-danger";
        return <span className={badgeClass}>{c.status.toUpperCase()}</span>;
      },
    },
    { key: "created_at", label: "Registered", render: (c) => formatDate(c.created_at) },
    {
      key: "actions",
      label: "Actions",
      render: (c) => (
        <div className="row" style={{ gap: "var(--space-2)" }}>
          <button
            className="btn btn-sm btn-ghost"
            onClick={() => openEditModal(c)}
            title="View details or edit company"
          >
            View / Edit
          </button>
          {c.status === "pending" && (
            <>
              <button className="btn btn-sm btn-primary" onClick={() => setApproveTarget(c)}>
                Approve
              </button>
              <button className="btn btn-sm btn-danger" onClick={() => setRejectTarget(c)}>
                Reject
              </button>
            </>
          )}
        </div>
      ),
    },
  ];

  const pendingColumns: DataTableColumn<CompanyResponse>[] = [
    { key: "name", label: "Name", render: (c) => c.name },
    { key: "code", label: "Code", render: (c) => c.code },
    { key: "email", label: "Email", render: (c) => c.email },
    { key: "industry", label: "Industry", render: (c) => c.industry ?? "—" },
    { key: "created_at", label: "Registered", render: (c) => formatDate(c.created_at) },
    {
      key: "actions",
      label: "Actions",
      render: (c) => (
        <div className="row" style={{ gap: "var(--space-2)" }}>
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
      <PageHeader title="Platform Admin & Company Management" breadcrumb="Super Admin" />

      {stats && (
        <div className="stat-grid mb-6">
          <div
            className="card"
            style={{ cursor: "pointer", border: activeTab === "pending" ? "2px solid var(--color-primary)" : undefined }}
            onClick={() => setActiveTab("pending")}
          >
            <div className="stat-label">Pending approvals</div>
            <div className="stat-value">{stats.pending_approvals}</div>
            <div className="text-xs text-muted mt-1">Click to view pending requests</div>
          </div>
          <div className="card">
            <div className="stat-label">Platform users</div>
            <div className="stat-value">{stats.platform_user_count}</div>
            <div className="text-xs text-muted mt-1">Across all registered tenants</div>
          </div>
          {Object.entries(stats.company_counts_by_status).map(([status, count]) => (
            <div
              className="card"
              key={status}
              style={{
                cursor: "pointer",
                border: activeTab === "all" && statusFilter === status ? "2px solid var(--color-primary)" : undefined,
              }}
              onClick={() => {
                setActiveTab("all");
                setStatusFilter(status);
              }}
            >
              <div className="stat-label">Companies — {status}</div>
              <div className="stat-value">{count}</div>
              <div className="text-xs text-muted mt-1">Click to filter by {status}</div>
            </div>
          ))}
        </div>
      )}

      {approved && (
        <div className="alert alert-success stack mb-4">
          <div>
            Approved <strong>{approved.company.name}</strong>. Login credentials for{" "}
            <code>{approved.hr_admin_email}</code> have been sent (and copied to your inbox).
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

      {/* Navigation Tabs */}
      <div className="row mb-4" style={{ gap: "var(--space-2)", borderBottom: "1px solid var(--color-border)", paddingBottom: "var(--space-2)" }}>
        <button
          className={`btn btn-sm ${activeTab === "all" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => {
            setActiveTab("all");
            setPage(1);
          }}
        >
          🏢 All Registered Companies
        </button>
        <button
          className={`btn btn-sm ${activeTab === "pending" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => {
            setActiveTab("pending");
            setPage(1);
          }}
        >
          ⏳ Pending Approvals {stats && stats.pending_approvals > 0 ? `(${stats.pending_approvals})` : ""}
        </button>
      </div>

      {activeTab === "all" && (
        <>
          <div className="card mb-4" style={{ padding: "var(--space-3)" }}>
            <div className="row" style={{ gap: "var(--space-3)", flexWrap: "wrap", alignItems: "center" }}>
              <div style={{ flex: 1, minWidth: "220px" }}>
                <input
                  type="text"
                  placeholder="🔍 Search by company name or code..."
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setPage(1);
                  }}
                  className="input"
                  style={{ width: "100%" }}
                />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                <span className="text-sm font-semibold">Status:</span>
                <select
                  value={statusFilter}
                  onChange={(e) => {
                    setStatusFilter(e.target.value);
                    setPage(1);
                  }}
                  className="input"
                  style={{ width: "auto" }}
                >
                  <option value="all">All Statuses</option>
                  <option value="active">Active</option>
                  <option value="pending">Pending</option>
                  <option value="rejected">Rejected</option>
                  <option value="suspended">Suspended</option>
                </select>
              </div>
              {(searchQuery || statusFilter !== "all") && (
                <button
                  className="btn btn-sm btn-ghost"
                  onClick={() => {
                    setSearchQuery("");
                    setStatusFilter("all");
                    setPage(1);
                  }}
                >
                  Clear Filters
                </button>
              )}
            </div>
          </div>

          <DataTable
            columns={allColumns}
            page={allCompaniesQuery.data}
            isLoading={allCompaniesQuery.isLoading}
            isError={allCompaniesQuery.isError}
            error={allCompaniesQuery.error}
            currentPage={page}
            onPageChange={setPage}
            sort={null}
            onSortChange={() => {}}
            emptyMessage="No companies found matching the criteria."
            rowKey={(c) => c.id}
          />
        </>
      )}

      {activeTab === "pending" && (
        <>
          <PageHeader title="Pending Company Approvals" />
          <DataTable
            columns={pendingColumns}
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
        </>
      )}

      {/* Edit / Detail Modal */}
      {editTargetId && (
        <div className="modal-backdrop" onClick={() => setEditTargetId(null)}>
          <div
            className="modal stack"
            style={{ maxWidth: "600px", width: "95%" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
              <h3>🏢 Company Details & Profile</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setEditTargetId(null)}
                disabled={busy}
                title="Close"
              >
                ✕
              </button>
            </div>

            {editLoading ? (
              <div className="row justify-center py-6">
                <div className="spinner" />
                <span className="ml-2 text-muted">Loading company profile...</span>
              </div>
            ) : (
              <form onSubmit={handleSaveCompany} className="stack">
                {editError && <div className="alert alert-error">{editError}</div>}
                {editSuccess && <div className="alert alert-success">{editSuccess}</div>}

                {companyDetail && (
                  <div className="card mb-3" style={{ background: "var(--color-bg-subtle)", padding: "var(--space-3)" }}>
                    <div className="stat-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--space-2)" }}>
                      <div>
                        <span className="text-xs text-muted block">Company Code</span>
                        <code>{companyDetail.code}</code>
                      </div>
                      <div>
                        <span className="text-xs text-muted block">Total Users</span>
                        <strong>{companyDetail.counts?.users ?? 0}</strong>
                      </div>
                      <div>
                        <span className="text-xs text-muted block">Departments</span>
                        <strong>{companyDetail.counts?.departments ?? 0}</strong>
                      </div>
                      <div>
                        <span className="text-xs text-muted block">Registered Date</span>
                        <span>{formatDate(companyDetail.created_at)}</span>
                      </div>
                      <div>
                        <span className="text-xs text-muted block">Approved Date</span>
                        <span>{companyDetail.approved_at ? formatDate(companyDetail.approved_at) : "—"}</span>
                      </div>
                      <div>
                        <span className="text-xs text-muted block">Email</span>
                        <span style={{ fontSize: "12px", wordBreak: "break-all" }}>{companyDetail.email}</span>
                      </div>
                    </div>
                    {companyDetail.rejection_reason && (
                      <div className="mt-2 text-xs text-danger">
                        <strong>Rejection Reason:</strong> {companyDetail.rejection_reason}
                      </div>
                    )}
                  </div>
                )}

                <div className="row" style={{ gap: "var(--space-3)" }}>
                  <div className="field" style={{ flex: 2 }}>
                    <label>Company Name *</label>
                    <input
                      type="text"
                      required
                      value={editFormData.name ?? ""}
                      onChange={(e) => setEditFormData({ ...editFormData, name: e.target.value })}
                    />
                  </div>
                  <div className="field" style={{ flex: 1 }}>
                    <label>Status</label>
                    <select
                      value={editFormData.status ?? "active"}
                      onChange={(e) => setEditFormData({ ...editFormData, status: e.target.value })}
                    >
                      <option value="active">Active</option>
                      <option value="pending">Pending</option>
                      <option value="suspended">Suspended</option>
                      <option value="rejected">Rejected</option>
                    </select>
                  </div>
                </div>

                <div className="row" style={{ gap: "var(--space-3)" }}>
                  <div className="field" style={{ flex: 1 }}>
                    <label>Industry</label>
                    <input
                      type="text"
                      value={editFormData.industry ?? ""}
                      onChange={(e) => setEditFormData({ ...editFormData, industry: e.target.value })}
                    />
                  </div>
                  <div className="field" style={{ flex: 1 }}>
                    <label>Phone</label>
                    <input
                      type="text"
                      value={editFormData.phone ?? ""}
                      onChange={(e) => setEditFormData({ ...editFormData, phone: e.target.value })}
                    />
                  </div>
                </div>

                <div className="field">
                  <label>Website</label>
                  <input
                    type="text"
                    placeholder="https://..."
                    value={editFormData.website ?? ""}
                    onChange={(e) => setEditFormData({ ...editFormData, website: e.target.value })}
                  />
                </div>

                <div className="field">
                  <label>Address</label>
                  <input
                    type="text"
                    value={editFormData.address ?? ""}
                    onChange={(e) => setEditFormData({ ...editFormData, address: e.target.value })}
                  />
                </div>

                <div className="row" style={{ gap: "var(--space-3)" }}>
                  <div className="field" style={{ flex: 1 }}>
                    <label>City</label>
                    <input
                      type="text"
                      value={editFormData.city ?? ""}
                      onChange={(e) => setEditFormData({ ...editFormData, city: e.target.value })}
                    />
                  </div>
                  <div className="field" style={{ flex: 1 }}>
                    <label>State</label>
                    <input
                      type="text"
                      value={editFormData.state ?? ""}
                      onChange={(e) => setEditFormData({ ...editFormData, state: e.target.value })}
                    />
                  </div>
                  <div className="field" style={{ flex: 1 }}>
                    <label>Pincode</label>
                    <input
                      type="text"
                      value={editFormData.pincode ?? ""}
                      onChange={(e) => setEditFormData({ ...editFormData, pincode: e.target.value })}
                    />
                  </div>
                </div>

                <div className="row-end" style={{ gap: "var(--space-2)", marginTop: "var(--space-3)" }}>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => setEditTargetId(null)}
                    disabled={busy}
                  >
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-primary" disabled={busy}>
                    {busy ? "Saving Changes..." : "Save Changes"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Confirm Approve Dialog */}
      <ConfirmDialog
        open={Boolean(approveTarget)}
        title="Approve company?"
        message={
          actionError ??
          `Approving ${approveTarget?.name ?? ""} seeds its departments, leave types, and company settings, creates an HR admin account, and sends credentials via email.`
        }
        confirmLabel="Approve"
        busy={busy}
        onConfirm={handleApprove}
        onCancel={() => {
          setApproveTarget(null);
          setActionError(null);
        }}
      />

      {/* Reject Dialog */}
      {rejectTarget && (
        <div className="modal-backdrop" onClick={() => setRejectTarget(null)}>
          <div className="modal stack" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
              <h3>Reject {rejectTarget.name}?</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => {
                  setRejectTarget(null);
                  setActionError(null);
                }}
                disabled={busy}
                title="Close"
              >
                ✕
              </button>
            </div>
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

