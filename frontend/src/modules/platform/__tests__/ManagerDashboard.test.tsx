import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "../pages/DashboardPage";
import * as PlatformApi from "../api";
import * as TimeLeaveApi from "../../time_leave/api";
import * as ProjectsApi from "../../projects/api";
import * as PerformanceApi from "../../performance/api";
import * as HrApi from "../../hr/api";
import * as AuthContextModule from "../../../app/auth-context";

import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");
vi.mock("../../time_leave/api");
vi.mock("../../projects/api");
vi.mock("../../performance/api");
vi.mock("../../hr/api");

const mockManagerUser: AuthContextModule.CurrentUser = {
  id: "usr-mgr-1",
  email: "manager@acme.com",
  role: "manager",
  company_id: "cmp-acme",
  is_active: true,
  must_change_password: false,
  employee: {
    id: "emp-mgr-1",
    employee_code: "EMP-MGR-01",
    first_name: "Michael",
    last_name: "Scott",
    department_id: "dept-sales",
    position: "Sales Regional Manager",
  },
  permissions: [],
};

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return render(
    <ToastProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>
    </ToastProvider>
  );
}

describe("PART E: Manager Dashboard - What Needs Me Today", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: mockManagerUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });
    vi.mocked(PlatformApi.fetchAnnouncements).mockResolvedValue([]);
  });

  it("E4: renders all actionable queue cards with non-zero figures and correct links", async () => {
    vi.mocked(PlatformApi.fetchDashboard).mockResolvedValue({
      role: "manager",
      generated_at: "2026-11-23T10:00:00Z",
      data: {
        team_headcount: 5,
        team_present_today: 4,
        team_leave_requests_awaiting: 2,
      },
    });

    vi.mocked(ProjectsApi.fetchTimeEntries).mockResolvedValue([
      { id: "te-1", status: "submitted" } as any,
      { id: "te-2", status: "submitted" } as any,
      { id: "te-3", status: "submitted" } as any,
    ]);

    vi.mocked(TimeLeaveApi.listLeaves).mockResolvedValue({
      items: [{ id: "l-1" } as any],
      total: 1,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });

    vi.mocked(PerformanceApi.listPIPs).mockResolvedValue([
      { id: "pip-1", status: "active" } as any,
    ]);

    vi.mocked(PerformanceApi.listPerformanceCycles).mockResolvedValue({
      items: [{ id: "cycle-1", status: "active" } as any],
      total: 1,
      page: 1,
      limit: 20,
      pages: 1,
      has_next: false,
    });

    vi.mocked(HrApi.listEmployees).mockResolvedValue({
      items: [
        { id: "emp-rep-1", reporting_manager_id: "emp-mgr-1" } as any,
      ],
      total: 1,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });

    vi.mocked(PerformanceApi.getPerformanceSummary).mockResolvedValue(null);

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText("What Needs Me Today")).toBeInTheDocument();
      expect(screen.getByText("3")).toBeInTheDocument();
    });

    // 1. Leave requests awaiting my approval: 2
    expect(screen.getByText("Leave requests awaiting my approval")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    // 2. Timesheet entries awaiting my approval: 3
    expect(screen.getByText("Timesheet entries awaiting my approval")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();

    // 3. Team members on leave today: 1
    expect(screen.getByText("Team members on leave today")).toBeInTheDocument();

    // 4. Open PIPs on my team: 1
    expect(screen.getByText("Open PIPs on my team")).toBeInTheDocument();

    // 5. Reviews I still owe this cycle: 1
    expect(screen.getByText("Reviews I still owe this cycle")).toBeInTheDocument();

    expect(screen.getAllByText("1").length).toBe(3);

    // Check link targets
    const leaveLinks = screen.getAllByRole("link").filter((l) => l.getAttribute("href") === "/leaves");
    expect(leaveLinks.length).toBeGreaterThanOrEqual(1);

    const timesheetLinks = screen.getAllByRole("link").filter((l) => l.getAttribute("href") === "/timesheets");
    expect(timesheetLinks.length).toBe(1);

    const performanceLinks = screen.getAllByRole("link").filter((l) => l.getAttribute("href") === "/performance");
    expect(performanceLinks.length).toBe(1);

    const teamGoalsLinks = screen.getAllByRole("link").filter((l) => l.getAttribute("href") === "/performance/team-goals");
    expect(teamGoalsLinks.length).toBe(1);
  });

  it("E3 & E4: renders 'Nothing waiting' when actionable figures are zero", async () => {
    vi.mocked(PlatformApi.fetchDashboard).mockResolvedValue({
      role: "manager",
      generated_at: "2026-11-23T10:00:00Z",
      data: {
        team_headcount: 5,
        team_present_today: 5,
        team_leave_requests_awaiting: 0,
      },
    });

    vi.mocked(ProjectsApi.fetchTimeEntries).mockResolvedValue([]);
    vi.mocked(TimeLeaveApi.listLeaves).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      limit: 100,
      pages: 0,
      has_next: false,
    });
    vi.mocked(PerformanceApi.listPIPs).mockResolvedValue([]);
    vi.mocked(PerformanceApi.listPerformanceCycles).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      limit: 20,
      pages: 0,
      has_next: false,
    });

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText("What Needs Me Today")).toBeInTheDocument();
      expect(screen.getAllByText("Nothing waiting").length).toBe(5);
    });
  });
});
