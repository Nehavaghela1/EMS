import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ManagerDashboard } from "../pages/ManagerDashboard";
import * as TimeLeaveApi from "../../time_leave/api";
import * as ProjectsApi from "../../projects/api";
import * as PerformanceApi from "../../performance/api";
import * as HrApi from "../../hr/api";
import * as PayrollApi from "../../payroll/api";
import * as AuthContextModule from "../../../app/auth-context";

vi.mock("../../time_leave/api");
vi.mock("../../projects/api");
vi.mock("../../performance/api");
vi.mock("../../hr/api");
vi.mock("../../payroll/api");

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

const mockDirectReports = [
  {
    id: "emp-rep-1",
    employee_code: "EMP-001",
    first_name: "Jim",
    last_name: "Halpert",
    position: "Sales Representative",
    reporting_manager_id: "emp-mgr-1",
    company_id: "cmp-acme",
    is_active: true,
  },
  {
    id: "emp-rep-2",
    employee_code: "EMP-002",
    first_name: "Pam",
    last_name: "Beesly",
    position: "Office Administrator",
    reporting_manager_id: "emp-mgr-1",
    company_id: "cmp-acme",
    is_active: true,
  },
];

function renderManagerDashboard(dataProps?: any) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  const defaultData = {
    team_headcount: 2,
    team_present_today: 1,
    team_leave_requests_awaiting: 1,
  };
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/dashboard"]}>
        <ManagerDashboard data={dataProps || defaultData} user={mockManagerUser} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("ManagerDashboard Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(HrApi.listEmployees).mockResolvedValue({
      items: mockDirectReports as any,
      total: 2,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });
    vi.mocked(TimeLeaveApi.listAttendance).mockResolvedValue({
      items: [
        {
          id: "att-1",
          employee_id: "emp-rep-1",
          date: new Date().toISOString().slice(0, 10),
          status: "present",
          check_in: "09:00:00",
          check_out: null,
        } as any,
      ],
      total: 1,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });
    vi.mocked(TimeLeaveApi.listLeaves).mockResolvedValue({
      items: [
        {
          id: "lv-1",
          employee_id: "emp-rep-2",
          leave_type_id: "lt-vacation",
          start_date: new Date().toISOString().slice(0, 10),
          end_date: new Date().toISOString().slice(0, 10),
          status: "approved",
          is_half_day: false,
        } as any,
      ],
      total: 1,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });
    vi.mocked(TimeLeaveApi.listLeaveTypes).mockResolvedValue([
      { id: "lt-vacation", name: "Annual Vacation" } as any,
    ]);
    vi.mocked(ProjectsApi.fetchTimeEntries).mockResolvedValue([]);
    vi.mocked(PerformanceApi.listPIPs).mockResolvedValue([]);
    vi.mocked(PerformanceApi.listPerformanceCycles).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      limit: 20,
      pages: 0,
      has_next: false,
    });
    vi.mocked(PerformanceApi.listPerformanceGoals).mockResolvedValue([
      { id: "g-1", progress: 75, weightage: "50" } as any,
    ]);
    vi.mocked(PayrollApi.listReimbursements).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      limit: 100,
      pages: 0,
      has_next: false,
    });
  });

  it("leads with direct reports rows displaying avatar initials, names, positions and status", async () => {
    renderManagerDashboard();

    await waitFor(() => {
      expect(screen.getByText("My Team")).toBeInTheDocument();
      expect(screen.getAllByText("Jim Halpert").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("Pam Beesly").length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getByText("Sales Representative")).toBeInTheDocument();
    expect(screen.getByText("Office Administrator")).toBeInTheDocument();
    expect(screen.getByText("Working now")).toBeInTheDocument();
    expect(screen.getByText("Annual Vacation")).toBeInTheDocument();
  });

  it("renders the 14-day leave schedule strip with horizontal scroll container and direct reports", async () => {
    const { container } = renderManagerDashboard();

    await waitFor(() => {
      expect(screen.getByText("Next 14 Days Team Schedule")).toBeInTheDocument();
      expect(container.querySelector(".manager-leave-strip-container")).toBeInTheDocument();
    });

    const teamRows = container.querySelectorAll(".manager-team-row");
    expect(teamRows.length).toBe(2);
  });

  it("renders empty state with finished checkmark when manager has no direct reports", async () => {
    vi.mocked(HrApi.listEmployees).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      limit: 100,
      pages: 0,
      has_next: false,
    });

    renderManagerDashboard({ team_headcount: 0, team_present_today: 0, team_leave_requests_awaiting: 0 });

    await waitFor(() => {
      expect(screen.getByText("No direct reports assigned")).toBeInTheDocument();
    });
  });
});
