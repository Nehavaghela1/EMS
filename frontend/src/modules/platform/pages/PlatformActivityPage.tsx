import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { listPlatformActivityStats, type CompanyActivityStats } from "../api";

/** Which companies are actually using the product, and which are quiet. The
 * useful default is not alphabetical: it is "who needs attention" — idle
 * companies first, then whoever has work piling up. */

type Sort = "idle" | "busiest" | "waiting";

function activityScore(c: CompanyActivityStats): number {
  const leaves = Object.values(c.leave_requests_by_status ?? {}).reduce((s, n) => s + n, 0);
  return c.punch_count + leaves + c.active_projects + Number(c.approved_hours_logged || 0);
}

export function PlatformActivityPage() {
  const [sort, setSort] = useState<Sort>("idle");
  const stats = useQuery({
    queryKey: ["platform", "stats", "activity"],
    queryFn: () => listPlatformActivityStats({ limit: 100 }),
    retry: false,
  });

  const rows = useMemo(() => {
    const items = [...(stats.data?.items ?? [])];
    if (sort === "busiest") return items.sort((a, b) => activityScore(b) - activityScore(a));
    if (sort === "waiting") {
      return items.sort(
        (a, b) =>
          b.pending_approvals + b.pending_regularizations -
          (a.pending_approvals + a.pending_regularizations)
      );
    }
    return items.sort((a, b) => activityScore(a) - activityScore(b));
  }, [stats.data, sort]);

  const idle = rows.filter((c) => activityScore(c) === 0).length;
  const waiting = rows.reduce((s, c) => s + c.pending_approvals + c.pending_regularizations, 0);

  return (
    <div className="container">
      <PageHeader title="Company activity" breadcrumb="Super Admin" />

      {stats.isLoading && <p className="text-muted">Loading activity…</p>}

      {stats.isError && (
        <div className="card p-6" style={{ borderLeft: "3px solid #dc2626", borderRadius: 0 }}>
          <strong>Could not load activity statistics.</strong>
          <button className="btn btn-sm" style={{ marginTop: "0.5rem" }} onClick={() => stats.refetch()}>
            Try again
          </button>
        </div>
      )}

      {stats.data && (
        <>
          <div className="grid grid-3 gap-4 my-4">
            <div className="card p-4">
              <div className="text-xs text-muted" style={{ textTransform: "uppercase" }}>Companies</div>
              <div style={{ fontSize: "1.75rem", fontWeight: 500 }}>{rows.length}</div>
            </div>
            <div className="card p-4" style={{ borderLeft: idle > 0 ? "3px solid #ca8a04" : undefined, borderRadius: idle > 0 ? 0 : undefined }}>
              <div className="text-xs text-muted" style={{ textTransform: "uppercase" }}>No activity at all</div>
              <div style={{ fontSize: "1.75rem", fontWeight: 500 }}>{idle}</div>
              <div className="text-xs text-muted">Signed up but not using it</div>
            </div>
            <div className="card p-4">
              <div className="text-xs text-muted" style={{ textTransform: "uppercase" }}>Waiting on someone</div>
              <div style={{ fontSize: "1.75rem", fontWeight: 500 }}>{waiting}</div>
              <div className="text-xs text-muted">Approvals and regularizations</div>
            </div>
          </div>

          <div className="flex gap-2 my-4">
            {([
              ["idle", "Quietest first"],
              ["busiest", "Busiest first"],
              ["waiting", "Most waiting"],
            ] as [Sort, string][]).map(([key, label]) => (
              <button
                key={key}
                className={`btn btn-sm ${sort === key ? "btn-primary" : ""}`}
                onClick={() => setSort(key)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="card p-6">
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "#64748b", fontSize: "0.72rem", textTransform: "uppercase" }}>
                  <th style={{ padding: "10px 12px" }}>Company</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Punches</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Leave requests</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Waiting</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Projects</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Hours logged</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => {
                  const leaves = Object.values(c.leave_requests_by_status ?? {}).reduce((s, n) => s + n, 0);
                  const quiet = activityScore(c) === 0;
                  return (
                    <tr key={c.company_id} style={{ borderTop: "1px solid #f1f5f9", opacity: quiet ? 0.65 : 1 }}>
                      <td style={{ padding: "10px 12px" }}>
                        <div style={{ fontWeight: 500 }}>{c.company_name}</div>
                        <div className="text-xs text-muted">
                          {c.company_code}
                          {quiet && " · no activity"}
                        </div>
                      </td>
                      <td style={{ padding: "10px 12px", textAlign: "right" }}>{c.punch_count}</td>
                      <td style={{ padding: "10px 12px", textAlign: "right" }}>{leaves}</td>
                      <td style={{ padding: "10px 12px", textAlign: "right" }}>
                        {c.pending_approvals + c.pending_regularizations > 0 ? (
                          <span style={{ color: "#b45309", fontWeight: 500 }}>
                            {c.pending_approvals + c.pending_regularizations}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td style={{ padding: "10px 12px", textAlign: "right" }}>{c.active_projects}</td>
                      <td style={{ padding: "10px 12px", textAlign: "right" }}>
                        {Number(c.approved_hours_logged || 0).toFixed(1)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
