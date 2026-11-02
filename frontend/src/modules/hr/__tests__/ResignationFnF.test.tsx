import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
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
    submitResignation: vi.fn(),
    approveResignation: vi.fn(),
    terminateEmployee: vi.fn(),
    getFnFSettlement: vi.fn(),
    updateFnFClearance: vi.fn(),
    updateEmployee: vi.fn(),
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

describe("Sub-feature 2.6: Resignation, Termination & FnF Settlement Frontend", () => {
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
      first_name: "John",
      last_name: "Doe",
      department_id: "dept-1",
      position: "Senior Engineer",
    },
    permissions: [],
  };

  const activeEmployee: HrApi.Employee = {
    id: "emp-1",
    user_id: "usr-emp-1",
    company_id: "cmp-1",
    employee_code: "EMP001",
    first_name: "John",
    last_name: "Doe",
    email: "emp@company.com",
    personal_email: "john.personal@gmail.com",
    phone: "9876543210",
    department_id: "dept-1",
    department_name: "Engineering",
    location_id: "loc-1",
    reporting_manager_id: null,
    position: "Senior Engineer",
    level: "L2",
    employment_type: "full_time",
    hire_date: "2023-01-01",
    probation_end_date: null,
    notice_period_days: 30,
    is_active: true,
    invitation_status: "activated",
    resignation_status: "none",
    created_at: "2023-01-01T00:00:00Z",
  };

  const resignedEmployee: HrApi.Employee = {
    ...activeEmployee,
    resignation_status: "submitted",
    resignation_date: "2026-03-01",
    last_working_date: "2026-03-31",
    notice_waived: false,
    notice_recovery_days: 0,
  };

  const approvedEmployee: HrApi.Employee = {
    ...activeEmployee,
    is_active: false,
    resignation_status: "approved",
    resignation_date: "2026-03-01",
    last_working_date: "2026-03-31",
    it_clearance: true,
    hr_clearance: false,
    finance_clearance: false,
  };

  const mockFnFData: HrApi.FnFSettlement = {
    employee_id: "emp-1",
    employee_name: "John Doe",
    last_working_date: "2026-03-31",
    separation_type: "voluntary",
    notice_days_required: 30,
    notice_days_served: 30,
    notice_waived: false,
    notice_recovery_days: 0,
    notice_recovery_amount: 0,
    encashable_leave_days: 5,
    leave_encashment_amount: 10000,
    unpaid_salary_days: 30,
    unpaid_salary_amount: 80000,
    monthly_gross_salary: 80000,
    per_day_salary: 2666.67,
    severance_pay: 0,
    pending_reimbursements: 5000,
    gratuity_bonus: 5000,
    asset_deductions: 0,
    it_clearance: true,
    hr_clearance: false,
    finance_clearance: false,
    can_release_settlement: false,
    fnf_settled_at: null,
    total_settlement_amount: 100000,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.spyOn(ToastContextModule, "useToast").mockReturnValue({
      notify: mockNotify,
    });
    vi.mocked(TimeLeaveApi.getAssignedShift).mockResolvedValue(null);
  });

  function renderProfile(user: AuthContextModule.CurrentUser, employee: HrApi.Employee, fnfData: HrApi.FnFSettlement = mockFnFData) {
    vi.mocked(HrApi.getEmployee).mockResolvedValue(employee);
    vi.mocked(HrApi.getFnFSettlement).mockResolvedValue(fnfData);

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

  it("Rule 1: allows employee to submit resignation with last working date and reason", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.submitResignation).mockResolvedValueOnce(resignedEmployee);

    renderProfile(employeeUser, activeEmployee);

    // Switch to Exit tab
    const exitTab = await screen.findByRole("button", { name: /Resignation & FnF/i });
    await user.click(exitTab);

    expect(await screen.findByText(/John Doe's Exit details/i)).toBeInTheDocument();

    const lwdInput = screen.getByPlaceholderText("dd/MM/yyyy");
    await user.type(lwdInput, "2026-04-15");

    const reasonSelect = screen.getByRole("combobox");
    await user.selectOptions(reasonSelect, "Better Opportunity");

    const submitBtn = screen.getByRole("button", { name: /^Proceed$/i });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(HrApi.submitResignation).toHaveBeenCalledWith(
        "emp-1",
        expect.objectContaining({
          last_working_date: "2026-04-15",
          reason: expect.stringContaining("Better Opportunity"),
        })
      );
      expect(mockNotify).toHaveBeenCalledWith(
        "Exit details saved successfully. Employee status updated to Serving Notice."
      );
    });
  });

  it("Rule 2: shows review panel for HR when resignation is submitted, computes notice and allows approval", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.approveResignation).mockResolvedValueOnce(approvedEmployee);

    renderProfile(hrUser, resignedEmployee);

    const exitTab = await screen.findByRole("button", { name: /Resignation & FnF/i });
    await user.click(exitTab);

    expect(await screen.findByText(/HR Approval & Notice Terms/i)).toBeInTheDocument();
    expect(screen.getByText(/Contractual Notice:/i)).toBeInTheDocument();

    const approveBtn = screen.getByRole("button", { name: /Approve Resignation & Set Serving Notice/i });
    await user.click(approveBtn);

    await waitFor(() => {
      expect(HrApi.approveResignation).toHaveBeenCalledWith(
        "emp-1",
        expect.objectContaining({
          approved: true,
        })
      );
      expect(mockNotify).toHaveBeenCalledWith(
        "Resignation approved. Employee is Serving Notice / Separated."
      );
    });
  });

  it("Rule 3: displays multi-department clearance sign-offs (IT, HR, Finance) during exit", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.updateFnFClearance).mockResolvedValueOnce({ ...mockFnFData, it_clearance: false });

    renderProfile(hrUser, approvedEmployee);

    const exitTab = await screen.findByRole("button", { name: /Resignation & FnF/i });
    await user.click(exitTab);

    expect(await screen.findByText("🪪 HR Department")).toBeInTheDocument();
    expect(screen.getByText("💻 IT Department")).toBeInTheDocument();
    expect(screen.getByText("💰 Finance Department")).toBeInTheDocument();

    // Toggle IT clearance
    const itClearanceBtn = screen.getByRole("button", { name: /✓ Returned/i });
    await user.click(itClearanceBtn);

    await waitFor(() => {
      expect(HrApi.updateFnFClearance).toHaveBeenCalledWith(
        "emp-1",
        expect.objectContaining({
          it_clearance: false,
        })
      );
      expect(mockNotify).toHaveBeenCalledWith("Clearance sign-off updated.");
    });
  });

  it("Rule 4: displays FnF settlement calculation and disables release until all clearances are completed", async () => {
    const user = userEvent.setup();
    renderProfile(hrUser, approvedEmployee);

    const exitTab = await screen.findByRole("button", { name: /Resignation & FnF/i });
    await user.click(exitTab);

    expect(await screen.findByText(/Full-and-Final \(FnF\) Settlement Statement/i)).toBeInTheDocument();
    expect(await screen.findByText(/Total Net FnF Payout/i)).toBeInTheDocument();

    const releaseBtn = screen.getByRole("button", { name: /Clearance Sign-off Required/i });
    expect(releaseBtn).toBeDisabled();
  });

  it("Rule 5: enables settlement release when clearances are complete and prompts confirmation", async () => {
    const user = userEvent.setup();
    const readyFnFData: HrApi.FnFSettlement = {
      ...mockFnFData,
      can_release_settlement: true,
    };

    renderProfile(hrUser, approvedEmployee, readyFnFData);

    const exitTab = await screen.findByRole("button", { name: /Resignation & FnF/i });
    await user.click(exitTab);

    const releaseBtn = await screen.findByRole("button", { name: /Release Full & Final Settlement/i });
    expect(releaseBtn).not.toBeDisabled();
    await user.click(releaseBtn);

    expect(await screen.findByText(/Confirm FnF Final Settlement Release/i)).toBeInTheDocument();
  });

  it("Rule 5b: release only happens after typing CONFIRM in the dialog", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.updateFnFClearance).mockResolvedValueOnce({
      ...mockFnFData,
      can_release_settlement: true,
      fnf_settled_at: "2026-04-01T00:00:00Z",
    });

    renderProfile(hrUser, approvedEmployee, { ...mockFnFData, can_release_settlement: true });

    await user.click(await screen.findByRole("button", { name: /Resignation & FnF/i }));
    await user.click(await screen.findByRole("button", { name: /Release Full & Final Settlement/i }));

    expect(await screen.findByText(/Confirm FnF Final Settlement Release/i)).toBeInTheDocument();
    expect(HrApi.updateFnFClearance).not.toHaveBeenCalled();

    const authorizeBtn = screen.getByRole("button", { name: /Authorize & Release/i });
    expect(authorizeBtn).toBeDisabled();

    await user.type(screen.getByPlaceholderText("Type CONFIRM here"), "confirm");
    expect(authorizeBtn).not.toBeDisabled();
    await user.click(authorizeBtn);

    await waitFor(() => {
      expect(HrApi.updateFnFClearance).toHaveBeenCalledWith("emp-1", { mark_settled: true });
    });
    expect(mockNotify).toHaveBeenCalledWith(
      "FnF Settlement released successfully! Employee account finalized.",
      "success"
    );
  });

  it("Rule 2b: an employee viewing a submitted resignation does not get the HR approval button", async () => {
    const user = userEvent.setup();
    renderProfile(employeeUser, resignedEmployee);

    await user.click(await screen.findByRole("button", { name: /Resignation & FnF/i }));

    expect(await screen.findByText("Resignation Pending Review")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Approve Resignation & Set Serving Notice/i })
    ).not.toBeInTheDocument();
    expect(HrApi.approveResignation).not.toHaveBeenCalled();
  });

  it("Rule 1b: shows the server message and does not claim success when the resignation is rejected", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.submitResignation).mockRejectedValueOnce(
      new AxiosError("Request failed with status code 422", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 422,
        statusText: "Unprocessable Entity",
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: { error: { code: "validation_error", message: "Last working date must be today or later." } },
      })
    );

    renderProfile(employeeUser, activeEmployee);

    await user.click(await screen.findByRole("button", { name: /Resignation & FnF/i }));
    await user.type(await screen.findByPlaceholderText("dd/MM/yyyy"), "2026-04-15");
    await user.selectOptions(screen.getByRole("combobox"), "Better Opportunity");
    await user.click(screen.getByRole("button", { name: /^Proceed$/i }));

    await waitFor(() => {
      expect(mockNotify).toHaveBeenCalledWith("Last working date must be today or later.", "error");
    });
    expect(mockNotify).not.toHaveBeenCalledWith(
      "Exit details saved successfully. Employee status updated to Serving Notice."
    );
  });
});
