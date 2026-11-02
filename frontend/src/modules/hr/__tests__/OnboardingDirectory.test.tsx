import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EmployeeListPage } from "../pages/EmployeeListPage";
import { EmployeeFormPage } from "../pages/EmployeeFormPage";
import * as AuthContextModule from "../../../app/auth-context";
import * as HrApi from "../api";
import * as IdentityApi from "../../identity/api";
import * as PayrollApi from "../../payroll/api";
import * as ToastContextModule from "../../../app/toast-context";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    listEmployees: vi.fn(),
    listDepartments: vi.fn(),
    createEmployee: vi.fn(),
    updateEmployee: vi.fn(),
    getEmployee: vi.fn(),
    bulkResendInviteEmployees: vi.fn(),
    searchManagers: vi.fn(),
  };
});

vi.mock("../../identity/api", async () => {
  const actual = await vi.importActual<typeof import("../../identity/api")>("../../identity/api");
  return {
    ...actual,
    listLocations: vi.fn(),
    listCompanies: vi.fn(),
  };
});

vi.mock("../../payroll/api", async () => {
  const actual = await vi.importActual<typeof import("../../payroll/api")>("../../payroll/api");
  return {
    ...actual,
    listStructures: vi.fn(),
    assignEmployeeSalary: vi.fn(),
  };
});

