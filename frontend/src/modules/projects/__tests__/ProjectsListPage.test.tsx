import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ProjectsListPage } from "../pages/ProjectsListPage";
import * as api from "../api";
import { ToastProvider } from "../../../app/toast-context";
import * as AuthContextModule from "../../../app/auth-context";

vi.mock("../api");
vi.mock("../../../app/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockProjects: api.Project[] = [
  {
    id: "proj-1",
    company_id: "comp-1",
    name: "Enterprise ERP System",
    code: "ERP-001",
    description: "Core ERP modernization",
    status: "active",
    start_date: "2026-01-01",
    deadline: "2026-12-31",
    budget: 50000,
    client_name: "Acme Corp",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "proj-2",
    company_id: "comp-1",
    name: "Mobile App Redesign",
    code: "MOB-002",
    description: "React Native mobile client",
    status: "planning",
    start_date: "2026-06-01",
    deadline: "2026-11-30",
    budget: 25000,
    client_name: "Globex Inc",
    created_at: "2026-05-01T00:00:00Z",
    updated_at: "2026-05-01T00:00:00Z",
  },
];

function setupAuth(userRole = "hr_admin") {
  vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
    user: {
      id: "u-1",
      email: "admin@company.com",
      role: userRole as any,
      company_id: "comp-1",
      employee: { id: "emp-1" } as any,
    } as any,
    token: "mock-token",
    login: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
    isLoading: false,
  });
}

function renderComponent() {
  return render(
    <ToastProvider>
      <MemoryRouter>
        <ProjectsListPage />
      </MemoryRouter>
    </ToastProvider>
  );
}

describe("ProjectsListPage (Module 7.1 Projects Lifecycle & Scoping)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchProjects).mockResolvedValue(mockProjects);
  });

  it("renders projects list correctly", async () => {
    setupAuth("hr_admin");
    renderComponent();

    expect(screen.getByText("Projects")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Enterprise ERP System")).toBeInTheDocument();
      expect(screen.getByText("Mobile App Redesign")).toBeInTheDocument();
      expect(screen.getByText("ERP-001")).toBeInTheDocument();
      expect(screen.getByText("MOB-002")).toBeInTheDocument();
    });
  });

  it("filters projects by status via tab buttons", async () => {
    setupAuth("hr_admin");
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Enterprise ERP System")).toBeInTheDocument();
    });

    const activeTabButton = screen.getByRole("button", { name: "Active" });
    fireEvent.click(activeTabButton);

    await waitFor(() => {
      expect(api.fetchProjects).toHaveBeenCalledWith("active", undefined);
    });
  });

  it("shows '+ Create Project' button for HR/Manager but hides for regular employee", async () => {
    setupAuth("employee");
    const { unmount } = renderComponent();
    await waitFor(() => {
      expect(screen.queryByText("+ Create Project")).not.toBeInTheDocument();
    });
    unmount();

    setupAuth("hr_admin");
    renderComponent();
    await waitFor(() => {
      expect(screen.getByText("+ Create Project")).toBeInTheDocument();
    });
  });

  it("creates a new project via the modal with validation", async () => {
    vi.mocked(api.createProject).mockResolvedValue({
      id: "proj-3",
      company_id: "comp-1",
      name: "Cloud Migration",
      code: "CLD-003",
      status: "active",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    });

    setupAuth("hr_admin");
    renderComponent();
    await waitFor(() => {
      expect(screen.getByText("+ Create Project")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("+ Create Project"));

    expect(screen.getByText("+ Create New Project")).toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText("e.g. Mobile App Redesign");
    const codeInput = screen.getByPlaceholderText("e.g. MAP-01");

    fireEvent.change(nameInput, { target: { value: "Cloud Migration" } });
    fireEvent.change(codeInput, { target: { value: "CLD-003" } });

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(api.createProject).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Cloud Migration",
          code: "CLD-003",
        })
      );
    });
  });
});
