import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { LeavePage } from "../pages/LeavePage";
import * as timeLeaveApi from "../api";
import * as hrApi from "../../hr/api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");
vi.mock("../../hr/api");

const mockLeaveTypes: timeLeaveApi.LeaveType[] = [
  {
    id: "lt-1",
    name: "Paid Time Off",
    code: "PTO",
    annual_allowance: "18.00",
    carry_forward_limit: "5.00",
    max_consecutive_days: 10,
    requires_approval: true,
    is_paid: true,
    is_encashable: true,
    is_active: true,
  },
  {
    id: "lt-2",
    name: "Loss of Pay",
    code: "LOP",
    annual_allowance: "0.00",
    carry_forward_limit: "0.00",
    max_consecutive_days: null,
    requires_approval: true,
    is_paid: false,
    is_encashable: false,
    is_active: true,
  },
];

const mockBalances: timeLeaveApi.LeaveBalance[] = [
  {
    leave_type_id: "lt-1",
    leave_type_name: "Paid Time Off",
    year: 2026,
    opening_balance: "18.00",
    allocated: "18.00",
    used: "3.00",
    encashed: "0.00",
    available: "15.00",
  },
];

const mockLeaves: timeLeaveApi.Leave[] = [
  {
    id: "leave-1",
    employee_id: "emp-2",
    leave_type_id: "lt-1",
    start_date: "2026-11-20",
    end_date: "2026-11-22",
    total_days: "3.00",
    is_half_day: false,
    reason: "Personal family event",
    status: "pending",
    approved_by: null,
    approved_at: null,
    rejection_reason: null,
    created_at: "2026-11-15T00:00:00Z",
  },
];

const mockEmployees = {
  items: [
    { id: "emp-1", first_name: "Jane", last_name: "Doe" },
    { id: "emp-2", first_name: "Bob", last_name: "Taylor" },
  ],
  total: 2,
  page: 1,
  limit: 100,
  pages: 1,
  has_next: false,
};

