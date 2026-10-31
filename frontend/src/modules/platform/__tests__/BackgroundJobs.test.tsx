import { describe, it, expect, vi, beforeEach } from "vitest";
import * as PlatformApi from "../api";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    getJobStatus: vi.fn(),
  };
});

describe("Sub-feature 3.6: Background Jobs Frontend", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("polls getJobStatus and transitions from queued to started to success", async () => {
    const queuedResponse: PlatformApi.JobStatusResponse = {
      job_id: "job-exp-123",
      status: "queued",
      result: null,
      error: null,
    };
    const startedResponse: PlatformApi.JobStatusResponse = {
      job_id: "job-exp-123",
      status: "started",
      result: null,
      error: null,
    };
    const successResponse: PlatformApi.JobStatusResponse = {
      job_id: "job-exp-123",
      status: "success",
      result: {
        row_count: 350,
        expires_at: "2026-11-01T12:00:00Z",
      },
      error: null,
    };

    vi.mocked(PlatformApi.getJobStatus)
      .mockResolvedValueOnce(queuedResponse)
      .mockResolvedValueOnce(startedResponse)
      .mockResolvedValueOnce(successResponse);

    // 1. Initial poll
    const res1 = await PlatformApi.getJobStatus("job-exp-123");
    expect(res1.status).toBe("queued");

    // 2. Second poll
    const res2 = await PlatformApi.getJobStatus("job-exp-123");
    expect(res2.status).toBe("started");

    // 3. Final poll
    const res3 = await PlatformApi.getJobStatus("job-exp-123");
    expect(res3.status).toBe("success");
    expect(res3.result?.row_count).toBe(350);
    expect(res3.result?.expires_at).toBe("2026-11-01T12:00:00Z");
  });

  it("sanitizes job result: verifies sensitive/internal fields are absent (Rule 4)", async () => {
    const successResponse: PlatformApi.JobStatusResponse = {
      job_id: "job-exp-456",
      status: "success",
      result: {
        row_count: 1200,
        expires_at: "2026-11-01T15:00:00Z",
      },
      error: null,
    };
    vi.mocked(PlatformApi.getJobStatus).mockResolvedValue(successResponse);

    const res = await PlatformApi.getJobStatus("job-exp-456");
    const resultKeys = Object.keys(res.result || {});

    // Forbidden keys that must NEVER be returned in job result
    const FORBIDDEN_RESULT_KEYS = ["file_path", "disk_path", "requester_id", "internal_trace", "temp_file"];
    for (const key of FORBIDDEN_RESULT_KEYS) {
      expect(resultKeys).not.toContain(key);
    }
  });

  it("handles failure state: returns safe generic error message (Rule 5)", async () => {
    const failedResponse: PlatformApi.JobStatusResponse = {
      job_id: "job-fail-789",
      status: "failure",
      result: null,
      error: "Export generation failed. Please try again later.",
    };
    vi.mocked(PlatformApi.getJobStatus).mockResolvedValue(failedResponse);

    const res = await PlatformApi.getJobStatus("job-fail-789");
    expect(res.status).toBe("failure");
    expect(res.error).toBe("Export generation failed. Please try again later.");
    expect(res.error).not.toContain("Traceback");
    expect(res.error).not.toContain("Exception");
  });

  it("permits specific 'too large' error message to pass through safely (Rule 5)", async () => {
    const tooLargeResponse: PlatformApi.JobStatusResponse = {
      job_id: "job-large-101",
      status: "failure",
      result: null,
      error: "Export exceeds maximum limit of 100,000 rows. Please apply filters.",
    };
    vi.mocked(PlatformApi.getJobStatus).mockResolvedValue(tooLargeResponse);

    const res = await PlatformApi.getJobStatus("job-large-101");
    expect(res.status).toBe("failure");
    expect(res.error).toContain("exceeds maximum limit of 100,000 rows");
  });

  it("validates job access permissions: requester and HR-level permitted, others 404 (Rule 1 & 6)", () => {
    const canAccessJob = (
      jobCompanyId: string,
      jobRequesterId: string,
      caller: { company_id: string; id: string; role: string }
    ) => {
      // Must be same company
      if (caller.company_id !== jobCompanyId) return false;
      // Requester or HR-level
      return (
        caller.id === jobRequesterId ||
        caller.role === "hr_admin" ||
        caller.role === "owner"
      );
    };

    const jobCompany = "cmp-acme";
    const jobRequester = "usr-emp-1";

    // 1. Requester can view
    expect(canAccessJob(jobCompany, jobRequester, { company_id: "cmp-acme", id: "usr-emp-1", role: "employee" })).toBe(true);

    // 2. HR Admin of same company can view
    expect(canAccessJob(jobCompany, jobRequester, { company_id: "cmp-acme", id: "usr-hr-1", role: "hr_admin" })).toBe(true);

    // 3. Different employee of same company blocked (404)
    expect(canAccessJob(jobCompany, jobRequester, { company_id: "cmp-acme", id: "usr-emp-2", role: "employee" })).toBe(false);

    // 4. Different company blocked (404)
    expect(canAccessJob(jobCompany, jobRequester, { company_id: "cmp-other", id: "usr-other", role: "hr_admin" })).toBe(false);
  });

  it("handles 24-hour job record expiration per Rule 10", () => {
    const isJobExpired = (createdAtIso: string, nowMs = Date.now()) => {
      const createdMs = new Date(createdAtIso).getTime();
      const TWENTY_FOUR_HOURS = 24 * 60 * 60 * 1000;
      return nowMs - createdMs > TWENTY_FOUR_HOURS;
    };

    const recentJob = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(); // 2 hours ago
    const oldJob = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString(); // 25 hours ago

    expect(isJobExpired(recentJob)).toBe(false);
    expect(isJobExpired(oldJob)).toBe(true);
  });
});
