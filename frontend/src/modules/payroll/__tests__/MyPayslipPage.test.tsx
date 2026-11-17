import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MyPayslipPage } from "../pages/MyPayslipPage";
import * as payrollApi from "../api";
import * as hrApi from "../../hr/api";
import * as identityApi from "../../identity/api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");
vi.mock("../../hr/api");
vi.mock("../../identity/api");

const mockUser: AuthContextModule.CurrentUser = {
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

const mockCompany: identityApi.CompanyResponse = {
  id: "cmp-acme",
  name: "Acme Innovations Ltd",
  slug: "acme",
  country: "IN",
  address: "Tower A, Tech Park",
  city: "Ahmedabad",
  state: "Gujarat",
  pincode: "380015",
  gst_number: "24AAACA1234A1Z5",
  pan_number: "AAACA1234A",
} as unknown as identityApi.CompanyResponse;

const mockPayslips: payrollApi.PayrollItem[] = [
  {
    id: "item-oct-2026",
    payroll_run_id: "run-oct-2026",
    employee_id: "emp-1",
    ctc_snapshot: "840000.00",
    gross_salary: "70000.00",
    total_deductions: "8400.00",
    net_salary: "61600.00",
    employer_cost: "77000.00",
    earnings_json: [
      { code: "BASIC", name: "Basic Salary", amount: "35000.00" },
      { code: "HRA", name: "House Rent Allowance", amount: "17500.00" },
      { code: "SPECIAL", name: "Special Allowance", amount: "17500.00" },
    ],
    deductions_json: [
      { code: "EPF", name: "Provident Fund", amount: "1800.00" },
      { code: "PT", name: "Professional Tax", amount: "200.00" },
      { code: "TDS", name: "Income Tax (TDS)", amount: "6400.00" },
    ],
    employer_contributions_json: [],
    working_days: "31.0",
    present_days: "29.0",
    absent_days: "0.0",
    half_days: "0.0",
    paid_leave_days: "2.0",
    lop_days: "0.0",
    reimbursement_amount: "0.00",
  },
];

describe("Sub-feature 5.5: MyPayslipPage Frontend", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: mockUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });
    vi.mocked(payrollApi.listMyPayslips).mockResolvedValue(mockPayslips);
    vi.mocked(identityApi.getMyCompany).mockResolvedValue(mockCompany);
    vi.mocked(hrApi.getFnFSettlement).mockResolvedValue(null as unknown as hrApi.FnFSettlement);
  });

  it("5.5 F1: renders employee's monthly payslip history and company info", async () => {
    render(
      <ToastProvider>
        <MyPayslipPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(payrollApi.listMyPayslips).toHaveBeenCalled();
      expect(screen.getByText("My Payslips & Statements")).toBeInTheDocument();
    });

    expect(screen.getByText("Acme Innovations Ltd")).toBeInTheDocument();
    expect(screen.getByText(/GSTIN: 24AAACA1234A1Z5/i)).toBeInTheDocument();
    expect(screen.getByText(/PAN: AAACA1234A/i)).toBeInTheDocument();
  });

  it("5.5 F2: displays itemized earnings and deductions breakdown exactly matching gross & net", async () => {
    render(
      <ToastProvider>
        <MyPayslipPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Basic Salary")).toBeInTheDocument();
      expect(screen.getByText("House Rent Allowance")).toBeInTheDocument();
      expect(screen.getByText("Provident Fund")).toBeInTheDocument();
      expect(screen.getByText("Professional Tax")).toBeInTheDocument();
    });

    expect(screen.getAllByText(/₹61,600/i).length).toBeGreaterThan(0);
  });

  it("5.5 F3: shows empty state when an admin or employee without payslips views the page", async () => {
    vi.mocked(payrollApi.listMyPayslips).mockResolvedValue([]);

    render(
      <ToastProvider>
        <MyPayslipPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("No approved payslips available yet.")).toBeInTheDocument();
    });
  });

  it("5.5 F4: triggers window.print when Download Statement (PDF / Print) button is clicked", async () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});

    render(
      <ToastProvider>
        <MyPayslipPage />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Download Statement \(PDF \/ Print\)/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Download Statement \(PDF \/ Print\)/i));

    expect(printSpy).toHaveBeenCalled();
  });
});
