import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { PerformanceCyclesPage } from "../pages/PerformanceCyclesPage";
import * as api from "../api";
import * as hrApi from "../../hr/api";
import { ToastProvider } from "../../../app/toast-context";

import * as AuthContextModule from "../../../app/auth-context";

vi.mock("../api");
vi.mock("../../hr/api");

const mockCycles: api.PerformanceCycle[] = [
  {
    id: "cycle-1",
    name: "Q4 2026 Annual Cycle",
    cycle_type: "annual",
    start_date: "2026-10-01",
    end_date: "2026-12-31",
    status: "active",
    self_review_deadline: "2026-11-15",
    manager_review_deadline: "2026-12-01",
    created_at: "2026-09-15T00:00:00Z",
  },
  {
    id: "cycle-2",
    name: "Q1 2027 Upcoming",
    cycle_type: "quarterly",
    start_date: "2027-01-01",
    end_date: "2027-03-31",
    status: "draft",
    self_review_deadline: null,
    manager_review_deadline: null,
    created_at: "2026-11-01T00:00:00Z",
  },
];

const mockReport: api.PerformanceReport = {
  active_cycle: mockCycles[0],
  total_employees: 50,
  completed_reviews: 35,
  completion_rate_percent: "70.00",
  rating_distribution: { "3": 10, "4": 20, "5": 5 },
};

const mockPips: api.PerformancePIP[] = [
  {
    id: "pip-1",
    employee_id: "emp-1",
    employee_name: "Alice Smith",
    employee_code: "EMP-001",
    mentor_id: "emp-2",
    mentor_name: "Bob Jones",
    title: "Engineering PIP",
    description: "Improve code quality and delivery",
    milestones_kpis: "Close 5 bug tickets weekly",
    start_date: "2026-11-01",
    end_date: "2026-12-01",
    status: "active",
    created_at: "2026-11-01T00:00:00Z",
  },
];

function renderComponent() {
  return render(
    <ToastProvider>
      <PerformanceCyclesPage />
    </ToastProvider>
  );
}

const mockHrUser: AuthContextModule.CurrentUser = {
  id: "usr-hr-1",
  email: "hr@acme.com",
  role: "hr_admin",
  company_id: "cmp-acme",
  is_active: true,
  must_change_password: false,
  employee: null,
  permissions: [],
};

function stubAuth(role: "hr_admin" | "manager") {
  vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
    status: "authenticated",
    user: { ...mockHrUser, role },
    login: vi.fn(),
    establishSession: vi.fn(),
    logout: vi.fn(),
    sessionExpired: false,
  });
}

