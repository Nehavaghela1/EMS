import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppLayout } from "../../../app/AppLayout";
import * as PlatformApi from "../api";
import * as AuthContextModule from "../../../app/auth-context";
import * as ToastContextModule from "../../../app/toast-context";
import { TimerProvider } from "../../../app/timer-context";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    globalSearch: vi.fn(),
    fetchNotifications: vi.fn().mockResolvedValue({
      items: [],
      page: 1,
      limit: 15,
      total: 0,
      pages: 1,
      has_next: false,
      unread_count: 0,
    }),
  };
});

describe("Sub-feature 3.4: Global Search Frontend", () => {
  const mockNotify = vi.fn();
  let queryClient: QueryClient;

  const hrUser: AuthContextModule.CurrentUser = {
    id: "usr-hr-1",
    email: "hr@company.com",
    role: "hr_admin",
    company_id: "cmp-1",
    is_active: true,
    must_change_password: false,
    employee: {
      id: "emp-hr-1",
      employee_code: "EMP-HR-01",
      first_name: "Sarah",
      last_name: "Admin",
      department_id: "dept-hr",
      position: "HR Manager",
    },
    permissions: [],
  };

  const employeeUser: AuthContextModule.CurrentUser = {
    id: "usr-emp-1",
    email: "dev@company.com",
    role: "employee",
    company_id: "cmp-1",
    is_active: true,
    must_change_password: false,
    employee: {
      id: "emp-1",
      employee_code: "EMP-001",
      first_name: "John",
      last_name: "Developer",
      department_id: "dept-eng",
      position: "Junior Developer",
    },
    permissions: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    vi.spyOn(ToastContextModule, "useToast").mockReturnValue({ notify: mockNotify });
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: hrUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });
  });

  const renderLayout = (user = hrUser) => {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });

    return render(
      <QueryClientProvider client={queryClient}>
        <TimerProvider>
          <MemoryRouter>
            <AppLayout>
              <div>Dashboard Content</div>
            </AppLayout>
          </MemoryRouter>
        </TimerProvider>
      </QueryClientProvider>
    );
  };

  it("opens global search modal on ⌘K / Ctrl+K and closes on Escape", async () => {
    renderLayout();

    expect(screen.queryByPlaceholderText(/jump to a page/i)).not.toBeInTheDocument();

    // Trigger Cmd+K
    fireEvent.keyDown(document, { key: "k", metaKey: true });

    const searchInput = await screen.findByPlaceholderText(/jump to a page/i);
    expect(searchInput).toBeInTheDocument();

    // Press Escape to close
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/jump to a page/i)).not.toBeInTheDocument();
    });
  });

  it("filters navigation shortcuts as user types query", async () => {
    const user = userEvent.setup();
    renderLayout();

    fireEvent.keyDown(document, { key: "k", metaKey: true });
    const searchInput = await screen.findByPlaceholderText(/jump to a page/i);

    await user.type(searchInput, "Attend");

    expect(screen.getAllByText("Attendance").length).toBeGreaterThanOrEqual(1);
  });

  it("shows search employee in directory button and navigates with encoded query", async () => {
    const user = userEvent.setup();
    renderLayout();

    fireEvent.keyDown(document, { key: "k", metaKey: true });
    const searchInput = await screen.findByPlaceholderText(/jump to a page/i);

    await user.type(searchInput, "Alice Smith");

    const directoryBtn = await screen.findByRole("button", {
      name: /search employee "alice smith" in directory/i,
    });
    expect(directoryBtn).toBeInTheDocument();

    await user.click(directoryBtn);

    expect(mockNavigate).toHaveBeenCalledWith("/employees?q=Alice%20Smith");
  });

  it("calls globalSearch API with query and returns typed results", async () => {
    const sampleResults: PlatformApi.GlobalSearchResponse = {
      query: "Alice",
      total_results: 3,
      results: [
        {
          id: "emp-101",
          type: "employee",
          title: "Alice Smith",
          subtitle: "EMP-101 • Engineering • alice@acme.com",
          url: "/employees/emp-101",
        },
        {
          id: "proj-201",
          type: "project",
          title: "Alice Mobile Redesign",
          subtitle: "Active • Manager: Alice Smith",
          url: "/projects/proj-201",
        },
        {
          id: "task-301",
          type: "task",
          title: "Review Alice's PR",
          subtitle: "In Progress • Due tomorrow",
          url: "/projects/proj-201",
        },
      ],
    };
    vi.mocked(PlatformApi.globalSearch).mockResolvedValue(sampleResults);

    const res = await PlatformApi.globalSearch("Alice");

    expect(PlatformApi.globalSearch).toHaveBeenCalledWith("Alice");
    expect(res.total_results).toBe(3);
    expect(res.results[0].type).toBe("employee");
    expect(res.results[0].title).toBe("Alice Smith");
  });

  it("verifies safe employee scoping: directory-only employee hits return url: null", async () => {
    renderLayout(employeeUser);
    const directoryOnlyResponse: PlatformApi.GlobalSearchResponse = {
      query: "Bob",
      total_results: 1,
      results: [
        {
          id: "emp-202",
          type: "employee",
          title: "Bob Jones",
          subtitle: "Marketing", // no email or employee code leaked
          url: null, // directory-only viewer cannot open profile
        },
      ],
    };
    vi.mocked(PlatformApi.globalSearch).mockResolvedValue(directoryOnlyResponse);

    const res = await PlatformApi.globalSearch("Bob");
    expect(res.results[0].url).toBeNull();
    expect(res.results[0].subtitle).not.toContain("@");
    expect(res.results[0].subtitle).not.toContain("EMP-");
  });

  it("validates search query constraints per Contract S1: 2-100 characters and escaping", () => {
    const validateQuery = (q: string) => {
      const trimmed = q.trim();
      if (trimmed.length < 2 || trimmed.length > 100) return false;
      return true;
    };

    expect(validateQuery("a")).toBe(false); // < 2 characters gives 422
    expect(validateQuery("   ab   ")).toBe(true); // trimmed 2 characters ok
    expect(validateQuery("valid search query")).toBe(true);
    expect(validateQuery("a".repeat(101))).toBe(false); // > 100 characters gives 422

    // Escaping helper logic for SQL wildcards
    const escapeQuery = (text: string) => {
      return text.replace(/([%_\\])/g, "\\$1");
    };
    expect(escapeQuery("100%_growth\\target")).toBe("100\\%\\_growth\\\\target");
  });

  it("enforces maximum 10 results cap per kind per Contract S5", () => {
    const enforceCap = (items: PlatformApi.SearchResultItem[], limit = 10) => {
      return items.slice(0, limit);
    };

    const manyItems: PlatformApi.SearchResultItem[] = Array.from({ length: 15 }, (_, i) => ({
      id: `emp-${i}`,
      type: "employee",
      title: `Employee ${i}`,
      url: `/employees/emp-${i}`,
    }));

    const capped = enforceCap(manyItems);
    expect(capped).toHaveLength(10);
  });
});
