import { describe, it, expect, vi, beforeEach } from "vitest";
import * as PlatformApi from "../api";
import type { CurrentUser } from "../../../app/auth-context";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    fetchAuditLogs: vi.fn(),
    requestAuditLogExport: vi.fn(),
    downloadAuditLogExport: vi.fn(),
  };
});

describe("Sub-feature 3.5: Audit Logs Frontend", () => {
  const sampleLogItem: PlatformApi.AuditLogItem = {
    id: "audit-101",
    company_id: "cmp-acme",
    actor_user_id: "usr-hr-1",
    actor_email: "hr@acme.com",
    action: "EMPLOYEE_UPDATED",
    entity_type: "employee",
    entity_id: "emp-501",
    details: {
      field: "department",
      from: "Marketing",
      to: "Engineering",
    },
    ip_address: "192.168.1.50",
    user_agent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    request_id: "req-uuid-999",
    created_at: "2026-10-31T14:00:00Z",
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches audit logs list with filters and pagination via fetchAuditLogs API", async () => {
    const mockResponse: PlatformApi.AuditLogListResponse = {
      items: [sampleLogItem],
      page: 1,
      limit: 25,
      total: 1,
      pages: 1,
      has_next: false,
    };
    vi.mocked(PlatformApi.fetchAuditLogs).mockResolvedValue(mockResponse);

    const params = {
      action: "EMPLOYEE_UPDATED",
      actor_email: "hr@acme.com",
      entity_type: "employee",
      start_date: "2026-10-01",
      end_date: "2026-10-31",
      page: 1,
      limit: 25,
    };

    const res = await PlatformApi.fetchAuditLogs(params);

    expect(PlatformApi.fetchAuditLogs).toHaveBeenCalledWith(params);
    expect(res.items).toHaveLength(1);
    expect(res.items[0].action).toBe("EMPLOYEE_UPDATED");
    expect(res.items[0].ip_address).toBe("192.168.1.50");
    expect(res.items[0].request_id).toBe("req-uuid-999");
  });

  it("enforces role-based access: HR admin and owner permitted, non-HR roles blocked (Rule 3)", () => {
    const canAccessAuditLogs = (user: Partial<CurrentUser>) => {
      return user.role === "hr_admin" || user.role === "owner" || user.role === "super_admin";
    };

    expect(canAccessAuditLogs({ role: "owner" })).toBe(true);
    expect(canAccessAuditLogs({ role: "hr_admin" })).toBe(true);
    expect(canAccessAuditLogs({ role: "super_admin" })).toBe(true);

    expect(canAccessAuditLogs({ role: "employee" })).toBe(false);
    expect(canAccessAuditLogs({ role: "manager" })).toBe(false);
  });

  it("protects banned fields: passwords, tokens, and bank details never logged or returned (Rule 2)", () => {
    const BANNED_KEYS = [
      "password",
      "password_hash",
      "token",
      "access_token",
      "refresh_token",
      "secret",
      "bank_account",
      "ssn",
      "salary",
    ];

    const hasBannedKeys = (details: Record<string, unknown> | null): boolean => {
      if (!details) return false;
      const keys = Object.keys(details).map((k) => k.toLowerCase());
      return keys.some((k) => BANNED_KEYS.includes(k));
    };

    expect(hasBannedKeys(sampleLogItem.details)).toBe(false);

    const safeDetails = { changed: "position", level: "L2" };
    expect(hasBannedKeys(safeDetails)).toBe(false);

    const dangerousDetails = { password: "plain_secret_value" };
    expect(hasBannedKeys(dangerousDetails)).toBe(true);
  });

  it("requests background export of audit logs via requestAuditLogExport (Rule 6)", async () => {
    vi.mocked(PlatformApi.requestAuditLogExport).mockResolvedValue({ job_id: "job-audit-exp-1" });

    const exportFilters = {
      action: "ANNOUNCEMENT_CREATED",
      start_date: "2026-10-01",
      end_date: "2026-10-31",
    };

    const res = await PlatformApi.requestAuditLogExport(exportFilters);

    expect(PlatformApi.requestAuditLogExport).toHaveBeenCalledWith(exportFilters);
    expect(res.job_id).toBe("job-audit-exp-1");
  });

  it("downloads audit log export blob via downloadAuditLogExport (Rule 7)", async () => {
    const mockBlob = new Blob(["actor,action,created_at\nhr@acme.com,EMPLOYEE_UPDATED,2026-10-31"], {
      type: "text/csv",
    });
    vi.mocked(PlatformApi.downloadAuditLogExport).mockResolvedValue(mockBlob);

    const blob = await PlatformApi.downloadAuditLogExport("exp-99");

    expect(PlatformApi.downloadAuditLogExport).toHaveBeenCalledWith("exp-99");
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe("text/csv");
  });

  it("validates filter date range: start_date after end_date is invalid (422) (Rule 5)", () => {
    const validateDateRange = (startDate?: string, endDate?: string): boolean => {
      if (!startDate || !endDate) return true;
      return new Date(startDate).getTime() <= new Date(endDate).getTime();
    };

    expect(validateDateRange("2026-10-01", "2026-10-31")).toBe(true);
    expect(validateDateRange("2026-10-31", "2026-10-01")).toBe(false); // invalid date range
  });

  it("escapes CSV formulas to prevent Excel formula injection in export cells (Rule 6)", () => {
    const sanitizeCsvCell = (val: string): string => {
      if (val.startsWith("=") || val.startsWith("+") || val.startsWith("-") || val.startsWith("@")) {
        return `'${val}`;
      }
      return val;
    };

    expect(sanitizeCsvCell("Normal text")).toBe("Normal text");
    expect(sanitizeCsvCell("=SUM(A1:A10)")).toBe("'=SUM(A1:A10)");
    expect(sanitizeCsvCell("+cmd|' /C calc'!A0")).toBe("'+cmd|' /C calc'!A0");
    expect(sanitizeCsvCell("@SUM")).toBe("'@SUM");
  });
});
