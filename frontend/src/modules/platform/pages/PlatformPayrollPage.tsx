import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { listPlatformPayrollStats, type CompanyMonthlyPayrollStats } from "../api";

/** Net paid across every company, by month. One chart rather than five: it is
 * the clearest single proof the product is doing its job. The data comes from
 * /platform/stats/payroll, which has always been there and was never called. */

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function monthKey(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

function formatMoney(value: number): string {
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/** The last twelve months ending with the current one, oldest first. */
function lastTwelveMonths(): { year: number; month: number }[] {
  const now = new Date();
  const out: { year: number; month: number }[] = [];
  for (let back = 11; back >= 0; back--) {
    const d = new Date(now.getFullYear(), now.getMonth() - back, 1);
    out.push({ year: d.getFullYear(), month: d.getMonth() + 1 });
  }
  return out;
}

export function PlatformPayrollPage() {
  const months = useMemo(lastTwelveMonths, []);
  const from = monthKey(months[0].year, months[0].month);
  const to = monthKey(months[months.length - 1].year, months[months.length - 1].month);

  const stats = useQuery({
    queryKey: ["platform", "stats", "payroll", from, to],
    queryFn: () => listPlatformPayrollStats({ from, to, limit: 100 }),
    retry: false,
  });

  const rows: CompanyMonthlyPayrollStats[] = stats.data?.items ?? [];

  const byMonth = useMemo(() => {
    const totals = new Map<string, number>();
    for (const r of rows) {
      const key = monthKey(r.year, r.month);
      totals.set(key, (totals.get(key) ?? 0) + Number(r.total_net_paid || 0));
    }
    return months.map((m) => ({
      key: monthKey(m.year, m.month),
      label: MONTH_NAMES[m.month - 1],
      year: m.year,
      value: totals.get(monthKey(m.year, m.month)) ?? 0,
    }));
  }, [rows, months]);

  const peak = Math.max(...byMonth.map((m) => m.value), 1);
  const thisMonth = byMonth[byMonth.length - 1]?.value ?? 0;
  const lastMonth = byMonth[byMonth.length - 2]?.value ?? 0;
  const change = lastMonth > 0 ? ((thisMonth - lastMonth) / lastMonth) * 100 : null;

  const latestByCompany = useMemo(() => {
    const seen = new Map<string, CompanyMonthlyPayrollStats>();
    for (const r of rows) {
      const current = seen.get(r.company_id);
      if (!current || r.year > current.year || (r.year === current.year && r.month > current.month)) {
        seen.set(r.company_id, r);
      }
    }
    return [...seen.values()].sort(
      (a, b) => Number(b.total_net_paid || 0) - Number(a.total_net_paid || 0)
    );
  }, [rows]);

  return (
    <div className="container">
      <PageHeader title="Payroll across the platform" breadcrumb="Super Admin" />

      {stats.isLoading && <p className="text-muted">Loading twelve months of payroll…</p>}

      {stats.isError && (
        <div className="card p-6" style={{ borderLeft: "3px solid #dc2626", borderRadius: 0 }}>
          <strong>Could not load payroll statistics.</strong>
          <button className="btn btn-sm" style={{ marginTop: "0.5rem" }} onClick={() => stats.refetch()}>
            Try again
          </button>
        </div>
      )}

      {stats.data && rows.length === 0 && (
        <div className="card p-6 my-4">
          <strong>No payroll has been run yet.</strong>
          <p className="text-muted text-sm">
            Once a company approves its first pay run, its totals appear here.
          </p>
        </div>
      )}

      {stats.data && rows.length > 0 && (
        <>
          <div className="grid grid-3 gap-4 my-4">
            <div className="card p-4">
              <div className="text-xs text-muted" style={{ textTransform: "uppercase" }}>
                Net paid this month
              </div>
              <div style={{ fontSize: "1.75rem", fontWeight: 500 }}>{formatMoney(thisMonth)}</div>
              {change !== null && (
                <div className="text-xs" style={{ color: change >= 0 ? "#15803d" : "#b91c1c" }}>
                  {change >= 0 ? "▲" : "▼"} {Math.abs(change).toFixed(1)}% on last month
                </div>
              )}
            </div>
            <div className="card p-4">
              <div className="text-xs text-muted" style={{ textTransform: "uppercase" }}>
                Companies running payroll
              </div>
              <div style={{ fontSize: "1.75rem", fontWeight: 500 }}>{latestByCompany.length}</div>
              <div className="text-xs text-muted">In the last twelve months</div>
            </div>
            <div className="card p-4">
              <div className="text-xs text-muted" style={{ textTransform: "uppercase" }}>
                Paid over twelve months
              </div>
              <div style={{ fontSize: "1.75rem", fontWeight: 500 }}>
                {formatMoney(byMonth.reduce((sum, m) => sum + m.value, 0))}
              </div>
              <div className="text-xs text-muted">Every company, every run</div>
            </div>
          </div>

          <div className="card p-6 my-4">
            <h3>Net paid by month</h3>
            <p className="text-muted text-sm">Every company together, last twelve months.</p>
            <div
              style={{ display: "flex", alignItems: "flex-end", gap: "6px", height: "180px", marginTop: "1rem" }}
              role="img"
              aria-label={`Net paid by month: ${byMonth.map((m) => `${m.label} ${formatMoney(m.value)}`).join(", ")}`}
            >
              {byMonth.map((m) => (
                <div key={m.key} style={{ flex: 1, textAlign: "center" }} title={`${m.label} ${m.year}: ${formatMoney(m.value)}`}>
                  <div
                    style={{
                      height: `${Math.max((m.value / peak) * 150, m.value > 0 ? 3 : 1)}px`,
                      background: m.value > 0 ? "#2563eb" : "#e2e8f0",
                      borderRadius: "3px 3px 0 0",
                    }}
                  />
                  <div className="text-xs text-muted" style={{ marginTop: "4px" }}>{m.label}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="card p-6 my-4">
            <h3>Most recent run per company</h3>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "#64748b", fontSize: "0.72rem", textTransform: "uppercase" }}>
                  <th style={{ padding: "10px 12px" }}>Company</th>
                  <th style={{ padding: "10px 12px" }}>Period</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Employees</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Net paid</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Employer cost</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Statutory</th>
                </tr>
              </thead>
              <tbody>
                {latestByCompany.map((r) => (
                  <tr key={r.company_id} style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "10px 12px" }}>
                      <div style={{ fontWeight: 500 }}>{r.company_name}</div>
                      <div className="text-xs text-muted">{r.company_code}</div>
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      {MONTH_NAMES[r.month - 1]} {r.year}
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "right" }}>{r.total_employees_in_run}</td>
                    <td style={{ padding: "10px 12px", textAlign: "right", fontWeight: 500 }}>
                      {formatMoney(Number(r.total_net_paid || 0))}
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "right" }}>
                      {formatMoney(Number(r.total_employer_cost || 0))}
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "right" }}>
                      {formatMoney(Number(r.total_statutory_contributions || 0))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
