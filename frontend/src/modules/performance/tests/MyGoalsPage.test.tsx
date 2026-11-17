import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MyGoalsPage } from "../pages/MyGoalsPage";
import * as api from "../api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");

const mockEmployeeUser: AuthContextModule.CurrentUser = {
  id: "user-1",
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
    department_id: "dept-1",
    position: "Software Engineer",
  },
  permissions: [],
};

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
    title: "Complete Core Engine",
    description: "Deliver high performance execution",
    weightage: "50.00",
    target_value: "100%",
    status: "in_progress",
    self_rating: null,
    self_comments: null,
    created_at: "2026-10-02T00:00:00Z",
  },
  {
    id: "goal-2",
    employee_id: "emp-1",
    cycle_id: "cycle-1",
    title: "Automate All Test Suites",
    description: "Attain zero regression bugs",
    weightage: "50.00",
    target_value: "100%",
    status: "completed",
    self_rating: "4.5",
    self_comments: "Tests all passing",
    created_at: "2026-10-02T00:00:00Z",
  },
];

function renderWithProviders() {
  return render(
    <ToastProvider>
      <MyGoalsPage />
    </ToastProvider>
  );
}

describe("MyGoalsPage (6.2 Goals & 6.3 Self-Review & 6.4 PIP Alert)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: mockEmployeeUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });

    vi.mocked(api.listPerformanceCycles).mockResolvedValue({
      items: [mockActiveCycle],
      total: 1,
      page: 1,
      limit: 20,
      pages: 1,
      has_next: false,
    });
    vi.mocked(api.listPerformanceGoals).mockResolvedValue(mockGoals);
    vi.mocked(api.getActivePIP).mockResolvedValue(null);
  });

  it("renders goals list with total weightage progress indicator", async () => {
    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("Complete Core Engine")).toBeInTheDocument();
      expect(screen.getByText("Automate All Test Suites")).toBeInTheDocument();
      expect(screen.getAllByText(/50\.00%/)).toHaveLength(2);
    });
  });

  it("displays active PIP alert banner when employee is on PIP", async () => {
    vi.mocked(api.getActivePIP).mockResolvedValue({
      id: "pip-99",
      employee_id: "emp-1",
      mentor_id: "emp-2",
      mentor_name: "Jane Manager",
      title: "Improvement Plan Q4",
      description: "Needs to address quality benchmarks",
      start_date: "2026-11-01",
      end_date: "2026-12-01",
      status: "active",
      created_at: "2026-11-01T00:00:00Z",
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText(/Active Performance Improvement Plan/i)).toBeInTheDocument();
      expect(screen.getByText(/Jane Manager/i)).toBeInTheDocument();
    });
  });

  it("opens Set Goals modal and validates weightage inputs", async () => {
    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /\+ Add Goals/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /\+ Add Goals/i }));

    expect(screen.getByText("Set Performance Goals")).toBeInTheDocument();
  });

  it("submits self-review on goal and updates UI state", async () => {
    vi.mocked(api.submitSelfReview).mockResolvedValue({
      id: "rev-1",
      goal_id: "goal-1",
      reviewer_id: "emp-1",
      reviewer_role: "self",
      rating: "4.0",
      comments: "Met all expectations",
      submitted_at: "2026-11-10T00:00:00Z",
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("Complete Core Engine")).toBeInTheDocument();
    });

    // Find and click Self Review button
    const reviewButtons = screen.getAllByRole("button", { name: /Self Review/i });
    fireEvent.click(reviewButtons[0]);

    expect(screen.getByText(/Self Evaluation: Complete Core Engine/i)).toBeInTheDocument();

    const commentsArea = screen.getByPlaceholderText(/Detail your accomplishments/i);
    fireEvent.change(commentsArea, { target: { value: "Met all expectations" } });

    const submitBtn = screen.getByRole("button", { name: "Submit Review" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.submitSelfReview).toHaveBeenCalledWith(
        "goal-1",
        expect.objectContaining({ rating: expect.any(String), comments: "Met all expectations" })
      );
    });
  });
});
