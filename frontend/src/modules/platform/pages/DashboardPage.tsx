import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { parseApiError } from "../../../shared/api/errors";
import { fetchDashboard } from "../api";

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
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

  return (
    <div>
      <PageHeader title="Dashboard" breadcrumb="Overview" />

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
            <div className="stat-grid">
              <Stat label="Pending approvals" value={data.data.pending_approvals} />
              <Stat label="Platform users" value={data.data.platform_user_count} />
              {Object.entries(data.data.company_counts_by_status).map(([status, count]) => (
                <Stat key={status} label={`Companies — ${status}`} value={count} />
              ))}
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