describe("PerformanceCyclesPage (6.1 Appraisal Cycles & 6.4 PIPs)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubAuth("hr_admin");
    vi.mocked(api.listPerformanceCycles).mockResolvedValue({
      items: mockCycles,
      total: 2,
      page: 1,
      limit: 20,
      pages: 1,
      has_next: false,
    });
    vi.mocked(api.getPerformanceReport).mockResolvedValue(mockReport);
    vi.mocked(api.listPIPs).mockResolvedValue(mockPips);
    vi.mocked(hrApi.listEmployees).mockResolvedValue({
      items: [
        { id: "emp-1", full_name: "Alice Smith", employee_code: "EMP-001", is_active: true } as any,
        { id: "emp-2", full_name: "Bob Jones", employee_code: "EMP-002", is_active: true } as any,
      ],
      total: 2,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });
  });

  it("renders cycle list and performance report card", async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Q4 2026 Annual Cycle")).toBeInTheDocument();
      expect(screen.getByText("Q1 2027 Upcoming")).toBeInTheDocument();
      expect(screen.getByText(/70\.00%/)).toBeInTheDocument();
    });
  });

  it("filters cycle list by clicking report summary stat", async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Q4 2026 Annual Cycle")).toBeInTheDocument();
    });

    const activeFilterBox = screen.getByTitle("Filter by active cycles");
    fireEvent.click(activeFilterBox);

    expect(screen.getByText("Q4 2026 Annual Cycle")).toBeInTheDocument();
    expect(screen.queryByText("Q1 2027 Upcoming")).not.toBeInTheDocument();
  });

  it("activates a draft cycle and handles transition", async () => {
    vi.mocked(api.updatePerformanceCycle).mockResolvedValue({
      ...mockCycles[1],
      status: "active",
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Q1 2027 Upcoming")).toBeInTheDocument();
    });

    const activateBtn = screen.getByRole("button", { name: "Activate" });
    fireEvent.click(activateBtn);

    await waitFor(() => {
      expect(api.updatePerformanceCycle).toHaveBeenCalledWith("cycle-2", "active");
    });
  });

  it("opens cycle creation modal and validates inputs", async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /\+ Create Cycle/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /\+ Create Cycle/i }));

    expect(screen.getByText("Create Performance Cycle")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/FY 2026–27 Annual Review/i)).toBeInTheDocument();
  });

  it("switches to PIP tab, renders PIP list and displays active PIP records", async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/^⚠️ Performance Improvement Plans \(PIP\)$/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/^⚠️ Performance Improvement Plans \(PIP\)$/i));

    await waitFor(() => {
      expect(screen.getByText("Engineering PIP")).toBeInTheDocument();
      expect(screen.getByText("Alice Smith")).toBeInTheDocument();
    });
  });

  it("opens evaluate PIP modal and allows submitting outcome", async () => {
    vi.mocked(api.evaluatePIP).mockResolvedValue({
      ...mockPips[0],
      status: "passed",
      outcome_notes: "Demonstrated clear improvement",
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/^⚠️ Performance Improvement Plans \(PIP\)$/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/^⚠️ Performance Improvement Plans \(PIP\)$/i));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Evaluate Outcome" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Evaluate Outcome" }));

    expect(screen.getByText(/Evaluate PIP:/i)).toBeInTheDocument();

    // Fill required evaluation notes
    const notesInput = screen.getByPlaceholderText(/Detail observations, mentor recommendations/i);
    fireEvent.change(notesInput, { target: { value: "Demonstrated clear improvement" } });

    const submitBtn = screen.getByRole("button", { name: "Submit PIP Evaluation" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.evaluatePIP).toHaveBeenCalledWith(
        "pip-1",
        expect.objectContaining({ outcome: "passed", outcome_notes: "Demonstrated clear improvement" })
      );
    });
  });

  it("6.4 F5: a draft PIP offers Activate and is never described as concluded", async () => {
    vi.mocked(api.listPIPs).mockResolvedValue([
      { ...mockPips[0], id: "pip-draft", status: "draft" },
    ]);
    vi.mocked(api.activatePIP).mockResolvedValue({
      ...mockPips[0],
      id: "pip-draft",
      status: "active",
    });

    renderComponent();
    fireEvent.click(await screen.findByRole("button", { name: /Performance Improvement Plans/i }));

    const activateBtn = await screen.findByRole("button", { name: /^Activate$/i });
    expect(screen.queryByText(/Concluded/i)).not.toBeInTheDocument();

    fireEvent.click(activateBtn);
    await waitFor(() => {
      expect(api.activatePIP).toHaveBeenCalledWith("pip-draft");
    });
  });

  it("6.5 F1: a manager sees the PIP tab and no appraisal cycles tab", async () => {
    stubAuth("manager");
    renderComponent();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Performance Improvement Plans/i })).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: /Appraisal Cycles/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /\+ Create Cycle/i })).not.toBeInTheDocument();
  });

  it("F1: failed PIP displays 'Awaiting HR decision'", async () => {
    vi.mocked(api.listPIPs).mockResolvedValue([
      { ...mockPips[0], id: "pip-failed-1", status: "failed" },
    ]);
    renderComponent();
    fireEvent.click(await screen.findByRole("button", { name: /Performance Improvement Plans/i }));

    await waitFor(() => {
      expect(screen.getByText("Awaiting HR decision")).toBeInTheDocument();
    });
  });

  it("F2: Separations pending decision tab shows failed PIP and allows confirming separation", async () => {
    vi.mocked(api.listPIPs).mockResolvedValue([
      {
        ...mockPips[0],
        id: "pip-failed-2",
        status: "failed",
        evaluated_by: "mgr-1",
        evaluated_at: "2026-11-20T10:00:00Z",
      },
    ]);
    vi.mocked(api.decidePIPSeparation).mockResolvedValue({
      id: "dec-1",
      pip_id: "pip-failed-2",
      decision: "separate",
      decided_by: "hr-1",
      decided_at: "2026-11-21T10:00:00Z",
      last_working_date: "2026-12-01",
      notice_choice: "served",
      notes: null,
    });

    renderComponent();

    const pendingTab = await screen.findByRole("button", { name: /Separations pending decision/i });
    fireEvent.click(pendingTab);

    expect(await screen.findByText("Failed PIP Records Requiring Action")).toBeInTheDocument();
    expect(screen.getByText("Alice Smith")).toBeInTheDocument();

    const separateBtn = screen.getByRole("button", { name: /^Separate$/i });
    fireEvent.click(separateBtn);

    expect(screen.getByText(/Confirm Separation: Alice Smith/i)).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: /Confirm Separate/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(api.decidePIPSeparation).toHaveBeenCalledWith(
        "pip-failed-2",
        expect.objectContaining({
          decision: "separate",
          notice_choice: "served",
        })
      );
    });
  });
});
