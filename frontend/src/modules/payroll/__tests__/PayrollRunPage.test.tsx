import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { PayrollRunPage } from "../pages/PayrollRunPage";
import * as payrollApi from "../api";
import * as hrApi from "../../hr/api";
import * as identityApi from "../../identity/api";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");
vi.mock("../../hr/api");
vi.mock("../../identity/api");

const mockRuns: payrollApi.PayrollRun[] = [
  {
    id: "run-1",
    company_id: "cmp-1",
    month: 11,
    year: 2026,
    status: "draft",
    run_type: "regular",
    idempotency_key: "key-1",
    total_employees: 2,
    total_gross: "150000.00",
    total_deductions: "18000.00",
    total_net: "132000.00",
    total_employer_cost: "165000.00",
    approved_by: null,
    approved_at: null,
    error_message: null,
    created_at: "2026-11-01T00:00:00Z",
  },
  {
    id: "run-2",
    company_id: "cmp-1",
    month: 10,
    year: 2026,
    status: "approved",
    run_type: "regular",
    idempotency_key: "key-2",
    total_employees: 2,
    total_gross: "150000.00",
    total_deductions: "18000.00",
    total_net: "132000.00",
    total_employer_cost: "165000.00",
    approved_by: "usr-admin",
    approved_at: "2026-11-05T00:00:00Z",
    error_message: null,
    created_at: "2026-10-01T00:00:00Z",
  },
];

const mockEmployees: hrApi.Employee[] = [
  {
    id: "emp-1",
    employee_code: "EMP-001",
    first_name: "Rahul",
    last_name: "Sharma",
    work_email: "rahul@example.com",
    department_id: "dept-1",
    department_name: "Engineering",
    position: "Senior Engineer",
    level: "L2",
    is_active: true,
    joining_date: "2026-01-15",
  } as unknown as hrApi.Employee,
];

const mockRunDetail: payrollApi.PayrollRunDetail = {
  run: mockRuns[0],
  items: [
    {
      id: "item-1",
      payroll_run_id: "run-1",
      employee_id: "emp-1",
      ctc_snapshot: "900000.00",
      gross_salary: "75000.00",
      total_deductions: "9000.00",
      net_salary: "66000.00",
      employer_cost: "82500.00",
      earnings_json: [
        { code: "BASIC", name: "Basic Salary", amount: "37500.00" },
        { code: "HRA", name: "House Rent Allowance", amount: "18750.00" },
        { code: "SPECIAL", name: "Special Allowance", amount: "18750.00" },
      ],
      deductions_json: [
        { code: "EPF", name: "Provident Fund", amount: "1800.00" },
        { code: "PT", name: "Professional Tax", amount: "200.00" },
      ],
      employer_contributions_json: [],
      working_days: "30.0",
      present_days: "30.0",
      absent_days: "0.0",
      half_days: "0.0",
      paid_leave_days: "0.0",
      lop_days: "0.0",
      reimbursement_amount: "0.00",
    },
  ],
};

function renderPage() {
  return render(
    <ToastProvider>
      <PayrollRunPage />
    </ToastProvider>
  );
}

