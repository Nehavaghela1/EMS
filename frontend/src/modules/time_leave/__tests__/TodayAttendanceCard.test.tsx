import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TodayAttendanceCard } from "../components/TodayAttendanceCard";
import * as timeLeaveApi from "../api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");

const mockAssignedShift: timeLeaveApi.AssignedShiftDetail = {
  shift: {
    id: "shift-1",
    name: "General Day Shift",
    start_time: "09:00:00",
    end_time: "18:00:00",
    break_minutes: 60,
    night_allowance: "0.00",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  },
  effective_from: "2026-01-01",
  effective_to: null,
};

function renderCard(userRole = "employee", hasEmployee = true) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });

  const user = {
    id: "usr-1",
    company_id: "cmp-1",
    email: "emp@example.com",
    role: userRole,
    employee: hasEmployee
      ? {
          id: "emp-1",
          employee_code: "EMP-001",
          first_name: "Jane",
          last_name: "Doe",
          company_id: "cmp-1",
        }
      : null,
  } as any;

  vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
    status: "authenticated",
    user,
    login: vi.fn(),
    logout: vi.fn(),
    establishSession: vi.fn(),
    sessionExpired: false,
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <TodayAttendanceCard />
      </ToastProvider>
    </QueryClientProvider>
  );
}

