import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AttendanceCalendar } from "../components/AttendanceCalendar";
import * as timeLeaveApi from "../api";

vi.mock("../api");

const mockCalendarDays: timeLeaveApi.CalendarDay[] = [
  {
    date: "2026-11-01",
    day_of_week: 6,
    status: "weekend",
    work_duration_hours: null,
    check_in: null,
    check_out: null,
    badge_label: "Weekend",
    holiday_name: null,
    leave_type_name: null,
    is_today: false,
    is_future: false,
  },
  {
    date: "2026-11-02",
    day_of_week: 0,
    status: "present",
    work_duration_hours: "8.50",
    check_in: "2026-11-02T09:00:00Z",
    check_out: "2026-11-02T17:30:00Z",
    badge_label: "Present",
    holiday_name: null,
    leave_type_name: null,
    is_today: false,
    is_future: false,
  },
  {
    date: "2026-11-03",
    day_of_week: 1,
    status: "holiday",
    work_duration_hours: null,
    check_in: null,
    check_out: null,
    badge_label: "Diwali",
    holiday_name: "Diwali",
    leave_type_name: null,
    is_today: false,
    is_future: false,
  },
  {
    date: "2026-11-04",
    day_of_week: 2,
    status: "on_leave",
    work_duration_hours: null,
    check_in: null,
    check_out: null,
    badge_label: "Casual Leave",
    holiday_name: null,
    leave_type_name: "Casual Leave",
    is_today: false,
    is_future: false,
  },
];

const mockCalendarData: timeLeaveApi.AttendanceCalendarData = {
  employee_id: "emp-1",
  month: 11,
  year: 2026,
  days: mockCalendarDays,
  summary: {
    present: 1,
    weekend: 1,
    holiday: 1,
    on_leave: 1,
    absent: 0,
  },
};

const mockHolidays: timeLeaveApi.Holiday[] = [
  {
    id: "hol-1",
    name: "Diwali",
    date: "2026-11-03",
    is_optional: false,
    applies_to_department_id: null,
  },
];

function renderCalendar() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AttendanceCalendar employeeId="emp-1" employeeName="Jane Doe" />
    </QueryClientProvider>
  );
}

describe("Sub-feature 4.4: Monthly Attendance Calendar Frontend (AttendanceCalendar)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(timeLeaveApi.getAttendanceCalendar).mockResolvedValue(mockCalendarData);
    vi.mocked(timeLeaveApi.listHolidays).mockResolvedValue(mockHolidays);
  });

  it("renders calendar month header and employee name", async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByText(/Attendance schedule for/)).toBeInTheDocument();
      expect(screen.getByText("Jane Doe")).toBeInTheDocument();
      expect(screen.getByText(/Holidays \(1\)/)).toBeInTheDocument();
    });
  });

  it("renders calendar days with statuses and summary chips", async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByText("Diwali")).toBeInTheDocument();
      expect(screen.getByText("Casual Leave")).toBeInTheDocument();
    });
  });

  it("navigates between months using Prev and Next buttons", async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "← Prev" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Next →" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Next →" }));

    await waitFor(() => {
      expect(timeLeaveApi.getAttendanceCalendar).toHaveBeenCalledWith(
        expect.objectContaining({
          employee_id: "emp-1",
        })
      );
    });
  });

  it("opens holidays modal when clicking Holidays button", async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByText(/Holidays \(1\)/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Holidays \(1\)/));

    await waitFor(() => {
      expect(screen.getByText(/Company Holiday Schedule/)).toBeInTheDocument();
    });
  });
});