describe("Sub-feature 5.4: PayrollRunPage Frontend", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(payrollApi.listPayrollRuns).mockResolvedValue({
      items: mockRuns,
      total: 2,
      page: 1,
      limit: 20,
      pages: 1,
      has_next: false,
    });
    vi.mocked(hrApi.listEmployees).mockResolvedValue({
      items: mockEmployees,
      total: 1,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });
    vi.mocked(identityApi.getMyCompany).mockResolvedValue({
      id: "cmp-1",
      name: "Acme Corp",
      slug: "acme",
      country: "IN",
    } as unknown as identityApi.CompanyResponse);
    vi.mocked(payrollApi.getStatutoryConfig).mockResolvedValue({
      pf_enabled: true,
      pf_employee_rate: "12.0",
      pf_employer_rate: "12.0",
      pf_wage_ceiling: "15000",
      pf_restrict_to_ceiling: true,
      esi_enabled: false,
      esi_employee_rate: "0.75",
      esi_employer_rate: "3.25",
      esi_wage_ceiling: "21000",
      pt_enabled: true,
      pt_state: "Gujarat",
      lwf_enabled: false,
      lwf_employee_amount: "0",
      lwf_months: [],
      tds_enabled: true,
      default_tax_regime: "new",
      payout_bank_name: "ICICI Bank Corporate",
      payout_account_number: "9876543210",
      payout_ifsc_code: "ICIC0000412",
      payout_enabled: true,
    });
  });

  it("5.4 F1: loads and displays active and past payroll runs", async () => {
    renderPage();

    await waitFor(() => {
      expect(payrollApi.listPayrollRuns).toHaveBeenCalled();
    });

    expect(screen.getByText("Run Payroll")).toBeInTheDocument();
    expect(screen.getByText("Payroll History")).toBeInTheDocument();
  });

  it("5.4 F2: switches to Payroll History tab and initiates a new payroll run modal", async () => {
    vi.mocked(payrollApi.createPayrollRun).mockResolvedValue(mockRuns[0]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Payroll History")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Payroll History"));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /\+ Create Pay Run/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /\+ Create Pay Run/i }));

    expect(screen.getByText("Initiate Payroll Run")).toBeInTheDocument();

    const submitBtn = screen.getByRole("button", { name: /^Run$/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(payrollApi.createPayrollRun).toHaveBeenCalled();
    });
  });

  it("5.4 F3: opens run detail view, displays itemized employee breakdown, and approves run", async () => {
    vi.mocked(payrollApi.getPayrollRunDetail).mockResolvedValue(mockRunDetail);
    vi.mocked(payrollApi.approvePayrollRun).mockResolvedValue({
      ...mockRuns[0],
      status: "approved",
      approved_by: "usr-admin",
      approved_at: "2026-11-17T00:00:00Z",
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /View & Process Pay Run/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /View & Process Pay Run/i }));

    await waitFor(() => {
      expect(payrollApi.getPayrollRunDetail).toHaveBeenCalledWith("run-1");
      expect(screen.getByText("Rahul Sharma")).toBeInTheDocument();
    });

    // Check approve button is present for draft run
    const approveBtn = screen.getByRole("button", { name: /Approve & Record Payment/i });
    expect(approveBtn).toBeInTheDocument();

    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(payrollApi.approvePayrollRun).toHaveBeenCalledWith("run-1");
    });
  });

  it("5.4 F4: opens payslip modal from run items and displays payslip breakdown", async () => {
    vi.mocked(payrollApi.getPayrollRunDetail).mockResolvedValue(mockRunDetail);

    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /View & Process Pay Run/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /View & Process Pay Run/i }));

    await waitFor(() => {
      expect(screen.getByText("Rahul Sharma")).toBeInTheDocument();
    });

    const viewPayslipBtn = screen.getAllByRole("button", { name: /^View$/i })[0];
    fireEvent.click(viewPayslipBtn);

    await waitFor(() => {
      expect(screen.getByText(/Basic Salary/i)).toBeInTheDocument();
      expect(screen.getByText(/House Rent Allowance/i)).toBeInTheDocument();
    });
  });

  it("5.4 F5: deletes/cancels a draft payroll run", async () => {
    vi.mocked(payrollApi.getPayrollRunDetail).mockResolvedValue(mockRunDetail);
    vi.mocked(payrollApi.deletePayrollRun).mockResolvedValue();

    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /View & Process Pay Run/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /View & Process Pay Run/i }));

    await waitFor(() => {
      expect(screen.getByText("Rahul Sharma")).toBeInTheDocument();
    });

    // Open 3-dot or more options menu
    const moreActionsBtn = screen.getByTitle("More Options / Actions");
    fireEvent.click(moreActionsBtn);

    const deleteBtn = screen.getByRole("button", { name: /Cancel \/ Delete Draft Run/i });
    fireEvent.click(deleteBtn);

    // Confirm dialog
    await waitFor(() => {
      expect(screen.getByText(/Cancel Draft Payroll Run\?/i)).toBeInTheDocument();
    });

    const confirmBtn = screen.getByRole("button", { name: /Cancel Run/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(payrollApi.deletePayrollRun).toHaveBeenCalledWith("run-1");
    });
  });

  it("F4: hero renders the exact sum of item net_salary values", async () => {
    // 2 items: 66,000.00 and 44,000.00 -> total net must be 1,10,000.00
    const fixtureDetail: payrollApi.PayrollRunDetail = {
      run: {
        ...mockRuns[0],
        total_net: "999999.00", // deliberate run mismatch to prove hero renders sum of item net_salaries
        total_gross: "150000.00",
        total_deductions: "40000.00",
      },
      items: [
        {
          ...mockRunDetail.items[0],
          id: "item-1",
          net_salary: "66000.00",
        },
        {
          ...mockRunDetail.items[0],
          id: "item-2",
          employee_id: "emp-2",
          net_salary: "44000.00",
        },
      ],
    };
    vi.mocked(payrollApi.getPayrollRunDetail).mockResolvedValue(fixtureDetail);

    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /View & Process Pay Run/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /View & Process Pay Run/i }));

    await waitFor(() => {
      expect(screen.getByText("Rahul Sharma")).toBeInTheDocument();
    });

    // 66,000 + 44,000 = 1,10,000.00
    // In Indian locale formatting: ₹1,10,000.00
    expect(screen.getByText("₹1,10,000.00")).toBeInTheDocument();
    expect(screen.queryByText("₹9,99,999.00")).not.toBeInTheDocument();
  });

  it("G5: does not render dummy toast controls and kept action buttons make expected network calls", async () => {
    vi.mocked(payrollApi.getPayrollRunDetail).mockResolvedValue(mockRunDetail);
    vi.mocked(payrollApi.downloadPaymentFile).mockResolvedValue();

    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /View & Process Pay Run/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /View & Process Pay Run/i }));

    await waitFor(() => {
      expect(screen.getByText("Rahul Sharma")).toBeInTheDocument();
    });

    // Dummy controls must not exist:
    // 1. Comments feature button
    expect(screen.queryByTitle("Add Comments / Notes")).not.toBeInTheDocument();
    // 2. Send Payslip button
    expect(screen.queryByRole("button", { name: /Send Payslip/i })).not.toBeInTheDocument();
    // 3. Filter button in summary table
    expect(screen.queryByTitle("Filter employees")).not.toBeInTheDocument();
    // 4. Duplicate Export Data button in summary table
    expect(screen.queryByRole("button", { name: /Export Data ▾/i })).not.toBeInTheDocument();
    // 5. TDS View link
    expect(screen.queryByRole("button", { name: /The TDS worksheet download/i })).not.toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();

    // Kept action: Download Bank Advice button makes real network call
    const bankAdviceBtn = screen.getByRole("button", { name: /Download Bank Advice/i });
    fireEvent.click(bankAdviceBtn);

    await waitFor(() => {
      expect(payrollApi.downloadPaymentFile).toHaveBeenCalledWith("run-1");
    });
  });

  it("I4: generated CSV first data row contains employee code and name, and no UUID", async () => {
    vi.mocked(payrollApi.getPayrollRunDetail).mockResolvedValue(mockRunDetail);

    // Spy on createElement & appendChild to inspect CSV content
    let downloadedContent = "";
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tagName: string) => {
      const element = originalCreateElement(tagName);
      if (tagName.toLowerCase() === "a") {
        const origSetAttribute = element.setAttribute.bind(element);
        element.setAttribute = (name: string, value: string) => {
          if (name === "href" && value.startsWith("data:text/csv")) {
            downloadedContent = decodeURI(value.replace("data:text/csv;charset=utf-8,", ""));
          }
          return origSetAttribute(name, value);
        };
      }
      return element;
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /View & Process Pay Run/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /View & Process Pay Run/i }));

    await waitFor(() => {
      expect(screen.getByText("Rahul Sharma")).toBeInTheDocument();
    });

    // Open options menu and trigger CSV export
    const moreActionsBtn = screen.getByTitle("More Options / Actions");
    fireEvent.click(moreActionsBtn);

    const exportBtn = screen.getByRole("button", { name: /Export Payroll Summary \(CSV\)/i });
    fireEvent.click(exportBtn);

    expect(downloadedContent).toBeTruthy();
    const [headerLine, firstDataLine] = downloadedContent.split("\n");
    expect(headerLine).toBe("Employee Code,Employee Name,CTC Snapshot,Gross Salary,Deductions,Net Salary");
    // emp-1 has employee_code EMP-001, name "Rahul Sharma", and ctc 900000.00
    expect(firstDataLine).toBe('EMP-001,"Rahul Sharma",900000.00,75000.00,9000.00,66000.00');
    // Ensure no UUID in data line
    expect(firstDataLine).not.toContain("emp-1");
    expect(firstDataLine).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  });
});
