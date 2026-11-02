import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EmployeeProfilePage } from "../pages/EmployeeProfilePage";
import * as AuthContextModule from "../../../app/auth-context";
import * as HrApi from "../api";
import * as TimeLeaveApi from "../../time_leave/api";
import * as ToastContextModule from "../../../app/toast-context";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    getEmployee: vi.fn(),
    updateEmployee: vi.fn(),
    deactivateEmployee: vi.fn(),
    reactivateEmployee: vi.fn(),
    resendInvite: vi.fn(),
    updateUserRole: vi.fn(),
  };
});

vi.mock("../../payroll/api", async () => {
  const actual = await vi.importActual<typeof import("../../payroll/api")>("../../payroll/api");
  return {
    ...actual,
    listEmployeePayslips: vi.fn(),
    listStructures: vi.fn(),
    assignEmployeeSalary: vi.fn(),
    getStatutoryConfig: vi.fn(),
    updateStatutoryConfig: vi.fn(),
  };
});

vi.mock("../../time_leave/api", async () => {
  const actual = await vi.importActual<typeof import("../../time_leave/api")>("../../time_leave/api");
  return {
    ...actual,
    getAssignedShift: vi.fn(),
    getLeaveBalance: vi.fn(),
    listHolidays: vi.fn(),
    listLeaveTypes: vi.fn(),
    applyLeave: vi.fn(),
  };
});

describe("Sub-feature 2.3: Profile & Editing Frontend", () => {
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

  const selfEmployeeUser: AuthContextModule.CurrentUser = {
    id: "usr-emp-1",
    email: "emp@company.com",
    role: "employee",
    company_id: "cmp-1",
    is_active: true,
    must_change_password: false,
    employee: {
      id: "emp-1",
      employee_code: "EMP-001",
      first_name: "Alice",
      last_name: "Smith",
      department_id: "dept-1",
      position: "Software Engineer",
    },
    permissions: [],
  };

  const otherEmployeeUser: AuthContextModule.CurrentUser = {
    id: "usr-emp-999",
    email: "other@company.com",
    role: "employee",
    company_id: "cmp-1",
    is_active: true,
    must_change_password: false,
    employee: {
      id: "emp-999",
      employee_code: "EMP-999",
      first_name: "Stranger",
      last_name: "Person",
      department_id: "dept-1",
      position: "Engineer",
    },
    permissions: [],
  };

  const mockEmployeeData: HrApi.Employee = {
    id: "emp-1",
    user_id: "usr-emp-1",
    company_id: "cmp-1",
    employee_code: "EMP001",
    first_name: "Alice",
    last_name: "Smith",
    email: "alice@company.com",
    personal_email: "alice.personal@gmail.com",
    phone: "9876543210",
    department_id: "dept-1",
    department_name: "Engineering",
    location_id: "loc-1",
    reporting_manager_id: null,
    position: "Software Engineer",
    level: "L1",
    employment_type: "full_time",
    hire_date: "2024-01-01",
    probation_end_date: null,
    notice_period_days: 30,
    is_active: true,
    invitation_status: "activated",
    created_at: "2024-01-01T00:00:00Z",
  };

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.spyOn(ToastContextModule, "useToast").mockReturnValue({
      notify: mockNotify,
    });
    vi.mocked(HrApi.getEmployee).mockResolvedValue(mockEmployeeData);
    vi.mocked(TimeLeaveApi.getAssignedShift).mockResolvedValue(null);
  });

  function renderProfile(user: AuthContextModule.CurrentUser = hrUser) {
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
        <MemoryRouter initialEntries={["/employees/emp-1"]}>
          <Routes>
            <Route path="/employees/:id" element={<EmployeeProfilePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  it("Rule 1: renders employee overview with details, code, and active status", async () => {
    renderProfile(hrUser);

    expect(await screen.findByRole("heading", { level: 1, name: /Alice Smith/i })).toBeInTheDocument();
    expect(screen.getAllByText("EMP001").length).toBeGreaterThan(0);
    expect(screen.getByText(/● Active/i)).toBeInTheDocument();
    expect(screen.getByText("Basic Information")).toBeInTheDocument();
    expect(screen.getByText("Personal Information")).toBeInTheDocument();
  });

  it("Rule 2: allows employee to edit their own personal information via modal", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.updateEmployee).mockResolvedValueOnce({
      ...mockEmployeeData,
      personal_email: "alice.updated@gmail.com",
    });

    renderProfile(selfEmployeeUser);

    expect(await screen.findByRole("heading", { level: 1, name: /Alice Smith/i })).toBeInTheDocument();

    // Find and click the edit personal info button
    const editPersonalBtn = screen.getByTitle("Edit Personal Information");
    await user.click(editPersonalBtn);

    expect(await screen.findByRole("heading", { level: 3, name: "Edit Personal Information" })).toBeInTheDocument();

    const personalEmailInput = screen.getByPlaceholderText("e.g. personal@gmail.com");
    await user.clear(personalEmailInput);
    await user.type(personalEmailInput, "alice.updated@gmail.com");

    const saveBtn = screen.getByRole("button", { name: /Save Details/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(HrApi.updateEmployee).toHaveBeenCalledWith(
        "emp-1",
        expect.objectContaining({
          personal_email: "alice.updated@gmail.com",
        })
      );
      expect(mockNotify).toHaveBeenCalledWith("Personal details updated successfully.");
    });
  });

  it("Rule 3: employee cannot edit protected first_name and work email in Basic Information modal", async () => {
    const user = userEvent.setup();
    renderProfile(selfEmployeeUser);

    expect(await screen.findByRole("heading", { level: 1, name: /Alice Smith/i })).toBeInTheDocument();

    const editBasicBtn = screen.getByTitle("Edit Contact Information");
    await user.click(editBasicBtn);

    expect(await screen.findByRole("heading", { level: 3, name: "Edit Basic Information" })).toBeInTheDocument();

    const firstNameInput = screen.getByDisplayValue("Alice");
    const emailInput = screen.getByDisplayValue("alice@company.com");

    expect(firstNameInput).toBeDisabled();
    expect(emailInput).toBeDisabled();
  });

  it("Rule 4: HR admin can edit basic fields (first_name, position, department) in Basic Information modal", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.updateEmployee).mockResolvedValueOnce({
      ...mockEmployeeData,
      first_name: "Alicia",
    });

    renderProfile(hrUser);

    expect(await screen.findByRole("heading", { level: 1, name: /Alice Smith/i })).toBeInTheDocument();

    const editBasicBtn = screen.getByTitle("Edit Basic Information");
    await user.click(editBasicBtn);

    expect(await screen.findByRole("heading", { level: 3, name: "Edit Basic Information" })).toBeInTheDocument();

    const firstNameInput = screen.getByDisplayValue("Alice");
    expect(firstNameInput).not.toBeDisabled();

    await user.clear(firstNameInput);
    await user.type(firstNameInput, "Alicia");

    const saveBtn = screen.getByRole("button", { name: /Save Changes/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(HrApi.updateEmployee).toHaveBeenCalledWith(
        "emp-1",
        expect.objectContaining({
          first_name: "Alicia",
        })
      );
      expect(mockNotify).toHaveBeenCalledWith("Basic information updated successfully.");
    });
  });

  it("Rule 5: another employee without HR role cannot see edit buttons on someone else's profile", async () => {
    renderProfile(otherEmployeeUser);

    expect(await screen.findByRole("heading", { level: 1, name: /Alice Smith/i })).toBeInTheDocument();

    expect(screen.queryByTitle("Edit Basic Information")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Edit Contact Information")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Edit Personal Information")).not.toBeInTheDocument();
  });
});
