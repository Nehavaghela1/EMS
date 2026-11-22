import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { PayrollSetupPage } from "../pages/PayrollSetupPage";
import * as payrollApi from "../api";
import * as hrApi from "../../hr/api";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");
vi.mock("../../hr/api");

const mockStructures: payrollApi.SalaryStructureListItem[] = [
  {
    id: "struct-1",
    name: "Engineering Standard Structure",
    country: "IN",
    level: "L1",
    is_active: true,
    version: 1,
    component_count: 3,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    created_by_email: "hr@acme.com",
    updated_by_email: "hr@acme.com",
  },
  {
    id: "struct-2",
    name: "Management Structure",
    country: "IN",
    level: "L3",
    is_active: true,
    version: 2,
    component_count: 4,
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-03-05T00:00:00Z",
    created_by_email: "hr@acme.com",
    updated_by_email: "owner@acme.com",
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
  {
    id: "emp-2",
    employee_code: "EMP-002",
    first_name: "Priya",
    last_name: "Patel",
    work_email: "priya@example.com",
    department_id: "dept-2",
    department_name: "Product",
    position: "Product Manager",
    level: "L3",
    is_active: true,
    joining_date: "2026-02-01",
  } as unknown as hrApi.Employee,
];

const mockStatutoryConfig: payrollApi.StatutoryConfig = {
  pf_enabled: true,
  pf_employee_rate: "12.000",
  pf_employer_rate: "12.000",
  pf_wage_ceiling: "15000.00",
  pf_restrict_to_ceiling: true,
  esi_enabled: true,
  esi_employee_rate: "0.750",
  esi_employer_rate: "3.250",
  esi_wage_ceiling: "21000.00",
  pt_enabled: true,
  pt_state: "Gujarat",
  lwf_enabled: true,
  lwf_employee_amount: "6.00",
  lwf_months: [6, 12],
  tds_enabled: true,
  default_tax_regime: "new",
  payout_bank_name: "ICICI Bank Corporate",
  payout_account_number: "9876543210",
  payout_ifsc_code: "ICIC0000412",
  payout_enabled: true,
};

const mockPtSlabs: payrollApi.PtSlab[] = [
  {
    id: "pt-1",
    state: "Gujarat",
    income_min: "0.00",
    income_max: "12000.00",
    monthly_amount: "0.00",
    special_month: null,
    special_month_amount: null,
    source_note: "Gujarat PT Act",
  },
  {
    id: "pt-2",
    state: "Gujarat",
    income_min: "12000.01",
    income_max: null,
    monthly_amount: "200.00",
    special_month: null,
    special_month_amount: null,
    source_note: "Gujarat PT Act",
  },
];

const mockTaxSlabs: payrollApi.TaxSlab[] = [
  {
    id: "tax-1",
    country: "IN",
    financial_year: "2026-2027",
    regime: "new",
    min_income: "0.00",
    max_income: "300000.00",
    rate_percent: "0.00",
    cess_percent: "4.00",
    surcharge_rules: null,
    source_note: "Finance Act 2026",
  },
  {
    id: "tax-2",
    country: "IN",
    financial_year: "2026-2027",
    regime: "new",
    min_income: "300000.01",
    max_income: "700000.00",
    rate_percent: "5.00",
    cess_percent: "4.00",
    surcharge_rules: null,
    source_note: "Finance Act 2026",
  },
];

function renderSetupPage(route = "/payroll/setup") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ToastProvider>
        <PayrollSetupPage />
      </ToastProvider>
    </MemoryRouter>
  );
}

