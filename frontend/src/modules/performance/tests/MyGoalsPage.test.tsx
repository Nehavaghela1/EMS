import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MyGoalsPage } from "../pages/MyGoalsPage";
import { TeamGoalsPage } from "../pages/TeamGoalsPage";
import * as api from "../api";
import * as hrApi from "../../hr/api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");
vi.mock("../../hr/api");

const mockEmployeeUser: AuthContextModule.CurrentUser = {
  id: "user-1",
  email: "john@acme.com",
  role: "employee",
  company_id: "cmp-acme",
  is_active: true,
  must_change_password: false,
  employee: {
    id: "emp-1",
    employee_code: "EMP-001",
    first_name: "John",
    last_name: "Doe",
    department_id: "dept-1",
    position: "Software Engineer",
  },
  permissions: [],
};

const mockManagerUser: AuthContextModule.CurrentUser = {
  id: "user-2",
  email: "manager@acme.com",
  role: "manager",
  company_id: "cmp-acme",
  is_active: true,
  must_change_password: false,
  employee: {
    id: "emp-2",
    employee_code: "EMP-002",
    first_name: "Mary",
    last_name: "Manager",
    department_id: "dept-1",
    position: "Engineering Manager",
  },
  permissions: [],
};

const mockActiveCycle: api.PerformanceCycle = {
  id: "cycle-1",
  name: "Q4 2026 Annual Cycle",
  cycle_type: "annual",
  start_date: "2026-10-01",
  end_date: "2026-12-31",
  status: "active",
  self_review_deadline: "2026-11-15",
  manager_review_deadline: "2026-12-01",
  created_at: "2026-09-15T00:00:00Z",
};

const mockGoals: api.PerformanceGoal[] = [
  {
    id: "goal-1",
    employee_id: "emp-1",
    cycle_id: "cycle-1",
    title: "Complete Core Engine",
    description: "Deliver high performance execution",
    weightage: "50.00",
    target_value: "100%",
    status: "in_progress",
    self_rating: null,
    self_comments: null,
    created_at: "2026-10-02T00:00:00Z",
  },
  {
    id: "goal-2",
    employee_id: "emp-1",
    cycle_id: "cycle-1",
    title: "Automate All Test Suites",
    description: "Attain zero regression bugs",
    weightage: "50.00",
    target_value: "100%",
    status: "completed",
    self_rating: "4.5",
    self_comments: "Tests all passing",
    created_at: "2026-10-02T00:00:00Z",
  },
];

const mockEmployeesList = [
  {
    id: "emp-1",
    employee_code: "EMP-001",
    first_name: "John",
    last_name: "Doe",
    position: "Software Engineer",
  },
  {
    id: "emp-3",
    employee_code: "EMP-003",
    first_name: "Bob",
    last_name: "Builder",
    position: "DevOps Engineer",
  },
] as hrApi.Employee[];

describe("MyGoalsPage (Part C: C1, C5, C6)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: mockEmployeeUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });

    vi.mocked(api.listPerformanceCycles).mockResolvedValue({
      items: [mockActiveCycle],
      total: 1,
      page: 1,
      limit: 20,
      pages: 1,
      has_next: false,
    });
    vi.mocked(api.listPerformanceGoals).mockResolvedValue(mockGoals);
    vi.mocked(api.getActivePIP).mockResolvedValue(null);
  });

  it("renders 'My Performance Goals' with expected subtitle and NO employee switcher even for manager", async () => {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: mockManagerUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });

    render(
      <ToastProvider>
        <MyGoalsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("My Performance Goals");
      expect(screen.getByText(/Your goals for this appraisal cycle\. Weightages must total 100%/i)).toBeInTheDocument();
      // Ensure no Switch Employee dropdown exists in My Goals
      expect(screen.queryByLabelText(/Switch Employee/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Viewing & Setting Goals For/i)).not.toBeInTheDocument();
    });
  });

  it("shows lock icon for locked goal and does not open edit modal or fire toast on double click (C5)", async () => {
    render(
      <ToastProvider>
        <MyGoalsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Automate All Test Suites")).toBeInTheDocument();
    });

    // Check lock icon exists
    const lockIcon = screen.getByRole("img", { name: "Locked" });
    expect(lockIcon).toBeInTheDocument();

    // Double click the row of the locked goal
    const lockedRow = screen.getByText("Automate All Test Suites").closest("tr")!;
    fireEvent.doubleClick(lockedRow);

    // Edit modal should NOT open
    expect(screen.queryByRole("heading", { name: "Edit Goal" })).not.toBeInTheDocument();
  });
});

describe("TeamGoalsPage (Part C: C2, C3, C4, C6)", () => {
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

    vi.mocked(hrApi.listEmployees).mockResolvedValue({
      items: mockEmployeesList,
      total: 2,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });

    vi.mocked(api.listPerformanceCycles).mockResolvedValue({
      items: [mockActiveCycle],
      total: 1,
      page: 1,
      limit: 20,
      pages: 1,
      has_next: false,
    });

    vi.mocked(api.listPerformanceGoals).mockResolvedValue(mockGoals);
    vi.mocked(api.getActivePIP).mockResolvedValue(null);
  });

  it("renders 'Team Goals' with switcher and header matching dropdown selection (C2, C3, C6)", async () => {
    render(
      <ToastProvider>
        <TeamGoalsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Team Goals");
      expect(screen.getByText(/Rate each goal your team member has self-rated/i)).toBeInTheDocument();
      // Dropdown and Header match
      expect(screen.getByText("John Doe (EMP-001)")).toBeInTheDocument();
      const select = screen.getByLabelText(/Switch Employee/i) as HTMLSelectElement;
      expect(select.value).toBe("emp-1");
    });
  });

  it("switching employee clears previous rows and shows loading state before fetching new ones (C4)", async () => {
    let resolveGoalsPromise: (value: api.PerformanceGoal[]) => void;
    const delayedGoalsPromise = new Promise<api.PerformanceGoal[]>((resolve) => {
      resolveGoalsPromise = resolve;
    });

    render(
      <ToastProvider>
        <TeamGoalsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Complete Core Engine")).toBeInTheDocument();
    });

    // Mock delayed response for second employee
    vi.mocked(api.listPerformanceGoals).mockImplementation(() => delayedGoalsPromise);

    const select = screen.getByLabelText(/Switch Employee/i);
    fireEvent.change(select, { target: { value: "emp-3" } });

    // Assert immediately: previous goals must be cleared and loading text must appear
    expect(screen.getByText("Loading performance goals...")).toBeInTheDocument();
    expect(screen.queryByText("Complete Core Engine")).not.toBeInTheDocument();

    // Now resolve delayed promise
    resolveGoalsPromise!([
      {
        id: "goal-3",
        employee_id: "emp-3",
        cycle_id: "cycle-1",
        title: "DevOps Infrastructure Setup",
        description: "Set up CI/CD pipeline",
        weightage: "100.00",
        target_value: "100%",
        status: "in_progress",
        self_rating: null,
        self_comments: null,
        created_at: "2026-10-02T00:00:00Z",
      },
    ]);

    await waitFor(() => {
      expect(screen.getByText("DevOps Infrastructure Setup")).toBeInTheDocument();
      expect(screen.queryByText("Loading performance goals...")).not.toBeInTheDocument();
    });
  });
});
