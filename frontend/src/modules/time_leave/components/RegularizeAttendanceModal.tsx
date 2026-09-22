import React, { useState, useMemo } from "react";
import { formatDate } from "../../../shared/utils/date";
import { parseApiError } from "../../../shared/api/errors";

export interface Props {
  isOpen: boolean;
  onClose: () => void;
  isAdmin: boolean;
  employeeName: string;
  attendanceDate: string;
  currentStatus?: string;
  initialCheckIn?: string | null;
  initialCheckOut?: string | null;
  existingReason?: string | null;
  existingAttachmentUrl?: string | null;
  onSubmit: (data: FormData) => Promise<void>;
  onApprove?: (adjustedCheckIn?: string, adjustedCheckOut?: string, adminNotes?: string) => Promise<void>;
  onReject?: (rejectionReason: string) => Promise<void>;
}

export const RegularizeAttendanceModal: React.FC<Props> = ({
  isOpen,
  onClose,
  isAdmin,
  employeeName,
  attendanceDate,
  currentStatus,
  initialCheckIn,
  initialCheckOut,
  existingReason,
  existingAttachmentUrl,
  onSubmit,
  onApprove,
  onReject,
}) => {
  // Helper to convert ISO string to datetime-local input string YYYY-MM-DDTHH:mm
  const toDateTimeLocal = (isoStr?: string | null, fallbackDate?: string, defaultTime = "09:00"): string => {
    if (isoStr) {
      try {
        const d = new Date(isoStr);
        if (!isNaN(d.getTime())) {
          const pad = (n: number) => String(n).padStart(2, "0");
          return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
        }
      } catch {
        // ignore
      }
    }
    return fallbackDate ? `${fallbackDate}T${defaultTime}` : "";
  };

  const [checkIn, setCheckIn] = useState<string>(() =>
    toDateTimeLocal(initialCheckIn, attendanceDate, "09:00")
  );
  const [checkOut, setCheckOut] = useState<string>(() =>
    toDateTimeLocal(initialCheckOut, attendanceDate, "18:00")
  );
  const [reason, setReason] = useState(existingReason || "");
  const [adminNotes, setAdminNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [rejectionReason, setRejectionReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Live calculated duration
  const { computedHours, durationLabel, durationColor } = useMemo(() => {
    if (!checkIn || !checkOut) {
      return { computedHours: 0, durationLabel: "0.00 hours", durationColor: "var(--color-muted, #64748b)" };
    }
    const tIn = new Date(checkIn).getTime();
    const tOut = new Date(checkOut).getTime();
    if (isNaN(tIn) || isNaN(tOut) || tOut <= tIn) {
      return { computedHours: 0, durationLabel: "Invalid Range (Out ≤ In)", durationColor: "#dc2626" };
    }
    const hours = Math.round(((tOut - tIn) / (1000 * 3600)) * 100) / 100;
    let label = `${hours.toFixed(2)} hours`;
    let color = "#dc2626"; // Under minimum / absent

    if (hours >= 7.5) {
      label += " (Full Day)";
      color = "#16a34a"; // Green
    } else if (hours >= 4.0) {
      label += " (Half Day)";
      color = "#d97706"; // Amber
    } else {
      label += " (Under Minimum)";
      color = "#dc2626";
    }

    return { computedHours: hours, durationLabel: label, durationColor: color };
  }, [checkIn, checkOut]);

  if (!isOpen) return null;

  // Handle Employee Submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (checkIn && checkOut && new Date(checkOut) <= new Date(checkIn)) {
      setError("Actual Check-Out must be strictly after Actual Check-In time.");
      return;
    }

    if (!isAdmin) {
      if (!reason.trim()) {
        setError("Please provide a mandatory explanation / reason for regularization.");
        return;
      }
    }

    setBusy(true);
    try {
      if (isAdmin && onApprove) {
        const inIso = checkIn ? new Date(checkIn).toISOString() : undefined;
        const outIso = checkOut ? new Date(checkOut).toISOString() : undefined;
        await onApprove(inIso, outIso, adminNotes);
      } else {
        const formData = new FormData();
        const inIso = checkIn ? new Date(checkIn).toISOString() : "";
        const outIso = checkOut ? new Date(checkOut).toISOString() : "";

        formData.append("check_in", inIso);
        formData.append("check_out", outIso);

        if (isAdmin) {
          if (adminNotes.trim()) formData.append("admin_notes", adminNotes.trim());
        } else {
          formData.append("reason", reason.trim());
          if (file) {
            formData.append("attachment", file);
          }
        }

        await onSubmit(formData);
      }
      onClose();
    } catch (err) {
      setError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  };

  // Handle Admin Direct Reject
  const handleRejectConfirm = async () => {
    if (!rejectionReason.trim()) {
      setError("Rejection reason is mandatory when rejecting a regularization request.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (onReject) {
        await onReject(rejectionReason.trim());
      }
      onClose();
    } catch (err) {
      setError(parseApiError(err).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "rgba(15, 23, 42, 0.45)",
        backdropFilter: "blur(4px)",
        padding: "16px",
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: "#ffffff",
          borderRadius: "16px",
          boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
          border: "1px solid #e2e8f0",
          width: "100%",
          maxWidth: "540px",
          overflow: "hidden",
          animation: "modalSlideIn 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          style={{
            padding: "18px 24px",
            borderBottom: "1px solid #f1f5f9",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: isAdmin ? "linear-gradient(135deg, #f8fafc 0%, #eff6ff 100%)" : "#ffffff",
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "1.2rem" }}>{isAdmin ? "🛡️" : "⏱️"}</span>
              <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#1e293b" }}>
                {isAdmin ? `Review Regularization — ${employeeName}` : "Apply for Regularization"}
              </h3>
            </div>
            <p style={{ margin: "4px 0 0 0", fontSize: "0.8rem", color: "#64748b" }}>
              {isAdmin
                ? `Inspect and verify missed punch timestamps for ${formatDate(attendanceDate)}.`
                : "Correct your punch-in/out timestamps for accurate payroll hours."}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            style={{
              background: "transparent",
              border: "none",
              color: "#94a3b8",
              fontSize: "1.25rem",
              cursor: "pointer",
              padding: "4px 8px",
              borderRadius: "6px",
              lineHeight: 1,
            }}
            title="Close"
          >
            ✕
          </button>
        </div>

        {/* Error notification banner */}
        {error && (
          <div
            style={{
              margin: "16px 24px 0 24px",
              padding: "10px 14px",
              backgroundColor: "#fef2f2",
              border: "1px solid #fecaca",
              borderRadius: "8px",
              color: "#b91c1c",
              fontSize: "0.84rem",
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* Rejection Sub-Modal Form (when Admin clicks Reject) */}
        {rejecting ? (
          <div style={{ padding: "20px 24px" }}>
            <div
              style={{
                backgroundColor: "#fff1f2",
                border: "1px solid #fecdd3",
                borderRadius: "10px",
                padding: "14px",
                marginBottom: "16px",
              }}
            >
              <h4 style={{ margin: "0 0 6px 0", color: "#9f1239", fontSize: "0.92rem", fontWeight: 700 }}>
                Reject Regularization Request
              </h4>
              <p style={{ margin: 0, fontSize: "0.82rem", color: "#be123c" }}>
                Please provide a rejection note explaining why this attendance request is being turned down. The employee will receive this feedback.
              </p>
            </div>

            <div className="field" style={{ marginBottom: "16px" }}>
              <label style={{ display: "block", fontSize: "0.82rem", fontWeight: 600, color: "#334155", marginBottom: "6px" }}>
                Rejection Reason (Mandatory) *
              </label>
              <textarea
                rows={3}
                placeholder="e.g., Gate logs show exit at 2:15 PM without outdoor duty slip; unapproved absence."
                value={rejectionReason}
                onChange={(e) => setRejectionReason(e.target.value)}
                autoFocus
                required
                style={{
                  width: "100%",
                  fontSize: "0.85rem",
                  padding: "8px 12px",
                  borderRadius: "8px",
                  border: "1px solid #cbd5e1",
                  boxSizing: "border-box",
                }}
              />
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
              <button
                type="button"
                onClick={() => setRejecting(false)}
                disabled={busy}
                className="btn"
                style={{ fontSize: "0.85rem" }}
              >
                Back to Review
              </button>
              <button
                type="button"
                onClick={handleRejectConfirm}
                disabled={busy || !rejectionReason.trim()}
                style={{
                  backgroundColor: "#e11d48",
                  color: "#ffffff",
                  border: "none",
                  padding: "8px 16px",
                  borderRadius: "8px",
                  fontSize: "0.85rem",
                  fontWeight: 600,
                  cursor: busy || !rejectionReason.trim() ? "not-allowed" : "pointer",
                  opacity: busy || !rejectionReason.trim() ? 0.6 : 1,
                }}
              >
                {busy ? "Rejecting…" : "Confirm Rejection"}
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={{ padding: "20px 24px" }}>
            {/* Time Picker Card */}
            <div
              style={{
                backgroundColor: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: "12px",
                padding: "16px",
                marginBottom: "16px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <span style={{ fontSize: "0.78rem", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {isAdmin ? "Adjust Timings (If Needed)" : "Requested Clock Times"}
                </span>
                {currentStatus && (
                  <span
                    style={{
                      fontSize: "0.72rem",
                      fontWeight: 600,
                      padding: "2px 8px",
                      borderRadius: "6px",
                      backgroundColor: "#e2e8f0",
                      color: "#334155",
                    }}
                  >
                    Recorded: {currentStatus.replace("_", " ")}
                  </span>
                )}
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "0.78rem", fontWeight: 600, color: "#334155", marginBottom: "4px" }}>
                    Actual Check-In Time *
                  </label>
                  <input
                    type="datetime-local"
                    value={checkIn}
                    onChange={(e) => setCheckIn(e.target.value)}
                    required
                    style={{
                      width: "100%",
                      fontSize: "0.84rem",
                      border: "1px solid #cbd5e1",
                      borderRadius: "8px",
                      padding: "8px 10px",
                      boxSizing: "border-box",
                      backgroundColor: "#ffffff",
                    }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "0.78rem", fontWeight: 600, color: "#334155", marginBottom: "4px" }}>
                    Actual Check-Out Time *
                  </label>
                  <input
                    type="datetime-local"
                    value={checkOut}
                    onChange={(e) => setCheckOut(e.target.value)}
                    required
                    style={{
                      width: "100%",
                      fontSize: "0.84rem",
                      border: "1px solid #cbd5e1",
                      borderRadius: "8px",
                      padding: "8px 10px",
                      boxSizing: "border-box",
                      backgroundColor: "#ffffff",
                    }}
                  />
                </div>
              </div>

              {/* Calculated Duration Preview */}
              <div
                style={{
                  marginTop: "12px",
                  paddingTop: "10px",
                  borderTop: "1px dashed #cbd5e1",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  fontSize: "0.82rem",
                }}
              >
                <span style={{ color: "#64748b", fontWeight: 500 }}>Calculated Duration Preview:</span>
                <span style={{ fontWeight: 700, color: durationColor }}>
                  {durationLabel}
                </span>
              </div>
            </div>

            {/* Role-Aware Middle Content */}
            {isAdmin ? (
              /* ADMIN / MANAGER PERSPECTIVE: "Review & Regularize" */
              <div style={{ display: "flex", flexDirection: "column", gap: "14px", marginBottom: "20px" }}>
                {/* Audit Trail Inspection */}
                <div
                  style={{
                    backgroundColor: "#f1f5f9",
                    border: "1px solid #e2e8f0",
                    borderRadius: "10px",
                    padding: "14px",
                  }}
                >
                  <span
                    style={{
                      fontSize: "0.72rem",
                      fontWeight: 700,
                      color: "#475569",
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      display: "block",
                      marginBottom: "4px",
                    }}
                  >
                    Employee's Submitted Reason
                  </span>
                  <p style={{ margin: 0, fontSize: "0.86rem", color: "#1e293b", fontStyle: "italic", lineHeight: 1.4 }}>
                    "{existingReason || "No explanation recorded"}"
                  </p>

                  {/* Supporting Document preview for admin */}
                  {existingAttachmentUrl && (
                    <div
                      style={{
                        marginTop: "10px",
                        paddingTop: "8px",
                        borderTop: "1px solid #e2e8f0",
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                      }}
                    >
                      <span style={{ fontSize: "0.9rem" }}>📎</span>
                      <a
                        href={existingAttachmentUrl}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          fontSize: "0.82rem",
                          fontWeight: 600,
                          color: "#2563eb",
                          textDecoration: "underline",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        View Supporting Document ↗
                      </a>
                    </div>
                  )}
                </div>

                {/* Admin Optional Notes */}
                <div>
                  <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "#334155", marginBottom: "4px" }}>
                    Admin / Manager Notes (Optional)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g., Client visit confirmed with client lead"
                    value={adminNotes}
                    onChange={(e) => setAdminNotes(e.target.value)}
                    style={{
                      width: "100%",
                      fontSize: "0.84rem",
                      border: "1px solid #cbd5e1",
                      borderRadius: "8px",
                      padding: "8px 12px",
                      boxSizing: "border-box",
                    }}
                  />
                </div>
              </div>
            ) : (
              /* EMPLOYEE PERSPECTIVE: "Apply for Regularization" */
              <div style={{ display: "flex", flexDirection: "column", gap: "14px", marginBottom: "20px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "#334155", marginBottom: "4px" }}>
                    Reason for Regularization (Mandatory) *
                  </label>
                  <textarea
                    rows={2}
                    placeholder="e.g., Device was offline during morning punch, or attended client meeting offsite."
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    required
                    style={{
                      width: "100%",
                      fontSize: "0.84rem",
                      border: "1px solid #cbd5e1",
                      borderRadius: "8px",
                      padding: "8px 12px",
                      boxSizing: "border-box",
                    }}
                  />
                </div>

                {/* File Attachment Dropzone */}
                <div>
                  <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "#334155", marginBottom: "4px" }}>
                    Supporting Document (Optional / Recommended)
                  </label>
                  <div
                    style={{
                      border: "1px dashed #cbd5e1",
                      borderRadius: "10px",
                      padding: "12px 16px",
                      textAlign: "center",
                      backgroundColor: "#f8fafc",
                    }}
                  >
                    <input
                      type="file"
                      accept=".pdf,.png,.jpg,.jpeg"
                      onChange={(e) => setFile(e.target.files?.[0] || null)}
                      style={{ fontSize: "0.82rem", color: "#475569" }}
                    />
                    <p style={{ margin: "6px 0 0 0", fontSize: "0.74rem", color: "#94a3b8" }}>
                      Upload gate pass, client approval email, or outdoor duty slip (PDF, PNG, JPG up to 10MB)
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Modal Action Buttons */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                paddingTop: "14px",
                borderTop: "1px solid #f1f5f9",
              }}
            >
              <div>
                {isAdmin && onReject && (
                  <button
                    type="button"
                    onClick={() => setRejecting(true)}
                    disabled={busy}
                    style={{
                      backgroundColor: "#fee2e2",
                      color: "#b91c1c",
                      border: "1px solid #fca5a5",
                      padding: "7px 14px",
                      borderRadius: "8px",
                      fontSize: "0.82rem",
                      fontWeight: 600,
                      cursor: busy ? "not-allowed" : "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "4px",
                    }}
                  >
                    <span>❌</span> <span>Reject</span>
                  </button>
                )}
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <button
                  type="button"
                  onClick={onClose}
                  disabled={busy}
                  className="btn"
                  style={{ fontSize: "0.84rem", padding: "7px 14px" }}
                >
                  Cancel
                </button>

                {isAdmin ? (
                  <button
                    type="submit"
                    disabled={busy || computedHours <= 0}
                    style={{
                      backgroundColor: "#2563eb",
                      color: "#ffffff",
                      border: "none",
                      padding: "8px 18px",
                      borderRadius: "8px",
                      fontSize: "0.84rem",
                      fontWeight: 600,
                      boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
                      cursor: busy || computedHours <= 0 ? "not-allowed" : "pointer",
                      opacity: busy || computedHours <= 0 ? 0.6 : 1,
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                    }}
                  >
                    <span>{checkIn !== toDateTimeLocal(initialCheckIn, attendanceDate, "09:00") || checkOut !== toDateTimeLocal(initialCheckOut, attendanceDate, "18:00") ? "✏️" : "✔"}</span>
                    <span>
                      {busy
                        ? "Saving…"
                        : checkIn !== toDateTimeLocal(initialCheckIn, attendanceDate, "09:00") || checkOut !== toDateTimeLocal(initialCheckOut, attendanceDate, "18:00")
                        ? "Adjust & Approve"
                        : "Approve & Regularize"}
                    </span>
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={busy || computedHours <= 0}
                    style={{
                      backgroundColor: "#2563eb",
                      color: "#ffffff",
                      border: "none",
                      padding: "8px 18px",
                      borderRadius: "8px",
                      fontSize: "0.84rem",
                      fontWeight: 600,
                      boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
                      cursor: busy || computedHours <= 0 ? "not-allowed" : "pointer",
                      opacity: busy || computedHours <= 0 ? 0.6 : 1,
                    }}
                  >
                    {busy ? "Submitting…" : "Submit Regularization Request"}
                  </button>
                )}
              </div>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
