import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ShiftsPage } from "../pages/ShiftsPage";
import * as timeLeaveApi from "../api";
import * as hrApi from "../../hr/api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");
vi.mock("../../hr/api");

const mockShifts: timeLeaveApi.Shift[] = [
  {
    id: "shift-1",
    name: "General Day Shift",
    start_time: "09:00:00",
    end_time: "18:00:00",
    break_minutes: 60,
    night_allowance: "0.00",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "shift-2",
    name: "Night Owls",
    start_time: "22:00:00",
    end_time: "06:00:00",
    break_minutes: 45,
    night_allowance: "500.00",
    is_active: true,
    created_at: "2026-01-02T00:00:00Z",
  },
];

const mockAssignedShift: timeLeaveApi.AssignedShiftDetail = {
  shift: mockShifts[0],
  effective_from: "2026-01-01",
  effective_to: null,
};

const mockEmployees = {
  items: [
    { id: "emp-1", first_name: "John", last_name: "Doe", department_id: "dept-1" },
    { id: "emp-2", first_name: "Jane", last_name: "Smith", department_id: "dept-2" },
  ],
  total: 2,
  page: 1,
  limit: 100,
  pages: 1,
  has_next: false,
};

const mockDepartments = {
  items: [
    { id: "dept-1", name: "Engineering" },
    { id: "dept-2", name: "Human Resources" },
  ],
  total: 2,
  page: 1,
  limit: 100,
  pages: 1,
  has_next: false,
};

function renderWithProviders(userRole: any = "hr_admin", hasEmployee = true) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });

  const user = {
    id: "usr-1",
    company_id: "cmp-1",
    email: "user@example.com",
    role: userRole,
    employee: hasEmployee
      ? {
          id: "emp-1",
          employee_code: "EMP-001",
          first_name: "John",
          last_name: "Doe",
          company_id: "cmp-1",
          designation: "Developer",
          department_id: "dept-1",
        }
      : null,
  } as any;

  vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
    status: "authenticated",
    user,
    login: vi.fn(),
    logout: vi.fn(),
    establishSession: vi.fn(),
    sessionExpired: false,
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ShiftsPage />
      </ToastProvider>
    </QueryClientProvider>
  );
}

describe("Sub-feature 4.1: Shifts Frontend (ShiftsPage)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(timeLeaveApi.listShifts).mockResolvedValue({
      items: mockShifts,
      total: 2,
      page: 1,
      limit: 10,
      pages: 1,
      has_next: false,
    });
    vi.mocked(timeLeaveApi.getAssignedShift).mockResolvedValue(mockAssignedShift);
    vi.mocked(hrApi.listEmployees).mockResolvedValue(mockEmployees as any);
    vi.mocked(hrApi.listDepartments).mockResolvedValue(mockDepartments as any);
  });

  it("renders shifts list and management tabs for HR admin", async () => {
    renderWithProviders("hr_admin", true);

    expect(screen.getByText("Shift Schedule")).toBeInTheDocument();
    expect(screen.getByText("+ New shift")).toBeInTheDocument();
    expect(screen.getByText("🏢 Company Shift Management")).toBeInTheDocument();
    expect(screen.getByText("📅 My Weekly Shift Schedule")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("General Day Shift")).toBeInTheDocument();
      expect(screen.getByText("Night Owls")).toBeInTheDocument();
    });
  });

  it("hides HR management tools and '+ New shift' button for regular employee", async () => {
    renderWithProviders("employee", true);

    expect(screen.getByText("Shift Schedule")).toBeInTheDocument();
    expect(screen.queryByText("+ New shift")).not.toBeInTheDocument();
    expect(screen.queryByText("🏢 Company Shift Management")).not.toBeInTheDocument();

    // Regular employee sees their own weekly shift schedule
    await waitFor(() => {
      expect(screen.getByText(/Assigned Shift:/)).toBeInTheDocument();
      expect(screen.getByText("General Day Shift")).toBeInTheDocument();
    });
  });

  it("creates a new shift when HR fills the shift form", async () => {
    vi.mocked(timeLeaveApi.createShift).mockResolvedValue({
      id: "shift-3",
      name: "Evening Shift",
      start_time: "16:00:00",
      end_time: "00:00:00",
      break_minutes: 30,
      night_allowance: "100.00",
      is_active: true,
      created_at: "2026-01-03T00:00:00Z",
    });

    renderWithProviders("hr_admin", true);

    await waitFor(() => {
      expect(screen.getByText("+ New shift")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("+ New shift"));

    expect(screen.getByText("Create shift")).toBeInTheDocument();

    const form = screen.getByText("Create shift").closest("form")!;
    const nameInput = form.querySelector("input")!;
    fireEvent.change(nameInput, { target: { value: "Evening Shift" } });

    fireEvent.click(screen.getByText("Create shift"));

    await waitFor(() => {
      expect(timeLeaveApi.createShift).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Evening Shift",
        })
      );
    });
  });

  it("opens assign dialog and allows assigning shift to employee", async () => {
    vi.mocked(timeLeaveApi.assignShift).mockResolvedValue({
      id: "assign-1",
      shift_id: "shift-1",
      employee_id: "emp-1",
      effective_from: "2026-02-01",
      effective_to: null,
    });

    renderWithProviders("hr_admin", true);

    await waitFor(() => {
      expect(screen.getByText("General Day Shift")).toBeInTheDocument();
    });

    const assignButtons = screen.getAllByText("Assign");
    fireEvent.click(assignButtons[0]);

    await waitFor(() => {
      expect(screen.getByText(/Assign "General Day Shift" Shift/)).toBeInTheDocument();
    });

    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "emp-1" } });

    fireEvent.click(screen.getByText("Confirm & Assign"));

    await waitFor(() => {
      expect(timeLeaveApi.assignShift).toHaveBeenCalledWith(
        "shift-1",
        expect.objectContaining({
          employee_id: "emp-1",
        })
      );
    });
  });

  it("handles shift deletion confirmation", async () => {
    vi.mocked(timeLeaveApi.deleteShift).mockResolvedValue();

    renderWithProviders("hr_admin", true);

    await waitFor(() => {
      expect(screen.getByText("Night Owls")).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByText("Delete");
    fireEvent.click(deleteButtons[1]); // Night Owls delete

    await waitFor(() => {
      expect(screen.getByText("Delete shift?")).toBeInTheDocument();
    });

    const modal = screen.getByRole("dialog");
    const confirmBtn = modal.querySelector(".btn-danger")!;
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(timeLeaveApi.deleteShift).toHaveBeenCalledWith("shift-2");
    });
  });
});
