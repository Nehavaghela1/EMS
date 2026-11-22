import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { fetchPlatformHealth } from "../api";

/** A health panel earns its place by being ignorable: green and quiet until
 * something is actually wrong, then loud. Every number here already existed on
 * /platform/stats/platform-health; nothing in the UI had ever asked for it. */

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, i);
  // One decimal only where it says something: "2 MB" reads better than "2.0 MB".
  const shown = value >= 10 || i === 0 ? String(Math.round(value)) : String(Math.round(value * 10) / 10);
  return `${shown} ${units[i]}`;
}

interface Signal {
  label: string;
  value: number;
  /** At or above this, the signal needs a human. */
  threshold: number;
  hint: string;
}

export function PlatformHealthPage() {
  const health = useQuery({
    queryKey: ["platform", "health"],
    queryFn: fetchPlatformHealth,
    retry: false,
    refetchInterval: 60_000,
  });

  const data = health.data;
  const signals: Signal[] = data
    ? [
        {
          label: "Job failures (24h)",
          value: data.job_failures_last_24h,
          threshold: 1,
          hint: "Background jobs that failed in the last day",
        },
        {
          label: "Jobs queued",
          value: data.jobs_by_status.queued ?? 0,
          threshold: 25,
          hint: "Waiting to start — a growing queue means the worker is behind",
        },
        {
          label: "Rate drafts to verify",
          value: data.rate_drafts_awaiting_verification,
          threshold: 1,
          hint: "Statutory rate changes waiting on a human to confirm",
        },
        {
          label: "Notification backlog",
          value: data.notification_backlog,
          threshold: 500,
          hint: "Unread notifications across the platform",
        },
      ]
    : [];

  const needsAttention = signals.filter((s) => s.value >= s.threshold);
  const allClear = data !== undefined && needsAttention.length === 0;

  const storage = Object.entries(data?.storage_bytes_by_company ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);
  const totalStorage = Object.values(data?.storage_bytes_by_company ?? {}).reduce(
    (sum, n) => sum + n,
    0
  );
  const rateChecks = Object.entries(data?.next_scheduled_rate_checks ?? {});

  return (
    <div className="container">
      <PageHeader title="Platform Health" breadcrumb="Super Admin" />

      {health.isLoading && <p className="text-muted">Checking the platform…</p>}

      {health.isError && (
        <div className="card p-6" style={{ borderLeft: "3px solid #dc2626", borderRadius: 0 }}>
          <strong>Could not reach the health data.</strong>
          <p className="text-muted text-sm">
            The API did not answer. Everything else on this page is unavailable until it does.
          </p>
          <button className="btn btn-sm" onClick={() => health.refetch()}>
            Try again
          </button>
        </div>
      )}

      {data && (
        <>
          <div
            className="card p-4 my-4"
            style={{
              background: allClear ? "#f0fdf4" : "#fef2f2",
              border: `1px solid ${allClear ? "#bbf7d0" : "#fecaca"}`,
            }}
          >
            <div style={{ fontWeight: 500, color: allClear ? "#15803d" : "#b91c1c" }}>
              {allClear
                ? "All clear — nothing needs attention right now."
                : needsAttention.length === 1
                  ? "1 thing needs attention"
                  : `${needsAttention.length} things need attention`}
            </div>
            {!allClear && (
              <div className="text-sm" style={{ color: "#7f1d1d", marginTop: "0.25rem" }}>
                {needsAttention.map((s) => s.label).join(" · ")}
              </div>
            )}
          </div>

          <div className="grid grid-4 gap-4">
            {signals.map((s) => {
              const hot = s.value >= s.threshold;
              return (
                <div
                  key={s.label}
                  className="card p-4"
                  style={{ borderLeft: `3px solid ${hot ? "#dc2626" : "#16a34a"}`, borderRadius: 0 }}
                >
                  <div className="text-xs text-muted" style={{ textTransform: "uppercase" }}>
                    {s.label}
                  </div>
                  <div
                    style={{
                      fontSize: "1.75rem",
                      fontWeight: 500,
                      color: hot ? "#b91c1c" : "#0f172a",
                    }}
                  >
                    {s.value}
                  </div>
                  <div className="text-xs text-muted">{s.hint}</div>
                </div>
              );
            })}
          </div>

          <div className="card my-4 p-6">
            <h3>Storage by company</h3>
            <p className="text-muted text-sm">
              {totalStorage > 0
                ? `${formatBytes(totalStorage)} in total across ${Object.keys(data.storage_bytes_by_company).length} companies.`
                : "No files stored yet."}
            </p>
            {storage.length > 0 && (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                <thead>
                  <tr style={{ textAlign: "left", color: "#64748b" }}>
                    <th style={{ padding: "8px 0" }}>COMPANY</th>
                    <th style={{ padding: "8px 0", textAlign: "right" }}>STORED</th>
                  </tr>
                </thead>
                <tbody>
                  {storage.map(([companyId, bytes]) => (
                    <tr key={companyId} style={{ borderTop: "1px solid #f1f5f9" }}>
                      <td style={{ padding: "8px 0", fontFamily: "monospace", fontSize: "0.75rem" }}>
                        {companyId}
                      </td>
                      <td style={{ padding: "8px 0", textAlign: "right" }}>{formatBytes(bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card my-4 p-6">
            <h3>Next scheduled rate checks</h3>
            {rateChecks.length === 0 ? (
              <p className="text-muted text-sm">
                Nothing scheduled. Rate sources are checked daily by the beat scheduler; an empty
                list usually means beat is not running.
              </p>
            ) : (
              <ul className="text-sm">
                {rateChecks.map(([source, when]) => (
                  <li key={source}>
                    {source} — {String(when)}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
