import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { PerformanceReviewPage } from "../pages/PerformanceReviewPage";
import * as api from "../api";
import * as hrApi from "../../hr/api";
import { ToastProvider } from "../../../app/toast-context";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("../api");
vi.mock("../../hr/api");

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
});
