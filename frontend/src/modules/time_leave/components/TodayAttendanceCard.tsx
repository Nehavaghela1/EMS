import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { parseApiError } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { checkIn, checkOut, getAssignedShift, listAttendance, submitRegularizationRequest } from "../api";
import { RegularizeAttendanceModal } from "./RegularizeAttendanceModal";

function formatTimeString(timeStr: string): string {
  // Converts "09:00:00" or "09:00" to "09:00 AM"
  const parts = timeStr.split(":");
  let hours = parseInt(parts[0], 10);
  const minutes = parts[1] || "00";
  if (isNaN(hours)) return timeStr;
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12;
  hours = hours ? hours : 12;
  return `${String(hours).padStart(2, "0")}:${minutes} ${ampm}`;
}

function formatPunchTime(isoString: string): string {
  try {
    const d = new Date(isoString);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return isoString;
  }
}

function formatHoursValue(val: string | number | null | undefined): string {
  if (val === null || val === undefined) return "0.00";
  const num = typeof val === "number" ? val : parseFloat(val);
  return isNaN(num) ? "0.00" : num.toFixed(2);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Part 2: check-in/out from the employee's own landing page (the
 * dashboard), not only the shared team/company attendance screen — the
 * same widget also still appears at the top of AttendancePage itself, so
 * there is exactly one implementation of "today's status," not two drifting
 * copies.
 */
