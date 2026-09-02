import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { parseApiError } from "../../../shared/api/errors";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { checkIn, checkOut, listAttendance } from "../api";

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

  const [checkBusy, setCheckBusy] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);

  async function refreshAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["attendance"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    ]);
  }

  async function handleCheckIn() {
    setCheckBusy(true);
    setCheckError(null);
    try {
      await checkIn();
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

  return (
    <div className="card mb-6">
      {!user?.employee ? (
        <span className="text-muted">
          No employee record is linked to this account — attendance check-in/out doesn't apply.
        </span>
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
  );
}
