import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DepartmentListPage } from "../pages/DepartmentListPage";
import * as AuthContextModule from "../../../app/auth-context";
import * as HrApi from "../api";
import * as ToastContextModule from "../../../app/toast-context";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    listDepartments: vi.fn(),
    createDepartment: vi.fn(),
    updateDepartment: vi.fn(),
    deleteDepartment: vi.fn(),
  };
});

describe("Sub-feature 2.1: Departments Frontend", () => {
  const mockNotify = vi.fn();
  let queryClient: QueryClient;

  const hrUser: AuthContextModule.CurrentUser = {
    id: "usr-hr-1",
    email: "hr@company.com",
    role: "hr_admin",
    company_id: "cmp-1",
    is_active: true,
    must_change_password: false,
    employee: null,
    permissions: [],
  };

  const employeeUser: AuthContextModule.CurrentUser = {
    id: "usr-emp-1",
    email: "emp@company.com",
    role: "employee",
    company_id: "cmp-1",
    is_active: true,
    must_change_password: false,
    employee: {
      id: "emp-1",
      employee_code: "EMP-001",
      first_name: "Jane",
      last_name: "Doe",
      department_id: "dept-1",
      position: "Engineer",
    },
    permissions: [],
  };

  const sampleDepartments: HrApi.Department[] = [
    {
      id: "dept-1",
      name: "Engineering",
      description: "Core tech team",
      head_employee_id: null,
      employee_count: 5,
      created_at: "2026-01-01T00:00:00Z",
    },
    {
      id: "dept-2",
      name: "Marketing",
      description: null,
      head_employee_id: null,
      employee_count: 0,
      created_at: "2026-01-02T00:00:00Z",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.spyOn(ToastContextModule, 'useToast').mockReturnValue({
      notify: mockNotify,
    });
    vi.mocked(HrApi.listDepartments).mockResolvedValue({
      items: sampleDepartments,
      total: sampleDepartments.length,
      page: 1,
      limit: 50,
      pages: 1,
      has_next: false,
    });
  });

  function renderPage(currentUser: AuthContextModule.CurrentUser = hrUser) {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: currentUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });

    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/departments"]}>
          <DepartmentListPage />
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  it("Rule 1: shows '+ New department' button and Edit/Delete actions for HR Admin", async () => {
    renderPage(hrUser);

    expect(await screen.findByRole("button", { name: /\+ new department/i })).toBeInTheDocument();
    expect(await screen.findByText("Engineering")).toBeInTheDocument();
    expect(screen.getByText("Marketing")).toBeInTheDocument();

    // Edit buttons visible
    const editButtons = screen.getAllByRole("button", { name: /edit/i });
    expect(editButtons.length).toBeGreaterThan(0);
  });

  it("Rule 1: hides '+ New department' button and action column for plain employee", async () => {
    renderPage(employeeUser);

    expect(await screen.findByText("Engineering")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /\+ new department/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
  });

  it("Rule 2: validates required name and rejects empty or whitespace-only name", async () => {
    const user = userEvent.setup();
    renderPage(hrUser);

    const newBtn = await screen.findByRole("button", { name: /\+ new department/i });
    await user.click(newBtn);

    const submitBtn = screen.getByRole("button", { name: /create department/i });
    await user.click(submitBtn);

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(HrApi.createDepartment).not.toHaveBeenCalled();
  });

  it("Rule 2: rejects a whitespace-only name and does not call the api", async () => {
    const user = userEvent.setup();
    renderPage(hrUser);

    await user.click(await screen.findByRole("button", { name: /\+ new department/i }));
    const form = screen.getByRole("button", { name: /create department/i }).closest("form");
    if (!form) throw new Error("department form not rendered");
    const nameInput = form.querySelector("input");
    if (!nameInput) throw new Error("name input not rendered");
    await user.type(nameInput, "     ");
    await user.click(screen.getByRole("button", { name: /create department/i }));

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(HrApi.createDepartment).not.toHaveBeenCalled();
  });

  it("Rule 3 & 4: creates department with the typed name and description and shows success toast", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.createDepartment).mockResolvedValueOnce({
      id: "dept-3",
      name: "Operations",
      description: "Ops & Logistics",
      head_employee_id: null,
      employee_count: 0,
      created_at: "2026-01-03T00:00:00Z",
    });

    renderPage(hrUser);

    const newBtn = await screen.findByRole("button", { name: /\+ new department/i });
    await user.click(newBtn);

    const form = screen.getByRole("button", { name: /create department/i }).closest("form")!;
    const nameInput = form.querySelector("input")!;
    const descInput = form.querySelector("textarea")!;

    await user.type(nameInput, "Operations");
    await user.type(descInput, "Ops & Logistics");

    const submitBtn = screen.getByRole("button", { name: /create department/i });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(HrApi.createDepartment).toHaveBeenCalledWith({
        name: "Operations",
        description: "Ops & Logistics",
      });
      expect(mockNotify).toHaveBeenCalledWith("Department created.");
    });
  });

  it.todo("GAP: department name with surrounding spaces is sent trimmed (page sends the raw name)");

  it("Rule 6: blocks delete button with locked indicator when department has active employees", async () => {
    renderPage(hrUser);

    expect(await screen.findByText("Engineering")).toBeInTheDocument();
    // dept-1 has employee_count: 5 -> button is disabled with 'Locked (5)'
    const lockedBtn = screen.getByRole("button", { name: /locked \(5\)/i });
    expect(lockedBtn).toBeDisabled();

    // dept-2 has employee_count: 0 -> Delete button is enabled
    const deleteBtn = screen.getByRole("button", { name: /^delete$/i });
    expect(deleteBtn).not.toBeDisabled();
  });

  it("Rule 6: opens confirm dialog and deletes empty department", async () => {
    const user = userEvent.setup();
    vi.mocked(HrApi.deleteDepartment).mockResolvedValueOnce();

    renderPage(hrUser);

    const deleteBtn = await screen.findByRole("button", { name: /^delete$/i });
    await user.click(deleteBtn);

    expect(screen.getByText(/delete department\?/i)).toBeInTheDocument();
    const modal = screen.getByRole("dialog");
    const confirmBtn = modal.querySelector(".modal-footer button.btn-danger") as HTMLButtonElement;
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(HrApi.deleteDepartment).toHaveBeenCalledWith("dept-2");
      expect(mockNotify).toHaveBeenCalledWith("Department deleted.");
    });
  });
});