describe("Sub-feature 4.2: Punch In/Out Frontend (TodayAttendanceCard)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(timeLeaveApi.getAssignedShift).mockResolvedValue(mockAssignedShift);
  });

  it("shows 'You haven't checked in today' and Check in button when not clocked in", async () => {
    vi.mocked(timeLeaveApi.listAttendance).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      limit: 1,
      pages: 0,
      has_next: false,
    });

    renderCard("employee", true);

    await waitFor(() => {
      expect(screen.getByText("You haven't checked in today.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Check in" })).toBeInTheDocument();
      expect(screen.getByText(/Assigned Shift: General Day Shift/)).toBeInTheDocument();
    });
  });

  it("calls checkIn when user clicks 'Check in' button", async () => {
    vi.mocked(timeLeaveApi.listAttendance).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      limit: 1,
      pages: 0,
      has_next: false,
    });
    vi.mocked(timeLeaveApi.checkIn).mockResolvedValue({
      id: "att-1",
      employee_id: "emp-1",
      date: "2026-11-17",
      check_in: "2026-11-17T09:05:00Z",
      check_out: null,
      status: "present",
      hours_worked: null,
      source: "web",
      notes: null,
      created_at: "2026-11-17T09:05:00Z",
    });

    renderCard("employee", true);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Check in" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Check in" }));

    await waitFor(() => {
      expect(timeLeaveApi.checkIn).toHaveBeenCalled();
    });
  });

  it("shows clocked-in state and Check out button when already checked in", async () => {
    vi.mocked(timeLeaveApi.listAttendance).mockResolvedValue({
      items: [
        {
          id: "att-1",
          employee_id: "emp-1",
          date: "2026-11-17",
          check_in: "2026-11-17T09:00:00Z",
          check_out: null,
          status: "present",
          hours_worked: null,
          source: "web",
          notes: null,
          created_at: "2026-11-17T09:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      limit: 1,
      pages: 1,
      has_next: false,
    });

    renderCard("employee", true);

    await waitFor(() => {
      expect(screen.getByText(/Still clocked in/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Check out" })).toBeInTheDocument();
    });
  });

  it("calls checkOut when user clicks 'Check out' button", async () => {
    vi.mocked(timeLeaveApi.listAttendance).mockResolvedValue({
      items: [
        {
          id: "att-1",
          employee_id: "emp-1",
          date: "2026-11-17",
          check_in: "2026-11-17T09:00:00Z",
          check_out: null,
          status: "present",
          hours_worked: null,
          source: "web",
          notes: null,
          created_at: "2026-11-17T09:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      limit: 1,
      pages: 1,
      has_next: false,
    });
    vi.mocked(timeLeaveApi.checkOut).mockResolvedValue({
      id: "att-1",
      employee_id: "emp-1",
      date: "2026-11-17",
      check_in: "2026-11-17T09:00:00Z",
      check_out: "2026-11-17T18:00:00Z",
      status: "present",
      hours_worked: "9.00",
      source: "web",
      notes: null,
      created_at: "2026-11-17T09:00:00Z",
    });

    renderCard("employee", true);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Check out" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Check out" }));

    await waitFor(() => {
      expect(timeLeaveApi.checkOut).toHaveBeenCalled();
    });
  });

  it("shows 'Check in again' button and running figures when clocked out", async () => {
    vi.mocked(timeLeaveApi.listAttendance).mockResolvedValue({
      items: [
        {
          id: "att-1",
          employee_id: "emp-1",
          date: "2026-11-17",
          check_in: "2026-11-17T09:00:00Z",
          check_out: "2026-11-17T13:00:00Z",
          status: "present",
          hours_worked: "4.00",
          worked_hours: "4.00",
          span_hours: "4.00",
          outside_hours: "0.00",
          punches: [
            {
              id: "p-1",
              attendance_id: "att-1",
              employee_id: "emp-1",
              punched_at: "2026-11-17T09:00:00Z",
              direction: "in",
              source: "web",
              created_at: "2026-11-17T09:00:00Z",
            },
            {
              id: "p-2",
              attendance_id: "att-1",
              employee_id: "emp-1",
              punched_at: "2026-11-17T13:00:00Z",
              direction: "out",
              source: "web",
              created_at: "2026-11-17T13:00:00Z",
            },
          ],
          source: "web",
          notes: null,
          created_at: "2026-11-17T09:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      limit: 1,
      pages: 1,
      has_next: false,
    });
    vi.mocked(timeLeaveApi.checkIn).mockResolvedValue({
      id: "att-1",
      employee_id: "emp-1",
      date: "2026-11-17",
      check_in: "2026-11-17T09:00:00Z",
      check_out: null,
      status: "present",
      hours_worked: "4.00",
      worked_hours: "4.00",
      span_hours: "4.00",
      outside_hours: "0.00",
      source: "web",
      notes: null,
      created_at: "2026-11-17T09:00:00Z",
    });

    renderCard("employee", true);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Check in again" })).toBeInTheDocument();
      expect(screen.getByText("4.00 hrs")).toBeInTheDocument();
      expect(screen.getByText("0.00 hrs")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Check in again" }));

    await waitFor(() => {
      expect(timeLeaveApi.checkIn).toHaveBeenCalled();
    });
  });

  it("shows attendance exempt badge for owner", async () => {
    vi.mocked(timeLeaveApi.listAttendance).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      limit: 1,
      pages: 0,
      has_next: false,
    });

    renderCard("owner", true);

    await waitFor(() => {
      expect(screen.getByText(/Executive Account — Attendance Exempt/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Check in" })).not.toBeInTheDocument();
    });
  });

  it("shows missing check-out warning for unclosed past session", async () => {
    vi.mocked(timeLeaveApi.listAttendance)
      .mockResolvedValueOnce({
        items: [],
        total: 0,
        page: 1,
        limit: 1,
        pages: 0,
        has_next: false,
      })
      .mockResolvedValueOnce({
        items: [
          {
            id: "att-old",
            employee_id: "emp-1",
            date: "2026-11-10",
            check_in: "2026-11-10T09:00:00Z",
            check_out: null,
            status: "mispunch",
            hours_worked: null,
            source: "web",
            notes: null,
            created_at: "2026-11-10T09:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        limit: 5,
        pages: 1,
        has_next: false,
      });

    renderCard("employee", true);

    await waitFor(() => {
      expect(screen.getByText(/Missing Check-Out:/)).toBeInTheDocument();
      expect(screen.getByText("Regularize Now")).toBeInTheDocument();
    });
  });
});
