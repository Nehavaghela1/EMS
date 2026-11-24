import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PerformanceSummariesPage } from "../pages/PerformanceSummariesPage";
import * as PerformanceApi from "../api";
import * as HrApi from "../../hr/api";

vi.mock("../api", async () => {
  const actual = await vi.importActual("../api");
  return {
    ...actual,
    listPerformanceCycles: vi.fn(),
    listPerformanceSummaries: vi.fn(),
  };
});

vi.mock("../../hr/api", async () => {
  const actual = await vi.importActual("../../hr/api");
  return {
    ...actual,
    listEmployees: vi.fn(),
  };
});

describe("PerformanceSummariesPage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.clearAllMocks();
  });

  const renderComponent = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <PerformanceSummariesPage />
        </BrowserRouter>
      </QueryClientProvider>
    );

  it("renders page header, cycle selector, rating distribution and summaries table", async () => {
    vi.mocked(PerformanceApi.listPerformanceCycles).mockResolvedValue({
      items: [
        {
          id: "cycle-1",
          name: "Annual Review 2026",
          cycle_type: "annual",
          start_date: "2026-01-01",
          end_date: "2026-12-31",
          status: "active",
          self_review_deadline: null,
          manager_review_deadline: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      limit: 50,
      pages: 1,
    } as any);

    vi.mocked(HrApi.listEmployees).mockResolvedValue({
      items: [
        {
          id: "emp-1",
          first_name: "Alice",
          last_name: "Smith",
          email: "alice@example.com",
          employee_code: "EMP001",
          is_active: true,
        },
        {
          id: "emp-2",
          first_name: "Bob",
          last_name: "Jones",
          email: "bob@example.com",
          employee_code: "EMP002",
          is_active: true,
        },
      ],
      total: 2,
      page: 1,
      limit: 100,
      pages: 1,
    } as any);

    vi.mocked(PerformanceApi.listPerformanceSummaries).mockResolvedValue({
      items: [
        {
          id: "summ-1",
          employee_id: "emp-1",
          employee_name: "Alice Smith",
          employee_code: "EMP001",
          cycle_id: "cycle-1",
          final_rating: "4.5",
          overall_comments: "Exceeded expectations",
          salary_revision_recommended: true,
          recommended_increment_percent: "12.50",
          reviewed_by: "user-mgr-1",
          reviewed_by_name: "Jane Manager",
          finalized_at: "2026-11-20T10:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      limit: 100,
      pages: 1,
      has_next: false,
    });

    renderComponent();

    expect(screen.getByText("Performance Summaries")).toBeInTheDocument();
    expect(screen.getByText("Rating Distribution")).toBeInTheDocument();
    expect(screen.getByText("Increment Recommendations")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Alice Smith")).toBeInTheDocument();
      expect(screen.getByText("Bob Jones")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("★ 4.5")).toBeInTheDocument();
      expect(screen.getByText("+12.5%")).toBeInTheDocument();
      expect(screen.getByText("Jane Manager")).toBeInTheDocument();
      expect(screen.getAllByText("Pending").length).toBeGreaterThan(0);
    });
  });
});