export function TodayAttendanceCard({
  showWhenNoEmployee = true,
  collapsedPunchTrail = false,
}: {
  showWhenNoEmployee?: boolean;
  collapsedPunchTrail?: boolean;
}) {
  const { user } = useAuth();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const today = todayIso();
  const [, setCurrentTime] = useState(() => new Date());

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const todayQuery = useQuery({
    queryKey: ["attendance", "today", user?.employee?.id],
    queryFn: () =>
      listAttendance({
        employee_id: user!.employee!.id,
        date_from: today,
        date_to: today,
        page: 1,
        limit: 1,
      }),
    enabled: Boolean(user?.employee),
  });

  // Check if employee has an open attendance session from past days (Rule A/C: missing punch)
  const recentHistoryQuery = useQuery({
    queryKey: ["attendance", "recent_unclosed", user?.employee?.id],
    queryFn: () =>
      listAttendance({
        employee_id: user!.employee!.id,
        page: 1,
        limit: 5,
      }),
    enabled: Boolean(user?.employee),
  });

  // Attendance-exempt users (owners) never see missing-punch warnings
  const isAttendanceExempt = user?.role === 'owner';

  const unclosedPastRecord = isAttendanceExempt
    ? undefined
    : recentHistoryQuery.data?.items.find(
        (item) =>
          item.date < today &&
          item.check_in &&
          !item.check_out &&
          item.status !== "pending_regularization" &&
          item.active_regularization?.status !== "pending"
      );

  const assignedShiftQuery = useQuery({
    queryKey: ["shift", "assigned", user?.employee?.id],
    queryFn: () => getAssignedShift(user!.employee!.id),
    enabled: Boolean(user?.employee?.id),
  });

  const [checkBusy, setCheckBusy] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [showRegularizeModal, setShowRegularizeModal] = useState(false);
  const [dismissedPastWarning, setDismissedPastWarning] = useState(false);

  async function refreshAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["attendance"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    ]);
  }

  async function handleCheckIn() {
    setCheckBusy(true);
    setCheckError(null);

    let coords: { latitude: number; longitude: number; device_accuracy: number } | undefined = undefined;

    if (navigator.geolocation) {
      try {
        const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject, {
            timeout: 8000,
            enableHighAccuracy: true,
            maximumAge: 30000,
          });
        });
        coords = {
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          device_accuracy: pos.coords.accuracy,
        };
      } catch (geoErr) {
        // Geolocation denied or timed out; continue without coords
        // The backend will check if a geofence is mandatory for this employee's branch
      }
    }

    try {
      await checkIn(coords);
      notify("Checked in.");
      await refreshAll();
    } catch (err) {
      setCheckError(parseApiError(err).message);
    } finally {
      setCheckBusy(false);
    }
  }

  async function handleCheckOut() {
    setCheckBusy(true);
    setCheckError(null);
    try {
      await checkOut();
      notify("Checked out.");
      await refreshAll();
    } catch (err) {
      setCheckError(parseApiError(err).message);
    } finally {
      setCheckBusy(false);
    }
  }

  const todayRecord = todayQuery.data?.items[0] ?? null;

  // Determine current clock-in state:
  // If punches are present, the last punch direction is the authoritative state.
  // Otherwise fall back to check_in && !check_out.
  const lastPunchDirection =
    todayRecord?.punches && todayRecord.punches.length > 0
      ? todayRecord.punches[todayRecord.punches.length - 1].direction
      : null;
  const isCurrentlyClockedIn =
    lastPunchDirection != null
      ? lastPunchDirection === "in"
      : Boolean(todayRecord?.check_in && !todayRecord.check_out);

  if (!user?.employee && !showWhenNoEmployee) return null;

  const assignedShift = assignedShiftQuery.data?.shift;
  const shiftName = assignedShift?.name ?? "General";
  const shiftStart = assignedShift ? formatTimeString(assignedShift.start_time) : "09:00 AM";
  const shiftEnd = assignedShift ? formatTimeString(assignedShift.end_time) : "06:00 PM";
  const assignedShiftLabel = `Assigned Shift: ${shiftName} (${shiftStart} - ${shiftEnd})`;

  return (
    <div className="mb-6">
      {/* Attendance-exempt users (owner/executives) skip the punch clock strip entirely */}
      {user?.employee && !isAttendanceExempt && (
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            padding: "6px 14px",
            borderRadius: "8px",
            fontSize: "0.85rem",
            fontWeight: 500,
            color: "var(--color-primary, #2563eb)",
            backgroundColor: "var(--color-primary-subtle, #eff6ff)",
            border: "1px solid var(--color-primary-border, #bfdbfe)",
            marginBottom: "0.6rem",
          }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
          </svg>
          <span>{assignedShiftLabel}</span>
        </div>
      )}

      {unclosedPastRecord && !dismissedPastWarning && (
        <div
          className="alert check-out-alert-box"
          style={{
            backgroundColor: "#fffbeb",
            border: "1px solid #fde68a",
            color: "#92400e",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "12px",
            padding: "12px 16px",
            borderRadius: "10px",
            marginBottom: "1rem",
            boxShadow: "0 1px 3px rgba(0, 0, 0, 0.05)",
          }}
        >
          <div className="check-out-alert-text" style={{ display: "flex", alignItems: "flex-start", gap: "10px", flex: 1, minWidth: "240px" }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2.2" style={{ flexShrink: 0, marginTop: "2px" }}>
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
              <line x1="12" y1="9" x2="12" y2="13"></line>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            <div style={{ fontSize: "0.85rem", lineHeight: 1.45, color: "#92400e" }}>
              <strong>Missing Check-Out:</strong> Open punch on <strong>{unclosedPastRecord.date}</strong>. Live clock is closed. Submit regularization to record clock-out.
            </div>
          </div>
          <div className="check-out-alert-actions" style={{ display: "flex", alignItems: "center", gap: "10px", flexShrink: 0 }}>
            <button
              type="button"
              onClick={() => setShowRegularizeModal(true)}
              className="btn btn-sm"
              style={{
                backgroundColor: "#f59e0b",
                color: "#ffffff",
                border: "none",
                fontWeight: 600,
                padding: "7px 16px",
                borderRadius: "6px",
                whiteSpace: "nowrap",
                cursor: "pointer",
                fontSize: "0.82rem",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              Regularize Now
            </button>
            <button
              type="button"
              onClick={() => setDismissedPastWarning(true)}
              style={{
                background: "transparent",
                border: "none",
                color: "#92400e",
                cursor: "pointer",
                padding: "6px 8px",
                borderRadius: "4px",
                fontSize: "1.1rem",
                lineHeight: 1,
                opacity: 0.7,
                transition: "opacity 0.15s ease",
              }}
              title="Dismiss warning for now"
              aria-label="Dismiss warning"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {showRegularizeModal && unclosedPastRecord && (
        <RegularizeAttendanceModal
          isOpen={showRegularizeModal}
          onClose={() => setShowRegularizeModal(false)}
          isAdmin={false}
          employeeName={user?.employee ? `${user.employee.first_name} ${user.employee.last_name || ""}`.trim() : "My Attendance"}
          attendanceDate={unclosedPastRecord.date}
          currentStatus={unclosedPastRecord.status}
          initialCheckIn={unclosedPastRecord.check_in}
          initialCheckOut={unclosedPastRecord.check_out}
          existingReason={unclosedPastRecord.notes}
          onSubmit={async (formData) => {
            await submitRegularizationRequest(unclosedPastRecord.id, formData);
            notify("Regularization request submitted to your manager.");
            setShowRegularizeModal(false);
            await refreshAll();
          }}
        />
      )}

      <div className="card">
        {/* Attendance-exempt employees (owner/executives) never see punch prompts */}
        {!user?.employee ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 0" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <div
                style={{
                  width: "36px",
                  height: "36px",
                  borderRadius: "8px",
                  backgroundColor: "#eff6ff",
                  color: "#2563eb",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1.1rem",
                }}
              >
                🛡️
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: "0.95rem", color: "var(--color-heading, #1e293b)" }}>
                  HR Admin Attendance Portal
                </div>
                <div className="text-muted text-xs">
                  Viewing organization-wide attendance & shift records. Check-in/out applies to employee accounts.
                </div>
              </div>
            </div>
            <span className="badge badge-outline" style={{ fontWeight: 600 }}>Admin View</span>
          </div>
        ) : isAttendanceExempt ? (
          <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "4px 0" }}>
            <div
              style={{
                width: "36px", height: "36px", borderRadius: "8px",
                background: "linear-gradient(135deg, #f59e0b, #d97706)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "1.1rem", flexShrink: 0,
              }}
            >
              👑
            </div>
            <div>
              <div style={{ fontWeight: 600, fontSize: "0.9rem", color: "#92400e" }}>
                Executive Account — Attendance Exempt
              </div>
              <div style={{ fontSize: "0.78rem", color: "#b45309", marginTop: "1px" }}>
                Check-in / check-out tracking is disabled for your account by policy.
              </div>
            </div>
          </div>
        ) : todayQuery.isLoading ? (
          <div className="row">
            <div className="spinner" />
            <span className="text-muted">Loading today's status…</span>
          </div>
        ) : (
          <div className="stack">
            {checkError && <div className="alert alert-error">{checkError}</div>}
            
            {/* Primary Action Row */}
            {!todayRecord?.check_in && (
              <div className="row-between">
                <div>
                  <div style={{ fontWeight: 600, color: "#1e293b" }}>Not Clocked In</div>
                  <div className="text-muted text-xs">You haven't checked in today.</div>
                </div>
                <button className="btn btn-primary" onClick={handleCheckIn} disabled={checkBusy}>
                  {checkBusy ? "Checking in…" : "Check in"}
                </button>
              </div>
            )}

            {isCurrentlyClockedIn && (
              <div className="row-between">
                <div>
                  <div style={{ fontWeight: 600, color: "#059669" }}>
                    Clocked in since{" "}
                    {todayRecord?.punches && todayRecord.punches.length > 0
                      ? formatPunchTime(
                          [...todayRecord.punches].reverse().find((p) => p.direction === "in")?.punched_at ||
                            todayRecord.check_in!
                        )
                      : formatPunchTime(todayRecord!.check_in!)}
                  </div>
                  <div className="text-muted text-xs">Still clocked in · Active session</div>
                </div>
                <button
                  className="btn btn-primary"
                  onClick={handleCheckOut}
                  disabled={checkBusy}
                  style={{ backgroundColor: "#dc2626", borderColor: "#b91c1c" }}
                >
                  {checkBusy ? "Checking out…" : "Check out"}
                </button>
              </div>
            )}

            {!isCurrentlyClockedIn && todayRecord?.check_in && (
              <div className="row-between">
                <div>
                  <div style={{ fontWeight: 600, color: "#475569" }}>
                    Clocked out
                    {todayRecord.check_out ? ` at ${formatPunchTime(todayRecord.check_out)}` : ""}
                  </div>
                  <div className="text-muted text-xs">Day open · You can clock back in</div>
                </div>
                <button className="btn btn-primary" onClick={handleCheckIn} disabled={checkBusy}>
                  {checkBusy ? "Checking in…" : "Check in again"}
                </button>
              </div>
            )}

            {/* Live Figures from Attendance Row */}
            {todayRecord?.check_in && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))",
                  gap: "10px",
                  padding: "10px 14px",
                  background: "#f8fafc",
                  borderRadius: "8px",
                  border: "1px solid #e2e8f0",
                  marginTop: "8px",
                  fontSize: "0.82rem",
                }}
              >
                <div>
                  <span style={{ color: "#64748b" }}>Worked: </span>
                  <strong style={{ color: "#0f172a" }}>
                    {formatHoursValue(todayRecord.worked_hours ?? todayRecord.hours_worked)} hrs
                  </strong>
                </div>
                <div>
                  <span style={{ color: "#64748b" }}>Outside: </span>
                  <strong style={{ color: "#0f172a" }}>
                    {formatHoursValue(todayRecord.outside_hours)} hrs
                  </strong>
                </div>
                <div>
                  <span style={{ color: "#64748b" }}>First in: </span>
                  <strong style={{ color: "#0f172a" }}>
                    {formatPunchTime(todayRecord.check_in)}
                  </strong>
                </div>
                <div>
                  <span style={{ color: "#64748b" }}>Last out: </span>
                  <strong style={{ color: "#0f172a" }}>
                    {todayRecord.check_out ? formatPunchTime(todayRecord.check_out) : "—"}
                  </strong>
                </div>
              </div>
            )}

            {/* Punch Trail Sequence */}
            {todayRecord?.punches && todayRecord.punches.length > 0 && (
              <div
                style={{
                  marginTop: "6px",
                  padding: "6px 10px",
                  background: "#f1f5f9",
                  borderRadius: "6px",
                  fontSize: "0.78rem",
                  color: "#475569",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  overflowX: collapsedPunchTrail ? "hidden" : "auto",
                  textOverflow: collapsedPunchTrail ? "ellipsis" : "clip",
                  whiteSpace: "nowrap",
                }}
              >
                <span style={{ fontWeight: 600, color: "#64748b", textTransform: "uppercase", fontSize: "0.7rem" }}>
                  Trail:
                </span>
                {todayRecord.punches.map((p, idx) => (
                  <span key={p.id || idx} style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                    {idx > 0 && <span style={{ color: "#94a3b8" }}>→</span>}
                    <span
                      style={{
                        fontWeight: 600,
                        color: p.direction === "in" ? "#059669" : "#dc2626",
                      }}
                    >
                      {formatPunchTime(p.punched_at)} {p.direction}
                    </span>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}


