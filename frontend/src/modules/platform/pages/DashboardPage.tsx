import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { parseApiError } from "../../../shared/api/errors";
import { TodayAttendanceCard } from "../../time_leave/components/TodayAttendanceCard";
import { fetchDashboard, fetchAnnouncements } from "../api";
import {
  listCompanies,
  getCompanyDetail,
  updateCompanyByAdmin,
  type CompanyResponse,
  type CompanyDetailResponse,
  type AdminCompanyUpdateInput,
} from "../../identity/api";
import { formatDate } from "../../../shared/utils/date";

function Stat({ label, value, to, subtitle }: { label: string; value: React.ReactNode; to?: string; subtitle?: string }) {
  const content = (
    <div className="card" style={to ? { cursor: "pointer" } : undefined}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {subtitle && <div className="text-xs text-muted mt-1">{subtitle}</div>}
    </div>
  );

  if (to) {
    return <Link to={to} style={{ textDecoration: "none", color: "inherit" }}>{content}</Link>;
  }
  return content;
}

/**
 * Page 6 (Spec 14.3): one page against GET /dashboard, rendering whichever
 * of Spec 11.10's four role shapes comes back — not four separate pages.
 * super_admin also has its own page (5, `/admin`) with the platform-stats
 * subset of this same payload plus pending-company approve/reject actions
 * this endpoint doesn't provide; this page still renders the super_admin
 * shape too so the route works for any authenticated role, per Spec
 * 14.3's "Auth" access column.
 */
