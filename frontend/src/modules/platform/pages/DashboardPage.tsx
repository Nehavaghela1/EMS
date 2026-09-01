import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { parseApiError } from "../../../shared/api/errors";
import { fetchDashboard } from "../api";

/**
 * A genuine, working integration with route 121 (`GET /dashboard`,
 * WP-11) — not a mock. Page 6's role-shaped, designed layout is WP-14's
 * job (Spec 14.3); this is deliberately the "placeholder dashboard" WP-12's
 * gate asks for: proof that login → protected route → a real authenticated
 * API call all work end to end.
 */
export function DashboardPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: fetchDashboard,
  });

  return (
    <div>
      <PageHeader title="Dashboard" breadcrumb="Overview" />
      <div className="card">
        {isLoading && (
          <div className="row">
            <div className="spinner" />
            <span className="text-muted">Loading…</span>
          </div>
        )}
        {isError && <div className="alert alert-error">{parseApiError(error).message}</div>}
        {data && (
          <div className="stack">
            <div className="row">
              <span className="badge badge-muted">{data.role}</span>
              <span className="text-muted" style={{ fontSize: 12 }}>
                as of {new Date(data.generated_at).toLocaleString()}
              </span>
            </div>
            <div className="form-grid">
              {Object.entries(data.data).map(([key, value]) => (
                <div key={key} className="field">
                  <label>{key.replace(/_/g, " ")}</label>
                  <div>
                    {typeof value === "object" ? (
                      <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap" }}>
                        {JSON.stringify(value, null, 2)}
                      </pre>
                    ) : (
                      String(value)
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
