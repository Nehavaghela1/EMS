import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EmployeeFormPage } from "../pages/EmployeeFormPage";
import { EmployeeListPage } from "../pages/EmployeeListPage";
import * as AuthContextModule from "../../../app/auth-context";
import * as HrApi from "../api";
import * as ToastContextModule from "../../../app/toast-context";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    listEmployees: vi.fn(),
    listDepartments: vi.fn(),
    getEmployee: vi.fn(),
    createEmployee: vi.fn(),
    updateEmployee: vi.fn(),
    bulkDeactivateEmployees: vi.fn(),
    bulkReactivateEmployees: vi.fn(),
    bulkResendInviteEmployees: vi.fn(),
    requestEmployeeExport: vi.fn(),
    getJobStatus: vi.fn(),
    downloadEmployeeExport: vi.fn(),
    searchManagers: vi.fn(),
  };
});

describe("Sub-feature 2.4: Bulk actions and Export Frontend", () => {
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

  const defaultAuthValue: AuthContextModule.AuthContextValue = {
    status: "authenticated",
    user: hrUser,
    login: vi.fn(),
    establishSession: vi.fn(),
    logout: vi.fn(),
    sessionExpired: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue(defaultAuthValue);
    vi.spyOn(ToastContextModule, "useToast").mockReturnValue({ notify: mockNotify });
    vi.mocked(HrApi.listDepartments).mockResolvedValue({
      items: [{ id: "dept-1", name: "Engineering", description: null, head_employee_id: null, employee_count: 5, created_at: "2024-01-01" }],
      total: 1,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });
    vi.mocked(HrApi.searchManagers).mockResolvedValue([]);
  });

  describe("EmployeeFormPage (F1, F2, F3)", () => {
    it("F1: enforces level band selection and validates notice period 0-365 days", async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/employees/new"]}>
            <Routes>
              <Route path="/employees/new" element={<EmployeeFormPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      );

      expect(screen.getByRole("heading", { name: /onboard new employee/i })).toBeInTheDocument();

      // Fill in required fields: first_name, email, department
      await userEvent.type(screen.getByLabelText(/first name \*/i), "Alice");
      await userEvent.type(screen.getByLabelText(/work email \*/i), "alice@company.com");
      await userEvent.selectOptions(screen.getByLabelText(/department \*/i), "dept-1");

      const levelSelect = screen.getByLabelText(/level \(band\)/i) as HTMLSelectElement;
      expect(levelSelect).toBeInTheDocument();
      expect(levelSelect.value).toBe("L1");

      const noticeInput = screen.getByLabelText(/notice period \(days\)/i) as HTMLInputElement;
      expect(noticeInput).toBeInTheDocument();
      expect(noticeInput.value).toBe("30");

      // Change level to L3 auto-updates suggested notice period to 90
      await userEvent.selectOptions(levelSelect, "L3");
      expect(noticeInput.value).toBe("90");

      // Change notice period to invalid (>365)
      await userEvent.clear(noticeInput);
      await userEvent.type(noticeInput, "400");

      await userEvent.click(screen.getByRole("button", { name: /create & continue/i }));
      expect(await screen.findByText(/notice period must be between 0 and 365 days/i)).toBeInTheDocument();
    });

    it("F2: restricts non-HR employee from editing HR-only fields and sends changed fields only", async () => {
      const regularEmployeeUser: AuthContextModule.CurrentUser = {
        ...hrUser,
        role: "employee",
        id: "usr-emp-1",
      };
      vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
        ...defaultAuthValue,
        user: regularEmployeeUser,
      });

      const existingEmpData: HrApi.Employee = {
        id: "emp-1",
        user_id: "usr-emp-1",
        employee_code: "EMP-001",
        first_name: "Alice",
        last_name: "Smith",
        email: "alice@company.com",
        personal_email: "alice@gmail.com",
        phone: "+1234567890",
        department_id: "dept-1",
        department_name: "Engineering",
        location_id: null,
        position: "Developer",
        level: "L2",
        reporting_manager_id: null,
        employment_type: "full_time",
        hire_date: "2024-01-01",
        probation_end_date: null,
        notice_period_days: 60,
        is_active: true,
        invitation_status: "activated",
        created_at: "2024-01-01",
      };
      vi.mocked(HrApi.getEmployee).mockResolvedValue(existingEmpData);

      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/employees/emp-1/edit"]}>
            <Routes>
              <Route path="/employees/:id/edit" element={<EmployeeFormPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      );

      await waitFor(() => {
        expect(screen.getByDisplayValue("Alice")).toBeInTheDocument();
      });

      // First name, email, department, level should be disabled for regular employee
      expect(screen.getByDisplayValue("Alice")).toBeDisabled();
      expect(screen.getByDisplayValue("alice@company.com")).toBeDisabled();
      expect(screen.getByLabelText(/department \*/i)).toBeDisabled();
      expect(screen.getByLabelText(/level \(band\)/i)).toBeDisabled();

      // Last name, personal email, phone should be enabled
      const lastNameInput = screen.getByDisplayValue("Smith");
      expect(lastNameInput).not.toBeDisabled();

      await userEvent.clear(lastNameInput);
      await userEvent.type(lastNameInput, "Johnson");

      await userEvent.click(screen.getByRole("button", { name: /save changes/i }));

      await waitFor(() => {
        expect(HrApi.updateEmployee).toHaveBeenCalledTimes(1);
        expect(HrApi.updateEmployee).toHaveBeenCalledWith("emp-1", {
          last_name: "Johnson",
        });
      });
    });

    it("F3: shows informational warning notice when email or personal email is edited", async () => {
      const existingEmpData: HrApi.Employee = {
        id: "emp-1",
        user_id: "usr-emp-1",
        employee_code: "EMP-001",
        first_name: "Alice",
        last_name: "Smith",
        email: "alice@company.com",
        personal_email: "alice@gmail.com",
        phone: "+1234567890",
        department_id: "dept-1",
        department_name: "Engineering",
        location_id: null,
        position: "Developer",
        level: "L2",
        reporting_manager_id: null,
        employment_type: "full_time",
        hire_date: "2024-01-01",
        probation_end_date: null,
        notice_period_days: 60,
        is_active: true,
        invitation_status: "activated",
        created_at: "2024-01-01",
      };
      vi.mocked(HrApi.getEmployee).mockResolvedValue(existingEmpData);

      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/employees/emp-1/edit"]}>
            <Routes>
              <Route path="/employees/:id/edit" element={<EmployeeFormPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      );

      await waitFor(() => {
        expect(screen.getByDisplayValue("alice@gmail.com")).toBeInTheDocument();
      });

      // Initially no warning banner
      expect(screen.queryByText(/changing email will update login credentials/i)).not.toBeInTheDocument();

      const personalEmailInput = screen.getByDisplayValue("alice@gmail.com");
      await userEvent.clear(personalEmailInput);
      await userEvent.type(personalEmailInput, "alice_new@gmail.com");

      // Warning banner appears
      expect(await screen.findByText(/changing email will update login credentials/i)).toBeInTheDocument();
    });
  });

  describe("EmployeeListPage (F5, F6, F7)", () => {
    const mockEmployees: HrApi.Employee[] = [
      {
        id: "emp-1",
        user_id: "usr-1",
        employee_code: "EMP-001",
        first_name: "Alice",
        last_name: "Smith",
        email: "alice@test.com",
        personal_email: null,
        phone: null,
        department_id: "dept-1",
        department_name: "Engineering",
        location_id: null,
        position: "Developer",
        level: "L2",
        reporting_manager_id: null,
        employment_type: "full_time",
        hire_date: "2024-01-01",
        probation_end_date: null,
        notice_period_days: 60,
        is_active: true,
        invitation_status: "activated",
        created_at: "2024-01-01",
      },
      {
        id: "emp-2",
        user_id: "usr-2",
        employee_code: "EMP-002",
        first_name: "Bob",
        last_name: "Jones",
        email: "bob@test.com",
        personal_email: null,
        phone: null,
        department_id: "dept-1",
        department_name: "Engineering",
        location_id: null,
        position: "QA",
        level: "L1",
        reporting_manager_id: null,
        employment_type: "full_time",
        hire_date: "2024-01-01",
        probation_end_date: null,
        notice_period_days: 30,
        is_active: false,
        invitation_status: "sent",
        created_at: "2024-01-01",
      },
    ];

    beforeEach(() => {
      vi.mocked(HrApi.listEmployees).mockResolvedValue({
        items: mockEmployees,
        total: 2,
        page: 1,
        limit: 10,
        pages: 1,
        has_next: false,
      });
    });

    it("F5 & F6: triggers bulk action and displays results breakdown modal", async () => {
      vi.mocked(HrApi.bulkDeactivateEmployees).mockResolvedValue({
        requested: 1,
        succeeded: ["emp-1"],
        skipped: [],
        failed: [],
      });

      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/employees"]}>
            <Routes>
              <Route path="/employees" element={<EmployeeListPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      );

      await waitFor(() => {
        expect(screen.getByText(/Alice Smith/i)).toBeInTheDocument();
      });

      // Select first row checkbox
      const checkboxes = screen.getAllByRole("checkbox");
      // checkboxes[0] is header, checkboxes[1] is row 1
      await userEvent.click(checkboxes[1]);

      // Selection toolbar appears with Bulk Deactivate, Bulk Reactivate, Resend Invites
      const bulkDeactBtn = await screen.findByRole("button", { name: /bulk deactivate/i });
      expect(bulkDeactBtn).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /bulk reactivate/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /resend invites/i })).toBeInTheDocument();

      await userEvent.click(bulkDeactBtn);

      await waitFor(() => {
        expect(HrApi.bulkDeactivateEmployees).toHaveBeenCalledWith(["emp-1"]);
      });

      // Breakdown modal renders
      expect(await screen.findByTestId("bulk-results-modal")).toBeInTheDocument();
      expect(screen.getByText(/bulk deactivate results/i)).toBeInTheDocument();
      expect(screen.getByText("1")).toBeInTheDocument(); // Succeeded count
    });

    it("F7: requests export, polls job status, and triggers auto-download", async () => {
      vi.mocked(HrApi.requestEmployeeExport).mockResolvedValue({ job_id: "job-123" });
      vi.mocked(HrApi.getJobStatus).mockResolvedValue({
        job_id: "job-123",
        status: "SUCCESS",
        result: { file_name: "employees.csv", row_count: 2 },
      });
      vi.mocked(HrApi.downloadEmployeeExport).mockResolvedValue();

      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/employees"]}>
            <Routes>
              <Route path="/employees" element={<EmployeeListPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      );

      await waitFor(() => {
        expect(screen.getByText(/Alice Smith/i)).toBeInTheDocument();
      });

      // Select row 1
      const checkboxes = screen.getAllByRole("checkbox");
      await userEvent.click(checkboxes[1]);

      const exportBtn = await screen.findByRole("button", { name: /export selected/i });
      await userEvent.click(exportBtn);

      await waitFor(() => {
        expect(HrApi.requestEmployeeExport).toHaveBeenCalledWith(
          expect.objectContaining({
            employee_ids: ["emp-1"],
          })
        );
      });

      await waitFor(() => {
        expect(HrApi.getJobStatus).toHaveBeenCalledWith("job-123");
      });

      await waitFor(() => {
        expect(HrApi.downloadEmployeeExport).toHaveBeenCalledWith("job-123", "employees.csv");
      });

      expect(mockNotify).toHaveBeenCalledWith(
        expect.stringContaining("Export downloaded successfully"),
        "success"
      );
    });
  });
});