describe("Sub-feature 5.1 & 5.2 & 5.3: PayrollSetupPage Frontend", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(payrollApi.listStructures).mockResolvedValue({
      items: mockStructures,
      total: 2,
      page: 1,
      limit: 20,
      pages: 1,
      has_next: false,
    });
    vi.mocked(hrApi.listEmployees).mockResolvedValue({
      items: mockEmployees,
      total: 2,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });
    vi.mocked(payrollApi.getStatutoryConfig).mockResolvedValue(mockStatutoryConfig);
    vi.mocked(payrollApi.listPtSlabs).mockResolvedValue(mockPtSlabs);
    vi.mocked(payrollApi.listTaxSlabs).mockResolvedValue(mockTaxSlabs);
  });

  it("5.1 F1: loads and displays existing salary structures in the list", async () => {
    renderSetupPage();

    await waitFor(() => {
      expect(screen.getByText("Engineering Standard Structure")).toBeInTheDocument();
      expect(screen.getByText("Management Structure")).toBeInTheDocument();
    });

    expect(screen.getByText("Salary Structures")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /\+ Create Structure/i })).toBeInTheDocument();
  });

  it("5.1 F2: opens the create structure view, fills in details, and saves salary structure", async () => {
    vi.mocked(payrollApi.createStructure).mockResolvedValue({
      id: "struct-3",
      name: "New Sales Structure",
      country: "IN",
      level: "L1",
      is_active: true,
      version: 1,
      components: [],
      created_at: "2026-03-01T00:00:00Z",
      updated_at: "2026-03-01T00:00:00Z",
      created_by_email: "hr@acme.com",
      updated_by_email: "hr@acme.com",
    });

    renderSetupPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /\+ Create Structure/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /\+ Create Structure/i }));

    expect(screen.getByText("Create Salary Structure")).toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText(/e\.g\. Standard Full-time India Structure/i);
    fireEvent.change(nameInput, { target: { value: "New Sales Structure" } });

    // Click submit
    const submitBtn = screen.getAllByRole("button", { name: /Save Salary Structure/i })[0];
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(payrollApi.createStructure).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "New Sales Structure",
          country: "IN",
          level: "L1",
        })
      );
    });
  });

  it("5.3 F3: opens assign salary modal, selects employee and structure, and assigns CTC with effective date", async () => {
    vi.mocked(payrollApi.assignEmployeeSalary).mockResolvedValue({
      id: "sal-1",
      employee_id: "emp-1",
      structure_id: "struct-1",
      ctc: "850000.00",
      effective_from: "2026-04-01",
      created_at: "2026-03-01T00:00:00Z",
    });

    renderSetupPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Assign Employee Salary/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Assign Employee Salary/i }));

    expect(screen.getByText("Assign Salary Structure")).toBeInTheDocument();

    // Select employee
    const selectLabels = screen.getAllByRole("combobox");
    const empSelect = selectLabels[0];
    fireEvent.change(empSelect, { target: { value: "emp-1" } });

    // Select structure
    const structSelect = selectLabels[1];
    fireEvent.change(structSelect, { target: { value: "struct-1" } });

    // Submit form
    const submitBtn = screen.getByRole("button", { name: /^Save$/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(payrollApi.assignEmployeeSalary).toHaveBeenCalledWith(
        "emp-1",
        expect.objectContaining({
          structure_id: "struct-1",
          ctc: expect.any(String),
          effective_from: expect.any(String),
        })
      );
    });
  });

  it("5.2 F4: switches to Statutory tab, displays EPF/ESI/PT/TDS rules and updates statutory config", async () => {
    vi.mocked(payrollApi.updateStatutoryConfig).mockResolvedValue({
      ...mockStatutoryConfig,
      pt_state: "Maharashtra",
    });

    renderSetupPage("/payroll/setup?tab=statutory");

    await waitFor(() => {
      expect(payrollApi.getStatutoryConfig).toHaveBeenCalled();
      expect(screen.getByText(/EPF Settings/i)).toBeInTheDocument();
    });

    // Check presence of statutory settings
    expect(screen.getByText(/ESI Settings/i)).toBeInTheDocument();
    expect(screen.getByText(/Professional Tax & TDS/i)).toBeInTheDocument();

    // Save changes
    const saveBtn = screen.getByRole("button", { name: /Save Statutory Config/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(payrollApi.updateStatutoryConfig).toHaveBeenCalled();
    });
  });

  it("5.2 F5: switches to PT Slabs tab and renders slab thresholds", async () => {
    renderSetupPage("/payroll/setup?tab=pt_slabs");

    await waitFor(() => {
      expect(payrollApi.listPtSlabs).toHaveBeenCalledWith("Gujarat");
      expect(screen.getByText("Professional Tax Slabs (Gujarat)")).toBeInTheDocument();
    });

    expect(screen.getByText(/12,000\.01/i)).toBeInTheDocument();
    expect(screen.getByText("₹200.00")).toBeInTheDocument();
  });

  it("5.2 F6: switches to Income Tax Slabs tab and renders tax bracket rates", async () => {
    renderSetupPage("/payroll/setup?tab=tax_slabs");

    await waitFor(() => {
      expect(payrollApi.listTaxSlabs).toHaveBeenCalledWith("IN", "2026-2027", "new");
      expect(screen.getByText(/Income Tax Slabs/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/300,000\.01/i)).toBeInTheDocument();
    expect(screen.getByText("5.00%")).toBeInTheDocument();
  });

  it("5.1 F6: an edit sends back the edition it opened, so a stale save is refused", async () => {
    vi.mocked(payrollApi.getStructure).mockResolvedValue({
      id: "struct-1",
      name: "Engineering Standard Structure",
      country: "IN",
      level: "L1",
      is_active: true,
      version: 4,
      components: [
        {
          id: "comp-1",
          code: "BASIC",
          name: "Basic Pay",
          type: "earning",
          calculation_type: "percentage",
          value: "100.00",
          percentage_of: "ctc",
          is_taxable: true,
          is_statutory: false,
          display_order: 1,
        },
      ] as payrollApi.SalaryComponent[],
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      created_by_email: "hr@acme.com",
      updated_by_email: "hr@acme.com",
    });
    vi.mocked(payrollApi.updateStructure).mockResolvedValue({
      id: "struct-1",
      name: "Engineering Standard Structure",
      country: "IN",
      level: "L2",
      is_active: true,
      version: 5,
      components: [],
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-03-01T00:00:00Z",
      created_by_email: "hr@acme.com",
      updated_by_email: "hr@acme.com",
    });

    renderSetupPage();
    const editButtons = await screen.findAllByRole("button", { name: /^Edit$/i });
    fireEvent.click(editButtons[0]);

    await waitFor(() => {
      expect(payrollApi.getStructure).toHaveBeenCalledWith("struct-1");
    });

    fireEvent.click(await screen.findByRole("button", { name: /Save Changes/i }));

    await waitFor(() => {
      expect(payrollApi.updateStructure).toHaveBeenCalledWith(
        "struct-1",
        expect.objectContaining({ version: 4 })
      );
    });
  });

  it("5.1 F7: the structure list says who last changed each one", async () => {
    renderSetupPage();

    await waitFor(() => {
      expect(screen.getByText("Management Structure")).toBeInTheDocument();
    });
    expect(screen.getByText("owner@acme.com")).toBeInTheDocument();
  });
});
