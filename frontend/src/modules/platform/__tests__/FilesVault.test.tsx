import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProjectDetailPage } from "../../projects/pages/ProjectDetailPage";
import * as ProjectsApi from "../../projects/api";
import * as HrApi from "../../hr/api";
import * as AuthContextModule from "../../../app/auth-context";
import { ToastProvider } from "../../../app/toast-context";
import { TimerProvider } from "../../../app/timer-context";
import type { Project, ProjectDocument, ProjectSummary } from "../../projects/types";

vi.mock("../../projects/api", async () => {
  const actual = await vi.importActual<typeof import("../../projects/api")>("../../projects/api");
  return {
    ...actual,
    fetchProjectSummary: vi.fn(),
    fetchTasks: vi.fn(),
    fetchProjectMembers: vi.fn(),
    fetchMilestones: vi.fn(),
    fetchTimeEntries: vi.fn(),
    fetchProjectDocuments: vi.fn(),
    uploadProjectDocument: vi.fn(),
    downloadProjectDocument: vi.fn(),
  };
});

vi.mock("../../hr/api", async () => {
  const actual = await vi.importActual<typeof import("../../hr/api")>("../../hr/api");
  return { ...actual, listEmployees: vi.fn() };
});

function apiError(status: number, body: object): Error {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: body },
  });
}

describe("Sub-feature 3.3: project documents (ProjectDetailPage)", () => {
  const hrUser: AuthContextModule.CurrentUser = {
    id: "usr-hr-1",
    email: "hr@acme.com",
    role: "hr_admin",
    company_id: "cmp-acme",
    is_active: true,
    must_change_password: false,
    employee: {
      id: "emp-hr-1",
      employee_code: "EMP-HR-01",
      first_name: "Sarah",
      last_name: "HR",
      department_id: "dept-hr",
      position: "HR Manager",
    },
    permissions: [],
  };

  const project: Project = {
    id: "proj-123",
    company_id: "cmp-acme",
    name: "Apollo Project",
    code: "APL",
    description: "Space project",
    status: "active",
    manager_id: "emp-hr-1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };

  const summary: ProjectSummary = {
    project,
    total_tasks: 0,
    completed_tasks: 0,
    overdue_tasks: 0,
    completion_percentage: 0,
    total_logged_hours: 0,
    total_billable_hours: 0,
    members_count: 0,
    milestones_count: 0,
    completed_milestones_count: 0,
  };

  const existingDoc: ProjectDocument = {
    id: "doc-1",
    company_id: "cmp-acme",
    project_id: "proj-123",
    file_id: "fobj-1",
    name: "architecture_diagram.pdf",
    description: "High level architecture",
    file_size: 1048576,
    file_type: "application/pdf",
    created_at: "2026-10-30T10:00:00Z",
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      status: "authenticated",
      user: hrUser,
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    });
    vi.mocked(ProjectsApi.fetchProjectSummary).mockResolvedValue(summary);
    vi.mocked(ProjectsApi.fetchTasks).mockResolvedValue([]);
    vi.mocked(ProjectsApi.fetchProjectMembers).mockResolvedValue([]);
    vi.mocked(ProjectsApi.fetchMilestones).mockResolvedValue([]);
    vi.mocked(ProjectsApi.fetchTimeEntries).mockResolvedValue([]);
    vi.mocked(ProjectsApi.fetchProjectDocuments).mockResolvedValue([existingDoc]);
    vi.mocked(HrApi.listEmployees).mockResolvedValue({
      items: [],
      page: 1,
      limit: 100,
      total: 0,
      pages: 1,
      has_next: false,
    });
  });

  const openDocumentsTab = async (user: ReturnType<typeof userEvent.setup>) => {
    render(
      <ToastProvider>
        <TimerProvider>
          <MemoryRouter initialEntries={["/projects/proj-123"]}>
            <Routes>
              <Route path="/projects/:id" element={<ProjectDetailPage />} />
            </Routes>
          </MemoryRouter>
        </TimerProvider>
      </ToastProvider>
    );
    await user.click(await screen.findByText(/Documents & Files \(1\)/));
  };

  const openUploadModal = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole("button", { name: /Upload Document/ }));
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("file input not rendered");
    return input;
  };

  // jsdom treats a programmatically-set file input as empty and blocks click-submit on `required`,
  // so submit the real form element instead of clicking the button.
  const submitUpload = (input: HTMLInputElement) => {
    const form = input.closest("form");
    if (!form) throw new Error("upload form not rendered");
    fireEvent.submit(form);
  };

  it("uploads the chosen file and shows it at the top of the document list", async () => {
    const user = userEvent.setup();
    const file = new File(["pdf"], "requirements.pdf", { type: "application/pdf" });
    vi.mocked(ProjectsApi.uploadProjectDocument).mockResolvedValue({
      ...existingDoc,
      id: "doc-2",
      file_id: "fobj-2",
      name: "requirements.pdf",
      description: undefined,
    });

    await openDocumentsTab(user);
    const input = await openUploadModal(user);
    await user.upload(input, file);
    submitUpload(input);

    await waitFor(() => {
      expect(ProjectsApi.uploadProjectDocument).toHaveBeenCalledWith("proj-123", file, "");
    });
    expect(await screen.findByText("requirements.pdf")).toBeInTheDocument();
    expect(screen.getByText("architecture_diagram.pdf")).toBeInTheDocument();
    expect(screen.getByText("Document uploaded successfully!")).toBeInTheDocument();
  });

  it("downloads a document by its id when Download is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(ProjectsApi.downloadProjectDocument).mockResolvedValue(undefined);

    await openDocumentsTab(user);
    await user.click(await screen.findByRole("button", { name: /Download/ }));

    await waitFor(() => {
      expect(ProjectsApi.downloadProjectDocument).toHaveBeenCalledWith(
        "proj-123",
        "doc-1",
        "architecture_diagram.pdf"
      );
    });
    expect(await screen.findByText("Download started")).toBeInTheDocument();
  });

  it("shows the server message when the upload is rejected with 413", async () => {
    const user = userEvent.setup();
    vi.mocked(ProjectsApi.uploadProjectDocument).mockRejectedValue(
      apiError(413, { error: { message: "File too large for upload." } })
    );

    await openDocumentsTab(user);
    const input = await openUploadModal(user);
    await user.upload(input, new File(["x"], "big.pdf", { type: "application/pdf" }));
    submitUpload(input);

    expect(await screen.findByText("File too large for upload.")).toBeInTheDocument();
  });

  it("shows the validation message when the upload is rejected with 422", async () => {
    const user = userEvent.setup();
    vi.mocked(ProjectsApi.uploadProjectDocument).mockRejectedValue(
      apiError(422, { error: { details: { errors: [{ msg: "File type not allowed." }] } } })
    );

    await openDocumentsTab(user);
    const input = await openUploadModal(user);
    await user.upload(input, new File(["x"], "notes.pdf", { type: "application/pdf" }));
    submitUpload(input);

    expect(await screen.findByText("File type not allowed.")).toBeInTheDocument();
  });

  it("file picker restricts choices with an accept list that includes pdf, jpg, jpeg, png and docx", async () => {
    const user = userEvent.setup();
    await openDocumentsTab(user);
    const input = await openUploadModal(user);

    const accepted = input.accept.split(",");
    expect(accepted).toEqual(expect.arrayContaining([".pdf", ".jpg", ".jpeg", ".png", ".docx"]));
  });

  it.todo("GAP: file picker accept list should allow only pdf, jpg, jpeg, png, docx (page also allows .doc, .xlsx, .xls, .zip)");
});