export function DashboardPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: fetchDashboard,
  });

  const announcementsQuery = useQuery({
    queryKey: ["announcements"],
    queryFn: fetchAnnouncements,
  });

  return (
    <div>
      <PageHeader title="Dashboard" breadcrumb="Overview" />

      {/* Announcements Banner / List */}
      {announcementsQuery.data && announcementsQuery.data.length > 0 && (
        <div className="card mb-4" style={{ borderLeft: "4px solid var(--color-primary)" }}>
          <div className="row-between mb-2">
            <h3 className="mb-0" style={{ fontSize: "var(--text-base)" }}>Company Announcements</h3>
            <span className="badge badge-muted">{announcementsQuery.data.length} new</span>
          </div>
          <div className="stack-sm">
            {announcementsQuery.data.map((ann) => (
              <div key={ann.id} style={{ padding: "var(--space-2) 0", borderBottom: "1px solid var(--color-border)" }}>
                <div className="font-semibold text-sm">{ann.title}</div>
                <div className="text-muted text-sm">{ann.content}</div>
                <div className="text-faint text-xs mt-1">{formatDate(ann.created_at)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Part 2: check in/out from the landing page directly — no need to
          visit the shared attendance screen. Renders nothing for a role
          with no linked employee record (e.g. an HR admin created at
          company approval, WP-05). */}
      <TodayAttendanceCard showWhenNoEmployee={false} />

      {isLoading && (
        <div className="row">
          <div className="spinner" />
          <span className="text-muted">Loading…</span>
        </div>
      )}
      {isError && <div className="alert alert-error">{parseApiError(error).message}</div>}

      {data && (
        <div className="stack">
          <span className="text-xs text-faint">
            Updated {new Date(data.generated_at).toLocaleString()}
          </span>

          {data.role === "super_admin" && (
            <div className="stack">
              <div className="row-between mb-2">
                <h3 className="mb-0">Platform Overview</h3>
                <Link to="/admin" className="btn btn-sm btn-ghost">
                  Go to Approvals & Pending Queue →
                </Link>
              </div>
              <div className="stat-grid mb-4">
                <Stat
                  label="Pending approvals"
                  value={data.data.pending_approvals}
                  to="/admin"
                  subtitle="Click to view & approve"
                />
                <Stat
                  label="Platform users"
                  value={data.data.platform_user_count}
                  subtitle="Across all companies"
                />
                {Object.entries(data.data.company_counts_by_status).map(([status, count]) => (
                  <Stat
                    key={status}
                    label={`Companies — ${status}`}
                    value={count}
                    subtitle={`Total ${status} tenants`}
                  />
                ))}
              </div>

              {/* Directly visible Companies Directory on Dashboard */}
              <SuperAdminCompaniesSection />
            </div>
          )}

          {data.role === "hr_admin" && (
            <>
              <div className="stat-grid">
                <Stat label="Headcount" value={data.data.headcount} />
                <Stat label="Present today" value={data.data.present_today} />
                <Stat label="On leave today" value={data.data.on_leave_today} />
                <Stat label="Pending leave requests" value={data.data.pending_leave_requests} />
              </div>
              <div className="card">
                <h3>Department distribution</h3>
                {Object.keys(data.data.department_distribution).length === 0 ? (
                  <span className="text-muted">No departments yet.</span>
                ) : (
                  <div className="stack-sm">
                    {Object.entries(data.data.department_distribution).map(([name, count]) => (
                      <div key={name} className="row-between">
                        <span>{name}</span>
                        <span className="text-muted">{count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="card">
                <h3>Recent hires</h3>
                {data.data.recent_hires.length === 0 ? (
                  <span className="text-muted">No recent hires.</span>
                ) : (
                  <div className="stack-sm">
                    {data.data.recent_hires.map((h) => (
                      <div key={h.id} className="row-between">
                        <span>
                          {h.first_name}
                          {h.last_name ? ` ${h.last_name}` : ""}
                        </span>
                        <span className="text-muted">{h.hire_date}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}

          {data.role === "manager" && (
            <div className="stat-grid">
              <Stat label="Team headcount" value={data.data.team_headcount} />
              <Stat label="Team present today" value={data.data.team_present_today} />
              <Stat
                label="Team leave requests awaiting you"
                value={data.data.team_leave_requests_awaiting}
              />
            </div>
          )}

          {data.role === "employee" && (
            <>
              <div className="stat-grid">
                <Stat label="Pending requests" value={data.data.pending_requests} />
                {Object.entries(data.data.attendance_this_month).map(([status, count]) => (
                  <Stat key={status} label={`This month — ${status.replace("_", " ")}`} value={count} />
                ))}
              </div>
              <div className="card">
                <h3>Leave balances</h3>
                {data.data.leave_balances.length === 0 ? (
                  <span className="text-muted">No leave balances yet.</span>
                ) : (
                  <div className="stack-sm">
                    {data.data.leave_balances.map((b) => (
                      <div key={b.leave_type_id} className="row-between">
                        <span>{b.leave_type_name ?? "Unknown leave type"}</span>
                        <span className="text-muted">{b.available} available</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function SuperAdminCompaniesSection() {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const { page, limit, setPage } = usePagination(10);
  const queryClient = useQueryClient();

  const companiesQuery = useQuery({
    queryKey: ["companies", "dashboard", { page, limit, status: statusFilter, q: searchQuery }],
    queryFn: () => listCompanies({ page, limit, status: statusFilter, q: searchQuery }),
    placeholderData: (prev) => prev,
  });

  // Modal edit state
  const [editTargetId, setEditTargetId] = useState<string | null>(null);
  const [editFormData, setEditFormData] = useState<AdminCompanyUpdateInput>({});
  const [editLoading, setEditLoading] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [editSuccess, setEditSuccess] = useState<string | null>(null);
  const [companyDetail, setCompanyDetail] = useState<CompanyDetailResponse | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["companies"] });
    await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  }

  async function openEdit(company: CompanyResponse) {
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

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!editTargetId) return;
    setBusy(true);
    setEditError(null);
    setEditSuccess(null);
    try {
      await updateCompanyByAdmin(editTargetId, editFormData);
      setEditSuccess("Company updated successfully!");
      await refresh();
      setTimeout(() => {
        setEditTargetId(null);
        setEditSuccess(null);
      }, 900);
    } catch (err) {
      setEditError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  }

  const columns: DataTableColumn<CompanyResponse>[] = [
    { key: "name", label: "Company Name", render: (c) => <strong>{c.name}</strong> },
    {
      key: "code",
      label: "Code",
      render: (c) => <code style={{ fontSize: "11px", padding: "2px 6px" }}>{c.code}</code>,
    },
    { key: "email", label: "Company Email", render: (c) => c.email },
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
      label: "Action",
      render: (c) => (
        <button
          className="btn btn-sm btn-ghost"
          onClick={() => openEdit(c)}
          title="View metrics or edit company profile"
        >
          View / Edit
        </button>
      ),
    },
  ];

  return (
    <div className="card mt-4" style={{ padding: "var(--space-4)" }}>
      <div className="row-between mb-4">
        <div>
          <h3 className="mb-0">🏢 Registered Companies Directory</h3>
          <span className="text-xs text-muted">
            All onboarded client companies across the EMS platform
          </span>
        </div>
        <Link to="/admin" className="btn btn-sm btn-primary">
          Open Full Management Portal →
        </Link>
      </div>

      <div className="row mb-4" style={{ gap: "var(--space-3)", flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ flex: 1, minWidth: "220px" }}>
          <input
            type="text"
            placeholder="🔍 Search company by name or code..."
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
          <span className="text-sm font-semibold">Filter:</span>
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
            Reset
          </button>
        )}
      </div>

      <DataTable
        columns={columns}
        page={companiesQuery.data}
        isLoading={companiesQuery.isLoading}
        isError={companiesQuery.isError}
        error={companiesQuery.error}
        currentPage={page}
        onPageChange={setPage}
        sort={null}
        onSortChange={() => {}}
        emptyMessage="No companies found."
        rowKey={(c) => c.id}
      />

      {/* Edit Modal */}
      {editTargetId && (
        <div className="modal-backdrop" onClick={() => setEditTargetId(null)}>
          <div
            className="modal stack"
            style={{ maxWidth: "600px", width: "95%" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
              <h3>🏢 Company Details & Edit Profile</h3>
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
                <span className="ml-2 text-muted">Loading profile...</span>
              </div>
            ) : (
              <form onSubmit={handleSave} className="stack">
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
                        <span className="text-xs text-muted block">Registered</span>
                        <span>{formatDate(companyDetail.created_at)}</span>
                      </div>
                      <div>
                        <span className="text-xs text-muted block">Approved Date</span>
                        <span>{companyDetail.approved_at ? formatDate(companyDetail.approved_at) : "—"}</span>
                      </div>
                      <div>
                        <span className="text-xs text-muted block">Registered Email</span>
                        <span style={{ fontSize: "12px", wordBreak: "break-all" }}>{companyDetail.email}</span>
                      </div>
                    </div>
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
                    {busy ? "Saving..." : "Save Changes"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
