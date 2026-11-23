import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiClient } from "../../../app/api-client";
import { listReimbursements } from "../api";

vi.mock("../../../app/api-client", () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

describe("Reimbursement API params", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("passes status query parameter as status (not status_filter)", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        items: [],
        total: 0,
        page: 1,
        limit: 20,
        pages: 0,
        has_next: false,
      },
    });

    await listReimbursements("pending", 1, 20);

    expect(apiClient.get).toHaveBeenCalledWith("/payroll/reimbursements", {
      params: { status: "pending", page: 1, limit: 20 },
    });
  });
});
