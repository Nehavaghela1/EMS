import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProjectDetailPage } from "../pages/ProjectDetailPage";
import * as api from "../api";
import type {
  ProjectSummary,
  Task,
  ProjectMember,
  Milestone,
  ProjectDocument,
  TaskComment,
} from "../types";
import * as hrApi from "../../hr/api";
import { ToastProvider } from "../../../app/toast-context";
import { TimerProvider } from "../../../app/timer-context";
import * as AuthContextModule from "../../../app/auth-context";

vi.mock("../api");
vi.mock("../../hr/api");

const mockProjectSummary: ProjectSummary = {
  project: {
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
  total_tasks: 10,
  completed_tasks: 6,
  overdue_tasks: 1,
  completion_percentage: 60,
  total_logged_hours: 120,
  total_billable_hours: 100,
  members_count: 5,
  milestones_count: 3,
  completed_milestones_count: 1,
  budget_spent: 15000,
  budget_remaining: 35000,
  delivery_health: "Needs Attention",
  approved_billable_hours: 90,
  approved_logged_hours: 110,
};

const mockTasks: Task[] = [
  {
    id: "task-1",
    company_id: "comp-1",
    project_id: "proj-1",
    title: "Implement Auth Flow",
    description: "JWT & OAuth2 integration",
    priority: "high",
    status: "todo",
    due_date: "2026-12-01",
    estimated_hours: 16,
    assigned_to: "emp-1",
    assigned_to_name: "Alice Smith",
    created_at: "2026-01-10T00:00:00Z",
    updated_at: "2026-01-10T00:00:00Z",
  },
  {
    id: "task-2",
    company_id: "comp-1",
    project_id: "proj-1",
    title: "Setup CI/CD Pipeline",
    description: "GitHub Actions workflow",
    priority: "critical",
    status: "done",
    due_date: "2026-02-01",
    estimated_hours: 8,
    assigned_to: "emp-2",
    assigned_to_name: "Bob Jones",
    created_at: "2026-01-05T00:00:00Z",
    updated_at: "2026-01-15T00:00:00Z",
  },
];

const mockMembers: ProjectMember[] = [
  {
    id: "pm-1",
    company_id: "comp-1",
    project_id: "proj-1",
    employee_id: "emp-1",
    employee_name: "Alice Smith",
    employee_email: "alice@company.com",
    employee_code: "EMP-001",
    role: "lead",
    joined_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "pm-2",
    company_id: "comp-1",
    project_id: "proj-1",
    employee_id: "emp-2",
    employee_name: "Bob Jones",
    employee_email: "bob@company.com",
    employee_code: "EMP-002",
    role: "member",
    joined_at: "2026-01-05T00:00:00Z",
    created_at: "2026-01-05T00:00:00Z",
  },
];

const mockMilestones: Milestone[] = [
  {
    id: "ms-1",
    company_id: "comp-1",
    project_id: "proj-1",
    title: "Phase 1 - Architecture & Database",
    description: "Postgres schema and initial migrations",
    due_date: "2026-03-31",
    status: "completed",
    completion_percentage: 100,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-03-30T00:00:00Z",
  },
  {
    id: "ms-2",
    company_id: "comp-1",
    project_id: "proj-1",
    title: "Phase 2 - Core Microservices",
    description: "Employee and payroll management services",
    due_date: "2026-07-31",
    status: "in_progress",
    completion_percentage: 50,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-05-15T00:00:00Z",
  },
];

const mockDocuments: ProjectDocument[] = [
  {
    id: "doc-1",
    company_id: "comp-1",
    project_id: "proj-1",
    file_id: "file-101",
    name: "System_Architecture_Diagram.pdf",
    file_size: 2048576,
    file_type: "application/pdf",
    description: "Cloud architecture specifications",
    uploaded_by: "emp-1",
    uploaded_by_name: "Alice Smith",
    created_at: "2026-01-15T12:00:00Z",
  },
];

const mockComments: TaskComment[] = [
  {
    id: "comment-1",
    company_id: "comp-1",
    task_id: "task-1",
    user_id: "u-1",
    comment: "Initial requirements finalized with client.",
    created_at: "2026-01-12T10:00:00Z",
  },
];

function setupAuth(userRole = "hr_admin", employeeId = "emp-1") {
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
        id: employeeId,
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
        <MemoryRouter initialEntries={["/projects/proj-1"]}>
          <Routes>
            <Route path="/projects/:id" element={<ProjectDetailPage />} />
          </Routes>
        </MemoryRouter>
      </TimerProvider>
    </ToastProvider>
  );
}

