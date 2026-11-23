import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { PerformanceReviewPage } from "../pages/PerformanceReviewPage";
import * as api from "../api";
import * as hrApi from "../../hr/api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("../api");
vi.mock("../../hr/api");

const mockManagerUser: AuthContextModule.CurrentUser = {
  id: "user-mgr-1",
  email: "manager@acme.com",
  role: "manager",
  company_id: "cmp-acme",
  is_active: true,
  must_change_password: false,
  employee: {
    id: "emp-mgr",
    employee_code: "EMP-MGR",
    first_name: "Boss",
    last_name: "Manager",
    department_id: "dept-1",
    position: "Engineering Manager",
  },
  permissions: [],
};

const mockEmployee = {
  id: "emp-1",
  first_name: "Alice",
  last_name: "Smith",
  employee_code: "EMP-001",
  position: "Senior Engineer",
  department_name: "Engineering",
} as any;

const mockActiveCycle: api.PerformanceCycle = {
  id: "cycle-1",
  name: "Q4 2026 Annual Cycle",
  cycle_type: "annual",
  start_date: "2026-10-01",
  end_date: "2026-12-31",
  status: "active",
  self_review_deadline: "2026-11-15",
  manager_review_deadline: "2026-12-01",
  created_at: "2026-09-15T00:00:00Z",
};

const mockGoals: api.PerformanceGoal[] = [
  {
    id: "goal-1",
    employee_id: "emp-1",
    cycle_id: "cycle-1",
    title: "Core Service Migration",
    description: "Migrate auth service to sync SQLAlchemy",
    weightage: "60.00",
    target_value: "100%",
    status: "in_progress",
    self_rating: "4.5",
    self_comments: "Migration successfully deployed",
    self_review_status: "submitted",
    created_at: "2026-10-02T00:00:00Z",
  },
  {
    id: "goal-2",
    employee_id: "emp-1",
    cycle_id: "cycle-1",
    title: "Mentorship & Reviews",
    description: "Conduct 15 PR reviews",
    weightage: "40.00",
    target_value: "15 PRs",
    status: "completed",
    self_rating: "4.0",
    self_comments: "Reviewed 18 PRs",
    self_review_status: "submitted",
    created_at: "2026-10-02T00:00:00Z",
  },
];

function renderComponent() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/performance/review/emp-1"]}>
        <Routes>
          <Route path="/performance/review/:employeeId" element={<PerformanceReviewPage />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>
  );
}

describe("PerformanceReviewPage (6.3 Manager Review & 6.5 Performance Summary)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: mockManagerUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });
    vi.mocked(hrApi.listEmployees).mockResolvedValue({
      items: [mockEmployee],
      total: 1,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });
    vi.mocked(hrApi.getEmployee).mockResolvedValue(mockEmployee);
    vi.mocked(api.listPerformanceCycles).mockResolvedValue({
      items: [mockActiveCycle],
      total: 1,
      page: 1,
      limit: 20,
      pages: 1,
      has_next: false,
    });
    vi.mocked(api.listPerformanceGoals).mockResolvedValue(mockGoals);
    vi.mocked(api.getPerformanceSummary).mockResolvedValue(null);
  });

  it("renders employee details and goals under review", async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getAllByText(/Alice Smith/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("Core Service Migration")).toBeInTheDocument();
      expect(screen.getByText("Mentorship & Reviews")).toBeInTheDocument();
    });
  });

  it("opens Manager Review modal and submits rating", async () => {
    vi.mocked(api.submitManagerReview).mockResolvedValue({
      id: "rev-mgr-1",
      goal_id: "goal-1",
      reviewer_id: "emp-mgr",
      reviewer_role: "manager",
      rating: "4.0",
      comments: "Outstanding work on migration",
      submitted_at: "2026-11-12T00:00:00Z",
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Core Service Migration")).toBeInTheDocument();
    });

    const reviewBtns = screen.getAllByRole("button", { name: "Rate Goal as Manager" });
    fireEvent.click(reviewBtns[0]);

    expect(screen.getByText(/Rate Goal: Core Service Migration/i)).toBeInTheDocument();

    const commentsInput = screen.getByPlaceholderText(/Feedback on employee's achievements/i);
    fireEvent.change(commentsInput, { target: { value: "Outstanding work on migration" } });

    const submitBtn = screen.getByRole("button", { name: "Save" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.submitManagerReview).toHaveBeenCalledWith(
        "goal-1",
        expect.objectContaining({ rating: "4.0", comments: "Outstanding work on migration" })
      );
    });
  });

  it("finalizes performance summary with rating and salary recommendation", async () => {
    vi.mocked(api.finalizePerformanceSummary).mockResolvedValue({
      id: "summary-1",
      employee_id: "emp-1",
      cycle_id: "cycle-1",
      final_rating: "4.30",
      overall_comments: "Exceeds expectations across quarters",
      salary_revision_recommended: true,
      recommended_increment_percent: "10.00",
      reviewed_by: "emp-mgr",
      finalized_at: "2026-11-12T00:00:00Z",
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Evaluation Summary")).toBeInTheDocument();
    });

    const finalizeBtn = screen.getByRole("button", { name: "Finalize Evaluation" });
    fireEvent.submit(finalizeBtn.closest("form")!);

    await waitFor(() => {
      expect(api.finalizePerformanceSummary).toHaveBeenCalledWith(
        "emp-1",
        expect.objectContaining({
          cycle_id: "cycle-1",
          salary_revision_recommended: true,
        })
      );
    });
  });

  it("labels draft self-evaluation as Draft and disables Rate Goal as Manager with reason (K1, K2)", async () => {
    const draftGoals: api.PerformanceGoal[] = [
      {
        id: "goal-draft",
        employee_id: "emp-1",
        cycle_id: "cycle-1",
        title: "Draft Goal Evaluation",
        description: "Incomplete self review",
        weightage: "50.00",
        target_value: "50%",
        status: "in_progress",
        self_rating: "4.5",
        self_comments: "Draft comments saved",
        self_review_status: "draft",
        created_at: "2026-10-02T00:00:00Z",
      },
    ];
    vi.mocked(api.listPerformanceGoals).mockResolvedValue(draftGoals);

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Draft Goal Evaluation")).toBeInTheDocument();
    });

    // K1: Badge should show Draft
    expect(screen.getByText("Draft")).toBeInTheDocument();

    // K2: Button disabled and explanation shown before manager types anything
    const rateBtn = screen.getByRole("button", { name: "Rate Goal as Manager" });
    expect(rateBtn).toBeDisabled();
    expect(
      screen.getByText("Employee must submit their self-review before manager review can be submitted.")
    ).toBeInTheDocument();
  });

  it("removes signed-in user from the Select Team Member dropdown (K3)", async () => {
    const employeesList = [
      mockEmployee,
      {
        id: "emp-mgr",
        first_name: "Boss",
        last_name: "Manager",
        employee_code: "EMP-MGR",
        position: "Engineering Manager",
        department_name: "Engineering",
      } as any,
    ];
    vi.mocked(hrApi.listEmployees).mockResolvedValue({
      items: employeesList,
      total: 2,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/Select Team Member:/i)).toBeInTheDocument();
    });

    // Signed in user is emp-mgr ("Boss Manager")
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent(/Alice Smith/);
    expect(screen.queryByText(/Boss Manager/i)).not.toBeInTheDocument();
  });
});