function renderLeavePage(userRole: any = "manager", employeeId = "emp-1") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });

  const user = {
    id: "usr-1",
    company_id: "cmp-1",
    email: "manager@example.com",
    role: userRole,
    employee: employeeId
      ? {
          id: employeeId,
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
      <MemoryRouter>
        <ToastProvider>
          <LeavePage />
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Sub-features 4.5 & 4.6: Leave Balances & Requests Frontend (LeavePage)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(timeLeaveApi.listLeaveTypes).mockResolvedValue(mockLeaveTypes);
    vi.mocked(timeLeaveApi.getLeaveBalance).mockResolvedValue(mockBalances);
    vi.mocked(timeLeaveApi.listLeaves).mockResolvedValue({
      items: mockLeaves,
      total: 1,
      page: 1,
      limit: 10,
      pages: 1,
      has_next: false,
    });
    vi.mocked(hrApi.listEmployees).mockResolvedValue(mockEmployees as any);
  });

  it("renders leave balances grid and available days", async () => {
    renderLeavePage("employee", "emp-1");

    expect(screen.getByText("My balances")).toBeInTheDocument();

    await waitFor(() => {
      const balanceLabels = screen.getAllByText("Paid Time Off");
      expect(balanceLabels.length).toBeGreaterThan(0);
      expect(screen.getByText("15.00")).toBeInTheDocument();
      expect(screen.getByText(/18.00 allocated · 3.00 used/)).toBeInTheDocument();
    });
  });

  it("applies for leave when user fills apply form", async () => {
    vi.mocked(timeLeaveApi.applyLeave).mockResolvedValue({
      id: "leave-new",
      employee_id: "emp-1",
      leave_type_id: "lt-1",
      start_date: "2026-11-25",
      end_date: "2026-11-26",
      total_days: "2.00",
      is_half_day: false,
      reason: "Medical appointment",
      status: "pending",
      approved_by: null,
      approved_at: null,
      rejection_reason: null,
      created_at: "2026-11-17T00:00:00Z",
    });

    renderLeavePage("employee", "emp-1");

    await waitFor(() => {
      expect(screen.getByText("Apply for leave")).toBeInTheDocument();
      expect(screen.getAllByText("Paid Time Off").length).toBeGreaterThan(0);
    });

    const form = screen.getByText("Apply for leave").closest("form")!;
    
    // In employee mode (not manager/hr), the first select is leave type
    const select = form.querySelector("select")!;
    fireEvent.change(select, { target: { value: "lt-1" } });

    // Dates
    const dateInputs = form.querySelectorAll('input[type="date"]');
    const startInput = dateInputs[0];
    const endInput = dateInputs[1];
    fireEvent.change(startInput, { target: { value: "2026-11-25" } });
    fireEvent.change(endInput, { target: { value: "2026-11-26" } });

    // Reason
    const reasonInput = form.querySelector("textarea")!;
    fireEvent.change(reasonInput, { target: { value: "Medical appointment" } });

    // Click Apply button
    const submitBtn = screen.getByRole("button", { name: "Apply" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(timeLeaveApi.applyLeave).toHaveBeenCalledWith(
        expect.objectContaining({
          leave_type_id: "lt-1",
          start_date: "2026-11-25",
          end_date: "2026-11-26",
          reason: "Medical appointment",
        })
      );
    });
  });

  it("allows manager or HR to approve pending team leave requests", async () => {
    vi.mocked(timeLeaveApi.decideLeave).mockResolvedValue({
      ...mockLeaves[0],
      status: "approved",
      approved_by: "usr-1",
      approved_at: "2026-11-17T00:00:00Z",
    });

    renderLeavePage("manager", "emp-1");

    await waitFor(() => {
      expect(screen.getByText("Personal family event")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    // Confirm modal
    await waitFor(() => {
      expect(screen.getByText("Approve this leave request?")).toBeInTheDocument();
    });

    const modal = screen.getByText("Approve this leave request?").closest(".modal")!;
    const confirmApproveBtn = modal.querySelector(".btn-primary")!;
    fireEvent.click(confirmApproveBtn);

    await waitFor(() => {
      expect(timeLeaveApi.decideLeave).toHaveBeenCalledWith("leave-1", "approved", undefined);
    });
  });

  it("requires rejection reason when manager or HR rejects leave request", async () => {
    vi.mocked(timeLeaveApi.decideLeave).mockResolvedValue({
      ...mockLeaves[0],
      status: "rejected",
      rejection_reason: "Project critical release week",
    });

    renderLeavePage("manager", "emp-1");

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));

    // Confirm modal opens
    await waitFor(() => {
      expect(screen.getByText("Reject this leave request?")).toBeInTheDocument();
    });

    const modal = screen.getByText("Reject this leave request?").closest(".modal")!;
    const confirmRejectBtn = modal.querySelector(".btn-danger")!;

    // Clicking without reason shows validation error
    fireEvent.click(confirmRejectBtn);

    await waitFor(() => {
      expect(screen.getByText("A rejection reason is required.")).toBeInTheDocument();
    });

    // Fill reason
    const reasonInput = modal.querySelector("textarea")!;
    fireEvent.change(reasonInput, { target: { value: "Project critical release week" } });

    fireEvent.click(confirmRejectBtn);

    await waitFor(() => {
      expect(timeLeaveApi.decideLeave).toHaveBeenCalledWith(
        "leave-1",
        "rejected",
        "Project critical release week"
      );
    });
  });

  it("seeds leave balances when HR clicks '⚡ Seed Balances'", async () => {
    vi.mocked(timeLeaveApi.seedLeaveBalances).mockResolvedValue(mockBalances);

    renderLeavePage("hr_admin", "emp-1");

    await waitFor(() => {
      expect(screen.getByText("⚡ Seed Balances")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("⚡ Seed Balances"));

    await waitFor(() => {
      expect(timeLeaveApi.seedLeaveBalances).toHaveBeenCalledWith("emp-1", 2026);
    });
  });
});
