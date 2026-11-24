import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { formatDate } from "../../../shared/utils/date";
import { CATEGORICAL_PALETTE } from "../../../shared/utils/palette";
import {
  listPerformanceCycles,
  listPerformanceSummaries,
  type PerformanceSummary,
} from "../api";
import { listEmployees } from "../../hr/api";

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  text: string;
  subtext?: string;
}

export function PerformanceSummariesPage() {
  const [selectedCycleId, setSelectedCycleId] = useState<string>("");
  const [sortField, setSortField] = useState<keyof PerformanceSummary | "employee_name">("employee_name");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");

  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    text: "",
  });

  // 1. Fetch cycles
  const cyclesQuery = useQuery({
    queryKey: ["performance-summaries", "cycles"],
    queryFn: async () => {
      const res = await listPerformanceCycles(undefined, 1, 50);
      return res.items || [];
    },
  });

  const cycles = cyclesQuery.data ?? [];
  const activeCycle = cycles.find((c) => c.status === "active") || cycles[0];

  const currentCycleId = selectedCycleId || (activeCycle ? activeCycle.id : "");

  // 2. Fetch employees (to show pending employees when summary is not finalized)
  const employeesQuery = useQuery({
    queryKey: ["performance-summaries", "employees"],
    queryFn: async () => {
      const res = await listEmployees({ is_active: true, page: 1, limit: 100 });
      return res.items || [];
    },
  });

  // 3. Fetch summaries for the selected cycle
  const summariesQuery = useQuery({
    queryKey: ["performance-summaries", "list", currentCycleId],
    queryFn: async () => {
      if (!currentCycleId) return [];
      const res = await listPerformanceSummaries({ cycle_id: currentCycleId, page: 1, limit: 100 });
      return res.items || [];
    },
    enabled: Boolean(currentCycleId),
  });

  const employees = employeesQuery.data ?? [];
  const summaries = summariesQuery.data ?? [];

  // Map of finalized summary by employee_id
  const summaryByEmpId = new Map<string, PerformanceSummary>();
  summaries.forEach((s) => summaryByEmpId.set(s.employee_id, s));

  // Rating bands for rating distribution: [0-1.9, 2.0-2.9, 3.0-3.9, 4.0-4.9, 5.0]
  // One series, categorical palette / sequential
  const ratingBands = [
    { label: "1.0 - 1.9", min: 1.0, max: 1.99, count: 0 },
    { label: "2.0 - 2.9", min: 2.0, max: 2.99, count: 0 },
    { label: "3.0 - 3.9", min: 3.0, max: 3.99, count: 0 },
    { label: "4.0 - 4.9", min: 4.0, max: 4.99, count: 0 },
    { label: "5.0", min: 5.0, max: 5.05, count: 0 },
  ];

  let salaryRevisionCount = 0;
  const incrementPercentages: number[] = [];

  summaries.forEach((s) => {
    const rating = Number(s.final_rating);
    for (const b of ratingBands) {
      if (rating >= b.min && rating <= b.max) {
        b.count += 1;
        break;
      }
    }
    if (s.salary_revision_recommended) {
      salaryRevisionCount += 1;
    }
    if (s.recommended_increment_percent !== null && s.recommended_increment_percent !== undefined) {
      incrementPercentages.push(Number(s.recommended_increment_percent));
    }
  });

  const maxRatingCount = Math.max(...ratingBands.map((b) => b.count), 1);

  // Increment percentage spread buckets: [0-5%, 6-10%, 11-15%, 16-20%, >20%]
  const incrementBands = [
    { label: "0 - 5%", min: 0, max: 5.0, count: 0 },
    { label: "6 - 10%", min: 5.01, max: 10.0, count: 0 },
    { label: "11 - 15%", min: 10.01, max: 15.0, count: 0 },
    { label: "16 - 20%", min: 15.01, max: 20.0, count: 0 },
    { label: "> 20%", min: 20.01, max: 100.0, count: 0 },
  ];

  incrementPercentages.forEach((pct) => {
    for (const ib of incrementBands) {
      if (pct >= ib.min && pct <= ib.max) {
        ib.count += 1;
        break;
      }
    }
  });
  const maxIncrementCount = Math.max(...incrementBands.map((b) => b.count), 1);

  // Combined rows for sortable table:
  // "An employee with no finalised summary shows as pending, not omitted"
  interface SummaryTableRow {
    employee_id: string;
    employee_name: string;
    employee_code?: string;
    final_rating: number | null;
    salary_revision_recommended: boolean | null;
    recommended_increment_percent: number | null;
    finalized_at: string | null;
    reviewed_by_name: string | null;
    status: "finalized" | "pending";
  }

  const tableRows: SummaryTableRow[] = employees.map((emp) => {
    const s = summaryByEmpId.get(emp.id);
    const empName = `${emp.first_name} ${emp.last_name || ""}`.trim();
    if (s) {
      return {
        employee_id: emp.id,
        employee_name: s.employee_name || empName,
        employee_code: s.employee_code || emp.employee_code,
        final_rating: Number(s.final_rating),
        salary_revision_recommended: s.salary_revision_recommended,
        recommended_increment_percent: s.recommended_increment_percent !== null ? Number(s.recommended_increment_percent) : null,
        finalized_at: s.finalized_at,
        reviewed_by_name: s.reviewed_by_name || s.reviewed_by,
        status: "finalized",
      };
    }
    return {
      employee_id: emp.id,
      employee_name: empName,
      employee_code: emp.employee_code,
      final_rating: null,
      salary_revision_recommended: null,
      recommended_increment_percent: null,
      finalized_at: null,
      reviewed_by_name: null,
      status: "pending",
    };
  });

  // Sort rows
  tableRows.sort((a, b) => {
    let comp = 0;
    if (sortField === "employee_name") {
      comp = a.employee_name.localeCompare(b.employee_name);
    } else if (sortField === "final_rating") {
      const valA = a.final_rating ?? -1;
      const valB = b.final_rating ?? -1;
      comp = valA - valB;
    } else if (sortField === "salary_revision_recommended") {
      const valA = a.salary_revision_recommended ? 1 : 0;
      const valB = b.salary_revision_recommended ? 1 : 0;
      comp = valA - valB;
    } else if (sortField === "recommended_increment_percent") {
      const valA = a.recommended_increment_percent ?? -1;
      const valB = b.recommended_increment_percent ?? -1;
      comp = valA - valB;
    } else if (sortField === "finalized_at") {
      const valA = a.finalized_at ?? "";
      const valB = b.finalized_at ?? "";
      comp = valA.localeCompare(valB);
    }
    return sortOrder === "asc" ? comp : -comp;
  });

  const handleSort = (field: keyof PerformanceSummary | "employee_name") => {
    if (sortField === field) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortOrder("asc");
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem", position: "relative" }}>
      {/* Floating Tooltip */}
      {tooltip.visible && (
        <div
          style={{
            position: "fixed",
            left: `${tooltip.x + 12}px`,
            top: `${tooltip.y - 30}px`,
            background: "#1e293b",
            color: "#ffffff",
            padding: "6px 10px",
            borderRadius: "6px",
            fontSize: "0.75rem",
            pointerEvents: "none",
            zIndex: 9999,
            boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
            whiteSpace: "nowrap",
          }}
        >
          <div style={{ fontWeight: 600 }}>{tooltip.text}</div>
          {tooltip.subtext && <div style={{ opacity: 0.8, fontSize: "0.7rem" }}>{tooltip.subtext}</div>}
        </div>
      )}

      <PageHeader
        title="Performance Summaries"
        breadcrumb="End-of-cycle appraisals, final ratings distribution, and compensation revisions"
      />

      {/* Cycle Filter at the top, in one row above the charts */}
      <div
        className="card"
        style={{
          padding: "1rem 1.25rem",
          borderRadius: "10px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "1rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <label htmlFor="cycle-select" style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--color-text)" }}>
            Select Performance Cycle:
          </label>
          <select
            id="cycle-select"
            className="input"
            style={{ minWidth: "220px", padding: "6px 10px" }}
            value={currentCycleId}
            onChange={(e) => setSelectedCycleId(e.target.value)}
          >
            {cycles.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.status})
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "1rem", fontSize: "0.82rem", color: "var(--color-text-muted)" }}>
          <span>
            Finalized: <strong>{summaries.length}</strong>
          </span>
          <span>•</span>
          <span>
            Pending Review: <strong>{Math.max(0, employees.length - summaries.length)}</strong>
          </span>
          <span>•</span>
          <span>
            Total Eligible: <strong>{employees.length}</strong>
          </span>
        </div>
      </div>

      {/* Charts Section: Rating distribution & Increment recommendations spread */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: "1.25rem",
        }}
      >
        {/* Rating Distribution (One Series, One Axis, Inline SVG Bar Chart) */}
        <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--color-text)" }}>
                Rating Distribution
              </h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                Final rating spread across performance bands (One series, validated palette)
              </p>
            </div>
            <span className="badge badge-muted">{summaries.length} finalized</span>
          </div>

          <div style={{ marginTop: "1rem" }}>
            {(() => {
              const svgWidth = 400;
              const svgHeight = 180;
              const paddingLeft = 40;
              const paddingRight = 20;
              const paddingTop = 20;
              const paddingBottom = 30;

              const chartW = svgWidth - paddingLeft - paddingRight;
              const chartH = svgHeight - paddingTop - paddingBottom;
              const barWidth = Math.min(36, chartW / ratingBands.length - 12);

              return (
                <svg
                  width="100%"
                  height={svgHeight}
                  viewBox={`0 0 ${svgWidth} ${svgHeight}`}
                  style={{ overflow: "visible" }}
                >
                  {/* Axis baseline */}
                  <line
                    x1={paddingLeft}
                    y1={svgHeight - paddingBottom}
                    x2={svgWidth - paddingRight}
                    y2={svgHeight - paddingBottom}
                    stroke="var(--color-border, #e2e8f0)"
                    strokeWidth="1"
                  />

                  {/* Rating Bars */}
                  {ratingBands.map((band, idx) => {
                    const barH = (band.count / maxRatingCount) * chartH;
                    const x = paddingLeft + idx * (chartW / ratingBands.length) + (chartW / ratingBands.length - barWidth) / 2;
                    const y = svgHeight - paddingBottom - barH;
                    const color = CATEGORICAL_PALETTE[0]; // #3b5bdb (one series)

                    return (
                      <g
                        key={band.label}
                        style={{ cursor: "pointer" }}
                        onMouseMove={(e) => {
                          setTooltip({
                            visible: true,
                            x: e.clientX,
                            y: e.clientY,
                            text: `Rating Band ${band.label}: ${band.count} employees`,
                            subtext: summaries.length > 0 ? `${Math.round((band.count / summaries.length) * 100)}% of finalized reviews` : undefined,
                          });
                        }}
                        onMouseLeave={() => setTooltip((t) => ({ ...t, visible: false }))}
                      >
                        <rect
                          x={x}
                          y={y}
                          width={barWidth}
                          height={Math.max(band.count > 0 ? 4 : 0, barH)}
                          rx="4"
                          fill={color}
                        />

                        {/* Top count label if > 0 */}
                        {band.count > 0 && (
                          <text
                            x={x + barWidth / 2}
                            y={y - 6}
                            textAnchor="middle"
                            fontSize="11"
                            fontWeight="600"
                            fill="var(--color-text)"
                          >
                            {band.count}
                          </text>
                        )}

                        {/* X-axis band label */}
                        <text
                          x={x + barWidth / 2}
                          y={svgHeight - paddingBottom + 16}
                          textAnchor="middle"
                          fontSize="10"
                          fill="var(--color-text-muted)"
                        >
                          {band.label}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              );
            })()}

            <div style={{ textAlign: "right", marginTop: "4px" }}>
              <span style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>
                Series: Employee Count (Rating 1.0 - 5.0)
              </span>
            </div>
          </div>
        </div>

        {/* Increment Recommendations Spread */}
        <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--color-text)" }}>
                Increment Recommendations
              </h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                Count flagged for revision and spread of recommended percentages
              </p>
            </div>
            <div style={{ textAlign: "right" }}>
              <span style={{ fontSize: "0.85rem", fontWeight: 700, color: "#e8590c" }}>
                {salaryRevisionCount}
              </span>
              <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}> flagged</span>
            </div>
          </div>

          <div style={{ marginTop: "1rem" }}>
            {(() => {
              const svgWidth = 400;
              const svgHeight = 180;
              const paddingLeft = 40;
              const paddingRight = 20;
              const paddingTop = 20;
              const paddingBottom = 30;

              const chartW = svgWidth - paddingLeft - paddingRight;
              const chartH = svgHeight - paddingTop - paddingBottom;
              const barWidth = Math.min(36, chartW / incrementBands.length - 12);

              return (
                <svg
                  width="100%"
                  height={svgHeight}
                  viewBox={`0 0 ${svgWidth} ${svgHeight}`}
                  style={{ overflow: "visible" }}
                >
                  {/* Axis baseline */}
                  <line
                    x1={paddingLeft}
                    y1={svgHeight - paddingBottom}
                    x2={svgWidth - paddingRight}
                    y2={svgHeight - paddingBottom}
                    stroke="var(--color-border, #e2e8f0)"
                    strokeWidth="1"
                  />

                  {/* Increment Bars */}
                  {incrementBands.map((band, idx) => {
                    const barH = (band.count / maxIncrementCount) * chartH;
                    const x = paddingLeft + idx * (chartW / incrementBands.length) + (chartW / incrementBands.length - barWidth) / 2;
                    const y = svgHeight - paddingBottom - barH;
                    const color = CATEGORICAL_PALETTE[1]; // #e8590c (distinct single series)

                    return (
                      <g
                        key={band.label}
                        style={{ cursor: "pointer" }}
                        onMouseMove={(e) => {
                          setTooltip({
                            visible: true,
                            x: e.clientX,
                            y: e.clientY,
                            text: `Increment Band ${band.label}: ${band.count} employees`,
                            subtext: incrementPercentages.length > 0 ? `${Math.round((band.count / incrementPercentages.length) * 100)}% of recommended raises` : undefined,
                          });
                        }}
                        onMouseLeave={() => setTooltip((t) => ({ ...t, visible: false }))}
                      >
                        <rect
                          x={x}
                          y={y}
                          width={barWidth}
                          height={Math.max(band.count > 0 ? 4 : 0, barH)}
                          rx="4"
                          fill={color}
                        />

                        {/* Top count label if > 0 */}
                        {band.count > 0 && (
                          <text
                            x={x + barWidth / 2}
                            y={y - 6}
                            textAnchor="middle"
                            fontSize="11"
                            fontWeight="600"
                            fill="var(--color-text)"
                          >
                            {band.count}
                          </text>
                        )}

                        {/* X-axis band label */}
                        <text
                          x={x + barWidth / 2}
                          y={svgHeight - paddingBottom + 16}
                          textAnchor="middle"
                          fontSize="10"
                          fill="var(--color-text-muted)"
                        >
                          {band.label}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              );
            })()}

            <div style={{ textAlign: "right", marginTop: "4px" }}>
              <span style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>
                Series: Recommended Raise Spread (% Increment)
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Sortable Table */}
      <div className="card" style={{ padding: "1.25rem", borderRadius: "12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--color-text)" }}>
              Cycle Appraisals Roster
            </h3>
            <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
              Final reviews and increment recommendations. Unfinalised employees appear as pending.
            </p>
          </div>
          <span className="badge badge-muted">{tableRows.length} total roster</span>
        </div>

        <div style={{ overflowX: "auto" }}>
          <table className="table" style={{ width: "100%", tableLayout: "auto", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--color-border, #e2e8f0)", textAlign: "left" }}>
                <th
                  style={{ width: "220px", maxWidth: "260px", padding: "10px", cursor: "pointer", fontSize: "0.8rem", color: "var(--color-text-muted)" }}
                  onClick={() => handleSort("employee_name")}
                >
                  Employee {sortField === "employee_name" ? (sortOrder === "asc" ? "▲" : "▼") : ""}
                </th>
                <th
                  style={{ width: "110px", padding: "10px", cursor: "pointer", fontSize: "0.8rem", color: "var(--color-text-muted)" }}
                  onClick={() => handleSort("final_rating")}
                >
                  Final Rating {sortField === "final_rating" ? (sortOrder === "asc" ? "▲" : "▼") : ""}
                </th>
                <th
                  style={{ width: "150px", padding: "10px", cursor: "pointer", fontSize: "0.8rem", color: "var(--color-text-muted)" }}
                  onClick={() => handleSort("salary_revision_recommended")}
                >
                  Revision Recommended {sortField === "salary_revision_recommended" ? (sortOrder === "asc" ? "▲" : "▼") : ""}
                </th>
                <th
                  style={{ width: "110px", padding: "10px", cursor: "pointer", fontSize: "0.8rem", color: "var(--color-text-muted)" }}
                  onClick={() => handleSort("recommended_increment_percent")}
                >
                  Increment % {sortField === "recommended_increment_percent" ? (sortOrder === "asc" ? "▲" : "▼") : ""}
                </th>
                <th
                  style={{ width: "120px", padding: "10px", cursor: "pointer", fontSize: "0.8rem", color: "var(--color-text-muted)" }}
                  onClick={() => handleSort("finalized_at")}
                >
                  Finalised Date {sortField === "finalized_at" ? (sortOrder === "asc" ? "▲" : "▼") : ""}
                </th>
                <th style={{ width: "140px", padding: "10px", fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
                  Reviewed By
                </th>
                <th style={{ width: "120px", padding: "10px", fontSize: "0.8rem", color: "var(--color-text-muted)", textAlign: "right" }}>
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((row) => (
                <tr key={row.employee_id} style={{ borderBottom: "1px solid var(--color-border, #f1f5f9)" }}>
                  <td style={{ width: "220px", maxWidth: "260px", padding: "10px" }}>
                    <div style={{ fontWeight: 600, color: "var(--color-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {row.employee_name}
                    </div>
                    {row.employee_code && (
                      <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>{row.employee_code}</div>
                    )}
                  </td>

                  <td style={{ padding: "10px" }}>
                    {row.final_rating !== null ? (
                      <span
                        style={{
                          display: "inline-block",
                          padding: "2px 8px",
                          borderRadius: "4px",
                          fontWeight: 700,
                          fontSize: "0.85rem",
                          background: row.final_rating >= 4 ? "rgba(47, 158, 68, 0.15)" : row.final_rating >= 3 ? "rgba(59, 91, 219, 0.15)" : "rgba(232, 89, 12, 0.15)",
                          color: row.final_rating >= 4 ? "#2f9e44" : row.final_rating >= 3 ? "#3b5bdb" : "#e8590c",
                        }}
                      >
                        ★ {row.final_rating.toFixed(1)}
                      </span>
                    ) : (
                      <span className="badge badge-muted" style={{ fontSize: "0.72rem" }}>
                        Pending
                      </span>
                    )}
                  </td>

                  <td style={{ padding: "10px" }}>
                    {row.salary_revision_recommended !== null ? (
                      row.salary_revision_recommended ? (
                        <span style={{ color: "#2f9e44", fontWeight: 600, display: "flex", alignItems: "center", gap: "4px" }}>
                          <span>✓</span> Recommended
                        </span>
                      ) : (
                        <span style={{ color: "var(--color-text-muted)" }}>Not Recommended</span>
                      )
                    ) : (
                      <span style={{ color: "var(--color-text-muted)" }}>—</span>
                    )}
                  </td>

                  <td style={{ padding: "10px", fontWeight: 600 }}>
                    {row.recommended_increment_percent !== null ? (
                      <span style={{ color: "#1864ab" }}>+{row.recommended_increment_percent}%</span>
                    ) : (
                      <span style={{ color: "var(--color-text-muted)" }}>—</span>
                    )}
                  </td>

                  <td style={{ padding: "10px", fontSize: "0.82rem", color: "var(--color-text-muted)" }}>
                    {row.finalized_at ? formatDate(row.finalized_at) : "Pending"}
                  </td>

                  <td style={{ padding: "10px", fontSize: "0.85rem" }}>
                    {row.reviewed_by_name ? (
                      <span style={{ color: "var(--color-text)" }}>{row.reviewed_by_name}</span>
                    ) : (
                      <span style={{ color: "var(--color-text-muted)" }}>—</span>
                    )}
                  </td>

                  <td style={{ padding: "10px", textAlign: "right" }}>
                    <Link
                      to={`/performance/review/${row.employee_id}`}
                      className="btn btn-sm btn-ghost"
                      style={{ fontSize: "0.75rem" }}
                    >
                      {row.status === "finalized" ? "View Summary →" : "Review →"}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
