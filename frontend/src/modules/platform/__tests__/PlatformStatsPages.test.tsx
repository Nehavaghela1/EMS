import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PlatformHealthPage } from "../pages/PlatformHealthPage";
import { PlatformPayrollPage } from "../pages/PlatformPayrollPage";
import { PlatformActivityPage } from "../pages/PlatformActivityPage";
import * as PlatformApi from "../api";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    fetchPlatformHealth: vi.fn(),
    listPlatformPayrollStats: vi.fn(),
    listPlatformActivityStats: vi.fn(),
  };
});

const healthyPlatform: PlatformApi.PlatformHealth = {
  jobs_by_status: { queued: 0, started: 0, success: 12, failure: 0 },
  job_failures_last_24h: 0,
  rate_drafts_awaiting_verification: 0,
  next_scheduled_rate_checks: {},
  storage_bytes_by_company: { "cmp-1": 2_097_152 },
  notification_backlog: 4,
};

function page(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

/** A month key the page will actually ask for: the current month. */
function thisMonth(): { year: number; month: number } {
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth() + 1 };
}

function lastMonth(): { year: number; month: number } {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return { year: d.getFullYear(), month: d.getMonth() + 1 };
}

describe("Super admin platform statistics pages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Health", () => {
    it("P1: says all clear when nothing is over its threshold", async () => {
      vi.mocked(PlatformApi.fetchPlatformHealth).mockResolvedValue(healthyPlatform);
      page(<PlatformHealthPage />);

      await waitFor(() => {
        expect(screen.getByText(/All clear/i)).toBeInTheDocument();
      });
      expect(screen.queryByText(/need attention/i)).not.toBeInTheDocument();
    });

    it("P2: names what is wrong when a job has failed", async () => {
      vi.mocked(PlatformApi.fetchPlatformHealth).mockResolvedValue({
        ...healthyPlatform,
        job_failures_last_24h: 3,
      });
      page(<PlatformHealthPage />);

      await waitFor(() => {
        expect(screen.getByText(/1 thing needs attention/i)).toBeInTheDocument();
      });
      expect(screen.getAllByText(/Job failures \(24h\)/i).length).toBeGreaterThan(0);
    });

    it("P3: shows storage in human units, not raw bytes", async () => {
      vi.mocked(PlatformApi.fetchPlatformHealth).mockResolvedValue(healthyPlatform);
      page(<PlatformHealthPage />);

      await waitFor(() => {
        expect(document.body.textContent).toContain("2 MB");
      });
      expect(document.body.textContent).not.toContain("2097152");
    });

    it("P4: offers a retry when the API fails rather than an empty page", async () => {
      vi.mocked(PlatformApi.fetchPlatformHealth).mockRejectedValue(new Error("boom"));
      page(<PlatformHealthPage />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
      });
    });
  });

  describe("Payroll", () => {
    it("P5: totals net paid across companies for the month", async () => {
      const m = thisMonth();
      vi.mocked(PlatformApi.listPlatformPayrollStats).mockResolvedValue({
        items: [
          {
            company_id: "cmp-1",
            company_name: "NexusPay Fintech",
            company_code: "NEXUSPAY",
            year: m.year,
            month: m.month,
            runs_by_status: { paid: 1 },
            total_employees_in_run: 5,
            total_net_paid: "405000.00",
            total_employer_cost: "470000.00",
            total_statutory_contributions: "65000.00",
          },
          {
            company_id: "cmp-2",
            company_name: "Acme Ltd",
            company_code: "ACME",
            year: m.year,
            month: m.month,
            runs_by_status: { paid: 1 },
            total_employees_in_run: 2,
            total_net_paid: "95000.00",
            total_employer_cost: "110000.00",
            total_statutory_contributions: "15000.00",
          },
        ],
        total: 2,
        page: 1,
        limit: 100,
        pages: 1,
        has_next: false,
      });

      page(<PlatformPayrollPage />);

      // 405,000 + 95,000 across both companies.
      await waitFor(() => {
        expect(screen.getAllByText("₹5,00,000").length).toBeGreaterThan(0);
      });
      expect(screen.getByText("NexusPay Fintech")).toBeInTheDocument();
    });

    it("P6: shows the change against last month", async () => {
      const m = thisMonth();
      const prev = lastMonth();
      vi.mocked(PlatformApi.listPlatformPayrollStats).mockResolvedValue({
        items: [
          {
            company_id: "cmp-1", company_name: "NexusPay", company_code: "NEX",
            year: prev.year, month: prev.month, runs_by_status: { paid: 1 },
            total_employees_in_run: 5, total_net_paid: "100000.00",
            total_employer_cost: "0.00", total_statutory_contributions: "0.00",
          },
          {
            company_id: "cmp-1", company_name: "NexusPay", company_code: "NEX",
            year: m.year, month: m.month, runs_by_status: { paid: 1 },
            total_employees_in_run: 5, total_net_paid: "150000.00",
            total_employer_cost: "0.00", total_statutory_contributions: "0.00",
          },
        ],
        total: 2, page: 1, limit: 100, pages: 1, has_next: false,
      });

      page(<PlatformPayrollPage />);

      await waitFor(() => {
        expect(screen.getByText(/50\.0% on last month/)).toBeInTheDocument();
      });
    });

    it("P7: says so plainly when no payroll has run anywhere", async () => {
      vi.mocked(PlatformApi.listPlatformPayrollStats).mockResolvedValue({
        items: [], total: 0, page: 1, limit: 100, pages: 0, has_next: false,
      });
      page(<PlatformPayrollPage />);

      await waitFor(() => {
        expect(screen.getByText(/No payroll has been run yet/i)).toBeInTheDocument();
      });
    });
  });

  describe("Activity", () => {
    const activity: PlatformApi.CompanyActivityStats[] = [
      {
        company_id: "cmp-busy", company_name: "Busy Co", company_code: "BUSY",
        punch_count: 120, leave_requests_by_status: { pending: 2, approved: 5 },
        pending_approvals: 2, pending_regularizations: 1, active_projects: 3,
        approved_hours_logged: "88.50",
      },
      {
        company_id: "cmp-idle", company_name: "Dormant Co", company_code: "DORM",
        punch_count: 0, leave_requests_by_status: {}, pending_approvals: 0,
        pending_regularizations: 0, active_projects: 0, approved_hours_logged: "0.00",
      },
    ];

    it("P8: counts the companies doing nothing at all", async () => {
      vi.mocked(PlatformApi.listPlatformActivityStats).mockResolvedValue({
        items: activity, total: 2, page: 1, limit: 100, pages: 1, has_next: false,
      });
      page(<PlatformActivityPage />);

      await waitFor(() => {
        expect(screen.getByText(/No activity at all/i)).toBeInTheDocument();
      });
      expect(screen.getByText(/Signed up but not using it/i)).toBeInTheDocument();
      expect(screen.getAllByText(/no activity/i).length).toBeGreaterThan(0);
    });

    it("P9: defaults to the quietest company first, and can flip to busiest", async () => {
      vi.mocked(PlatformApi.listPlatformActivityStats).mockResolvedValue({
        items: activity, total: 2, page: 1, limit: 100, pages: 1, has_next: false,
      });
      page(<PlatformActivityPage />);

      await waitFor(() => {
        expect(screen.getByText("Dormant Co")).toBeInTheDocument();
      });
      const firstRow = () => document.querySelectorAll("tbody tr")[0]?.textContent ?? "";
      expect(firstRow()).toContain("Dormant Co");

      await userEvent.click(screen.getByRole("button", { name: /Busiest first/i }));
      await waitFor(() => {
        expect(firstRow()).toContain("Busy Co");
      });
    });
  });
});
