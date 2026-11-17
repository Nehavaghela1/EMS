import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ReimbursementsPage } from "../pages/ReimbursementsPage";
import * as payrollApi from "../api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");

const mockClaims: payrollApi.Reimbursement[] = [
  {
    id: "claim-1",
    employee_id: "emp-1",
    type: "travel",
    amount: "2500.00",
    expense_date: "2026-11-10",
    description: "Client on-site visit taxi fare",
    file_object_id: "file-receipt-1",
    status: "pending",
    approved_by: null,
    approved_at: null,
    rejection_reason: null,
    added_to_payroll_run_id: null,
    created_at: "2026-11-10T10:00:00Z",
  },
  {
    id: "claim-2",
    employee_id: "emp-1",
    type: "medical",
    amount: "1500.00",
    expense_date: "2026-11-05",
    description: "Annual health checkup",
    file_object_id: null,
    status: "approved",
    approved_by: "usr-hr",
    approved_at: "2026-11-06T10:00:00Z",
    rejection_reason: null,
    added_to_payroll_run_id: "run-nov-2026",
    created_at: "2026-11-05T10:00:00Z",
  },
];

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
    last_name: "Connor",
    department_id: "dept-hr",
    position: "HR Lead",
  },
  permissions: [],
};

describe("Sub-feature 5.6: ReimbursementsPage Frontend", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: mockHrUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });
    vi.mocked(payrollApi.listReimbursements).mockResolvedValue({
      items: mockClaims,
      total: 2,
      page: 1,
      limit: 20,
      pages: 1,
      has_next: false,
    });
  });

  it("5.6 F1: loads and displays reimbursement claims list and KPI metrics", async () => {
    render(
      <ToastProvider>
        <ReimbursementsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(payrollApi.listReimbursements).toHaveBeenCalled();
      expect(screen.getByText("Reimbursements")).toBeInTheDocument();
    });

    expect(screen.getByText("Client on-site visit taxi fare")).toBeInTheDocument();
    expect(screen.getByText("Annual health checkup")).toBeInTheDocument();
    expect(screen.getAllByText(/Pending Approval/i).length).toBeGreaterThan(0);
  });

  it("5.6 F2: opens submit claim modal, enters details, and submits reimbursement claim", async () => {
    vi.mocked(payrollApi.submitReimbursement).mockResolvedValue({
      id: "claim-3",
      employee_id: "emp-hr-1",
      type: "food",
      amount: "800.00",
      expense_date: "2026-11-15",
      description: "Team lunch meeting",
      file_object_id: null,
      status: "pending",
      approved_by: null,
      approved_at: null,
      rejection_reason: null,
      added_to_payroll_run_id: null,
      created_at: "2026-11-15T12:00:00Z",
    });

    render(
      <ToastProvider>
        <ReimbursementsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /\+ Submit Claim/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /\+ Submit Claim/i }));

    expect(screen.getByText("Submit Reimbursement Claim")).toBeInTheDocument();

    const descInput = screen.getByPlaceholderText(/Explain the expense details/i);
    fireEvent.change(descInput, { target: { value: "Team lunch meeting" } });

    const submitBtn = screen.getByRole("button", { name: /^Submit$/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(payrollApi.submitReimbursement).toHaveBeenCalledWith(
        expect.objectContaining({
          description: "Team lunch meeting",
        })
      );
    });
  });

  it("5.6 F3: opens review modal for pending claim and approves it", async () => {
    vi.mocked(payrollApi.reviewReimbursement).mockResolvedValue({
      ...mockClaims[0],
      status: "approved",
      approved_by: "usr-hr-1",
      approved_at: "2026-11-17T00:00:00Z",
    });

    render(
      <ToastProvider>
        <ReimbursementsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Client on-site visit taxi fare")).toBeInTheDocument();
    });

    // Click the pending claim row to open review modal
    fireEvent.click(screen.getByText("Client on-site visit taxi fare"));

    await waitFor(() => {
      expect(screen.getByText("Review Reimbursement Claim")).toBeInTheDocument();
    });

    const approveBtn = screen.getByRole("button", { name: /^Approve$/i });
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(payrollApi.reviewReimbursement).toHaveBeenCalledWith("claim-1", {
        action: "approve",
        rejection_reason: undefined,
      });
    });
  });

  it("5.6 F4: requires a rejection reason when rejecting a claim", async () => {
    render(
      <ToastProvider>
        <ReimbursementsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Client on-site visit taxi fare")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Client on-site visit taxi fare"));

    await waitFor(() => {
      expect(screen.getByText("Review Reimbursement Claim")).toBeInTheDocument();
    });

    // Try to reject without reason
    const rejectBtn = screen.getByRole("button", { name: /^Reject$/i });
    fireEvent.click(rejectBtn);

    expect(payrollApi.reviewReimbursement).not.toHaveBeenCalled();

    // Fill in rejection reason
    const reasonInput = screen.getByPlaceholderText(/Enter reason if rejecting/i);
    fireEvent.change(reasonInput, { target: { value: "Receipt is blurred" } });

    fireEvent.click(rejectBtn);

    await waitFor(() => {
      expect(payrollApi.reviewReimbursement).toHaveBeenCalledWith("claim-1", {
        action: "reject",
        rejection_reason: "Receipt is blurred",
      });
    });
  });
});
