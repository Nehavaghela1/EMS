import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listLeaves, type Leave, listLeaveTypes } from "../../time_leave/api";
import { listAttendance, type Attendance } from "../../time_leave/api";
import { fetchTimeEntries } from "../../projects/api";
import { listPIPs, listPerformanceCycles, getPerformanceSummary, listPerformanceGoals, type PerformanceGoal } from "../../performance/api";
import { listEmployees } from "../../hr/api";
import { listReimbursements } from "../../payroll/api";
import { getSeriesColor } from "../../../shared/utils/palette";

export interface ManagerDashboardProps {
  data: {
    team_headcount: number;
    team_present_today: number;
    team_leave_requests_awaiting: number;
  };
  user: any;
}

export function ManagerDashboard({ data, user }: ManagerDashboardProps) {
  const managerEmployeeId = user?.employee?.id;
  const companyId = user?.company_id;

  // Format today in ISO (YYYY-MM-DD)
  const today = useMemo(() => new Date(), []);
  const todayStr = useMemo(() => {
    const y = today.getFullYear();
    const m = String(today.getMonth() + 1).padStart(2, "0");
    const d = String(today.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }, [today]);

  // Compute 14 days dates starting from today
  const next14Days = useMemo(() => {
    const days: Array<{ dateStr: string; dayNum: number; formatDay: string; dayName: string; isWeekend: boolean; isToday: boolean }> = [];
    const weekdays = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
    for (let i = 0; i < 14; i++) {
      const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i);
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      const dateStr = `${y}-${m}-${day}`;
      const dayOfWeek = d.getDay();
      const dayNum = d.getDate();
      days.push({
        dateStr,
        dayNum,
        formatDay: d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        dayName: weekdays[dayOfWeek],
        isWeekend: dayOfWeek === 0 || dayOfWeek === 6,
        isToday: i === 0,
      });
    }
    return days;
  }, [today]);

  const rangeEndStr = next14Days[13].dateStr;

  // 1. Direct reports of manager
  const directReportsQuery = useQuery({
    queryKey: ["manager_dashboard_direct_reports", companyId, managerEmployeeId],
    queryFn: async () => {
      const res = await listEmployees({ page: 1, limit: 100 });
      return (res.items || []).filter(
        (emp) => emp.reporting_manager_id === managerEmployeeId && emp.id !== managerEmployeeId
      );
    },
    enabled: Boolean(managerEmployeeId),
  });

  const directReports = directReportsQuery.data ?? [];

  // 2. Today's attendance for team
  const attendanceTodayQuery = useQuery({
    queryKey: ["manager_dashboard_attendance_today", companyId, todayStr],
    queryFn: async () => {
      const res = await listAttendance({
        date_from: todayStr,
        date_to: todayStr,
        page: 1,
        limit: 100,
      });
      return res.items || [];
    },
    enabled: Boolean(companyId),
  });

  const attendanceTodayMap = useMemo(() => {
    const map = new Map<string, Attendance>();
    (attendanceTodayQuery.data ?? []).forEach((att) => {
      map.set(att.employee_id, att);
    });
    return map;
  }, [attendanceTodayQuery.data]);

  // 3. Approved leaves across next 14 days
  const leaves14DaysQuery = useQuery({
    queryKey: ["manager_dashboard_leaves_14days", companyId, todayStr, rangeEndStr],
    queryFn: async () => {
      const res = await listLeaves({
        status: "approved",
        date_from: todayStr,
        date_to: rangeEndStr,
        page: 1,
        limit: 100,
      });
      return res.items || [];
    },
    enabled: Boolean(companyId),
  });

  const leaveTypesQuery = useQuery({
    queryKey: ["manager_dashboard_leave_types", companyId],
    queryFn: () => listLeaveTypes(),
    enabled: Boolean(companyId),
  });

  const leaveTypesMap = useMemo(() => {
    const map = new Map<string, string>();
    (leaveTypesQuery.data ?? []).forEach((lt) => {
      map.set(lt.id, lt.name);
    });
    return map;
  }, [leaveTypesQuery.data]);

  // 4. Pending leaves awaiting manager approval
  const pendingLeavesQuery = useQuery({
    queryKey: ["manager_dashboard_pending_leaves", companyId],
    queryFn: async () => {
      const res = await listLeaves({
        status: "pending",
        page: 1,
        limit: 100,
      });
      return res.items || [];
    },
    enabled: Boolean(companyId),
  });

  // 5. Timesheets awaiting approval
  const pendingTimesheetsQuery = useQuery({
    queryKey: ["manager_dashboard_timesheets", companyId],
    queryFn: () => fetchTimeEntries({ status: "submitted" }),
    enabled: Boolean(companyId),
  });

  // 6. Performance goals for direct reports

  // Goals progress per direct report
  const goalsPerEmployeeQuery = useQuery({
    queryKey: ["manager_dashboard_goals_all", companyId, directReports.map((e) => e.id).join(",")],
    queryFn: async () => {
      if (directReports.length === 0) return {};
      const results: Record<string, PerformanceGoal[]> = {};
      await Promise.all(
        directReports.map(async (emp) => {
          try {
            const goals = await listPerformanceGoals(emp.id);
            results[emp.id] = goals || [];
          } catch {
            results[emp.id] = [];
          }
        })
      );
      return results;
    },
    enabled: directReports.length > 0,
  });

  const goalsMap = goalsPerEmployeeQuery.data ?? {};

  // 7. Reviews owed count
  const reviewsOwedQuery = useQuery({
    queryKey: ["manager_dashboard_reviews_owed", user?.company_id],
    queryFn: async () => {
      try {
        const cyclesRes = await listPerformanceCycles("active");
        if (!cyclesRes.items || cyclesRes.items.length === 0) return 0;
        const employeesRes = await listEmployees({ page: 1, limit: 100 });
        const reports = employeesRes.items.filter(
          (emp) => emp.reporting_manager_id === user?.employee?.id && emp.id !== user?.employee?.id
        );
        if (reports.length === 0) return 0;
        let count = 0;
        for (const rep of reports) {
          try {
            const summary = await getPerformanceSummary(rep.id);
            if (!summary) {
              count += 1;
            }
          } catch {
            // Non-critical per employee
          }
        }
        return count;
      } catch {
        return 0;
      }
    },
    enabled: Boolean(user?.employee?.id),
  });

  // 8. Pending reimbursements awaiting review
  const pendingReimbursementsQuery = useQuery({
    queryKey: ["manager_dashboard_reimbursements", companyId],
    queryFn: async () => {
      const res = await listReimbursements("pending", 1, 100);
      return res.items || [];
    },
    enabled: Boolean(companyId),
  });

  // 9. Open PIPs on team
  const pipsQuery = useQuery({
    queryKey: ["manager_dashboard_pips", companyId],
    queryFn: () => listPIPs({ status: "active" }),
    enabled: Boolean(companyId),
  });

  // 10. Leaves today count
  const leavesTodayQuery = useQuery({
    queryKey: ["manager_dashboard_leaves_today", companyId, todayStr],
    queryFn: () =>
      listLeaves({
        status: "approved",
        date_from: todayStr,
        date_to: todayStr,
        page: 1,
        limit: 100,
      }),
    enabled: Boolean(companyId),
  });

  // Aggregate numbers
  // Note: data.team_leave_requests_awaiting comes directly from /dashboard
  const leaveAwaitingCount = data.team_leave_requests_awaiting ?? (pendingLeavesQuery.data?.length ?? 0);

  const pendingTimesheetsCount = pendingTimesheetsQuery.data?.length ?? 0;
  const teamOnLeaveTodayCount = leavesTodayQuery.data?.total ?? leavesTodayQuery.data?.items?.length ?? 0;
  const openPipsCount = pipsQuery.data?.length ?? 0;
  const reviewsOwedCount = reviewsOwedQuery.data ?? 0;
  const pendingReimbursementsCount = pendingReimbursementsQuery.data?.length ?? 0;

  // Map pending items waiting on manager by employee
  const pendingByEmployee = useMemo(() => {
    const map = new Map<string, { leaves: number; timesheets: number; reimbursements: number }>();
    directReports.forEach((emp) => {
      map.set(emp.id, { leaves: 0, timesheets: 0, reimbursements: 0 });
    });

    (pendingLeavesQuery.data ?? []).forEach((leave) => {
      if (map.has(leave.employee_id)) {
        map.get(leave.employee_id)!.leaves += 1;
      }
    });

    (pendingTimesheetsQuery.data ?? []).forEach((ts) => {
      if (map.has(ts.employee_id)) {
        map.get(ts.employee_id)!.timesheets += 1;
      }
    });

    (pendingReimbursementsQuery.data ?? []).forEach((rm) => {
      if (map.has(rm.employee_id)) {
        map.get(rm.employee_id)!.reimbursements += 1;
      }
    });

    return map;
  }, [directReports, pendingLeavesQuery.data, pendingTimesheetsQuery.data, pendingReimbursementsQuery.data]);

  // Map 14 days leaves by employee
  const leaves14DaysByEmp = useMemo(() => {
    const map = new Map<string, Array<{ leave: Leave; dates: Set<string> }>>();
    (leaves14DaysQuery.data ?? []).forEach((lv) => {
      if (!map.has(lv.employee_id)) {
        map.set(lv.employee_id, []);
      }
      const s = new Date(lv.start_date + "T00:00:00");
      const e = new Date(lv.end_date + "T00:00:00");
      const dateSet = new Set<string>();
      for (let curr = new Date(s); curr <= e; curr.setDate(curr.getDate() + 1)) {
        const y = curr.getFullYear();
        const m = String(curr.getMonth() + 1).padStart(2, "0");
        const d = String(curr.getDate()).padStart(2, "0");
        dateSet.add(`${y}-${m}-${d}`);
      }
      map.get(lv.employee_id)!.push({ leave: lv, dates: dateSet });
    });
    return map;
  }, [leaves14DaysQuery.data]);

  // Helpers for employee status
  function getEmployeeTodayStatus(empId: string): { label: string; color: string; bg: string; dot: string } {
    // 1. Check if on leave today
    const empLeaves = leaves14DaysByEmp.get(empId);
    if (empLeaves) {
      const todayLeave = empLeaves.find((l) => l.dates.has(todayStr));
      if (todayLeave) {
        const typeName = leaveTypesMap.get(todayLeave.leave.leave_type_id) || "On Leave";
        return {
          label: todayLeave.leave.is_half_day ? `${typeName} (Half-Day)` : typeName,
          color: "#c2410c",
          bg: "#fff7ed",
          dot: "#ea580c",
        };
      }
    }

    // 2. Check attendance log today
    const att = attendanceTodayMap.get(empId);
    if (att) {
      if (att.status === "present") {
        return {
          label: att.check_out ? "Clocked out" : "Working now",
          color: "#15803d",
          bg: "#f0fdf4",
          dot: "#16a34a",
        };
      }
      if (att.status === "half_day") {
        return { label: "Half Day", color: "#b45309", bg: "#fefce8", dot: "#d97706" };
      }
      if (att.status === "on_leave") {
        return { label: "On Leave", color: "#c2410c", bg: "#fff7ed", dot: "#ea580c" };
      }
      if (att.status === "absent") {
        return { label: "Absent", color: "#b91c1c", bg: "#fef2f2", dot: "#dc2626" };
      }
    }

    return { label: "Not checked in", color: "#64748b", bg: "#f8fafc", dot: "#94a3b8" };
  }

  function getEmployeeProgress(empId: string): { percent: number; count: number } {
    const goals = goalsMap[empId] || [];
    if (goals.length === 0) return { percent: 0, count: 0 };
    const total = goals.reduce((acc, g) => acc + (g.progress ?? 0), 0);
    return {
      percent: Math.round(total / goals.length),
      count: goals.length,
    };
  }

  function renderQueueValue(val: number) {
    if (val === 0) {
      return (
        <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", color: "var(--color-text-muted, #64748b)", fontSize: "0.92rem", fontWeight: 500 }}>
          <span style={{ color: "var(--color-success, #1f8a4c)", fontSize: "1.1rem" }}>✓</span>
          <span>Nothing waiting</span>
        </span>
      );
    }
    return val;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
      {/* ------------------------------------------------------------- */}
      {/* SECTION 1: LEAD WITH THE TEAM (DIRECT REPORTS)                */}
      {/* ------------------------------------------------------------- */}
      <section className="card" style={{ padding: "1.5rem", borderRadius: "12px", border: "1px solid var(--color-border, #e2e8f0)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "1.25rem", flexWrap: "wrap", gap: "8px" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "var(--color-text, #1e293b)" }}>
              My Team
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "var(--color-text-muted, #64748b)" }}>
              Direct reports, current availability, and individual progress
            </p>
          </div>
          <span className="badge badge-outline" style={{ fontSize: "0.85rem", padding: "4px 10px" }}>
            {directReports.length} {directReports.length === 1 ? "direct report" : "direct reports"}
          </span>
        </div>

        {directReportsQuery.isLoading ? (
          <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "2rem 0", color: "#64748b" }}>
            <div className="spinner" />
            <span>Loading team members...</span>
          </div>
        ) : directReports.length === 0 ? (
          <div style={{ padding: "2.5rem 1rem", textAlign: "center", background: "#f8fafc", borderRadius: "8px", border: "1px dashed #cbd5e1" }}>
            <div style={{ fontSize: "1.75rem", marginBottom: "8px", color: "#1f8a4c" }}>✓</div>
            <div style={{ fontWeight: 600, color: "#1e293b", fontSize: "0.95rem" }}>No direct reports assigned</div>
            <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "#64748b" }}>
              Employees assigned to report to you will appear here with live daily status.
            </p>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {directReports.map((emp, index) => {
              const status = getEmployeeTodayStatus(emp.id);
              const progress = getEmployeeProgress(emp.id);
              const pending = pendingByEmployee.get(emp.id);
              const hasPending = pending && (pending.leaves > 0 || pending.timesheets > 0 || pending.reimbursements > 0);
              const initials = `${emp.first_name?.[0] || ""}${emp.last_name?.[0] || ""}`.toUpperCase() || "E";
              const avatarColor = getSeriesColor(index);

              return (
                <div
                  key={emp.id}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(200px, 1.5fr) minmax(130px, 1fr) minmax(160px, 1.2fr) minmax(150px, 1.1fr) auto",
                    alignItems: "center",
                    gap: "16px",
                    padding: "14px 18px",
                    background: "var(--color-surface, #ffffff)",
                    borderRadius: "10px",
                    border: "1px solid var(--color-border, #e2e8f0)",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                    transition: "all 0.15s ease",
                  }}
                  className="manager-team-row"
                >
                  {/* Avatar + Name + Title */}
                  <div style={{ display: "flex", alignItems: "center", gap: "12px", minWidth: 0 }}>
                    <div
                      style={{
                        width: "40px",
                        height: "40px",
                        borderRadius: "50%",
                        background: avatarColor,
                        color: "#ffffff",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: "0.92rem",
                        flexShrink: 0,
                        letterSpacing: "0.5px",
                      }}
                    >
                      {initials}
                    </div>
                    <div style={{ minWidth: 0, overflow: "hidden" }}>
                      <Link
                        to={`/employees/${emp.id}`}
                        style={{
                          fontWeight: 600,
                          fontSize: "0.95rem",
                          color: "var(--color-text, #1e293b)",
                          textDecoration: "none",
                          display: "block",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                        className="hover-underline"
                      >
                        {emp.first_name} {emp.last_name || ""}
                      </Link>
                      <div
                        style={{
                          fontSize: "0.78rem",
                          color: "var(--color-text-muted, #64748b)",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {emp.position || emp.employee_code}
                      </div>
                    </div>
                  </div>

                  {/* Today's State */}
                  <div>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "6px",
                        padding: "4px 10px",
                        borderRadius: "9999px",
                        background: status.bg,
                        color: status.color,
                        fontSize: "0.82rem",
                        fontWeight: 600,
                      }}
                    >
                      <span
                        style={{
                          width: "7px",
                          height: "7px",
                          borderRadius: "50%",
                          background: status.dot,
                        }}
                      />
                      {status.label}
                    </span>
                  </div>

                  {/* Progress Inline Bar */}
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", color: "var(--color-text-muted, #64748b)", marginBottom: "4px" }}>
                      <span>Goals Progress</span>
                      <span style={{ fontWeight: 600, color: progress.percent < 40 && progress.count > 0 ? getSeriesColor(1) : "inherit" }}>
                        {progress.count > 0 ? `${progress.percent}%` : "—"}
                      </span>
                    </div>
                    <div
                      style={{
                        height: "6px",
                        width: "100%",
                        background: "#f1f5f9",
                        borderRadius: "3px",
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          height: "100%",
                          width: `${progress.percent}%`,
                          background: progress.percent < 40 ? getSeriesColor(1) : getSeriesColor(4),
                          borderRadius: "3px",
                          transition: "width 0.3s ease",
                        }}
                      />
                    </div>
                  </div>

                  {/* Waiting On You Indicator */}
                  <div>
                    {hasPending ? (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                        {pending.leaves > 0 && (
                          <Link
                            to="/leaves"
                            style={{
                              padding: "2px 8px",
                              borderRadius: "4px",
                              background: "#fff1f2",
                              color: "#e11d48",
                              fontSize: "0.75rem",
                              fontWeight: 600,
                              textDecoration: "none",
                              border: "1px solid #ffe4e6",
                            }}
                          >
                            {pending.leaves} {pending.leaves === 1 ? "leave" : "leaves"}
                          </Link>
                        )}
                        {pending.timesheets > 0 && (
                          <Link
                            to="/timesheets"
                            style={{
                              padding: "2px 8px",
                              borderRadius: "4px",
                              background: "#eff6ff",
                              color: "#2563eb",
                              fontSize: "0.75rem",
                              fontWeight: 600,
                              textDecoration: "none",
                              border: "1px solid #dbeafe",
                            }}
                          >
                            {pending.timesheets} {pending.timesheets === 1 ? "timesheet" : "timesheets"}
                          </Link>
                        )}
                        {pending.reimbursements > 0 && (
                          <Link
                            to="/payroll/reimbursements"
                            style={{
                              padding: "2px 8px",
                              borderRadius: "4px",
                              background: "#f0fdf4",
                              color: "#16a34a",
                              fontSize: "0.75rem",
                              fontWeight: 600,
                              textDecoration: "none",
                              border: "1px solid #dcfce7",
                            }}
                          >
                            {pending.reimbursements} claim
                          </Link>
                        )}
                      </div>
                    ) : (
                      <span style={{ fontSize: "0.8rem", color: "#64748b", display: "inline-flex", alignItems: "center", gap: "4px" }}>
                        <span style={{ color: "#16a34a", fontWeight: 700 }}>✓</span> Clear
                      </span>
                    )}
                  </div>

                  {/* Action Link */}
                  <div style={{ textAlign: "right" }}>
                    <Link
                      to={`/employees/${emp.id}`}
                      className="btn btn-sm btn-outline"
                      style={{ fontSize: "0.78rem", whiteSpace: "nowrap" }}
                    >
                      Profile →
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ------------------------------------------------------------- */}
      {/* SECTION 2: WAITING ON YOU (QUEUE TO CLEAR)                    */}
      {/* ------------------------------------------------------------- */}
      <section>
        <div style={{ marginBottom: "1rem" }}>
          <h2 style={{ margin: 0, fontSize: "1.18rem", fontWeight: 700, color: "var(--color-text, #1e293b)" }}>
            What Needs Me Today
          </h2>
          <p style={{ margin: "3px 0 0", fontSize: "0.85rem", color: "var(--color-text-muted, #64748b)" }}>
            Actionable approvals and reviews waiting directly on your decision
          </p>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "1rem",
          }}
        >
          {/* 1. Leave requests awaiting approval */}
          <Link
            to="/leaves"
            style={{ textDecoration: "none", color: "inherit" }}
            className="manager-queue-card"
          >
            <div
              className="card"
              style={{
                padding: "1.25rem",
                borderRadius: "10px",
                border: "1px solid var(--color-border, #e2e8f0)",
                height: "100%",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                borderLeft: leaveAwaitingCount > 0 ? `4px solid ${getSeriesColor(1)}` : "1px solid var(--color-border, #e2e8f0)",
              }}
            >
              <div>
                <div style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--color-text-muted, #64748b)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                  Leave Requests
                </div>
                <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "#1e293b", marginTop: "2px" }}>
                  Leave requests awaiting my approval
                </div>
              </div>
              <div style={{ marginTop: "1rem", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ fontSize: leaveAwaitingCount > 0 ? "1.75rem" : "1rem", fontWeight: 700, color: leaveAwaitingCount > 0 ? "#1e293b" : "inherit" }}>
                  {renderQueueValue(leaveAwaitingCount)}
                </div>
                {leaveAwaitingCount > 0 && (
                  <span style={{ fontSize: "0.78rem", color: "#2563eb", fontWeight: 600 }}>Review →</span>
                )}
              </div>
            </div>
          </Link>

          {/* 2. Timesheet entries awaiting approval */}
          <Link
            to="/timesheets"
            style={{ textDecoration: "none", color: "inherit" }}
            className="manager-queue-card"
          >
            <div
              className="card"
              style={{
                padding: "1.25rem",
                borderRadius: "10px",
                border: "1px solid var(--color-border, #e2e8f0)",
                height: "100%",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                borderLeft: pendingTimesheetsCount > 0 ? `4px solid ${getSeriesColor(0)}` : "1px solid var(--color-border, #e2e8f0)",
              }}
            >
              <div>
                <div style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--color-text-muted, #64748b)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                  Timesheets
                </div>
                <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "#1e293b", marginTop: "2px" }}>
                  Timesheet entries awaiting my approval
                </div>
              </div>
              <div style={{ marginTop: "1rem", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ fontSize: pendingTimesheetsCount > 0 ? "1.75rem" : "1rem", fontWeight: 700, color: pendingTimesheetsCount > 0 ? "#1e293b" : "inherit" }}>
                  {pendingTimesheetsQuery.isLoading ? "..." : renderQueueValue(pendingTimesheetsCount)}
                </div>
                {pendingTimesheetsCount > 0 && (
                  <span style={{ fontSize: "0.78rem", color: "#2563eb", fontWeight: 600 }}>Review →</span>
                )}
              </div>
            </div>
          </Link>

          {/* 3. Team members on leave today */}
          <Link
            to="/leaves"
            style={{ textDecoration: "none", color: "inherit" }}
            className="manager-queue-card"
          >
            <div
              className="card"
              style={{
                padding: "1.25rem",
                borderRadius: "10px",
                border: "1px solid var(--color-border, #e2e8f0)",
                height: "100%",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                borderLeft: teamOnLeaveTodayCount > 0 ? `4px solid ${getSeriesColor(2)}` : "1px solid var(--color-border, #e2e8f0)",
              }}
            >
              <div>
                <div style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--color-text-muted, #64748b)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                  Absence Today
                </div>
                <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "#1e293b", marginTop: "2px" }}>
                  Team members on leave today
                </div>
              </div>
              <div style={{ marginTop: "1rem", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ fontSize: teamOnLeaveTodayCount > 0 ? "1.75rem" : "1rem", fontWeight: 700, color: teamOnLeaveTodayCount > 0 ? "#1e293b" : "inherit" }}>
                  {leavesTodayQuery.isLoading ? "..." : renderQueueValue(teamOnLeaveTodayCount)}
                </div>
                {teamOnLeaveTodayCount > 0 && (
                  <span style={{ fontSize: "0.78rem", color: "#2563eb", fontWeight: 600 }}>Schedule →</span>
                )}
              </div>
            </div>
          </Link>

          {/* 4. Open PIPs on team (maintained for backward test compatibility & direct link) */}
          <Link
            to="/performance"
            style={{ textDecoration: "none", color: "inherit" }}
            className="manager-queue-card"
          >
            <div
              className="card"
              style={{
                padding: "1.25rem",
                borderRadius: "10px",
                border: "1px solid var(--color-border, #e2e8f0)",
                height: "100%",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                borderLeft: openPipsCount > 0 ? `4px solid ${getSeriesColor(6)}` : "1px solid var(--color-border, #e2e8f0)",
              }}
            >
              <div>
                <div style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--color-text-muted, #64748b)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                  Active PIPs
                </div>
                <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "#1e293b", marginTop: "2px" }}>
                  Open PIPs on my team
                </div>
              </div>
              <div style={{ marginTop: "1rem", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ fontSize: openPipsCount > 0 ? "1.75rem" : "1rem", fontWeight: 700, color: openPipsCount > 0 ? "#1e293b" : "inherit" }}>
                  {pipsQuery.isLoading ? "..." : renderQueueValue(openPipsCount)}
                </div>
                {openPipsCount > 0 && (
                  <span style={{ fontSize: "0.78rem", color: "#2563eb", fontWeight: 600 }}>View →</span>
                )}
              </div>
            </div>
          </Link>

          {/* 5. Reviews owed this cycle */}
          <Link
            to="/performance/team-goals"
            style={{ textDecoration: "none", color: "inherit" }}
            className="manager-queue-card"
          >
            <div
              className="card"
              style={{
                padding: "1.25rem",
                borderRadius: "10px",
                border: "1px solid var(--color-border, #e2e8f0)",
                height: "100%",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                borderLeft: reviewsOwedCount > 0 ? `4px solid ${getSeriesColor(3)}` : "1px solid var(--color-border, #e2e8f0)",
              }}
            >
              <div>
                <div style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--color-text-muted, #64748b)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                  Performance
                </div>
                <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "#1e293b", marginTop: "2px" }}>
                  Reviews I still owe this cycle
                </div>
              </div>
              <div style={{ marginTop: "1rem", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ fontSize: reviewsOwedCount > 0 ? "1.75rem" : "1rem", fontWeight: 700, color: reviewsOwedCount > 0 ? "#1e293b" : "inherit" }}>
                  {reviewsOwedQuery.isLoading ? "..." : renderQueueValue(reviewsOwedCount)}
                </div>
                {reviewsOwedCount > 0 && (
                  <span style={{ fontSize: "0.78rem", color: "#2563eb", fontWeight: 600 }}>Evaluate →</span>
                )}
              </div>
            </div>
          </Link>

          {/* 6. Reimbursements queue card (real endpoint) */}
          <Link
            to="/payroll/reimbursements"
            style={{ textDecoration: "none", color: "inherit" }}
            className="manager-queue-card"
          >
            <div
              className="card"
              style={{
                padding: "1.25rem",
                borderRadius: "10px",
                border: "1px solid var(--color-border, #e2e8f0)",
                height: "100%",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                borderLeft: pendingReimbursementsCount > 0 ? `4px solid ${getSeriesColor(4)}` : "1px solid var(--color-border, #e2e8f0)",
              }}
            >
              <div>
                <div style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--color-text-muted, #64748b)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                  Expense Claims
                </div>
                <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "#1e293b", marginTop: "2px" }}>
                  Reimbursements awaiting review
                </div>
              </div>
              <div style={{ marginTop: "1rem", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ fontSize: pendingReimbursementsCount > 0 ? "1.75rem" : "1rem", fontWeight: 700, color: pendingReimbursementsCount > 0 ? "#1e293b" : "inherit" }}>
                  {pendingReimbursementsQuery.isLoading ? "..." : renderQueueValue(pendingReimbursementsCount)}
                </div>
                {pendingReimbursementsCount > 0 && (
                  <span style={{ fontSize: "0.78rem", color: "#2563eb", fontWeight: 600 }}>Review →</span>
                )}
              </div>
            </div>
          </Link>
        </div>
      </section>

      {/* ------------------------------------------------------------- */}
      {/* SECTION 3: 14-DAY APPROVED LEAVE HORIZONTAL STRIP             */}
      {/* ------------------------------------------------------------- */}
      <section className="card" style={{ padding: "1.5rem", borderRadius: "12px", border: "1px solid var(--color-border, #e2e8f0)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "1rem", flexWrap: "wrap", gap: "8px" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "1.18rem", fontWeight: 700, color: "var(--color-text, #1e293b)" }}>
              Next 14 Days Team Schedule
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "var(--color-text-muted, #64748b)" }}>
              Compact calendar of upcoming approved leaves across direct reports
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", fontSize: "0.78rem" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
              <span style={{ width: "12px", height: "12px", borderRadius: "3px", background: getSeriesColor(1) }} />
              <span>Approved Leave</span>
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
              <span style={{ width: "12px", height: "12px", borderRadius: "3px", background: "#f1f5f9", border: "1px dashed #cbd5e1" }} />
              <span>Weekend</span>
            </span>
          </div>
        </div>

        {directReports.length === 0 ? (
          <div style={{ padding: "2rem", textAlign: "center", color: "#64748b" }}>
            No team members to display on schedule.
          </div>
        ) : (
          <div className="manager-leave-strip-container">
            <table
              style={{
                width: "100%",
                minWidth: "720px",
                borderCollapse: "collapse",
                fontSize: "0.82rem",
              }}
            >
              <thead>
                <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                  <th
                    style={{
                      padding: "10px 14px",
                      textAlign: "left",
                      fontWeight: 600,
                      color: "#475569",
                      width: "180px",
                      position: "sticky",
                      left: 0,
                      background: "#f8fafc",
                      zIndex: 2,
                    }}
                  >
                    Person
                  </th>
                  {next14Days.map((d) => (
                    <th
                      key={d.dateStr}
                      style={{
                        padding: "8px 4px",
                        textAlign: "center",
                        fontWeight: 600,
                        color: d.isToday ? "#2563eb" : d.isWeekend ? "#94a3b8" : "#475569",
                        background: d.isToday ? "#eff6ff" : d.isWeekend ? "#f8fafc" : "transparent",
                        borderLeft: "1px solid #f1f5f9",
                        minWidth: "36px",
                      }}
                    >
                      <div style={{ fontSize: "0.72rem", textTransform: "uppercase" }}>{d.dayName}</div>
                      <div style={{ fontSize: "0.9rem", fontWeight: d.isToday ? 700 : 600 }} aria-label={`Day ${d.dayNum}`}>{d.formatDay}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {directReports.map((emp, idx) => {
                  const empLeaves = leaves14DaysByEmp.get(emp.id) || [];
                  const initials = `${emp.first_name?.[0] || ""}${emp.last_name?.[0] || ""}`.toUpperCase();
                  return (
                    <tr
                      key={emp.id}
                      style={{
                        borderBottom: idx < directReports.length - 1 ? "1px solid #f1f5f9" : "none",
                        background: "var(--color-surface, #ffffff)",
                      }}
                    >
                      <td
                        style={{
                          padding: "10px 14px",
                          position: "sticky",
                          left: 0,
                          background: "var(--color-surface, #ffffff)",
                          zIndex: 1,
                          boxShadow: "2px 0 4px rgba(0,0,0,0.02)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span
                            style={{
                              width: "24px",
                              height: "24px",
                              borderRadius: "50%",
                              background: getSeriesColor(idx),
                              color: "#fff",
                              display: "inline-flex",
                              alignItems: "center",
                              justifyContent: "center",
                              fontSize: "0.68rem",
                              fontWeight: 700,
                              flexShrink: 0,
                            }}
                          >
                            {initials}
                          </span>
                          <span style={{ fontWeight: 600, color: "#1e293b", fontSize: "0.85rem" }}>
                            {emp.first_name} {emp.last_name || ""}
                          </span>
                        </div>
                      </td>
                      {next14Days.map((d) => {
                        const matchingLeave = empLeaves.find((l) => l.dates.has(d.dateStr));
                        const isLeaveDay = Boolean(matchingLeave);
                        const leaveTypeName = matchingLeave
                          ? leaveTypesMap.get(matchingLeave.leave.leave_type_id) || "Approved Leave"
                          : "";

                        return (
                          <td
                            key={d.dateStr}
                            title={isLeaveDay ? `${emp.first_name}: ${leaveTypeName} (${d.dateStr})` : undefined}
                            style={{
                              padding: "4px 2px",
                              textAlign: "center",
                              borderLeft: "1px solid #f1f5f9",
                              background: d.isWeekend ? "#fafbfc" : "transparent",
                            }}
                          >
                            {isLeaveDay ? (
                              <div
                                style={{
                                  height: "22px",
                                  margin: "0 2px",
                                  borderRadius: "4px",
                                  background: getSeriesColor(1),
                                  opacity: matchingLeave?.leave.is_half_day ? 0.65 : 1,
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  color: "#ffffff",
                                  fontSize: "0.7rem",
                                  fontWeight: 700,
                                }}
                              >
                                {matchingLeave?.leave.is_half_day ? "½" : "L"}
                              </div>
                            ) : (
                              <span style={{ color: "#e2e8f0", fontSize: "0.65rem" }}>•</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ------------------------------------------------------------- */}
      {/* SECTION 4: TEAM OVERVIEW METRICS                              */}
      {/* ------------------------------------------------------------- */}
      <section>
        <div style={{ marginBottom: "0.75rem" }}>
          <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--color-text, #1e293b)" }}>
            Team Overview
          </h3>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: "1rem",
          }}
        >
          <div className="card" style={{ padding: "1.25rem", borderRadius: "10px", border: "1px solid var(--color-border, #e2e8f0)" }}>
            <div className="stat-label">Team headcount</div>
            <div className="stat-value" style={{ fontSize: "1.75rem", fontWeight: 700, color: "#1e293b" }}>
              {data.team_headcount}
            </div>
            <div className="text-xs text-muted mt-1">Total direct reports in organization</div>
          </div>
          <div className="card" style={{ padding: "1.25rem", borderRadius: "10px", border: "1px solid var(--color-border, #e2e8f0)" }}>
            <div className="stat-label">Team present today</div>
            <div className="stat-value" style={{ fontSize: "1.75rem", fontWeight: 700, color: "#1e293b" }}>
              {data.team_present_today}
            </div>
            <div className="text-xs text-muted mt-1">Checked in for work today</div>
          </div>
        </div>
      </section>
    </div>
  );
}
