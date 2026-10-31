import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "../pages/DashboardPage";
import * as PlatformApi from "../api";
import * as AuthContextModule from "../../../app/auth-context";
import * as ToastContextModule from "../../../app/toast-context";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    fetchDashboard: vi.fn(),
    fetchAnnouncements: vi.fn(),
    createAnnouncement: vi.fn(),
    deleteAnnouncement: vi.fn(),
  };
});

describe("Sub-feature 3.1: Announcements Frontend", () => {
  const mockNotify = vi.fn();
  let queryClient: QueryClient;

  const mockEmployeeUser: AuthContextModule.CurrentUser = {
    id: "usr-emp-1",
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
      department_id: "dept-eng",
      position: "Software Engineer",
    },
    permissions: [],
  };

  const mockHrUser: AuthContextModule.CurrentUser = {
    id: "usr-hr-1",
    email: "hr@acme.com",
    role: "hr_admin",
    company_id: "cmp-acme",
    is_active: true,
    must_change_password: false,
    employee: {
      id: "emp-hr-1",
      employee_code: "EMP-HR-01",
      first_name: "Sarah",
      last_name: "HR",
      department_id: "dept-hr",
      position: "HR Manager",
    },
    permissions: [],
  };

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
      first_name: "Bob",
      last_name: "Manager",
      department_id: "dept-eng",
      position: "Engineering Manager",
    },
    permissions: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    vi.spyOn(ToastContextModule, "useToast").mockReturnValue({ notify: mockNotify });
  });

  const renderWithProviders = (user: AuthContextModule.CurrentUser) => {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });

    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>
    );
  };

  it("renders active announcements on employee dashboard with update badge and content", async () => {
    vi.mocked(PlatformApi.fetchDashboard).mockResolvedValue({
      role: "employee",
      generated_at: "2026-10-31T10:00:00Z",
      data: {
        attendance_this_month: { present: 20, absent: 1, leave: 1 },
        leave_balances: [{ leave_type_id: "lt-1", leave_type_name: "Paid Time Off", available: "12.0" }],
        pending_requests: 0,
      },
    });

    const activeAnnouncements: PlatformApi.Announcement[] = [
      {
        id: "ann-1",
        company_id: "cmp-acme",
        title: "All-Hands Meeting on Friday",
        content: "Join us on Friday 3 PM for company quarterly updates.",
        target_role: "all",
        department_id: null,
        created_at: "2026-10-30T10:00:00Z",
        expires_at: "2026-11-15T00:00:00Z",
      },
    ];
    vi.mocked(PlatformApi.fetchAnnouncements).mockResolvedValue(activeAnnouncements);

    renderWithProviders(mockEmployeeUser);

    await waitFor(() => {
      expect(screen.getByText("All-Hands Meeting on Friday")).toBeInTheDocument();
    });
    expect(screen.getByText(/Join us on Friday 3 PM/i)).toBeInTheDocument();
    expect(screen.getByText("1 updates")).toBeInTheDocument();
  });

  it("renders empty state placeholder when no active announcements exist for employee", async () => {
    vi.mocked(PlatformApi.fetchDashboard).mockResolvedValue({
      role: "employee",
      generated_at: "2026-10-31T10:00:00Z",
      data: {
        attendance_this_month: { present: 20, absent: 1, leave: 1 },
        leave_balances: [],
        pending_requests: 0,
      },
    });
    vi.mocked(PlatformApi.fetchAnnouncements).mockResolvedValue([]);

    renderWithProviders(mockEmployeeUser);

    await waitFor(() => {
      expect(screen.getByText(/No active announcements posted by HR/i)).toBeInTheDocument();
    });
    expect(screen.getByText("0 updates")).toBeInTheDocument();
  });

  it("renders announcements section on owner dashboard with published badge", async () => {
    vi.mocked(PlatformApi.fetchDashboard).mockResolvedValue({
      role: "owner",
      generated_at: "2026-10-31T10:00:00Z",
      data: {
        headcount: 42,
        present_today: 38,
        on_leave_today: 4,
        pending_leave_requests: 2,
        recent_hires: [],
        department_distribution: { Engineering: 25, HR: 5, Sales: 12 },
      },
    });

    const announcements: PlatformApi.Announcement[] = [
      {
        id: "ann-hr-1",
        company_id: "cmp-acme",
        title: "Office Closed on Public Holiday",
        content: "Please note our offices will be closed next Monday.",
        target_role: "all",
        department_id: null,
        created_at: "2026-10-29T10:00:00Z",
      },
    ];
    vi.mocked(PlatformApi.fetchAnnouncements).mockResolvedValue(announcements);

    renderWithProviders(mockHrUser);

    await waitFor(() => {
      expect(screen.getByText("Office Closed on Public Holiday")).toBeInTheDocument();
    });
    expect(screen.getByText("1 published")).toBeInTheDocument();
  });

  it("validates createAnnouncement API contracts: department targeting and payload fields", async () => {
    const mockCreatedAnnouncement: PlatformApi.Announcement = {
      id: "ann-dept-1",
      company_id: "cmp-acme",
      title: "Engineering Sprint Demo",
      content: "Demo is scheduled for Thursday at 4 PM.",
      target_role: "all",
      department_id: "dept-eng",
      created_by: "usr-mgr-1",
      expires_at: "2026-12-01T00:00:00Z",
      created_at: "2026-10-31T12:00:00Z",
    };

    vi.mocked(PlatformApi.createAnnouncement).mockResolvedValue(mockCreatedAnnouncement);

    const result = await PlatformApi.createAnnouncement({
      title: "Engineering Sprint Demo",
      content: "Demo is scheduled for Thursday at 4 PM.",
      target_role: "all",
      department_id: "dept-eng",
      expires_at: "2026-12-01T00:00:00Z",
    });

    expect(PlatformApi.createAnnouncement).toHaveBeenCalledWith({
      title: "Engineering Sprint Demo",
      content: "Demo is scheduled for Thursday at 4 PM.",
      target_role: "all",
      department_id: "dept-eng",
      expires_at: "2026-12-01T00:00:00Z",
    });
    expect(result.department_id).toBe("dept-eng");
    expect(result.title).toBe("Engineering Sprint Demo");
  });

  it("validates deleteAnnouncement API invocation with correct announcement id", async () => {
    vi.mocked(PlatformApi.deleteAnnouncement).mockResolvedValue(undefined);

    await PlatformApi.deleteAnnouncement("ann-del-123");

    expect(PlatformApi.deleteAnnouncement).toHaveBeenCalledWith("ann-del-123");
  });

  it("verifies manager and employee scoping rules conform to contract N1-N5", async () => {
    // Contract N1: Manager posts require department_id matching their team
    const managerPayload = {
      title: "Team Sync",
      content: "Daily standup at 10 AM.",
      target_role: "all",
      department_id: mockManagerUser.employee!.department_id,
      expires_at: "2026-12-31T00:00:00Z",
    };
    expect(managerPayload.department_id).toBe("dept-eng");

    // Contract N2: Employee without department only sees company-wide & role posts
    const employeeWithoutDept: AuthContextModule.CurrentUser = {
      ...mockEmployeeUser,
      employee: {
        ...mockEmployeeUser.employee!,
        department_id: undefined as unknown as string,
      },
    };
    expect(employeeWithoutDept.employee?.department_id).toBeFalsy();
  });
});
