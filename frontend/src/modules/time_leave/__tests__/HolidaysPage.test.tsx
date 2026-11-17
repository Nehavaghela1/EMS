import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HolidaysPage } from "../pages/HolidaysPage";
import * as timeLeaveApi from "../api";
import * as identityApi from "../../identity/api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";

vi.mock("../api");
vi.mock("../../identity/api");

const mockHolidays: timeLeaveApi.Holiday[] = [
  {
    id: "hol-1",
    name: "Republic Day",
    date: "2026-01-26",
    is_optional: false,
    applies_to_department_id: null,
  },
  {
    id: "hol-2",
    name: "Independence Day",
    date: "2026-08-15",
    is_optional: false,
    applies_to_department_id: null,
  },
  {
    id: "hol-3",
    name: "Diwali",
    date: "2026-11-08",
    is_optional: true,
    applies_to_department_id: null,
  },
  {
    id: "hol-4",
    name: "Christmas",
    date: "2026-12-25",
    is_optional: false,
    applies_to_department_id: null,
  },
];

const mockRegions: Record<string, timeLeaveApi.CountryRegionInfo> = {
  IN: {
    name: "India",
    states: ["Gujarat", "Maharashtra", "Karnataka", "Delhi"],
  },
};

const mockRegionalPreview: timeLeaveApi.RegionalHolidayItem[] = [
  {
    name: "New Year's Day",
    date: "2026-01-01",
    is_optional: false,
  },
  {
    name: "Makar Sankranti",
    date: "2026-01-14",
    is_optional: false,
  },
];

function renderHolidaysPage(userRole: any = "hr_admin") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });

  const user = {
    id: "usr-1",
    company_id: "cmp-1",
    email: "hr@example.com",
    role: userRole,
    employee: {
      id: "emp-1",
      employee_code: "EMP-001",
      first_name: "Jane",
      last_name: "Doe",
      company_id: "cmp-1",
    },
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
        <HolidaysPage />
      </ToastProvider>
    </QueryClientProvider>
  );
}

describe("Sub-feature 4.7: Holidays Frontend (HolidaysPage)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(timeLeaveApi.listHolidays).mockResolvedValue(mockHolidays);
    vi.mocked(timeLeaveApi.getHolidayRegions).mockResolvedValue(mockRegions);
    vi.mocked(timeLeaveApi.previewRegionalHolidays).mockResolvedValue(mockRegionalPreview);
    vi.mocked(identityApi.listLocations).mockResolvedValue([]);
    vi.mocked(identityApi.getMyCompany).mockResolvedValue({
      id: "cmp-1",
      name: "Acme Corp",
      country: "IN",
      state: "Gujarat",
    } as any);
  });

  it("renders holidays list with names and status badges", async () => {
    renderHolidaysPage("hr_admin");

    await waitFor(() => {
      expect(screen.getByText("Republic Day")).toBeInTheDocument();
      expect(screen.getByText("Independence Day")).toBeInTheDocument();
      expect(screen.getByText("Diwali")).toBeInTheDocument();
      expect(screen.getByText("Christmas")).toBeInTheDocument();
      expect(screen.getByText(/Mandatory Gazetted/)).toBeInTheDocument();
    });
  });

  it("hides 'Add Custom Holiday' and 'Import' buttons for regular employee", async () => {
    renderHolidaysPage("employee");

    await waitFor(() => {
      expect(screen.getByText("Republic Day")).toBeInTheDocument();
    });

    expect(screen.queryByText(/Add Custom Holiday/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Import Statutory \(Gallery\)/)).not.toBeInTheDocument();
  });

  it("creates custom holiday when HR submits add modal", async () => {
    vi.mocked(timeLeaveApi.createHoliday).mockResolvedValue({
      id: "hol-5",
      name: "Founder's Day",
      date: "2026-12-30",
      is_optional: false,
      applies_to_department_id: null,
    });

    renderHolidaysPage("hr_admin");

    await waitFor(() => {
      expect(screen.getByText(/Add Custom Holiday/)).toBeInTheDocument();
    });

    const triggerBtn = screen.getByText(/Add Custom Holiday/);
    fireEvent.click(triggerBtn);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/e\.g\. Annual Company Foundation Day/)).toBeInTheDocument();
    });

    const nameInput = screen.getByPlaceholderText(/e\.g\. Annual Company Foundation Day/);
    fireEvent.change(nameInput, { target: { value: "Founder's Day" } });

    const form = nameInput.closest("form")!;
    const dateInput = form.querySelector('input[type="date"]')!;
    fireEvent.change(dateInput, { target: { value: "2026-12-30" } });

    const saveBtn = screen.getByRole("button", { name: "Add Holiday" });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(timeLeaveApi.createHoliday).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Founder's Day",
          date: "2026-12-30",
          is_optional: false,
        })
      );
    });
  });

  it("opens import regional gallery modal and executes statutory holiday import", async () => {
    vi.mocked(timeLeaveApi.importRegionalHolidays).mockResolvedValue({
      message: "Successfully imported 2 holidays.",
      imported_count: 2,
      total_holidays: 5,
      holidays: mockHolidays,
    });

    renderHolidaysPage("hr_admin");

    await waitFor(() => {
      expect(screen.getByText(/Import Statutory \(Gallery\)/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Import Statutory \(Gallery\)/));

    await waitFor(() => {
      expect(screen.getByText(/Holidays Gallery \(Regional Import\)/)).toBeInTheDocument();
      expect(screen.getByText("New Year's Day")).toBeInTheDocument();
    });

    const confirmImportBtn = screen.getByRole("button", { name: /Import Gujarat \(2026\) Holidays/ });
    fireEvent.click(confirmImportBtn);

    await waitFor(() => {
      expect(timeLeaveApi.importRegionalHolidays).toHaveBeenCalledWith(
        expect.objectContaining({
          country: "IN",
          state: "Gujarat",
        })
      );
    });
  });

  it("handles holiday deletion by HR on upcoming holidays", async () => {
    vi.mocked(timeLeaveApi.deleteHoliday).mockResolvedValue();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderHolidaysPage("hr_admin");

    await waitFor(() => {
      expect(screen.getByText("Christmas")).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByTitle("Delete holiday");
    expect(deleteButtons.length).toBeGreaterThan(0);
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      expect(timeLeaveApi.deleteHoliday).toHaveBeenCalledWith("hol-4");
    });
  });
});