describe("ProjectDetailPage (Module 7.2 Tasks, 7.3 Milestones, 7.4 Members, 7.6 Comments & Documents, 7.7 Summary)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchProjectSummary).mockResolvedValue(mockProjectSummary);
    vi.mocked(api.fetchTasks).mockResolvedValue(mockTasks);
    vi.mocked(api.fetchProjectMembers).mockResolvedValue(mockMembers);
    vi.mocked(api.fetchMilestones).mockResolvedValue(mockMilestones);
    vi.mocked(api.fetchTimeEntries).mockResolvedValue([]);
    vi.mocked(api.fetchProjectDocuments).mockResolvedValue(mockDocuments);
    vi.mocked(api.fetchTaskComments).mockResolvedValue(mockComments);
    vi.mocked(hrApi.listEmployees).mockResolvedValue({ items: [], total: 0, page: 1, limit: 100, pages: 1 } as any);
  });

  it("7.7 Project Summary & Financials: displays progress and health indicators for HR admin", async () => {
    setupAuth("hr_admin");
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Enterprise ERP System")).toBeInTheDocument();
      expect(screen.getByText("ERP-001")).toBeInTheDocument();
      expect(screen.getByText(/Needs Attention/i)).toBeInTheDocument();
      expect(screen.getByText("60%")).toBeInTheDocument();
    });
  });

  it("7.2 Kanban Tasks: renders tasks in columns and allows task creation", async () => {
    setupAuth("hr_admin");
    vi.mocked(api.createTask).mockResolvedValue({
      id: "task-3",
      company_id: "comp-1",
      project_id: "proj-1",
      title: "Write End-to-End Tests",
      priority: "high",
      status: "todo",
      created_at: "2026-02-01T00:00:00Z",
      updated_at: "2026-02-01T00:00:00Z",
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Implement Auth Flow")).toBeInTheDocument();
      expect(screen.getByText("Setup CI/CD Pipeline")).toBeInTheDocument();
    });

    const newTaskBtn = screen.getByRole("button", { name: "+ Add Task" });
    fireEvent.click(newTaskBtn);

    expect(screen.getByText("+ Create Task")).toBeInTheDocument();

    const titleInput = screen.getByText("Task Title *").nextElementSibling as HTMLInputElement;
    fireEvent.change(titleInput, { target: { value: "Write End-to-End Tests" } });

    fireEvent.click(screen.getByRole("button", { name: "Create Task" }));

    await waitFor(() => {
      expect(api.createTask).toHaveBeenCalledWith(
        "proj-1",
        expect.objectContaining({
          title: "Write End-to-End Tests",
        })
      );
    });
  });

  it("7.3 Milestones: displays milestones and allows viewing milestones tab", async () => {
    setupAuth("hr_admin");
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/Milestones/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Milestones/i));

    await waitFor(() => {
      expect(screen.getByText("Phase 1 - Architecture & Database")).toBeInTheDocument();
      expect(screen.getByText("Phase 2 - Core Microservices")).toBeInTheDocument();
    });
  });

  it("7.4 Team Members: displays member list with roles", async () => {
    setupAuth("hr_admin");
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/Users & Team/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Users & Team/i));

    await waitFor(() => {
      expect(screen.getByText("Alice Smith")).toBeInTheDocument();
      expect(screen.getByText("Bob Jones")).toBeInTheDocument();
    });
  });

  it("7.6 Documents & Lifecycle: displays document vault and handles download", async () => {
    setupAuth("hr_admin");
    vi.mocked(api.downloadProjectDocument).mockResolvedValue(undefined);

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/Documents & Files/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Documents & Files/i));

    await waitFor(() => {
      expect(screen.getByText("System_Architecture_Diagram.pdf")).toBeInTheDocument();
      expect(screen.getByText("Cloud architecture specifications")).toBeInTheDocument();
    });
  });
});
