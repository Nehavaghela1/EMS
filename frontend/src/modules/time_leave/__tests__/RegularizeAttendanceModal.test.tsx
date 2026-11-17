import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { RegularizeAttendanceModal } from "../components/RegularizeAttendanceModal";
import { apiClient } from "../../../app/api-client";

vi.mock("../../../app/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("Sub-feature 4.3: Attendance Regularization Frontend (RegularizeAttendanceModal)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders employee apply mode with form fields and handles submit", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(
      <RegularizeAttendanceModal
        isOpen={true}
        onClose={onClose}
        isAdmin={false}
        employeeName="John Doe"
        attendanceDate="2026-11-15"
        initialCheckIn="2026-11-15T09:00:00Z"
        initialCheckOut="2026-11-15T18:00:00Z"
        onSubmit={onSubmit}
      />
    );

    expect(screen.getByText("Apply for Regularization")).toBeInTheDocument();
    expect(screen.getByText("Correct your punch-in/out timestamps for accurate payroll hours.")).toBeInTheDocument();

    const reasonInput = screen.getByPlaceholderText(/Device was offline during morning punch/);
    fireEvent.change(reasonInput, { target: { value: "Biometric device offline in morning" } });

    const submitBtn = screen.getByRole("button", { name: "Submit Regularization Request" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });

    const formData = onSubmit.mock.calls[0][0] as FormData;
    expect(formData.get("reason")).toBe("Biometric device offline in morning");
    expect(onClose).toHaveBeenCalled();
  });

  it("renders manager/admin review mode with approve and reject actions", async () => {
    const onSubmit = vi.fn();
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const onReject = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(
      <RegularizeAttendanceModal
        isOpen={true}
        onClose={onClose}
        isAdmin={true}
        employeeName="Alice Smith"
        attendanceDate="2026-11-15"
        initialCheckIn="2026-11-15T09:00:00Z"
        initialCheckOut="2026-11-15T18:00:00Z"
        existingReason="Power outage at branch"
        onSubmit={onSubmit}
        onApprove={onApprove}
        onReject={onReject}
      />
    );

    expect(screen.getByText("Review Regularization — Alice Smith")).toBeInTheDocument();
    expect(screen.getByText('"Power outage at branch"')).toBeInTheDocument();

    // Verify approve button
    const approveBtn = screen.getByRole("button", { name: /Approve & Regularize/ });
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(onApprove).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("handles admin rejection with mandatory reason validation", async () => {
    const onSubmit = vi.fn();
    const onApprove = vi.fn();
    const onReject = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(
      <RegularizeAttendanceModal
        isOpen={true}
        onClose={onClose}
        isAdmin={true}
        employeeName="Alice Smith"
        attendanceDate="2026-11-15"
        initialCheckIn="2026-11-15T09:00:00Z"
        initialCheckOut="2026-11-15T18:00:00Z"
        existingReason="Power outage at branch"
        onSubmit={onSubmit}
        onApprove={onApprove}
        onReject={onReject}
      />
    );

    const rejectBtn = screen.getByRole("button", { name: /Reject/ });
    fireEvent.click(rejectBtn);

    // Switch to rejection mode
    expect(screen.getByText("Reject Regularization Request")).toBeInTheDocument();

    // Rejection button is disabled while reason is empty
    const confirmRejectBtn = screen.getByRole("button", { name: "Confirm Rejection" });
    expect(confirmRejectBtn).toBeDisabled();

    // Type rejection reason
    const reasonInput = screen.getByPlaceholderText(/Gate logs show exit at 2:15 PM/);
    fireEvent.change(reasonInput, { target: { value: "Punch record does not match turnstile log" } });

    expect(confirmRejectBtn).not.toBeDisabled();
    fireEvent.click(confirmRejectBtn);

    await waitFor(() => {
      expect(onReject).toHaveBeenCalledWith("Punch record does not match turnstile log");
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("revokes attachment blob URL after downloading to prevent memory leak", async () => {
    const createObjectURLSpy = vi.fn().mockReturnValue("blob:http://localhost/test-uuid");
    const revokeObjectURLSpy = vi.fn();
    window.URL.createObjectURL = createObjectURLSpy;
    window.URL.revokeObjectURL = revokeObjectURLSpy;

    const fakeBlob = new Blob(["fake attachment data"], { type: "image/png" });
    vi.mocked(apiClient.get).mockResolvedValue({
      data: fakeBlob,
    });

    vi.spyOn(window, "open").mockReturnValue({
      location: { href: "" },
      close: vi.fn(),
    } as any);

    render(
      <RegularizeAttendanceModal
        isOpen={true}
        onClose={vi.fn()}
        isAdmin={true}
        employeeName="John Doe"
        attendanceDate="2026-11-15"
        existingReason="Forgot swipe"
        existingAttachmentUrl="/api/v1/attendance/att-1/attachment"
        onSubmit={vi.fn()}
      />
    );

    const viewAttachmentBtn = screen.getByRole("button", { name: /View Supporting Document/ });
    expect(viewAttachmentBtn).toBeInTheDocument();

    fireEvent.click(viewAttachmentBtn);

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        "/attendance/att-1/attachment",
        expect.objectContaining({ responseType: "blob" })
      );
      expect(createObjectURLSpy).toHaveBeenCalledWith(fakeBlob);
    });

    // Advance timers by 60s
    vi.advanceTimersByTime(60000);

    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:http://localhost/test-uuid");
  });
});
