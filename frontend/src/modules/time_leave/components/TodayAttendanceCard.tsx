import { useState } from "react";
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
export function TodayAttendanceCard({ showWhenNoEmployee = true }: { showWhenNoEmployee?: boolean }) {
  const { user } = useAuth();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const today = todayIso();

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

  const unclosedPastRecord = recentHistoryQuery.data?.items.find(
    (item) => item.date < today && item.check_in && !item.check_out
  );

  const assignedShiftQuery = useQuery({
    queryKey: ["shift", "assigned", user?.employee?.id],
    queryFn: () => getAssignedShift(user!.employee!.id),
    enabled: Boolean(user?.employee?.id),
  });

  const [checkBusy, setCheckBusy] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [showRegularizeModal, setShowRegularizeModal] = useState(false);

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

  if (!user?.employee && !showWhenNoEmployee) return null;

  const assignedShift = assignedShiftQuery.data?.shift;
  const shiftName = assignedShift?.name ?? "General";
  const shiftStart = assignedShift ? formatTimeString(assignedShift.start_time) : "09:00 AM";
  const shiftEnd = assignedShift ? formatTimeString(assignedShift.end_time) : "06:00 PM";
  const assignedShiftLabel = `Assigned Shift: ${shiftName} (${shiftStart} - ${shiftEnd})`;

  return (
    <div className="mb-6">
      {user?.employee && (
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
            padding: "10px 16px",
            borderRadius: "8px",
            marginBottom: "1rem",
            fontSize: "0.88rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "1.1rem" }}>⚠️</span>
            <span>
              <strong>Missing Check-Out:</strong> You have an open attendance punch from{" "}
              <strong>{unclosedPastRecord.date}</strong>. Live clock is closed. Please apply for attendance regularization.
            </span>
          </div>
          <button
            type="button"
            onClick={() => setShowRegularizeModal(true)}
            className="btn btn-sm"
            style={{
              backgroundColor: "#f59e0b",
              color: "#ffffff",
              border: "none",
              fontWeight: 600,
              padding: "4px 12px",
              borderRadius: "6px",
              whiteSpace: "nowrap",
              cursor: "pointer",
            }}
          >
            Regularize Now
          </button>
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
        ) : todayQuery.isLoading ? (
          <div className="row">
            <div className="spinner" />
            <span className="text-muted">Loading today's status…</span>
          </div>
        ) : (
          <div className="stack">
            {checkError && <div className="alert alert-error">{checkError}</div>}
            {!todayRecord && (
              <div className="row-between">
                <span>You haven't checked in today.</span>
                <button className="btn btn-primary" onClick={handleCheckIn} disabled={checkBusy}>
                  {checkBusy ? "Checking in…" : "Check in"}
                </button>
              </div>
            )}
            {todayRecord && !todayRecord.check_out && (
              <div className="row-between">
                <span>
                  Checked in at {new Date(todayRecord.check_in!).toLocaleTimeString()}. Still clocked in.
                </span>
                <button className="btn btn-primary" onClick={handleCheckOut} disabled={checkBusy}>
                  {checkBusy ? "Checking out…" : "Check out"}
                </button>
              </div>
            )}
            {todayRecord && todayRecord.check_out && (
              <div>
                Done for today — {new Date(todayRecord.check_in!).toLocaleTimeString()} to{" "}
                {new Date(todayRecord.check_out).toLocaleTimeString()} ({todayRecord.hours_worked}h,{" "}
                {todayRecord.status.replace("_", " ")}).
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