describe("Sub-feature 2.2: Onboarding & Directory Frontend", () => {
  const mockNotify = vi.fn();
  let queryClient: QueryClient;

  const hrUser: AuthContextModule.CurrentUser = {
    id: "usr-hr-1",
    email: "hr@company.com",
    role: "hr_admin",
    company_id: "cmp-1",
    is_active: true,
    must_change_password: false,
    employee: null,
    permissions: [],
  };

  const employeeUser: AuthContextModule.CurrentUser = {
    id: "usr-emp-1",
    email: "emp@company.com",
    role: "employee",
    company_id: "cmp-1",
    is_active: true,
    must_change_password: false,
    employee: {
      id: "emp-1",
      employee_code: "EMP-001",
      first_name: "Jane",
      last_name: "Doe",
      department_id: "dept-1",
      position: "Engineer",
    },
    permissions: [],
  };

  const sampleEmployees: HrApi.Employee[] = [
    {
      id: "emp-1",
      user_id: "usr-emp-1",
      company_id: "cmp-1",
      employee_code: "EMP001",
      first_name: "Alice",
      last_name: "Smith",
      email: "alice@company.com",
      personal_email: "alice.personal@gmail.com",
      phone: "1234567890",
      department_id: "dept-1",
      department_name: "Engineering",
      location_id: "loc-1",
      reporting_manager_id: null,
      position: "Software Engineer",
      level: "L1",
      is_active: true,
      invitation_status: "activated",
      hire_date: "2025-01-01",
      probation_end_date: null,
      employment_type: "full_time",
      created_at: "2025-01-01T00:00:00Z",
    },
    {
      id: "emp-2",
      user_id: "usr-emp-2",
      company_id: "cmp-1",
      employee_code: "EMP002",
      first_name: "Bob",
      last_name: "Jones",
      email: "bob@company.com",
      personal_email: null,
      phone: null,
      department_id: "dept-1",
      department_name: "Engineering",
      location_id: "loc-1",
      reporting_manager_id: null,
      position: "QA Engineer",
      level: "L2",
      is_active: true,
      invitation_status: "sent",
      hire_date: "2025-02-01",
      probation_end_date: null,
      employment_type: "full_time",
      created_at: "2025-02-01T00:00:00Z",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.spyOn(ToastContextModule, "useToast").mockReturnValue({
      notify: mockNotify,
    });
    vi.mocked(HrApi.listDepartments).mockResolvedValue({
      items: [
        {
          id: "dept-1",
          name: "Engineering",
          description: null,
          head_employee_id: null,
          employee_count: 2,
          created_at: "2025-01-01T00:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      limit: 50,
      pages: 1,
      has_next: false,
    });
    vi.mocked(IdentityApi.listLocations).mockResolvedValue([
      {
        id: "loc-1",
        name: "HQ Mumbai",
        code: "MUM",
        city: "Mumbai",
        country: "IN",
        is_primary: true,
        company_id: "cmp-1",
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-01-01T00:00:00Z",
      },
    ]);
    vi.mocked(PayrollApi.listStructures).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      limit: 50,
      pages: 0,
      has_next: false,
    });
    vi.mocked(HrApi.listEmployees).mockResolvedValue({
      items: sampleEmployees,
      total: sampleEmployees.length,
      page: 1,
      limit: 50,
      pages: 1,
      has_next: false,
    });
  });

  function renderDirectory(currentUser: AuthContextModule.CurrentUser = hrUser) {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: currentUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });

    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/employees"]}>
          <Routes>
            <Route path="/employees" element={<EmployeeListPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  function renderOnboardForm(currentUser: AuthContextModule.CurrentUser = hrUser) {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: currentUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });

    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/employees/new"]}>
          <Routes>
            <Route path="/employees/new" element={<EmployeeFormPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  it("Rule 1: shows 'Add' employee button in directory for HR admin, but hides for plain employee", async () => {
    const { unmount } = renderDirectory(hrUser);
    expect(await screen.findByRole("button", { name: /add/i })).toBeInTheDocument();
    expect(await screen.findByText(/Alice Smith - EMP001/i)).toBeInTheDocument();
    unmount();

    renderDirectory(employeeUser);
    expect(await screen.findByText(/Alice Smith - EMP001/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add/i })).not.toBeInTheDocument();
  });

  it("Rule 2: validates required fields and schema constraints on onboarding form", async () => {
    const user = userEvent.setup();
    renderOnboardForm(hrUser);

    expect(await screen.findByText("Onboard New Employee")).toBeInTheDocument();

    const submitBtn = screen.getByRole("button", { name: /Create & Continue to Step 2/i });
    await user.click(submitBtn);

    // Validation prevents submission when mandatory fields are missing
    expect(HrApi.createEmployee).not.toHaveBeenCalled();
    expect(await screen.findByText(/first name is required/i)).toBeInTheDocument();
  });

  it("Rule 3 & 5: successfully submits employee onboarding with valid department and details", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.createEmployee).mockResolvedValueOnce({
      ...sampleEmployees[0],
      id: "emp-3",
      employee_code: "EMP003",
      first_name: "Charlie",
      last_name: "Brown",
      email: "charlie@company.com",
      invitation_status: "sent",
      invite: { sent_to: "charlie@company.com", expires_at: "2099-01-01T00:00:00Z" },
    });

    renderOnboardForm(hrUser);

    await user.type(await screen.findByLabelText(/first name \*/i), "Charlie");
    await user.type(screen.getByLabelText(/last name/i), "Brown");
    await user.type(screen.getByLabelText(/work email \*/i), "charlie@company.com");
    await user.selectOptions(screen.getByLabelText(/department \*/i), "dept-1");

    const submitBtn = screen.getByRole("button", { name: /Create & Continue to Step 2/i });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(HrApi.createEmployee).toHaveBeenCalledWith(
        expect.objectContaining({
          first_name: "Charlie",
          last_name: "Brown",
          email: "charlie@company.com",
          department_id: "dept-1",
        })
      );
    });
    expect(await screen.findByText(/Step 1 Complete:/i)).toBeInTheDocument();
  });

  it("Rule 6: allows HR to resend invite for invited employees with action feedback", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.bulkResendInviteEmployees).mockResolvedValueOnce({
      requested: 1,
      succeeded: ["emp-2"],
      skipped: [],
      failed: [],
    });

    renderDirectory(hrUser);

    expect(await screen.findByText(/Bob Jones - EMP002/i)).toBeInTheDocument();

    // Select Bob Jones checkbox
    const checkboxes = screen.getAllByRole("checkbox");
    // checkboxes[0] is select all, checkboxes[2] is Bob Jones (second employee)
    await user.click(checkboxes[2]);

    const resendBtn = await screen.findByRole("button", { name: /Resend Invites/i });
    await user.click(resendBtn);

    await waitFor(() => {
      expect(HrApi.bulkResendInviteEmployees).toHaveBeenCalledWith(["emp-2"]);
    });
    expect(await screen.findByTestId("bulk-results-modal")).toBeInTheDocument();
    expect(screen.getByText("Bulk Resend Invite Results")).toBeInTheDocument();
  });

  it("Rule 8: directory displays employee name, code, department and hides token fields", async () => {
    // A row that carries secret fields on the wire: the page must not display them.
    const leakyRow: HrApi.Employee & { activation_token: string; token_hash: string } = {
      ...sampleEmployees[0],
      activation_token: "SECRET-ACTIVATION-TOKEN-123",
      token_hash: "SECRET-TOKEN-HASH-456",
    };
    vi.mocked(HrApi.listEmployees).mockResolvedValue({
      items: [leakyRow, sampleEmployees[1]],
      total: 2,
      page: 1,
      limit: 50,
      pages: 1,
      has_next: false,
    });
    renderDirectory(hrUser);

    expect(await screen.findByText(/Alice Smith - EMP001/i)).toBeInTheDocument();
    expect(screen.getByText(/Bob Jones - EMP002/i)).toBeInTheDocument();
    expect(screen.getAllByText("Engineering").length).toBeGreaterThan(0);

    // Token fields or internal hashes never appear on DOM
    expect(screen.queryByText(/token_hash/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/activation_token/i)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("SECRET-ACTIVATION-TOKEN-123");
    expect(document.body.textContent).not.toContain("SECRET-TOKEN-HASH-456");
  });
});
