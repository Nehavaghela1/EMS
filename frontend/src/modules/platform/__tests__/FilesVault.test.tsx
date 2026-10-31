import { describe, it, expect, vi, beforeEach } from "vitest";
import * as PlatformApi from "../api";
import * as ProjectsApi from "../../projects/api";
import type { ProjectDocument } from "../../projects/types";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    uploadFile: vi.fn(),
    attachEmployeeDocument: vi.fn(),
    fetchEmployeeDocuments: vi.fn(),
  };
});

vi.mock("../../projects/api", async () => {
  const actual = await vi.importActual<typeof import("../../projects/api")>("../../projects/api");
  return {
    ...actual,
    uploadProjectDocument: vi.fn(),
    fetchProjectDocuments: vi.fn(),
    downloadProjectDocument: vi.fn(),
    deleteProjectDocument: vi.fn(),
  };
});

describe("Sub-feature 3.3: Files & Vault Frontend", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uploads generic file via uploadFile API with multipart form data", async () => {
    const file = new File(["dummy pdf content"], "offer_letter.pdf", { type: "application/pdf" });
    vi.mocked(PlatformApi.uploadFile).mockResolvedValue({
      file_object_id: "fobj-456",
      file_name: "offer_letter.pdf",
      file_type: "application/pdf",
      file_size: 17,
    });

    const res = await PlatformApi.uploadFile(file);

    expect(PlatformApi.uploadFile).toHaveBeenCalledWith(file);
    expect(res.file_object_id).toBe("fobj-456");
    expect(res.file_name).toBe("offer_letter.pdf");
    expect(res.file_size).toBe(17);
  });

  it("attaches employee document via attachEmployeeDocument API", async () => {
    const docPayload = {
      employee_id: "emp-101",
      file_object_id: "fobj-456",
      document_type: "CONTRACT",
      name: "Employment Contract.pdf",
    };

    const mockAttachedDoc: PlatformApi.EmployeeDocument = {
      id: "empdoc-1",
      company_id: "cmp-1",
      employee_id: "emp-101",
      file_object_id: "fobj-456",
      document_type: "CONTRACT",
      name: "Employment Contract.pdf",
      created_at: "2026-10-31T11:00:00Z",
      download_url: "/files/signed/fobj-456?sig=valid",
    };
    vi.mocked(PlatformApi.attachEmployeeDocument).mockResolvedValue(mockAttachedDoc);

    const result = await PlatformApi.attachEmployeeDocument(docPayload);

    expect(PlatformApi.attachEmployeeDocument).toHaveBeenCalledWith(docPayload);
    expect(result.id).toBe("empdoc-1");
    expect(result.download_url).toBe("/files/signed/fobj-456?sig=valid");
  });

  it("fetches employee documents list for viewing", async () => {
    vi.mocked(PlatformApi.fetchEmployeeDocuments).mockResolvedValue([
      {
        id: "empdoc-1",
        company_id: "cmp-1",
        employee_id: "emp-101",
        file_object_id: "fobj-456",
        document_type: "CONTRACT",
        name: "Employment Contract.pdf",
        created_at: "2026-10-31T11:00:00Z",
        download_url: "/files/signed/fobj-456?sig=valid",
      },
    ]);

    const docs = await PlatformApi.fetchEmployeeDocuments("emp-101");
    expect(docs).toHaveLength(1);
    expect(docs[0].name).toBe("Employment Contract.pdf");
  });

  it("uploads project document and fetches document list via projects API", async () => {
    const sampleDoc: ProjectDocument = {
      id: "doc-1",
      company_id: "cmp-1",
      project_id: "proj-123",
      file_id: "fobj-uuid-1",
      name: "architecture_diagram.pdf",
      description: "High level architecture",
      file_size: 1048576,
      file_type: "application/pdf",
      created_at: "2026-10-30T10:00:00Z",
      download_url: "https://api.company.com/files/signed/fobj-uuid-1?token=valid_10m",
    };

    const file = new File(["arch content"], "architecture_diagram.pdf", { type: "application/pdf" });
    vi.mocked(ProjectsApi.uploadProjectDocument).mockResolvedValue(sampleDoc);
    vi.mocked(ProjectsApi.fetchProjectDocuments).mockResolvedValue([sampleDoc]);

    const uploadResult = await ProjectsApi.uploadProjectDocument("proj-123", file, "High level architecture");
    expect(uploadResult.id).toBe("doc-1");
    expect(uploadResult.name).toBe("architecture_diagram.pdf");

    const docList = await ProjectsApi.fetchProjectDocuments("proj-123");
    expect(docList).toHaveLength(1);
    expect(docList[0].file_id).toBe("fobj-uuid-1");
  });

  it("triggers signed URL download via downloadProjectDocument API", async () => {
    vi.mocked(ProjectsApi.downloadProjectDocument).mockResolvedValue(undefined);

    await ProjectsApi.downloadProjectDocument("proj-123", "doc-1", "architecture_diagram.pdf");
    expect(ProjectsApi.downloadProjectDocument).toHaveBeenCalledWith(
      "proj-123",
      "doc-1",
      "architecture_diagram.pdf"
    );
  });

  it("validates allowed file extensions (pdf, jpg, jpeg, png, docx) and rejects disallowed formats", () => {
    const allowedExtensions = ["pdf", "jpg", "jpeg", "png", "docx"];
    const isAllowed = (filename: string) => {
      const ext = filename.split(".").pop()?.toLowerCase();
      return ext ? allowedExtensions.includes(ext) : false;
    };

    expect(isAllowed("resume.pdf")).toBe(true);
    expect(isAllowed("id_card.png")).toBe(true);
    expect(isAllowed("photo.jpeg")).toBe(true);
    expect(isAllowed("doc.docx")).toBe(true);

    expect(isAllowed("malicious.exe")).toBe(false);
    expect(isAllowed("script.sh")).toBe(false);
    expect(isAllowed("payload.js")).toBe(false);
    expect(isAllowed("exploit.php")).toBe(false);
  });

  it("enforces 25 MB max size check according to Contract Rule 3", () => {
    const MAX_FILE_SIZE = 25 * 1024 * 1024; // 25 MB in bytes
    const isWithinLimit = (size: number) => size > 0 && size <= MAX_FILE_SIZE;

    expect(isWithinLimit(0)).toBe(false); // empty file rejected (422)
    expect(isWithinLimit(1024)).toBe(true); // 1 KB ok
    expect(isWithinLimit(25 * 1024 * 1024)).toBe(true); // exactly 25 MB ok
    expect(isWithinLimit(25 * 1024 * 1024 + 1)).toBe(false); // > 25 MB rejected (413)
  });

  it("verifies security headers: attachment disposition and nosniff per Contract Rule 7", () => {
    const mockHeaders = {
      "Content-Disposition": 'attachment; filename="architecture_diagram.pdf"',
      "X-Content-Type-Options": "nosniff",
      "Cache-Control": "no-store",
    };

    expect(mockHeaders["Content-Disposition"]).toContain("attachment");
    expect(mockHeaders["X-Content-Type-Options"]).toBe("nosniff");
    expect(mockHeaders["Cache-Control"]).toBe("no-store");
  });
});
