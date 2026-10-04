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
import { getActivePIP } from "../../performance/api";
import { useAuth } from "../../../app/auth-context";
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
  const { user } = useAuth();
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: fetchDashboard,
  });

  const announcementsQuery = useQuery({
    queryKey: ["announcements"],
    queryFn: fetchAnnouncements,
  });

  const activePipQuery = useQuery({
    queryKey: ["active_pip", user?.employee?.id],
    queryFn: () => getActivePIP(user!.employee!.id),
    enabled: Boolean(user?.employee?.id),
  });
  const activePip = activePipQuery.data;

  const isOwnerOrHr = data?.role === "owner" || data?.role === "hr_admin";

  return (
    <div>
      {/* Suppress duplicate generic header for owner/hr_admin who get a rich executive hero banner */}
      {!isOwnerOrHr && <PageHeader title="Dashboard" breadcrumb="Overview" />}

      {/* Persistent Amber PIP Warning Banner — suppressed for owners */}
      {activePip && user?.role !== 'owner' && (
        <div
          className="card mb-4"
          style={{
            backgroundColor: "#fffbeb",
            borderColor: "#f59e0b",
            borderLeft: "5px solid #d97706",
            padding: "1rem 1.25rem",
          }}
        >
          <div className="flex justify-between items-center" style={{ flexWrap: "wrap", gap: "10px" }}>
            <div className="flex items-center gap-3">
              <span style={{ fontSize: "1.5rem" }}>⚠️</span>
              <div>
                <strong style={{ color: "#92400e", fontSize: "0.95rem" }}>
                  You are currently in an active Performance Evaluation Plan (Ends {formatDate(activePip.end_date)}).
                </strong>
                <p className="text-xs mb-0 mt-0.5" style={{ color: "#b45309" }}>
                  Track C warning period active. Review required milestone targets and mentor checkpoints.
                </p>
              </div>
            </div>
            <Link
              to="/performance/goals"
              className="btn btn-sm"
              style={{
                backgroundColor: "#d97706",
                color: "#ffffff",
                borderColor: "#b45309",
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              Review Targets Here →
            </Link>
          </div>
        </div>
      )}

      {/* Only render regular employee check-in card if NOT owner/admin who doesn't track punch clock */}
      {user?.role !== "owner" && <TodayAttendanceCard showWhenNoEmployee={false} />}

      {isLoading && (
        <div className="row" style={{ padding: "2rem 0" }}>
          <div className="spinner" />
          <span className="text-muted">Loading dashboard...</span>
        </div>
      )}
      {isError && <div className="alert alert-error">{parseApiError(error).message}</div>}

      {data && (
        <div className="stack" style={{ gap: "1.25rem" }}>
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

          {(data.role === "hr_admin" || data.role === "owner") && (
            <ZohoOwnerDashboard
              data={data.data}
              user={user}
              role={data.role}
              announcements={announcementsQuery.data ?? []}
              generatedAt={data.generated_at}
            />
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

interface ZohoOwnerDashboardProps {
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

function ZohoOwnerDashboard({ data, user, role, announcements, generatedAt }: ZohoOwnerDashboardProps) {
  const isOwner = role === "owner";
  const firstName = user?.employee?.first_name || (isOwner ? "Owner" : "Admin");
  const attendanceRate = data.headcount > 0 ? Math.round((data.present_today / data.headcount) * 100) : 0;

  // Department colors palette (Zoho style)
  const deptPalette = [
    { bg: "#3b82f6", light: "#eff6ff" },
    { bg: "#10b981", light: "#ecfdf5" },
    { bg: "#8b5cf6", light: "#f5f3ff" },
    { bg: "#f59e0b", light: "#fffbeb" },
    { bg: "#ec4899", light: "#fdf2f8" },
    { bg: "#06b6d4", light: "#ecfeff" },
  ];

  const totalInDepts = Object.values(data.department_distribution).reduce((acc, v) => acc + v, 0) || data.headcount || 1;

  // Format current date Zoho style (e.g. Tuesday, 29 September 2026)
  const todayFormatted = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(new Date());

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      {/* 1. Zoho People Executive Greeting & Action Banner */}
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
            Here is your live organization health, real-time headcount, and pending approvals.
          </p>
        </div>

        {/* Primary Executive Quick Actions */}
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
                padding: "8px 16px",
                borderRadius: "8px",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                textDecoration: "none",
                boxShadow: "0 2px 8px rgba(37, 99, 235, 0.35)",
              }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              Add Employee
            </Link>
          )}

          <Link
            to="/leaves?status=pending"
            className="btn btn-sm"
            style={{
              position: "relative",
              background: data.pending_leave_requests > 0 ? "#f59e0b" : "#334155",
              color: data.pending_leave_requests > 0 ? "#1e293b" : "#f1f5f9",
              border: "none",
              fontWeight: 700,
              padding: "8px 14px",
              borderRadius: "8px",
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              textDecoration: "none",
            }}
          >
            Leave Approvals
            {data.pending_leave_requests > 0 && (
              <span
                style={{
                  background: "#b45309",
                  color: "#ffffff",
                  fontSize: "0.7rem",
                  fontWeight: 800,
                  borderRadius: "10px",
                  padding: "1px 6px",
                  minWidth: "18px",
                  textAlign: "center",
                }}
              >
                {data.pending_leave_requests}
              </span>
            )}
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

          <Link
            to="/employees"
            className="btn btn-sm"
            style={{
              background: "transparent",
              color: "#cbd5e1",
              border: "1px solid #475569",
              fontWeight: 500,
              padding: "8px 14px",
              borderRadius: "8px",
              textDecoration: "none",
            }}
          >
            Directory →
          </Link>
        </div>
      </div>

      {/* 2. Zoho People Key Metric Widgets Grid (4 KPI Cards - Equal Height & Proportions) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: "1rem",
          alignItems: "stretch",
        }}
      >
        {/* Metric 1: Total Employees */}
        <Link
          to="/employees"
          style={{ textDecoration: "none", color: "inherit", display: "flex" }}
        >
          <div
            className="card"
            style={{
              padding: "1.25rem",
              borderRadius: "12px",
              borderTop: "4px solid #2563eb",
              transition: "transform 0.15s ease, box-shadow 0.15s ease",
              position: "relative",
              overflow: "hidden",
              width: "100%",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
              minHeight: "165px",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Total Employees
                  </div>
                  <div style={{ fontSize: "2rem", fontWeight: 800, color: "#0f172a", marginTop: "4px", lineHeight: 1.1 }}>
                    {data.headcount}
                  </div>
                  <div style={{ fontSize: "0.78rem", color: "#10b981", fontWeight: 600, marginTop: "6px", display: "flex", alignItems: "center", gap: "4px" }}>
                    <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#10b981", display: "inline-block" }}></span>
                    Active Roster
                  </div>
                </div>
                <div
                  style={{
                    width: "42px",
                    height: "42px",
                    borderRadius: "10px",
                    background: "#eff6ff",
                    color: "#2563eb",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                    <circle cx="9" cy="7" r="4"></circle>
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
                    <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                  </svg>
                </div>
              </div>
            </div>

            <div style={{ marginTop: "16px", paddingTop: "8px", borderTop: "1px solid #f1f5f9", display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "#64748b" }}>
              <span>View Employee Directory</span>
              <span style={{ fontWeight: 600, color: "#2563eb" }}>Browse →</span>
            </div>
          </div>
        </Link>

        {/* Metric 2: Present Today */}
        <Link
          to="/attendance"
          style={{ textDecoration: "none", color: "inherit", display: "flex" }}
        >
          <div
            className="card"
            style={{
              padding: "1.25rem",
              borderRadius: "12px",
              borderTop: "4px solid #10b981",
              transition: "transform 0.15s ease, box-shadow 0.15s ease",
              width: "100%",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
              minHeight: "165px",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Present Today
                  </div>
                  <div style={{ fontSize: "2rem", fontWeight: 800, color: "#0f172a", marginTop: "4px", lineHeight: 1.1 }}>
                    {data.present_today}
                  </div>
                  <div style={{ fontSize: "0.78rem", color: "#64748b", marginTop: "6px" }}>
                    <span style={{ fontWeight: 700, color: "#10b981" }}>{attendanceRate}%</span> attendance rate
                  </div>
                </div>
                <div
                  style={{
                    width: "42px",
                    height: "42px",
                    borderRadius: "10px",
                    background: "#ecfdf5",
                    color: "#10b981",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                    <polyline points="22 4 12 14.01 9 11.01"></polyline>
                  </svg>
                </div>
              </div>
            </div>

            <div style={{ marginTop: "16px", paddingTop: "8px", borderTop: "1px solid #f1f5f9", display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "#64748b" }}>
              <span>View Live Attendance</span>
              <span style={{ fontWeight: 600, color: "#10b981" }}>Log →</span>
            </div>
          </div>
        </Link>

        {/* Metric 3: On Leave Today */}
        <Link
          to="/leaves"
          style={{ textDecoration: "none", color: "inherit", display: "flex" }}
        >
          <div
            className="card"
            style={{
              padding: "1.25rem",
              borderRadius: "12px",
              borderTop: "4px solid #f59e0b",
              transition: "transform 0.15s ease, box-shadow 0.15s ease",
              width: "100%",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
              minHeight: "165px",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    On Leave Today
                  </div>
                  <div style={{ fontSize: "2rem", fontWeight: 800, color: "#0f172a", marginTop: "4px", lineHeight: 1.1 }}>
                    {data.on_leave_today}
                  </div>
                  <div style={{ fontSize: "0.78rem", color: "#64748b", marginTop: "6px" }}>
                    Scheduled time off
                  </div>
                </div>
                <div
                  style={{
                    width: "42px",
                    height: "42px",
                    borderRadius: "10px",
                    background: "#fffbeb",
                    color: "#f59e0b",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="16" y1="2" x2="16" y2="6"></line>
                    <line x1="8" y1="2" x2="8" y2="6"></line>
                    <line x1="3" y1="10" x2="21" y2="10"></line>
                  </svg>
                </div>
              </div>
            </div>

            <div style={{ marginTop: "16px", paddingTop: "8px", borderTop: "1px solid #f1f5f9", display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "#64748b" }}>
              <span>View Leave Calendar</span>
              <span style={{ fontWeight: 600, color: "#f59e0b" }}>Schedule →</span>
            </div>
          </div>
        </Link>

        {/* Metric 4: Pending Requests */}
        <Link
          to="/leaves?status=pending"
          style={{ textDecoration: "none", color: "inherit", display: "flex" }}
        >
          <div
            className="card"
            style={{
              padding: "1.25rem",
              borderRadius: "12px",
              borderTop: `4px solid ${data.pending_leave_requests > 0 ? "#ef4444" : "#64748b"}`,
              transition: "transform 0.15s ease, box-shadow 0.15s ease",
              background: data.pending_leave_requests > 0 ? "#fff" : undefined,
              width: "100%",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
              minHeight: "165px",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Pending Requests
                  </div>
                  <div style={{ fontSize: "2rem", fontWeight: 800, color: data.pending_leave_requests > 0 ? "#b91c1c" : "#0f172a", marginTop: "4px", lineHeight: 1.1 }}>
                    {data.pending_leave_requests}
                  </div>
                  <div style={{ fontSize: "0.78rem", color: data.pending_leave_requests > 0 ? "#dc2626" : "#64748b", fontWeight: 600, marginTop: "6px" }}>
                    {data.pending_leave_requests > 0 ? "Requires action" : "All cleared"}
                  </div>
                </div>
                <div
                  style={{
                    width: "42px",
                    height: "42px",
                    borderRadius: "10px",
                    background: data.pending_leave_requests > 0 ? "#fef2f2" : "#f1f5f9",
                    color: data.pending_leave_requests > 0 ? "#ef4444" : "#64748b",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                  </svg>
                </div>
              </div>
            </div>

            <div style={{ marginTop: "16px", paddingTop: "8px", borderTop: "1px solid #f1f5f9", display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "#64748b" }}>
              <span>Review Requests Queue</span>
              <span style={{ fontWeight: 600, color: data.pending_leave_requests > 0 ? "#ef4444" : "#64748b" }}>Review →</span>
            </div>
          </div>
        </Link>
      </div>

      {/* 3. Main Dashboard Widgets Grid (Equal Height Columns) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: "1.25rem",
          alignItems: "stretch",
        }}
      >
        {/* Widget A: Department Distribution with visual progress bars */}
        <div
          className="card"
          style={{
            padding: "1.25rem",
            borderRadius: "12px",
            display: "flex",
            flexDirection: "column",
            height: "100%",
            boxSizing: "border-box",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#1e293b" }}>Department Headcount</h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "#64748b" }}>Active employee distribution across teams</p>
            </div>
            <Link to="/employees" style={{ fontSize: "0.78rem", color: "#2563eb", fontWeight: 600, textDecoration: "none" }}>
              Manage →
            </Link>
          </div>

          <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: Object.keys(data.department_distribution).length === 0 ? "center" : "flex-start" }}>
            {Object.keys(data.department_distribution).length === 0 ? (
              <div style={{ textAlign: "center", padding: "2rem 0", color: "#94a3b8", fontSize: "0.85rem" }}>
                No departments configured yet.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                {Object.entries(data.department_distribution).map(([name, count], idx) => {
                  const colorObj = deptPalette[idx % deptPalette.length];
                  const pct = Math.round((count / totalInDepts) * 100);
                  return (
                    <div key={name}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82rem", marginBottom: "4px" }}>
                        <span style={{ fontWeight: 600, color: "#334155" }}>{name}</span>
                        <span style={{ color: "#64748b" }}>
                          <strong>{count}</strong> {count === 1 ? "member" : "members"} ({pct}%)
                        </span>
                      </div>
                      <div style={{ width: "100%", height: "8px", background: "#f1f5f9", borderRadius: "4px", overflow: "hidden" }}>
                        <div
                          style={{
                            width: `${pct}%`,
                            height: "100%",
                            background: colorObj.bg,
                            borderRadius: "4px",
                            transition: "width 0.3s ease",
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Widget B: Recent Onboarding & New Hires */}
        <div
          className="card"
          style={{
            padding: "1.25rem",
            borderRadius: "12px",
            display: "flex",
            flexDirection: "column",
            height: "100%",
            boxSizing: "border-box",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#1e293b" }}>Recent Onboarding</h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "#64748b" }}>Latest team members joined</p>
            </div>
            {isOwner && (
              <Link to="/employees/new" style={{ fontSize: "0.78rem", color: "#2563eb", fontWeight: 600, textDecoration: "none" }}>
                + Onboard
              </Link>
            )}
          </div>

          <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: data.recent_hires.length === 0 ? "center" : "flex-start" }}>
            {data.recent_hires.length === 0 ? (
              <div style={{ textAlign: "center", padding: "2rem 0", color: "#94a3b8", fontSize: "0.85rem" }}>
                No recent employee hires recorded.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
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
                        background: "#f8fafc",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                        <div
                          style={{
                            width: "36px",
                            height: "36px",
                            borderRadius: "50%",
                            background: "#e0e7ff",
                            color: "#4338ca",
                            fontSize: "0.8rem",
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
                            style={{ textDecoration: "none", color: "#0f172a", fontWeight: 600, fontSize: "0.85rem" }}
                          >
                            {fullName}
                          </Link>
                          <div style={{ fontSize: "0.72rem", color: "#64748b" }}>Joined {formatDate(h.hire_date)}</div>
                        </div>
                      </div>
                      <Link
                        to={`/employees/${h.id}`}
                        className="btn btn-sm btn-ghost"
                        style={{ fontSize: "0.75rem", padding: "4px 8px" }}
                      >
                        Profile →
                      </Link>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 4. Company Announcements & Notices Widget */}
      {announcements && announcements.length > 0 && (
        <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", borderLeft: "4px solid #2563eb" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "1.1rem" }}>📢</span>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#1e293b" }}>Company Announcements</h3>
            </div>
            <span className="badge badge-muted">{announcements.length} published</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {announcements.map((ann) => (
              <div key={ann.id} style={{ padding: "8px 0", borderBottom: "1px solid #f1f5f9" }}>
                <div style={{ fontWeight: 600, fontSize: "0.88rem", color: "#1e293b" }}>{ann.title}</div>
                <div style={{ fontSize: "0.82rem", color: "#475569", marginTop: "2px" }}>{ann.content}</div>
                <div style={{ fontSize: "0.72rem", color: "#94a3b8", marginTop: "4px" }}>{formatDate(ann.created_at)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 5. Zoho Quick Module Access / Shortcuts */}
      <div className="card" style={{ padding: "1.25rem", borderRadius: "12px" }}>
        <h3 style={{ margin: "0 0 1rem", fontSize: "0.95rem", fontWeight: 700, color: "#1e293b" }}>
          Quick Module Access
        </h3>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: "0.75rem",
          }}
        >
          <Link
            to="/attendance"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              padding: "10px 14px",
              background: "#f8fafc",
              borderRadius: "8px",
              textDecoration: "none",
              color: "#334155",
              fontSize: "0.85rem",
              fontWeight: 600,
              border: "1px solid #e2e8f0",
            }}
          >
            <span>⏱️</span>
            <span>Attendance Logs</span>
          </Link>

          <Link
            to="/shift-schedule"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              padding: "10px 14px",
              background: "#f8fafc",
              borderRadius: "8px",
              textDecoration: "none",
              color: "#334155",
              fontSize: "0.85rem",
              fontWeight: 600,
              border: "1px solid #e2e8f0",
            }}
          >
            <span>🗓️</span>
            <span>Shift Schedule</span>
          </Link>

          <Link
            to="/payroll/runs"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              padding: "10px 14px",
              background: "#f8fafc",
              borderRadius: "8px",
              textDecoration: "none",
              color: "#334155",
              fontSize: "0.85rem",
              fontWeight: 600,
              border: "1px solid #e2e8f0",
            }}
          >
            <span>💳</span>
            <span>Payroll Runs</span>
          </Link>

          <Link
            to="/performance/goals"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              padding: "10px 14px",
              background: "#f8fafc",
              borderRadius: "8px",
              textDecoration: "none",
              color: "#334155",
              fontSize: "0.85rem",
              fontWeight: 600,
              border: "1px solid #e2e8f0",
            }}
          >
            <span>🎯</span>
            <span>Performance Goals</span>
          </Link>

          <Link
            to="/settings"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              padding: "10px 14px",
              background: "#f8fafc",
              borderRadius: "8px",
              textDecoration: "none",
              color: "#334155",
              fontSize: "0.85rem",
              fontWeight: 600,
              border: "1px solid #e2e8f0",
            }}
          >
            <span>⚙️</span>
            <span>Organization Settings</span>
          </Link>
        </div>
      </div>

      <div style={{ textAlign: "right" }}>
        <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
          Live system status • Updated {new Date(generatedAt).toLocaleTimeString()}
        </span>
      </div>
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
