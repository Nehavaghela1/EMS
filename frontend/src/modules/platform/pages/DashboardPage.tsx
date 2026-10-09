import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { PageHeader } from "../../../shared/components/PageHeader";
import { DataTable, type DataTableColumn } from "../../../shared/components/DataTable";
import { usePagination } from "../../../shared/hooks/usePagination";
import { parseApiError } from "../../../shared/api/errors";
import { TodayAttendanceCard } from "../../time_leave/components/TodayAttendanceCard";
import { fetchDashboard, fetchAnnouncements, type EmployeeDashboardData } from "../api";
import {
  listHolidays,
  listAttendance,
  getAssignedShift,
  checkIn,
  checkOut,
} from "../../time_leave/api";
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
  const isEmployee = data?.role === "employee";

  return (
    <div>
      {/* Suppress duplicate generic header for owner/hr/employee who have tailored Zoho hero banners */}
      {!isOwnerOrHr && !isEmployee && <PageHeader title="Dashboard" breadcrumb="Overview" />}

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

      {/* Render standalone attendance card for manager (employee gets integrated Zoho punch card) */}
      {user?.role !== "owner" && !isEmployee && <TodayAttendanceCard showWhenNoEmployee={false} />}

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
            <ZohoEmployeeDashboard
              data={data.data}
              user={user}
              announcements={announcementsQuery.data ?? []}
            />
          )}
        </div>
      )}
    </div>
  );
}

interface ZohoEmployeeDashboardProps {
  data: EmployeeDashboardData;
  user: any;
  announcements: Array<{
    id: string;
    title: string;
    content: string;
    created_at: string;
  }>;
}

