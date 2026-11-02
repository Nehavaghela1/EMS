import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppLayout } from "../../../app/AppLayout";
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
});
