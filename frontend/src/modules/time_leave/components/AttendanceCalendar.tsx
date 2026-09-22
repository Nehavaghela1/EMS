import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getAttendanceCalendar, type CalendarDay } from "../api";
import { formatDate } from "../../../shared/utils/date";

interface AttendanceCalendarProps {
  employeeId?: string;
  employeeName?: string;
}

const STATUS_CONFIG: Record<
  string,
  { label: string; bg: string; border: string; text: string; dot: string }
> = {
  in_progress: {
    label: "In Progress",
    bg: "#eff6ff",
    border: "#93c5fd",
    text: "#1d4ed8",
    dot: "#2563eb",
  },
  present: {
    label: "Present",
    bg: "#ecfdf5",
    border: "#a7f3d0",
    text: "#065f46",
    dot: "#10b981",
  },
  half_day: {
    label: "Half Day",
    bg: "#fffbeb",
    border: "#fde68a",
    text: "#92400e",
    dot: "#f59e0b",
  },
  wfh: {
    label: "WFH",
    bg: "#f0fdf4",
    border: "#bbf7d0",
    text: "#166534",
    dot: "#22c55e",
  },
  mispunch: {
    label: "Mispunch",
    bg: "#fefce8",
    border: "#fef08a",
    text: "#854d0e",
    dot: "#eab308",
  },
  pending_regularization: {
    label: "Regularizing",
    bg: "#fef3c7",
    border: "#fde68a",
    text: "#b45309",
    dot: "#d97706",
  },
  on_leave: {
    label: "On Leave",
    bg: "#eff6ff",
    border: "#bfdbfe",
    text: "#1e40af",
    dot: "#3b82f6",
  },
  holiday: {
    label: "Holiday",
    bg: "#faf5ff",
    border: "#d8b4fe",
    text: "#6b21a8",
    dot: "#9333ea",
  },
  weekend: {
    label: "Weekend",
    bg: "#f8fafc",
    border: "#e2e8f0",
    text: "#64748b",
    dot: "#94a3b8",
  },
  absent: {
    label: "Absent",
    bg: "#fef2f2",
    border: "#fecaca",
    text: "#991b1b",
    dot: "#ef4444",
  },
  no_record: {
    label: "Upcoming",
    bg: "#ffffff",
    border: "#e2e8f0",
    text: "#94a3b8",
    dot: "#cbd5e1",
  },
};

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function AttendanceCalendar({ employeeId, employeeName }: AttendanceCalendarProps) {
  const now = new Date();
  const [currentMonth, setCurrentMonth] = useState<number>(now.getMonth() + 1);
  const [currentYear, setCurrentYear] = useState<number>(now.getFullYear());
  const [selectedDay, setSelectedDay] = useState<CalendarDay | null>(null);

  const calendarQuery = useQuery({
    queryKey: ["attendance-calendar", employeeId, currentMonth, currentYear],
    queryFn: () =>
      getAttendanceCalendar({
        month: currentMonth,
        year: currentYear,
        employee_id: employeeId,
      }),
  });

  const handlePrevMonth = () => {
    if (currentMonth === 1) {
      setCurrentMonth(12);
      setCurrentYear((y) => y - 1);
    } else {
      setCurrentMonth((m) => m - 1);
    }
  };

  const handleNextMonth = () => {
    if (currentMonth === 12) {
      setCurrentMonth(1);
      setCurrentYear((y) => y + 1);
    } else {
      setCurrentMonth((m) => m + 1);
    }
  };

  const days = calendarQuery.data?.days || [];
  const firstDayOfWeek = days.length > 0 ? days[0].day_of_week : 0;
  const summary = calendarQuery.data?.summary || {};

  return (
    <div className="stack gap-4">
      {/* Calendar Header Navigation */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          backgroundColor: "#ffffff",
          padding: "16px 20px",
          borderRadius: "12px",
          border: "1px solid var(--color-border, #e2e8f0)",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
        }}
      >
        <div>
          <h3 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#1e293b" }}>
            {MONTH_NAMES[currentMonth - 1]} {currentYear}
          </h3>
          {employeeName && (
            <div style={{ fontSize: "0.85rem", color: "#64748b", marginTop: "2px" }}>
              Attendance schedule for <strong>{employeeName}</strong>
            </div>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={handlePrevMonth}
            title="Previous Month"
          >
            ← Prev
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              setCurrentMonth(now.getMonth() + 1);
              setCurrentYear(now.getFullYear());
            }}
          >
            Today
          </button>
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={handleNextMonth}
            title="Next Month"
          >
            Next →
          </button>
        </div>
      </div>

      {/* Summary Chips */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "8px",
          alignItems: "center",
        }}
      >
        {(() => {
          // Curated enterprise order of status keys to display
          const displayOrder = [
            "present",
            "in_progress",
            "half_day",
            "on_leave",
            "holiday",
            "weekend",
            "absent",
            "mispunch",
            "pending_regularization",
            "no_record",
          ];

          return displayOrder
            .filter((key) => summary[key] !== undefined || ["present", "in_progress", "half_day", "on_leave", "holiday", "absent"].includes(key))
            .map((statusKey) => {
              const count = summary[statusKey] || 0;
              const cfg = STATUS_CONFIG[statusKey] || STATUS_CONFIG.no_record;
              return (
                <div
                  key={statusKey}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "4px 10px",
                    borderRadius: "9999px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    backgroundColor: cfg.bg,
                    border: `1px solid ${cfg.border}`,
                    color: cfg.text,
                    opacity: count === 0 ? 0.65 : 1,
                  }}
                  title={`${cfg.label}: ${count} day(s)`}
                >
                  <span
                    style={{
                      width: "7px",
                      height: "7px",
                      borderRadius: "50%",
                      backgroundColor: cfg.dot,
                      display: "inline-block",
                    }}
                  />
                  <span>
                    {cfg.label}: {count}
                  </span>
                </div>
              );
            });
        })()}
      </div>

      {/* 7-Column Calendar Grid */}
      <div
        style={{
          backgroundColor: "#ffffff",
          borderRadius: "12px",
          border: "1px solid var(--color-border, #e2e8f0)",
          overflow: "hidden",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
        }}
      >
        {/* Day-of-Week Column Headers */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(7, 1fr)",
            backgroundColor: "#f8fafc",
            borderBottom: "1px solid #e2e8f0",
            textAlign: "center",
            fontWeight: 700,
            fontSize: "0.82rem",
            color: "#64748b",
            padding: "10px 0",
          }}
        >
          {DAY_NAMES.map((name) => (
            <div key={name}>{name}</div>
          ))}
        </div>

        {/* Days Grid */}
        {calendarQuery.isLoading ? (
          <div style={{ padding: "48px", textAlign: "center", color: "#64748b" }}>
            Loading attendance calendar...
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(7, 1fr)",
              gridAutoRows: "minmax(95px, auto)",
              backgroundColor: "#f1f5f9",
              gap: "1px",
            }}
          >
            {/* Empty padding cells for days before the 1st of the month */}
            {Array.from({ length: firstDayOfWeek }).map((_, i) => (
              <div
                key={`empty-${i}`}
                style={{ backgroundColor: "#ffffff", opacity: 0.35 }}
              />
            ))}

            {days.map((day) => {
              const dayNum = parseInt(day.date.split("-")[2], 10);
              const cfg = STATUS_CONFIG[day.status] || STATUS_CONFIG.no_record;
              const isSelected = selectedDay?.date === day.date;

              return (
                <div
                  key={day.date}
                  onClick={() => setSelectedDay(day)}
                  style={{
                    backgroundColor: isSelected ? "#eff6ff" : cfg.bg,
                    padding: "8px",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                    cursor: "pointer",
                    position: "relative",
                    transition: "all 0.15s ease",
                    outline: isSelected ? "2px solid #3b82f6" : "none",
                    border: day.is_today ? "2px solid #2563eb" : "none",
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) e.currentTarget.style.filter = "brightness(0.96)";
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) e.currentTarget.style.filter = "none";
                  }}
                >
                  {/* Date Number + Today marker */}
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <span
                      style={{
                        fontWeight: day.is_today ? 800 : 600,
                        fontSize: "0.85rem",
                        color: day.is_today ? "#2563eb" : "#334155",
                        backgroundColor: day.is_today ? "#dbeafe" : "transparent",
                        padding: day.is_today ? "1px 6px" : "0",
                        borderRadius: "4px",
                      }}
                    >
                      {dayNum}
                    </span>
                    {day.work_duration_hours && (
                      <span
                        style={{
                          fontSize: "0.72rem",
                          fontWeight: 600,
                          color: "#059669",
                        }}
                      >
                        {parseFloat(String(day.work_duration_hours)).toFixed(1)}h
                      </span>
                    )}
                  </div>

                  {/* Badges / Status label */}
                  <div style={{ marginTop: "4px" }}>
                    {day.badge_label ? (
                      <div
                        style={{
                          fontSize: "0.72rem",
                          fontWeight: 600,
                          backgroundColor: "#ffffff",
                          border: `1px solid ${cfg.border}`,
                          color: cfg.text,
                          padding: "2px 5px",
                          borderRadius: "4px",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                        title={day.badge_label}
                      >
                        {day.badge_label}
                      </div>
                    ) : (
                      <div
                        style={{
                          fontSize: "0.72rem",
                          fontWeight: 500,
                          color: cfg.text,
                          display: "flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        <span
                          style={{
                            width: "5px",
                            height: "5px",
                            borderRadius: "50%",
                            backgroundColor: cfg.dot,
                            display: "inline-block",
                          }}
                        />
                        {cfg.label}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Selected Day Details Panel */}
      {selectedDay && (
        <div
          style={{
            backgroundColor: "#ffffff",
            borderRadius: "12px",
            border: "1px solid var(--color-border, #e2e8f0)",
            padding: "16px 20px",
            boxShadow: "0 2px 4px rgba(0,0,0,0.05)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "12px",
          }}
        >
          <div>
            <h4 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#1e293b" }}>
              {formatDate(selectedDay.date)} —{" "}
              <span style={{ textTransform: "capitalize", color: STATUS_CONFIG[selectedDay.status]?.text || "#1e293b" }}>
                {STATUS_CONFIG[selectedDay.status]?.label || selectedDay.status}
              </span>
            </h4>
            <div
              style={{
                fontSize: "0.82rem",
                color: "#64748b",
                marginTop: "4px",
                display: "flex",
                gap: "16px",
                flexWrap: "wrap",
              }}
            >
              <span>
                <strong>Check-In:</strong>{" "}
                {selectedDay.check_in ? new Date(selectedDay.check_in).toLocaleTimeString() : "—"}
              </span>
              <span>
                <strong>Check-Out:</strong>{" "}
                {selectedDay.check_out ? new Date(selectedDay.check_out).toLocaleTimeString() : "—"}
              </span>
              {selectedDay.work_duration_hours && (
                <span>
                  <strong>Logged Hours:</strong> {selectedDay.work_duration_hours}h
                </span>
              )}
              {selectedDay.holiday_name && (
                <span>
                  <strong>Holiday:</strong> {selectedDay.holiday_name}
                </span>
              )}
              {selectedDay.leave_type_name && (
                <span>
                  <strong>Leave:</strong> {selectedDay.leave_type_name}
                </span>
              )}
            </div>
          </div>

          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={() => setSelectedDay(null)}
          >
            Close ✕
          </button>
        </div>
      )}
    </div>
  );
}