function ZohoEmployeeDashboard({ data, user, announcements }: ZohoEmployeeDashboardProps) {
  const queryClient = useQueryClient();
  const firstName = user?.employee?.first_name || "Employee";
  const todayDate = new Date();

  // Live real-time clock ticker
  const [currentTime, setCurrentTime] = useState(new Date());
  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Today Attendance Status Query
  const todayStr = todayDate.toISOString().slice(0, 10);
  const todayAttendanceQuery = useQuery({
    queryKey: ["attendance", "today", user?.employee?.id],
    queryFn: () =>
      listAttendance({
        employee_id: user!.employee!.id,
        date_from: todayStr,
        date_to: todayStr,
        page: 1,
        limit: 1,
      }),
    enabled: Boolean(user?.employee?.id),
  });

  // Recent attendance for unclosed past records
  const recentAttendanceQuery = useQuery({
    queryKey: ["attendance", "recent_unclosed", user?.employee?.id],
    queryFn: () =>
      listAttendance({
        employee_id: user!.employee!.id,
        page: 1,
        limit: 5,
      }),
    enabled: Boolean(user?.employee?.id),
  });

  const [dismissedPastWarning, setDismissedPastWarning] = useState(false);

  const unclosedPastRecord = !dismissedPastWarning
    ? recentAttendanceQuery.data?.items.find(
        (item) => item.date < todayStr && item.check_in && !item.check_out
      )
    : null;

  // Shift assignment query
  const shiftQuery = useQuery({
    queryKey: ["shift", "assigned", user?.employee?.id],
    queryFn: () => getAssignedShift(user!.employee!.id),
    enabled: Boolean(user?.employee?.id),
  });

  // Upcoming holidays query
  const holidaysQuery = useQuery({
    queryKey: ["holidays", todayDate.getFullYear()],
    queryFn: () => listHolidays(todayDate.getFullYear()),
  });

  const upcomingHolidays = (holidaysQuery.data ?? [])
    .filter((h) => h.date >= todayStr)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, 3);

  // Punch actions
  const [punchBusy, setPunchBusy] = useState(false);
  const [punchError, setPunchError] = useState<string | null>(null);

  const todayRecord = todayAttendanceQuery.data?.items[0] ?? null;

  async function handlePunchIn() {
    setPunchBusy(true);
    setPunchError(null);
    try {
      let coords: { latitude: number; longitude: number; device_accuracy: number } | undefined = undefined;
      if (navigator.geolocation) {
        try {
          const pos = await new Promise<GeolocationPosition>((res, rej) =>
            navigator.geolocation.getCurrentPosition(res, rej, { timeout: 6000, enableHighAccuracy: true })
          );
          coords = {
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
            device_accuracy: pos.coords.accuracy,
          };
        } catch {
          // ignore geolocation refusal
        }
      }
      await checkIn(coords);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["attendance"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ]);
    } catch (err) {
      setPunchError(parseApiError(err).message);
    } finally {
      setPunchBusy(false);
    }
  }

  async function handlePunchOut() {
    setPunchBusy(true);
    setPunchError(null);
    try {
      await checkOut();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["attendance"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ]);
    } catch (err) {
      setPunchError(parseApiError(err).message);
    } finally {
      setPunchBusy(false);
    }
  }

  // Calculate live elapsed work time
  let elapsedFormatted = "00h 00m 00s";
  let elapsedPercent = 0; // of 8 hours (28800s)
  if (todayRecord?.check_in && !todayRecord.check_out) {
    const startMs = new Date(todayRecord.check_in).getTime();
    const nowMs = currentTime.getTime();
    const diffSec = Math.max(0, Math.floor((nowMs - startMs) / 1000));
    const h = Math.floor(diffSec / 3600);
    const m = Math.floor((diffSec % 3600) / 60);
    const s = diffSec % 60;
    elapsedFormatted = `${String(h).padStart(2, "0")}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
    elapsedPercent = Math.min(100, Math.round((diffSec / (8 * 3600)) * 100));
  } else if (todayRecord?.check_in && todayRecord.check_out) {
    const startMs = new Date(todayRecord.check_in).getTime();
    const endMs = new Date(todayRecord.check_out).getTime();
    const diffSec = Math.max(0, Math.floor((endMs - startMs) / 1000));
    const h = Math.floor(diffSec / 3600);
    const m = Math.floor((diffSec % 3600) / 60);
    const s = diffSec % 60;
    elapsedFormatted = `${String(h).padStart(2, "0")}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
    elapsedPercent = Math.min(100, Math.round((diffSec / (8 * 3600)) * 100));
  }

  // Format today's date in Zoho style: e.g. Thursday, 8 October 2026
  const formattedTodayLong = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(todayDate);

  const shift = shiftQuery.data?.shift;
  const shiftName = shift?.name ?? "General Shift";
  const shiftTimeStr = shift ? `${shift.start_time.slice(0, 5)} - ${shift.end_time.slice(0, 5)}` : "09:00 - 18:00";

  // Leave balances with color themes
  const leaveColors = [
    { border: "#3b82f6", bg: "#eff6ff", text: "#1d4ed8" }, // Blue
    { border: "#10b981", bg: "#ecfdf5", text: "#047857" }, // Emerald
    { border: "#8b5cf6", bg: "#f5f3ff", text: "#6d28d9" }, // Purple
    { border: "#f59e0b", bg: "#fffbeb", text: "#b45309" }, // Amber
    { border: "#06b6d4", bg: "#ecfeff", text: "#0e7490" }, // Cyan
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      {/* 1. Zoho People Hero Welcome & Live Date/Time Banner */}
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
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
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
              Employee Self-Service
            </span>
            <span style={{ fontSize: "0.82rem", color: "#94a3b8" }}>• {formattedTodayLong}</span>
          </div>

          <h2 style={{ margin: 0, fontSize: "1.4rem", fontWeight: 700, color: "#f8fafc" }}>
            Good {currentTime.getHours() < 12 ? "morning" : currentTime.getHours() < 17 ? "afternoon" : "evening"}, {firstName} 👋
          </h2>
          <p style={{ margin: "4px 0 0", color: "#94a3b8", fontSize: "0.85rem" }}>
            Track attendance, manage leaves, and log timesheets.
          </p>
        </div>

        {/* Live Digital Clock Pill in Header */}
        <div
          style={{
            background: "rgba(255, 255, 255, 0.07)",
            backdropFilter: "blur(8px)",
            border: "1px solid rgba(255, 255, 255, 0.12)",
            borderRadius: "10px",
            padding: "6px 14px",
            display: "flex",
            alignItems: "center",
            gap: "10px",
          }}
        >
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: "0.68rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "#94a3b8", fontWeight: 600 }}>
              Current Time
            </div>
            <div style={{ fontSize: "1.15rem", fontWeight: 700, letterSpacing: "0.04em", color: "#38bdf8", fontFamily: "monospace" }}>
              {currentTime.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </div>
          </div>
          <div
            style={{
              width: "32px",
              height: "32px",
              borderRadius: "8px",
              background: "rgba(56, 189, 248, 0.15)",
              color: "#38bdf8",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
          </div>
        </div>
      </div>

      {/* Unclosed Past Attendance Session Warning Alert */}
      {unclosedPastRecord && (
        <div
          className="alert"
          style={{
            backgroundColor: "#fffbeb",
            border: "1px solid #fde68a",
            color: "#92400e",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "10px",
            padding: "10px 16px",
            borderRadius: "10px",
            boxShadow: "0 1px 3px rgba(0, 0, 0, 0.05)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px", minWidth: 0, flex: 1 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2.2" style={{ flexShrink: 0 }}>
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
              <line x1="12" y1="9" x2="12" y2="13"></line>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            <div style={{ fontSize: "0.84rem", lineHeight: 1.4 }}>
              <strong>Missing Check-Out:</strong> Open punch on <strong>{unclosedPastRecord.date}</strong>. Submit regularization to record clock-out.
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexShrink: 0 }}>
            <Link
              to="/attendance"
              className="btn btn-sm"
              style={{
                backgroundColor: "#f59e0b",
                color: "#ffffff",
                border: "none",
                fontWeight: 600,
                padding: "6px 14px",
                borderRadius: "6px",
                whiteSpace: "nowrap",
                textDecoration: "none",
                fontSize: "0.8rem",
              }}
            >
              Regularize Now →
            </Link>
            <button
              type="button"
              onClick={() => setDismissedPastWarning(true)}
              style={{
                background: "transparent",
                border: "none",
                color: "#92400e",
                cursor: "pointer",
                padding: "4px 8px",
                borderRadius: "4px",
                fontSize: "1rem",
                lineHeight: 1,
                opacity: 0.75,
              }}
              title="Dismiss warning"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* 2. Zoho People Quick Actions Bar */}
      <div
        className="card quick-actions-container"
        style={{
          padding: "0.85rem 1.25rem",
          borderRadius: "12px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "10px",
          background: "#ffffff",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }} className="quick-actions-label">
          <span style={{ fontSize: "0.78rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "#64748b" }}>
            Quick Actions:
          </span>
        </div>
        <div className="quick-actions-grid" style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", flex: 1, justifyContent: "flex-end" }}>
          <Link
            to="/leaves"
            className="btn btn-sm quick-action-btn"
            style={{
              background: "#eff6ff",
              color: "#1d4ed8",
              border: "1px solid #bfdbfe",
              fontWeight: 600,
              padding: "7px 13px",
              borderRadius: "8px",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
              textDecoration: "none",
              fontSize: "0.82rem",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
              <line x1="16" y1="2" x2="16" y2="6"></line>
              <line x1="8" y1="2" x2="8" y2="6"></line>
              <line x1="12" y1="11" x2="12" y2="17"></line>
              <line x1="9" y1="14" x2="15" y2="14"></line>
            </svg>
            Apply Leave
          </Link>

          <Link
            to="/attendance"
            className="btn btn-sm quick-action-btn"
            style={{
              background: "#f0fdf4",
              color: "#15803d",
              border: "1px solid #bbf7d0",
              fontWeight: 600,
              padding: "7px 13px",
              borderRadius: "8px",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
              textDecoration: "none",
              fontSize: "0.82rem",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 14 14"></polyline>
            </svg>
            Regularize
          </Link>

          <Link
            to="/timesheets"
            className="btn btn-sm quick-action-btn"
            style={{
              background: "#f5f3ff",
              color: "#6d28d9",
              border: "1px solid #ddd6fe",
              fontWeight: 600,
              padding: "7px 13px",
              borderRadius: "8px",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
              textDecoration: "none",
              fontSize: "0.82rem",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
            </svg>
            Timesheet
          </Link>

          <Link
            to="/payroll/payslip"
            className="btn btn-sm quick-action-btn"
            style={{
              background: "#f8fafc",
              color: "#334155",
              border: "1px solid #cbd5e1",
              fontWeight: 600,
              padding: "7px 13px",
              borderRadius: "8px",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
              textDecoration: "none",
              fontSize: "0.82rem",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="2" y="4" width="20" height="16" rx="2"></rect>
              <line x1="2" y1="10" x2="22" y2="10"></line>
            </svg>
            Payslip
          </Link>

          <Link
            to="/payroll/reimbursements"
            className="btn btn-sm quick-action-btn"
            style={{
              background: "#fffbeb",
              color: "#b45309",
              border: "1px solid #fde68a",
              fontWeight: 600,
              padding: "6px 14px",
              borderRadius: "8px",
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              textDecoration: "none",
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="1" x2="12" y2="23"></line>
              <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
            </svg>
            Claim Reimbursement
          </Link>
        </div>
      </div>

      {/* 3. Hero Row: Zoho Live Attendance Punch Widget + Monthly Stats Overview */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
          gap: "1.25rem",
        }}
      >
        {/* Widget A: Zoho Live Punch Clock Widget */}
        <div
          className="card"
          style={{
            padding: "1.5rem",
            borderRadius: "14px",
            background: "#ffffff",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            boxShadow: "0 2px 8px rgba(0, 0, 0, 0.04)",
            border: "1px solid var(--color-border, #e2e8f0)",
          }}
        >
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span
                    style={{
                      width: "10px",
                      height: "10px",
                      borderRadius: "50%",
                      backgroundColor:
                        todayRecord?.check_in && !todayRecord.check_out
                          ? "#10b981"
                          : todayRecord?.check_out
                          ? "#64748b"
                          : "#f59e0b",
                      display: "inline-block",
                      boxShadow:
                        todayRecord?.check_in && !todayRecord.check_out
                          ? "0 0 0 3px rgba(16, 185, 129, 0.2)"
                          : "none",
                    }}
                  />
                  <h3 style={{ margin: 0, fontSize: "1.05rem", fontWeight: 700, color: "#1e293b" }}>
                    Attendance Punch Clock
                  </h3>
                </div>
                <div style={{ fontSize: "0.8rem", color: "#64748b", marginTop: "4px" }}>
                  {shiftName} • {shiftTimeStr}
                </div>
              </div>

              {/* Status Badge */}
              <span
                style={{
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  padding: "4px 10px",
                  borderRadius: "20px",
                  backgroundColor:
                    todayRecord?.check_in && !todayRecord.check_out
                      ? "#ecfdf5"
                      : todayRecord?.check_out
                      ? "#f1f5f9"
                      : "#fffbeb",
                  color:
                    todayRecord?.check_in && !todayRecord.check_out
                      ? "#059669"
                      : todayRecord?.check_out
                      ? "#475569"
                      : "#d97706",
                  border: `1px solid ${
                    todayRecord?.check_in && !todayRecord.check_out
                      ? "#a7f3d0"
                      : todayRecord?.check_out
                      ? "#cbd5e1"
                      : "#fde68a"
                  }`,
                }}
              >
                {todayRecord?.check_in && !todayRecord.check_out
                  ? "Clocked In"
                  : todayRecord?.check_out
                  ? "Completed Today"
                  : "Not Clocked In"}
              </span>
            </div>

            {punchError && (
              <div className="alert alert-error mb-3" style={{ fontSize: "0.82rem", padding: "8px 12px" }}>
                {punchError}
              </div>
            )}

            {/* Elapsed Time Digital Display */}
            <div
              style={{
                background: "#f8fafc",
                borderRadius: "12px",
                padding: "1.25rem",
                textAlign: "center",
                border: "1px solid #e2e8f0",
                marginBottom: "1.25rem",
              }}
            >
              <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Working Hours Today
              </div>
              <div
                style={{
                  fontSize: "2.25rem",
                  fontWeight: 800,
                  color: todayRecord?.check_in && !todayRecord.check_out ? "#0f172a" : "#475569",
                  fontFamily: "monospace",
                  marginTop: "4px",
                  letterSpacing: "0.02em",
                }}
              >
                {elapsedFormatted}
              </div>

              {/* Progress bar towards standard 8h day */}
              <div style={{ marginTop: "12px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.72rem", color: "#64748b", marginBottom: "4px" }}>
                  <span>Day Target: 8h 00m</span>
                  <span>{elapsedPercent}%</span>
                </div>
                <div style={{ height: "6px", width: "100%", background: "#e2e8f0", borderRadius: "3px", overflow: "hidden" }}>
                  <div
                    style={{
                      height: "100%",
                      width: `${elapsedPercent}%`,
                      background: elapsedPercent >= 100 ? "#10b981" : "#3b82f6",
                      borderRadius: "3px",
                      transition: "width 0.4s ease",
                    }}
                  />
                </div>
              </div>

              {/* Check-in / Check-out timestamps */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-around",
                  marginTop: "14px",
                  paddingTop: "12px",
                  borderTop: "1px solid #e2e8f0",
                  fontSize: "0.8rem",
                }}
              >
                <div>
                  <span style={{ color: "#64748b" }}>First In: </span>
                  <strong style={{ color: "#0f172a" }}>
                    {todayRecord?.check_in
                      ? new Date(todayRecord.check_in).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                      : "—"}
                  </strong>
                </div>
                <div>
                  <span style={{ color: "#64748b" }}>Last Out: </span>
                  <strong style={{ color: "#0f172a" }}>
                    {todayRecord?.check_out
                      ? new Date(todayRecord.check_out).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                      : "—"}
                  </strong>
                </div>
              </div>
            </div>
          </div>

          {/* Punch Button Actions */}
          <div>
            {!todayRecord?.check_in && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={handlePunchIn}
                disabled={punchBusy}
                style={{
                  width: "100%",
                  padding: "12px",
                  fontSize: "0.95rem",
                  fontWeight: 700,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "8px",
                  borderRadius: "10px",
                  boxShadow: "0 4px 12px rgba(37, 99, 235, 0.25)",
                }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"></path>
                  <polyline points="10 17 15 12 10 7"></polyline>
                  <line x1="15" y1="12" x2="3" y2="12"></line>
                </svg>
                {punchBusy ? "Checking In…" : "Check In Now"}
              </button>
            )}

            {todayRecord?.check_in && !todayRecord.check_out && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={handlePunchOut}
                disabled={punchBusy}
                style={{
                  width: "100%",
                  padding: "12px",
                  fontSize: "0.95rem",
                  fontWeight: 700,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "8px",
                  borderRadius: "10px",
                  backgroundColor: "#dc2626",
                  borderColor: "#b91c1c",
                  boxShadow: "0 4px 12px rgba(220, 38, 38, 0.25)",
                }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                  <polyline points="16 17 21 12 16 7"></polyline>
                  <line x1="21" y1="12" x2="9" y2="12"></line>
                </svg>
                {punchBusy ? "Checking Out…" : "Check Out for the Day"}
              </button>
            )}

            {todayRecord?.check_in && todayRecord.check_out && (
              <div
                style={{
                  textAlign: "center",
                  padding: "10px",
                  background: "#f1f5f9",
                  borderRadius: "8px",
                  fontSize: "0.85rem",
                  color: "#475569",
                  fontWeight: 600,
                }}
              >
                ✓ Day completed ({todayRecord.hours_worked || "8.0"} hrs recorded). See you tomorrow!
              </div>
            )}
          </div>
        </div>

        {/* Widget B: Monthly Attendance Summary & Pending Tasks */}
        <div
          className="card"
          style={{
            padding: "1.5rem",
            borderRadius: "14px",
            background: "#ffffff",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            boxShadow: "0 2px 8px rgba(0, 0, 0, 0.04)",
            border: "1px solid var(--color-border, #e2e8f0)",
          }}
        >
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2">
                  <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                  <line x1="16" y1="2" x2="16" y2="6"></line>
                  <line x1="8" y1="2" x2="8" y2="6"></line>
                  <line x1="3" y1="10" x2="21" y2="10"></line>
                </svg>
                <h3 style={{ margin: 0, fontSize: "1.05rem", fontWeight: 700, color: "#1e293b" }}>
                  This Month's Work Overview
                </h3>
              </div>
              <Link to="/attendance" style={{ fontSize: "0.8rem", color: "#2563eb", fontWeight: 600, textDecoration: "none" }}>
                Full Calendar →
              </Link>
            </div>

            {/* Monthly Attendance Stat Grid */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2, 1fr)",
                gap: "12px",
                marginBottom: "1.25rem",
              }}
            >
              <div
                style={{
                  background: "#f0fdf4",
                  border: "1px solid #bbf7d0",
                  borderRadius: "10px",
                  padding: "1rem",
                }}
              >
                <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "#15803d", textTransform: "uppercase" }}>
                  Days Present
                </div>
                <div style={{ fontSize: "1.75rem", fontWeight: 800, color: "#166534", marginTop: "4px" }}>
                  {data.attendance_this_month?.present ?? 0}
                </div>
                <div style={{ fontSize: "0.72rem", color: "#15803d", marginTop: "2px" }}>
                  Completed shifts
                </div>
              </div>

              <div
                style={{
                  background: "#eff6ff",
                  border: "1px solid #bfdbfe",
                  borderRadius: "10px",
                  padding: "1rem",
                }}
              >
                <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "#1d4ed8", textTransform: "uppercase" }}>
                  Leave Taken
                </div>
                <div style={{ fontSize: "1.75rem", fontWeight: 800, color: "#1e40af", marginTop: "4px" }}>
                  {data.attendance_this_month?.on_leave ?? 0}
                </div>
                <div style={{ fontSize: "0.72rem", color: "#1d4ed8", marginTop: "2px" }}>
                  Approved leaves
                </div>
              </div>

              <div
                style={{
                  background: "#fffbeb",
                  border: "1px solid #fde68a",
                  borderRadius: "10px",
                  padding: "1rem",
                }}
              >
                <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "#b45309", textTransform: "uppercase" }}>
                  Regularizations
                </div>
                <div style={{ fontSize: "1.75rem", fontWeight: 800, color: "#92400e", marginTop: "4px" }}>
                  {data.attendance_this_month?.pending_regularization ?? 0}
                </div>
                <div style={{ fontSize: "0.72rem", color: "#b45309", marginTop: "2px" }}>
                  Pending review
                </div>
              </div>

              <div
                style={{
                  background: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  borderRadius: "10px",
                  padding: "1rem",
                }}
              >
                <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "#475569", textTransform: "uppercase" }}>
                  Pending Requests
                </div>
                <div style={{ fontSize: "1.75rem", fontWeight: 800, color: "#0f172a", marginTop: "4px" }}>
                  {data.pending_requests ?? 0}
                </div>
                <div style={{ fontSize: "0.72rem", color: "#64748b", marginTop: "2px" }}>
                  Leave / approvals
                </div>
              </div>
            </div>
          </div>

          <div
            style={{
              paddingTop: "12px",
              borderTop: "1px solid #f1f5f9",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              fontSize: "0.8rem",
            }}
          >
            <span style={{ color: "#64748b" }}>Assigned Shift Rule:</span>
            <span style={{ fontWeight: 600, color: "#0f172a" }}>9 Hours Total (1h Break)</span>
          </div>
        </div>
      </div>

      {/* 4. Zoho Leave Balances Widget (Visual quota cards with direct Apply button) */}
      <div
        className="card"
        style={{
          padding: "1.5rem",
          borderRadius: "14px",
          background: "#ffffff",
          boxShadow: "0 2px 8px rgba(0, 0, 0, 0.04)",
          border: "1px solid var(--color-border, #e2e8f0)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem", flexWrap: "wrap", gap: "10px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2">
                <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
              </svg>
              <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#1e293b" }}>
                My Leave Balances ({todayDate.getFullYear()})
              </h3>
            </div>
            <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: "0.82rem" }}>
              Your current allocated annual quotas and available days for each leave policy.
            </p>
          </div>

          <Link
            to="/leaves"
            className="btn btn-sm"
            style={{
              backgroundColor: "#2563eb",
              color: "#ffffff",
              fontWeight: 600,
              padding: "8px 16px",
              borderRadius: "8px",
              textDecoration: "none",
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              boxShadow: "0 2px 8px rgba(37, 99, 235, 0.25)",
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            Apply Leave
          </Link>
        </div>

        {data.leave_balances.length === 0 ? (
          <div
            style={{
              padding: "2rem",
              textAlign: "center",
              background: "#f8fafc",
              borderRadius: "10px",
              border: "1px dashed #cbd5e1",
            }}
          >
            <div style={{ fontSize: "1.75rem", marginBottom: "6px" }}>🏖️</div>
            <div style={{ fontWeight: 600, color: "#1e293b" }}>No leave balances allocated yet</div>
            <div style={{ fontSize: "0.82rem", color: "#64748b", marginTop: "4px" }}>
              Leave balances are activated when your leave policy period starts or when approved by HR.
            </div>
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(185px, 1fr))",
              gap: "1rem",
            }}
          >
            {data.leave_balances.map((b, index) => {
              const theme = leaveColors[index % leaveColors.length];
              const availableNum = parseFloat(b.available) || 0;
              return (
                <Link
                  key={b.leave_type_id}
                  to={`/leaves?leave_type_id=${b.leave_type_id}`}
                  style={{
                    background: theme.bg,
                    border: `1px solid ${theme.border}`,
                    borderTop: `4px solid ${theme.border}`,
                    borderRadius: "10px",
                    padding: "1rem 1.15rem",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                    minHeight: "115px",
                    textDecoration: "none",
                    cursor: "pointer",
                    transition: "transform 0.15s ease, box-shadow 0.15s ease",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = "translateY(-2px)";
                    e.currentTarget.style.boxShadow = "0 6px 14px -2px rgba(0, 0, 0, 0.08)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = "none";
                    e.currentTarget.style.boxShadow = "none";
                  }}
                  title={`Click to apply for ${b.leave_type_name || "leave"}`}
                >
                  <div>
                    <div style={{ fontSize: "0.82rem", fontWeight: 700, color: theme.text, textTransform: "capitalize" }}>
                      {b.leave_type_name || "Leave"}
                    </div>
                    <div style={{ display: "flex", alignItems: "baseline", gap: "6px", marginTop: "6px" }}>
                      <span style={{ fontSize: "1.85rem", fontWeight: 800, color: "#0f172a", lineHeight: 1 }}>
                        {b.available}
                      </span>
                      <span style={{ fontSize: "0.8rem", color: "#64748b", fontWeight: 500 }}>
                        {availableNum === 1 ? "day left" : "days left"}
                      </span>
                    </div>
                  </div>

                  <div style={{ marginTop: "12px", paddingTop: "8px", borderTop: "1px solid rgba(0, 0, 0, 0.06)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: "0.72rem", color: "#64748b" }}>Available quota</span>
                    <span
                      style={{
                        fontSize: "0.75rem",
                        fontWeight: 700,
                        color: theme.text,
                      }}
                    >
                      Apply →
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>

      {/* 5. Bottom Two-Column: Upcoming Statutory Holidays & Company Announcements */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: "1.25rem",
        }}
      >
        {/* Widget: Upcoming Holidays */}
        <div
          className="card"
          style={{
            padding: "1.5rem",
            borderRadius: "14px",
            background: "#ffffff",
            boxShadow: "0 2px 8px rgba(0, 0, 0, 0.04)",
            border: "1px solid var(--color-border, #e2e8f0)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2">
                <circle cx="12" cy="12" r="10"></circle>
                <path d="M12 6v6l4 2"></path>
              </svg>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#1e293b" }}>
                Upcoming Holidays
              </h3>
            </div>
            <Link to="/holidays" style={{ fontSize: "0.8rem", color: "#2563eb", fontWeight: 600, textDecoration: "none" }}>
              All Holidays →
            </Link>
          </div>

          {upcomingHolidays.length === 0 ? (
            <div style={{ padding: "1.5rem", textAlign: "center", color: "#64748b", fontSize: "0.85rem" }}>
              No upcoming public holidays scheduled for this calendar period.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {upcomingHolidays.map((holiday) => {
                const holidayDate = new Date(holiday.date);
                const daysDiff = Math.ceil((holidayDate.getTime() - todayDate.getTime()) / (1000 * 3600 * 24));
                return (
                  <div
                    key={holiday.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "10px 14px",
                      background: "#f8fafc",
                      borderRadius: "10px",
                      border: "1px solid #f1f5f9",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                      <div
                        style={{
                          width: "40px",
                          height: "40px",
                          borderRadius: "8px",
                          background: "#eff6ff",
                          color: "#1d4ed8",
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "center",
                          justifyContent: "center",
                          fontWeight: 700,
                          lineHeight: 1,
                        }}
                      >
                        <span style={{ fontSize: "0.68rem", textTransform: "uppercase" }}>
                          {holidayDate.toLocaleString("en-US", { month: "short" })}
                        </span>
                        <span style={{ fontSize: "0.95rem", marginTop: "2px" }}>
                          {holidayDate.getDate()}
                        </span>
                      </div>
                      <div>
                        <div style={{ fontWeight: 600, fontSize: "0.88rem", color: "#1e293b" }}>
                          {holiday.name}
                        </div>
                        <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
                          {holidayDate.toLocaleDateString("en-US", { weekday: "long" })}
                        </div>
                      </div>
                    </div>

                    <span
                      style={{
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        padding: "3px 8px",
                        borderRadius: "12px",
                        background: daysDiff <= 7 ? "#fef3c7" : "#f1f5f9",
                        color: daysDiff <= 7 ? "#b45309" : "#475569",
                      }}
                    >
                      {daysDiff === 0 ? "Today" : daysDiff === 1 ? "Tomorrow" : `In ${daysDiff} days`}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Widget: Announcements & Organization Noticeboard */}
        <div
          className="card"
          style={{
            padding: "1.5rem",
            borderRadius: "14px",
            background: "#ffffff",
            boxShadow: "0 2px 8px rgba(0, 0, 0, 0.04)",
            border: "1px solid var(--color-border, #e2e8f0)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
              </svg>
              <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#1e293b" }}>
                Company Noticeboard
              </h3>
            </div>
            <span style={{ fontSize: "0.75rem", color: "#64748b", fontWeight: 600 }}>
              {announcements.length} updates
            </span>
          </div>

          {announcements.length === 0 ? (
            <div
              style={{
                padding: "2rem 1.5rem",
                textAlign: "center",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
                background: "#f8fafc",
                borderRadius: "10px",
                border: "1px dashed #e2e8f0",
              }}
            >
              <div
                style={{
                  width: "42px",
                  height: "42px",
                  borderRadius: "50%",
                  background: "#eff6ff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#2563eb",
                  marginBottom: "2px",
                }}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                  <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                </svg>
              </div>
              <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "#1e293b" }}>
                All Caught Up!
              </div>
              <div style={{ fontSize: "0.78rem", color: "#64748b", maxWidth: "260px", lineHeight: 1.4 }}>
                No active announcements posted by HR. Company updates and circulars will appear here.
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {announcements.slice(0, 3).map((ann) => (
                <div
                  key={ann.id}
                  style={{
                    padding: "10px 14px",
                    background: "#f8fafc",
                    borderRadius: "10px",
                    border: "1px solid #f1f5f9",
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: "0.88rem", color: "#1e293b" }}>{ann.title}</div>
                  <div style={{ fontSize: "0.8rem", color: "#475569", marginTop: "2px", lineHeight: 1.4 }}>
                    {ann.content}
                  </div>
                  <div style={{ fontSize: "0.72rem", color: "#94a3b8", marginTop: "6px" }}>
                    {formatDate(ann.created_at)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
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
