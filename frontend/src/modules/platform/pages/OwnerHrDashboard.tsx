import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { formatDate } from "../../../shared/utils/date";
import { getSeriesColor } from "../../../shared/utils/palette";
import { listPayrollRuns, type PayrollRun } from "../../payroll/api";
import { listLeaves } from "../../time_leave/api";
import { listReimbursements } from "../../payroll/api";
import { listEmployees } from "../../hr/api";

export interface ZohoOwnerDashboardProps {
  data: {
    headcount: number;
    present_today: number;
    on_leave_today: number;
    pending_leave_requests: number;
    department_distribution: Record<string, number>;
    recent_hires: Array<{
      id: string;
      first_name: string;
      last_name?: string | null;
      hire_date: string;
    }>;
  };
  user: any;
  role: string;
  announcements: Array<{
    id: string;
    title: string;
    content: string;
    created_at: string;
  }>;
  generatedAt: string;
}

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  text: string;
  subtext?: string;
}

export function ZohoOwnerDashboard({ data, user, role, announcements, generatedAt }: ZohoOwnerDashboardProps) {
  const isOwner = role === "owner";
  const firstName = user?.employee?.first_name || (isOwner ? "Owner" : "Admin");

  // Format current date
  const todayFormatted = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(new Date());

  // Tooltip states for charts
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    text: "",
  });

  // Fetch real payroll runs for the last 12 months payroll cost chart
  const payrollRunsQuery = useQuery({
    queryKey: ["hr-dashboard", "payroll-runs"],
    queryFn: async () => {
      const res = await listPayrollRuns(undefined, 1, 50);
      return res.items || [];
    },
    staleTime: 60_000,
  });

  // Pending Queue Queries
  // 1. Leave approvals
  const pendingLeavesQuery = useQuery({
    queryKey: ["hr-dashboard", "pending-leaves"],
    queryFn: async () => {
      const res = await listLeaves({ status: "pending", page: 1, limit: 1 });
      return res.total;
    },
    staleTime: 60_000,
  });

  // 2. Pending reimbursements
  const pendingReimbursementsQuery = useQuery({
    queryKey: ["hr-dashboard", "pending-reimbursements"],
    queryFn: async () => {
      const res = await listReimbursements("pending", 1, 1);
      return res.total;
    },
    staleTime: 60_000,
  });

  // 3. Pending probations & separations from employees list
  const activeEmployeesQuery = useQuery({
    queryKey: ["hr-dashboard", "active-employees"],
    queryFn: async () => {
      const res = await listEmployees({ is_active: true, page: 1, limit: 100 });
      return res.items || [];
    },
    staleTime: 60_000,
  });

  const employees = activeEmployeesQuery.data ?? [];
  const todayStr = new Date().toISOString().split("T")[0];

  // Probation confirmations pending: employees with probation_end_date <= today and not yet confirmed
  const pendingProbationsCount = employees.filter((e) => {
    if (!e.probation_end_date) return false;
    const isDue = e.probation_end_date <= todayStr;
    const status = (e as any).probation_status ?? "pending";
    return isDue && (status === "pending" || status === "extended");
  }).length;

  // Separations pending: employees with pending_separation flag or resignation submitted
  const pendingSeparationsCount = employees.filter((e) => {
    return Boolean(e.pending_separation || e.resignation_status === "submitted");
  }).length;

  const pendingLeavesCount = pendingLeavesQuery.data ?? data.pending_leave_requests;
  const pendingReimbursementsCount = pendingReimbursementsQuery.data ?? 0;

  // Process department distribution for horizontal bar chart
  // Must reconcile with the headcount tile!
  const deptEntries = Object.entries(data.department_distribution);
  // Sort descending by count
  deptEntries.sort((a, b) => b[1] - a[1]);
  // If more than 8 series, fold 9+ into "Other"
  let processedDepts: Array<{ name: string; count: number }> = [];
  if (deptEntries.length <= 8) {
    processedDepts = deptEntries.map(([name, count]) => ({ name, count }));
  } else {
    const top7 = deptEntries.slice(0, 7).map(([name, count]) => ({ name, count }));
    const restCount = deptEntries.slice(7).reduce((acc, curr) => acc + curr[1], 0);
    processedDepts = [...top7, { name: "Other Departments", count: restCount }];
  }

  const deptTotal = processedDepts.reduce((acc, d) => acc + d.count, 0);
  const maxDeptCount = Math.max(...processedDepts.map((d) => d.count), 1);

  // Attendance Today calculation
  const present = data.present_today;
  const onLeave = data.on_leave_today;
  const absent = Math.max(0, data.headcount - present - onLeave);
  const attendanceTotal = data.headcount || 1;

  // Payroll Cost by Month (last 12 months from real payroll runs)
  const runs = (payrollRunsQuery.data ?? []).filter((r: PayrollRun) => {
    // Only real pay runs with gross/net cost
    return r.total_gross !== null || r.total_employer_cost !== null;
  });

  // Sort chronological
  runs.sort((a, b) => {
    if (a.year !== b.year) return a.year - b.year;
    return a.month - b.month;
  });
  const recentRuns = runs.slice(-12);

  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

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

      {/* 1. Header & Welcome Banner */}
      <div
        style={{
          background: "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)",
          borderRadius: "14px",
          padding: "1.5rem 1.75rem",
          color: "#ffffff",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "1.25rem",
          boxShadow: "0 4px 20px -2px rgba(15, 23, 42, 0.15)",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
            <span
              style={{
                fontSize: "0.72rem",
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                background: "rgba(59, 130, 246, 0.2)",
                color: "#60a5fa",
                padding: "2px 8px",
                borderRadius: "4px",
                border: "1px solid rgba(96, 165, 250, 0.3)",
              }}
            >
              {isOwner ? "Executive Portal" : "HR Administration"}
            </span>
            <span style={{ fontSize: "0.8rem", color: "#94a3b8" }}>• {todayFormatted}</span>
          </div>

          <h2 style={{ margin: 0, fontSize: "1.5rem", fontWeight: 700, color: "#f8fafc" }}>
            Good {new Date().getHours() < 12 ? "morning" : new Date().getHours() < 17 ? "afternoon" : "evening"}, {firstName} 👋
          </h2>
          <p style={{ margin: "4px 0 0", color: "#94a3b8", fontSize: "0.875rem" }}>
            Organization health, live headcount, pending actions, and payroll trends.
          </p>
        </div>

        {/* Quick actions */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          {isOwner && (
            <Link
              to="/employees/new"
              className="btn btn-sm"
              style={{
                background: "#2563eb",
                color: "#ffffff",
                border: "none",
                fontWeight: 600,
                padding: "8px 14px",
                borderRadius: "8px",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                textDecoration: "none",
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              Add Employee
            </Link>
          )}

          <Link
            to="/performance/summaries"
            className="btn btn-sm"
            style={{
              background: "#4f46e5",
              color: "#ffffff",
              border: "none",
              fontWeight: 600,
              padding: "8px 14px",
              borderRadius: "8px",
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              textDecoration: "none",
            }}
          >
            <span>📊</span> Performance Summaries
          </Link>

          <Link
            to="/payroll/run"
            className="btn btn-sm"
            style={{
              background: "rgba(255, 255, 255, 0.1)",
              color: "#f8fafc",
              border: "1px solid rgba(255, 255, 255, 0.2)",
              fontWeight: 600,
              padding: "8px 14px",
              borderRadius: "8px",
              textDecoration: "none",
            }}
          >
            Payroll Runs
          </Link>
        </div>
      </div>

      {/* 2. Key Headcount & Top Metric Tiles */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "1rem",
        }}
      >
        <Link to="/employees" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", borderTop: "4px solid #3b5bdb" }}>
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text-muted)", textTransform: "uppercase" }}>
              Total Headcount
            </div>
            <div style={{ fontSize: "2rem", fontWeight: 800, marginTop: "4px", color: "var(--color-text)" }}>
              {data.headcount}
            </div>
            <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "4px" }}>
              Active company roster (Reconciles: {deptTotal})
            </div>
          </div>
        </Link>

        <Link to="/attendance" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", borderTop: "4px solid #2f9e44" }}>
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text-muted)", textTransform: "uppercase" }}>
              Present Today
            </div>
            <div style={{ fontSize: "2rem", fontWeight: 800, marginTop: "4px", color: "var(--color-text)" }}>
              {data.present_today}
            </div>
            <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "4px" }}>
              {data.headcount > 0 ? `${Math.round((data.present_today / data.headcount) * 100)}% present rate` : "No employees"}
            </div>
          </div>
        </Link>

        <Link to="/leaves" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", borderTop: "4px solid #e8590c" }}>
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text-muted)", textTransform: "uppercase" }}>
              On Leave Today
            </div>
            <div style={{ fontSize: "2rem", fontWeight: 800, marginTop: "4px", color: "var(--color-text)" }}>
              {data.on_leave_today}
            </div>
            <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "4px" }}>
              Approved scheduled leaves
            </div>
          </div>
        </Link>

        <Link to="/attendance" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", borderTop: "4px solid #868e96" }}>
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text-muted)", textTransform: "uppercase" }}>
              Absent Today
            </div>
            <div style={{ fontSize: "2rem", fontWeight: 800, marginTop: "4px", color: "var(--color-text)" }}>
              {absent}
            </div>
            <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "4px" }}>
              Unexcused or not checked in
            </div>
          </div>
        </Link>
      </div>

      {/* 3. Pending Queue Card */}
      <div className="card" style={{ padding: "1.25rem", borderRadius: "12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--color-text)" }}>
              Pending Action Queue
            </h3>
            <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
              Actionable operational queues waiting for HR or Owner decision
            </p>
          </div>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: "1rem",
          }}
        >
          {/* Leave approvals */}
          <Link
            to="/leaves?status=pending"
            style={{
              textDecoration: "none",
              padding: "1rem",
              borderRadius: "8px",
              background: "var(--color-surface, #f8fafc)",
              border: "1px solid var(--color-border, #e2e8f0)",
              display: "flex",
              flexDirection: "column",
              gap: "6px",
            }}
          >
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text-muted)" }}>
              Leave Approvals
            </div>
            <div style={{ fontSize: "1.5rem", fontWeight: 800, color: pendingLeavesCount > 0 ? "#e8590c" : "var(--color-text)" }}>
              {pendingLeavesCount > 0 ? pendingLeavesCount : "Nothing waiting"}
            </div>
            <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>
              {pendingLeavesCount > 0 ? "Requires review →" : "All cleared"}
            </div>
          </Link>

          {/* Reimbursements */}
          <Link
            to="/payroll/reimbursements?status=pending"
            style={{
              textDecoration: "none",
              padding: "1rem",
              borderRadius: "8px",
              background: "var(--color-surface, #f8fafc)",
              border: "1px solid var(--color-border, #e2e8f0)",
              display: "flex",
              flexDirection: "column",
              gap: "6px",
            }}
          >
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text-muted)" }}>
              Reimbursements
            </div>
            <div style={{ fontSize: "1.5rem", fontWeight: 800, color: pendingReimbursementsCount > 0 ? "#e8590c" : "var(--color-text)" }}>
              {pendingReimbursementsCount > 0 ? pendingReimbursementsCount : "Nothing waiting"}
            </div>
            <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>
              {pendingReimbursementsCount > 0 ? "Pending claims →" : "All cleared"}
            </div>
          </Link>

          {/* Probation Confirmations */}
          <Link
            to="/employees"
            style={{
              textDecoration: "none",
              padding: "1rem",
              borderRadius: "8px",
              background: "var(--color-surface, #f8fafc)",
              border: "1px solid var(--color-border, #e2e8f0)",
              display: "flex",
              flexDirection: "column",
              gap: "6px",
            }}
          >
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text-muted)" }}>
              Probation Decisions
            </div>
            <div style={{ fontSize: "1.5rem", fontWeight: 800, color: pendingProbationsCount > 0 ? "#e8590c" : "var(--color-text)" }}>
              {pendingProbationsCount > 0 ? pendingProbationsCount : "Nothing waiting"}
            </div>
            <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>
              {pendingProbationsCount > 0 ? "Probations due/overdue →" : "All cleared"}
            </div>
          </Link>

          {/* Separations Pending */}
          <Link
            to="/performance"
            style={{
              textDecoration: "none",
              padding: "1rem",
              borderRadius: "8px",
              background: "var(--color-surface, #f8fafc)",
              border: "1px solid var(--color-border, #e2e8f0)",
              display: "flex",
              flexDirection: "column",
              gap: "6px",
            }}
          >
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text-muted)" }}>
              Separations Pending
            </div>
            <div style={{ fontSize: "1.5rem", fontWeight: 800, color: pendingSeparationsCount > 0 ? "#c2255c" : "var(--color-text)" }}>
              {pendingSeparationsCount > 0 ? pendingSeparationsCount : "Nothing waiting"}
            </div>
            <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>
              {pendingSeparationsCount > 0 ? "Awaiting HR confirmation →" : "All cleared"}
            </div>
          </Link>
        </div>
      </div>

      {/* 4. Charts Row: Headcount by Department & Attendance Today */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: "1.25rem",
        }}
      >
        {/* Headcount by Department (Horizontal SVG Bar Chart) */}
        <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--color-text)" }}>
                Headcount by Department
              </h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                Distribution across teams (Reconciles with total: {deptTotal})
              </p>
            </div>
            <Link to="/departments" className="btn btn-sm btn-ghost" style={{ fontSize: "0.75rem" }}>
              Departments →
            </Link>
          </div>

          {processedDepts.length === 0 ? (
            <div style={{ padding: "2rem", textAlign: "center", color: "var(--color-text-muted)" }}>
              No departments configured yet.
            </div>
          ) : (
            <div style={{ marginTop: "1rem" }}>
              {/* Inline SVG Horizontal Bar Chart */}
              <svg
                width="100%"
                height={processedDepts.length * 36 + 20}
                viewBox={`0 0 400 ${processedDepts.length * 36 + 20}`}
                style={{ overflow: "visible" }}
              >
                {processedDepts.map((d, idx) => {
                  const y = idx * 36 + 10;
                  const barWidth = Math.max(8, (d.count / maxDeptCount) * 240);
                  const color = getSeriesColor(idx);
                  const pct = Math.round((d.count / (deptTotal || 1)) * 100);

                  return (
                    <g
                      key={d.name}
                      onMouseMove={(e) => {
                        setTooltip({
                          visible: true,
                          x: e.clientX,
                          y: e.clientY,
                          text: `${d.name}: ${d.count} employees`,
                          subtext: `${pct}% of total headcount`,
                        });
                      }}
                      onMouseLeave={() => setTooltip((t) => ({ ...t, visible: false }))}
                      style={{ cursor: "pointer" }}
                    >
                      {/* Department Name Label */}
                      <text
                        x="100"
                        y={y + 14}
                        textAnchor="end"
                        fill="currentColor"
                        fontSize="12"
                        fontWeight="500"
                      >
                        {d.name.length > 14 ? `${d.name.slice(0, 12)}…` : d.name}
                      </text>

                      {/* Bar Background Track */}
                      <rect
                        x="110"
                        y={y}
                        width="240"
                        height="20"
                        rx="4"
                        fill="var(--color-surface, #f1f5f9)"
                      />

                      {/* Bar End 4px rounded */}
                      <rect
                        x="110"
                        y={y}
                        width={barWidth}
                        height="20"
                        rx="4"
                        fill={color}
                      />

                      {/* Value Count Label */}
                      <text
                        x={110 + barWidth + 8}
                        y={y + 14}
                        fill="currentColor"
                        fontSize="11"
                        fontWeight="600"
                      >
                        {d.count} ({pct}%)
                      </text>
                    </g>
                  );
                })}
              </svg>

              {/* Direct Labels / Legend for 2+ series */}
              {processedDepts.length >= 2 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", marginTop: "1rem", paddingTop: "0.75rem", borderTop: "1px solid var(--color-border, #e2e8f0)" }}>
                  {processedDepts.map((d, idx) => (
                    <div key={d.name} style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.72rem" }}>
                      <span style={{ width: "10px", height: "10px", borderRadius: "2px", background: getSeriesColor(idx) }} />
                      <span style={{ color: "var(--color-text)" }}>{d.name}: {d.count}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Attendance Today (Stat tiles + One Stacked Bar Chart with Status Colours & Icons) */}
        <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--color-text)" }}>
                Attendance Today
              </h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                Daily presence, leaves, and absences with status indicators
              </p>
            </div>
            <Link to="/attendance" className="btn btn-sm btn-ghost" style={{ fontSize: "0.75rem" }}>
              Logs →
            </Link>
          </div>

          {/* 3 Stat Tiles */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "8px", margin: "1rem 0" }}>
            <div style={{ padding: "8px", borderRadius: "8px", background: "rgba(47, 158, 68, 0.1)", border: "1px solid rgba(47, 158, 68, 0.2)" }}>
              <div style={{ fontSize: "0.72rem", fontWeight: 700, color: "#2f9e44", display: "flex", alignItems: "center", gap: "4px" }}>
                <span>✓</span> Present
              </div>
              <div style={{ fontSize: "1.3rem", fontWeight: 800, color: "var(--color-text)", marginTop: "2px" }}>
                {present}
              </div>
              <div style={{ fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
                {Math.round((present / attendanceTotal) * 100)}%
              </div>
            </div>

            <div style={{ padding: "8px", borderRadius: "8px", background: "rgba(232, 89, 12, 0.1)", border: "1px solid rgba(232, 89, 12, 0.2)" }}>
              <div style={{ fontSize: "0.72rem", fontWeight: 700, color: "#e8590c", display: "flex", alignItems: "center", gap: "4px" }}>
                <span>✈️</span> On Leave
              </div>
              <div style={{ fontSize: "1.3rem", fontWeight: 800, color: "var(--color-text)", marginTop: "2px" }}>
                {onLeave}
              </div>
              <div style={{ fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
                {Math.round((onLeave / attendanceTotal) * 100)}%
              </div>
            </div>

            <div style={{ padding: "8px", borderRadius: "8px", background: "rgba(194, 37, 92, 0.1)", border: "1px solid rgba(194, 37, 92, 0.2)" }}>
              <div style={{ fontSize: "0.72rem", fontWeight: 700, color: "#c2255c", display: "flex", alignItems: "center", gap: "4px" }}>
                <span>✕</span> Absent
              </div>
              <div style={{ fontSize: "1.3rem", fontWeight: 800, color: "var(--color-text)", marginTop: "2px" }}>
                {absent}
              </div>
              <div style={{ fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
                {Math.round((absent / attendanceTotal) * 100)}%
              </div>
            </div>
          </div>

          {/* One Stacked Bar Chart in inline SVG */}
          <div style={{ marginTop: "0.5rem" }}>
            <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)", marginBottom: "6px" }}>
              Presence Proportion ({data.headcount} Total)
            </div>
            <svg
              width="100%"
              height="36"
              viewBox="0 0 400 36"
              style={{ overflow: "visible" }}
            >
              {(() => {
                const total = attendanceTotal;
                const width = 400;
                const presentW = (present / total) * width;
                const onLeaveW = (onLeave / total) * width;
                const absentW = Math.max(0, width - presentW - onLeaveW);

                return (
                  <g>
                    {/* Segment 1: Present (Good = #2f9e44) */}
                    {presentW > 0 && (
                      <rect
                        x="0"
                        y="4"
                        width={Math.max(2, presentW - 2)}
                        height="26"
                        rx="4"
                        fill="#2f9e44"
                        style={{ cursor: "pointer" }}
                        onMouseMove={(e) => {
                          setTooltip({
                            visible: true,
                            x: e.clientX,
                            y: e.clientY,
                            text: `Present: ${present} employees`,
                            subtext: `${Math.round((present / total) * 100)}% of headcount`,
                          });
                        }}
                        onMouseLeave={() => setTooltip((t) => ({ ...t, visible: false }))}
                      />
                    )}

                    {/* Segment 2: On Leave (Warning = #e8590c) */}
                    {onLeaveW > 0 && (
                      <rect
                        x={presentW}
                        y="4"
                        width={Math.max(2, onLeaveW - 2)}
                        height="26"
                        rx="4"
                        fill="#e8590c"
                        style={{ cursor: "pointer" }}
                        onMouseMove={(e) => {
                          setTooltip({
                            visible: true,
                            x: e.clientX,
                            y: e.clientY,
                            text: `On Leave: ${onLeave} employees`,
                            subtext: `${Math.round((onLeave / total) * 100)}% of headcount`,
                          });
                        }}
                        onMouseLeave={() => setTooltip((t) => ({ ...t, visible: false }))}
                      />
                    )}

                    {/* Segment 3: Absent (Critical = #c2255c) */}
                    {absentW > 0 && (
                      <rect
                        x={presentW + onLeaveW}
                        y="4"
                        width={absentW}
                        height="26"
                        rx="4"
                        fill="#c2255c"
                        style={{ cursor: "pointer" }}
                        onMouseMove={(e) => {
                          setTooltip({
                            visible: true,
                            x: e.clientX,
                            y: e.clientY,
                            text: `Absent: ${absent} employees`,
                            subtext: `${Math.round((absent / total) * 100)}% of headcount`,
                          });
                        }}
                        onMouseLeave={() => setTooltip((t) => ({ ...t, visible: false }))}
                      />
                    )}
                  </g>
                );
              })()}
            </svg>

            {/* Direct Labels Legend */}
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: "8px", fontSize: "0.72rem", color: "var(--color-text-muted)" }}>
              <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#2f9e44" }} />
                Present ({present})
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#e8590c" }} />
                On Leave ({onLeave})
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#c2255c" }} />
                Absent ({absent})
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 5. Payroll Cost by Month (One Series, One Axis, Last 12 Months from Real Pay Runs Only) */}
      <div className="card" style={{ padding: "1.25rem", borderRadius: "12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--color-text)" }}>
              Payroll Cost by Month
            </h3>
            <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
              One series, single axis, finalized runs only (last 12 months)
            </p>
          </div>
          <Link to="/payroll/runs" className="btn btn-sm btn-ghost" style={{ fontSize: "0.75rem" }}>
            Payroll History →
          </Link>
        </div>

        {recentRuns.length === 0 ? (
          <div style={{ padding: "2.5rem 1rem", textAlign: "center", color: "var(--color-text-muted)" }}>
            <p style={{ margin: 0, fontWeight: 500 }}>No finalized payroll runs recorded yet.</p>
            <p style={{ margin: "4px 0 0", fontSize: "0.78rem" }}>
              Cost history will render automatically when monthly pay runs are approved.
            </p>
          </div>
        ) : (
          <div>
            {/* Inline SVG Chart for Payroll Runs */}
            {(() => {
              const svgWidth = 600;
              const svgHeight = 200;
              const paddingLeft = 60;
              const paddingRight = 20;
              const paddingTop = 20;
              const paddingBottom = 30;

              const chartW = svgWidth - paddingLeft - paddingRight;
              const chartH = svgHeight - paddingTop - paddingBottom;

              const values = recentRuns.map((r) => Number(r.total_gross ?? r.total_employer_cost ?? 0));
              const maxVal = Math.max(...values, 1000);

              const barWidth = Math.min(36, (chartW / recentRuns.length) - 8);

              return (
                <svg
                  width="100%"
                  height={svgHeight}
                  viewBox={`0 0 ${svgWidth} ${svgHeight}`}
                  style={{ overflow: "visible" }}
                >
                  {/* Axis line */}
                  <line
                    x1={paddingLeft}
                    y1={svgHeight - paddingBottom}
                    x2={svgWidth - paddingRight}
                    y2={svgHeight - paddingBottom}
                    stroke="var(--color-border, #e2e8f0)"
                    strokeWidth="1"
                  />

                  {/* Y Axis Guide ticks (3 levels) */}
                  {[0, 0.5, 1].map((ratio) => {
                    const y = svgHeight - paddingBottom - ratio * chartH;
                    const val = Math.round(maxVal * ratio);
                    return (
                      <g key={ratio}>
                        <line
                          x1={paddingLeft}
                          y1={y}
                          x2={svgWidth - paddingRight}
                          y2={y}
                          stroke="var(--color-border, #f1f5f9)"
                          strokeDasharray="4 4"
                          strokeWidth="1"
                        />
                        <text
                          x={paddingLeft - 8}
                          y={y + 4}
                          textAnchor="end"
                          fontSize="10"
                          fill="var(--color-text-muted, #94a3b8)"
                        >
                          {val >= 1000 ? `${Math.round(val / 1000)}k` : val}
                        </text>
                      </g>
                    );
                  })}

                  {/* Bars - one series: series 1 color (#3b5bdb), 4px rounded top */}
                  {recentRuns.map((r, idx) => {
                    const val = Number(r.total_gross ?? r.total_employer_cost ?? 0);
                    const barH = (val / maxVal) * chartH;
                    const x = paddingLeft + (idx * (chartW / recentRuns.length)) + ((chartW / recentRuns.length - barWidth) / 2);
                    const y = svgHeight - paddingBottom - barH;
                    const label = `${monthNames[r.month - 1]} '${String(r.year).slice(-2)}`;

                    return (
                      <g
                        key={r.id}
                        style={{ cursor: "pointer" }}
                        onMouseMove={(e) => {
                          setTooltip({
                            visible: true,
                            x: e.clientX,
                            y: e.clientY,
                            text: `${label}: ₹${val.toLocaleString()}`,
                            subtext: `Status: ${r.status} (${r.total_employees ?? 0} employees)`,
                          });
                        }}
                        onMouseLeave={() => setTooltip((t) => ({ ...t, visible: false }))}
                      >
                        <rect
                          x={x}
                          y={y}
                          width={barWidth}
                          height={Math.max(2, barH)}
                          rx="4"
                          fill="#3b5bdb"
                        />
                        {/* Month text label */}
                        <text
                          x={x + barWidth / 2}
                          y={svgHeight - paddingBottom + 16}
                          textAnchor="middle"
                          fontSize="10"
                          fill="var(--color-text-muted, #64748b)"
                        >
                          {label}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              );
            })()}

            <div style={{ textAlign: "right", marginTop: "4px" }}>
              <span style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>
                Total finalized runs: {recentRuns.length} • Series: Gross Payroll (₹)
              </span>
            </div>
          </div>
        )}
      </div>

      {/* 6. Recent Hires & Announcements */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: "1.25rem",
        }}
      >
        {/* Recent Hires */}
        <div className="card" style={{ padding: "1.25rem", borderRadius: "12px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--color-text)" }}>
                Recent Team Additions
              </h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                Newly onboarded colleagues
              </p>
            </div>
            {isOwner && (
              <Link to="/employees/new" className="btn btn-sm btn-ghost" style={{ fontSize: "0.75rem" }}>
                + Add Employee
              </Link>
            )}
          </div>

          {data.recent_hires.length === 0 ? (
            <div style={{ padding: "1.5rem", textAlign: "center", color: "var(--color-text-muted)" }}>
              No recent employee hires recorded.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {data.recent_hires.slice(0, 5).map((h) => {
                const fullName = `${h.first_name} ${h.last_name || ""}`.trim();
                const initials = (h.first_name[0] + (h.last_name ? h.last_name[0] : "")).toUpperCase();
                return (
                  <div
                    key={h.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "8px 10px",
                      borderRadius: "8px",
                      background: "var(--color-surface, #f8fafc)",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                      <div
                        style={{
                          width: "32px",
                          height: "32px",
                          borderRadius: "50%",
                          background: "#e0e7ff",
                          color: "#4338ca",
                          fontSize: "0.78rem",
                          fontWeight: 700,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flexShrink: 0,
                        }}
                      >
                        {initials}
                      </div>
                      <div>
                        <Link
                          to={`/employees/${h.id}`}
                          style={{ textDecoration: "none", color: "var(--color-text)", fontWeight: 600, fontSize: "0.85rem" }}
                        >
                          {fullName}
                        </Link>
                        <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>Joined {formatDate(h.hire_date)}</div>
                      </div>
                    </div>
                    <Link to={`/employees/${h.id}`} className="btn btn-sm btn-ghost" style={{ fontSize: "0.75rem" }}>
                      Profile →
                    </Link>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Company Announcements */}
        <div className="card" style={{ padding: "1.25rem", borderRadius: "12px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--color-text)" }}>
                Announcements
              </h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                Broadcast notices across company
              </p>
            </div>
            <span className="badge badge-muted">{announcements?.length ?? 0} published</span>
          </div>

          {(!announcements || announcements.length === 0) ? (
            <div style={{ padding: "1.5rem", textAlign: "center", color: "var(--color-text-muted)" }}>
              No company announcements posted.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {announcements.slice(0, 4).map((ann) => (
                <div key={ann.id} style={{ padding: "8px", borderRadius: "6px", background: "var(--color-surface, #f8fafc)" }}>
                  <div style={{ fontWeight: 600, fontSize: "0.85rem", color: "var(--color-text)" }}>{ann.title}</div>
                  <div style={{ fontSize: "0.78rem", color: "var(--color-text-muted)", marginTop: "2px" }}>{ann.content}</div>
                  <div style={{ fontSize: "0.7rem", color: "var(--color-text-muted)", marginTop: "4px" }}>{formatDate(ann.created_at)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div style={{ textAlign: "right" }}>
        <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
          Live system status • Generated at {new Date(generatedAt).toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
}
