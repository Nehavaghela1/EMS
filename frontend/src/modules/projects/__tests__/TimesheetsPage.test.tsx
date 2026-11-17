import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { TimesheetsPage } from "../pages/TimesheetsPage";
import * as api from "../api";
import type { TimeEntry, Project } from "../types";
import * as hrApi from "../../hr/api";
import { ToastProvider } from "../../../app/toast-context";
import { TimerProvider } from "../../../app/timer-context";
import * as AuthContextModule from "../../../app/auth-context";

vi.mock("../api");
vi.mock("../../hr/api");

const mockTimeEntries: TimeEntry[] = [
  {
    id: "te-1",
    company_id: "comp-1",
    project_id: "proj-1",
    project_name: "Enterprise ERP System",
    project_code: "ERP-001",
    employee_id: "emp-1",
    employee_name: "Alice Smith",
    employee_code: "EMP-001",
    date: "2026-11-16",
    hours: 7.5,
    description: "Built API endpoints for timesheets",
    is_billable: true,
    status: "submitted",
    created_at: "2026-11-16T18:00:00Z",
    updated_at: "2026-11-16T18:00:00Z",
  },
  {
    id: "te-2",
    company_id: "comp-1",
    project_id: "proj-1",
    project_name: "Enterprise ERP System",
    project_code: "ERP-001",
    employee_id: "emp-2",
    employee_name: "Bob Jones",
    employee_code: "EMP-002",
    date: "2026-11-16",
    hours: 4.0,
    description: "Database schema migration",
    is_billable: false,
    status: "approved",
    approved_by: "emp-mgr",
    created_at: "2026-11-16T17:00:00Z",
    updated_at: "2026-11-16T19:00:00Z",
  },
];

const mockProjects: Project[] = [
  {
    id: "proj-1",
    company_id: "comp-1",
    name: "Enterprise ERP System",
    code: "ERP-001",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

function setupAuth(userRole = "hr_admin") {
  vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
    status: "authenticated",
    user: {
      id: "u-1",
      email: "admin@company.com",
      role: userRole as any,
      company_id: "comp-1",
      is_active: true,
      must_change_password: false,
      permissions: [],
      employee: {
        id: "emp-1",
        employee_code: "EMP-001",
        first_name: "Admin",
        last_name: "User",
        department_id: null,
        position: null,
      },
    },
    login: vi.fn(),
    establishSession: vi.fn(),
    logout: vi.fn(),
    sessionExpired: false,
  });
}

function renderComponent() {
  return render(
    <ToastProvider>
      <TimerProvider>
        <MemoryRouter>
          <TimesheetsPage />
        </MemoryRouter>
      </TimerProvider>
    </ToastProvider>
  );
}

describe("TimesheetsPage (Module 7.5 Time Tracking & Approvals)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchTimeEntries).mockResolvedValue(mockTimeEntries);
    vi.mocked(api.fetchProjects).mockResolvedValue(mockProjects);
    vi.mocked(api.fetchTasks).mockResolvedValue([]);
    vi.mocked(hrApi.listEmployees).mockResolvedValue({ items: [], total: 0, page: 1, limit: 100, pages: 1 } as any);
  });

  it("renders timesheets and entries correctly", async () => {
    setupAuth("hr_admin");
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Built API endpoints for timesheets")).toBeInTheDocument();
      expect(screen.getByText("Database schema migration")).toBeInTheDocument();
    });
  });

  it("switches to approvals tab for manager/hr_admin", async () => {
    setupAuth("manager");
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/Approvals Queue/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Approvals Queue/i));

    await waitFor(() => {
      expect(screen.getByText("Alice Smith")).toBeInTheDocument();
      expect(screen.getByText("Bob Jones")).toBeInTheDocument();
    });
  });

  it("approves pending timesheet entry", async () => {
    vi.mocked(api.approveRejectTimeEntry).mockResolvedValue({
      ...mockTimeEntries[0],
      status: "approved",
    });

    setupAuth("manager");
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/Approvals Queue/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Approvals Queue/i));

    await waitFor(() => {
      expect(screen.getByText("✓ Approve")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("✓ Approve"));

    await waitFor(() => {
      expect(api.approveRejectTimeEntry).toHaveBeenCalledWith("te-1", "approved", undefined);
    });
  });

  it("rejects pending timesheet entry with required reason", async () => {
    vi.mocked(api.approveRejectTimeEntry).mockResolvedValue({
      ...mockTimeEntries[0],
      status: "rejected",
      rejection_reason: "Hours mismatch with attendance",
    });

    setupAuth("manager");
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/Approvals Queue/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Approvals Queue/i));

    await waitFor(() => {
      expect(screen.getByText("✕ Reject")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("✕ Reject"));

    expect(screen.getByText("Reject Time Entry")).toBeInTheDocument();

    const reasonInput = screen.getByPlaceholderText(/Explain why this time entry is being rejected/i);
    fireEvent.change(reasonInput, { target: { value: "Hours mismatch with attendance" } });

    fireEvent.click(screen.getByRole("button", { name: "❌ Confirm Reject" }));

    await waitFor(() => {
      expect(api.approveRejectTimeEntry).toHaveBeenCalledWith(
        "te-1",
        "rejected",
        "Hours mismatch with attendance"
      );
    });
  });
});
