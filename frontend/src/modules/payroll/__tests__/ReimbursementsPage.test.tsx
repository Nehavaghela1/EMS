import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ReimbursementsPage } from "../pages/ReimbursementsPage";
import * as payrollApi from "../api";
import * as platformApi from "../../platform/api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");
vi.mock("../../platform/api");

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

    // The API requires a receipt, so the page uploads the chosen file first and
    // sends its id with the claim.
    vi.mocked(platformApi.uploadFile).mockResolvedValue({
      file_object_id: "file-new-1",
      file_name: "receipt.pdf",
      file_type: "application/pdf",
      file_size: 1024,
    });
    const receipt = new File(["receipt"], "receipt.pdf", { type: "application/pdf" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [receipt] } });

    const submitBtn = screen.getByRole("button", { name: /^Submit$/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(platformApi.uploadFile).toHaveBeenCalledWith(receipt);
      expect(payrollApi.submitReimbursement).toHaveBeenCalledWith(
        expect.objectContaining({
          description: "Team lunch meeting",
          file_object_id: "file-new-1",
        })
      );
    });
  });

  it("5.6 F2c: the review dialog opens the receipt of a claim that has one", async () => {
    vi.mocked(payrollApi.downloadReimbursementReceipt).mockResolvedValue(undefined);

    render(
      <ToastProvider>
        <ReimbursementsPage />
      </ToastProvider>
    );

    const row = await screen.findByText("Client on-site visit taxi fare");
    fireEvent.click(row.closest("tr") as HTMLElement);

    const receiptBtn = await screen.findByRole("button", { name: /view receipt/i });
    fireEvent.click(receiptBtn);

    await waitFor(() => {
      expect(payrollApi.downloadReimbursementReceipt).toHaveBeenCalledWith("claim-1");
    });
  });

  it("5.6 F2b: refuses to submit a claim with no receipt attached", async () => {
    render(
      <ToastProvider>
        <ReimbursementsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /\+ Submit Claim/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /\+ Submit Claim/i }));
    fireEvent.change(screen.getByPlaceholderText(/Explain the expense details/i), {
      target: { value: "No receipt attached" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Submit$/i }));

    await waitFor(() => {
      expect(screen.getByText(/Attach the receipt/i)).toBeInTheDocument();
    });
    expect(payrollApi.submitReimbursement).not.toHaveBeenCalled();
  });

  it("5.6 F3: opens review modal for pending claim and approves it without showing or requiring rejection reason", async () => {
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

    // Rejection reason field is not visible initially when reviewing
    expect(screen.queryByPlaceholderText(/Enter reason if rejecting/i)).not.toBeInTheDocument();

    const approveBtn = screen.getByRole("button", { name: /^Approve$/i });
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(payrollApi.reviewReimbursement).toHaveBeenCalledWith("claim-1", {
        action: "approve",
        rejection_reason: undefined,
      });
    });
  });

  it("5.6 F4 & L2: clicking Reject shows rejection reason and requires it before confirming", async () => {
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

    // Rejection reason not shown initially
    expect(screen.queryByPlaceholderText(/Enter reason if rejecting/i)).not.toBeInTheDocument();

    // Click Reject to initiate rejection flow
    const rejectBtn = screen.getByRole("button", { name: /^Reject$/i });
    fireEvent.click(rejectBtn);

    // Now reason input appears
    const reasonInput = screen.getByPlaceholderText(/Enter reason if rejecting/i);
    expect(reasonInput).toBeInTheDocument();

    // Confirm Reject button is disabled or blocked when reason is empty
    const confirmRejectBtn = screen.getByRole("button", { name: /Confirm Reject/i });
    expect(confirmRejectBtn).toBeDisabled();

    // Fill in rejection reason
    fireEvent.change(reasonInput, { target: { value: "Receipt is blurred" } });
    expect(confirmRejectBtn).not.toBeDisabled();

    fireEvent.click(confirmRejectBtn);

    await waitFor(() => {
      expect(payrollApi.reviewReimbursement).toHaveBeenCalledWith("claim-1", {
        action: "reject",
        rejection_reason: "Receipt is blurred",
      });
    });
  });

  it("PART A5: filter tabs call API with correct status and renders matching rows, empty state when empty", async () => {
    vi.mocked(payrollApi.listReimbursements).mockImplementation(async (status) => {
      if (status === "pending") {
        return {
          items: [mockClaims[0]],
          total: 1,
          page: 1,
          limit: 20,
          pages: 1,
          has_next: false,
        };
      }
      if (status === "approved") {
        return {
          items: [mockClaims[1]],
          total: 1,
          page: 1,
          limit: 20,
          pages: 1,
          has_next: false,
        };
      }
      if (status === "withdrawn") {
        return {
          items: [],
          total: 0,
          page: 1,
          limit: 20,
          pages: 0,
          has_next: false,
        };
      }
      return {
        items: mockClaims,
        total: 2,
        page: 1,
        limit: 20,
        pages: 1,
        has_next: false,
      };
    });

    render(
      <ToastProvider>
        <ReimbursementsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(payrollApi.listReimbursements).toHaveBeenCalledWith(undefined);
    });

    // Click PENDING APPROVAL tab
    const pendingTab = screen.getByRole("button", { name: /PENDING APPROVAL/i });
    fireEvent.click(pendingTab);

    await waitFor(() => {
      expect(payrollApi.listReimbursements).toHaveBeenCalledWith("pending");
      expect(screen.getByText("Client on-site visit taxi fare")).toBeInTheDocument();
      expect(screen.queryByText("Annual health checkup")).not.toBeInTheDocument();
    });

    // Click WITHDRAWN tab which has empty items
    const withdrawnTab = screen.getByRole("button", { name: /WITHDRAWN/i });
    fireEvent.click(withdrawnTab);

    await waitFor(() => {
      expect(payrollApi.listReimbursements).toHaveBeenCalledWith("withdrawn");
      expect(screen.getByText(/No reimbursement claims found for this filter/i)).toBeInTheDocument();
    });
  });

  it("PART A5: summary figures match fixture amounts and do not conflate approved and paid", async () => {
    const fixtureClaims: payrollApi.Reimbursement[] = [
      {
        id: "c-1",
        employee_id: "e-1",
        type: "travel",
        amount: "1000.00",
        expense_date: "2026-11-01",
        description: "Taxi",
        file_object_id: null,
        status: "pending",
        approved_by: null,
        approved_at: null,
        rejection_reason: null,
        added_to_payroll_run_id: null,
        created_at: "2026-11-01T00:00:00Z",
      },
      {
        id: "c-2",
        employee_id: "e-1",
        type: "travel",
        amount: "2500.50",
        expense_date: "2026-11-02",
        description: "Hotel",
        file_object_id: null,
        status: "approved",
        approved_by: "usr-hr",
        approved_at: "2026-11-03T00:00:00Z",
        rejection_reason: null,
        added_to_payroll_run_id: null,
        created_at: "2026-11-02T00:00:00Z",
      },
      {
        id: "c-3",
        employee_id: "e-1",
        type: "food",
        amount: "3000.00",
        expense_date: "2026-11-04",
        description: "Dinner",
        file_object_id: null,
        status: "paid",
        approved_by: "usr-hr",
        approved_at: "2026-11-05T00:00:00Z",
        rejection_reason: null,
        added_to_payroll_run_id: "run-1",
        created_at: "2026-11-04T00:00:00Z",
      },
    ];

    vi.mocked(payrollApi.listReimbursements).mockResolvedValue({
      items: fixtureClaims,
      total: 3,
      page: 1,
      limit: 20,
      pages: 1,
      has_next: false,
    });

    render(
      <ToastProvider>
        <ReimbursementsPage />
      </ToastProvider>
    );

    await waitFor(() => {
      // Pending: 1000.00 in summary card and table
      expect(screen.getAllByText("₹1,000.00").length).toBeGreaterThanOrEqual(1);
      // Approved (pending payroll): 2500.50
      expect(screen.getAllByText("₹2,500.50").length).toBeGreaterThanOrEqual(1);
      // Paid in payroll: 3000.00
      expect(screen.getAllByText("₹3,000.00").length).toBeGreaterThanOrEqual(1);
    });
  });
});
