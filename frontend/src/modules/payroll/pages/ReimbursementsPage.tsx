import { useState, useEffect } from "react";
import {
  listReimbursements,
  submitReimbursement,
  reviewReimbursement,
  type Reimbursement,
  type ReimbursementStatus,
  type ReimbursementType,
} from "../api";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { formatDate } from "../../../shared/utils/date";
import { parseApiError } from "../../../shared/api/errors";

export function ReimbursementsPage() {
  const { user } = useAuth();
  const { notify } = useToast();

  const [claims, setClaims] = useState<Reimbursement[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<ReimbursementStatus | "all">("all");

  // Submit Modal state
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [type, setType] = useState<ReimbursementType>("travel");
  const [amount, setAmount] = useState("1000.00");
  const [expenseDate, setExpenseDate] = useState(new Date().toISOString().split("T")[0]);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [receiptFile, setReceiptFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // Review Modal state
  const [selectedClaim, setSelectedClaim] = useState<Reimbursement | null>(null);
  const [rejectionReason, setRejectionReason] = useState("");
  const [reviewing, setReviewing] = useState(false);

  const isHR = user?.role === "hr_admin" || user?.role === "super_admin" || user?.role === "owner";
  const isManager = user?.role === "manager";
  // Employees can NEVER approve or reject claims — only HR Admins and Managers can.
  // Managers can only review their direct reports' claims (enforced server-side too).
  const canReview = isHR || isManager;

  useEffect(() => {
    fetchClaims();
  }, [statusFilter]);

  async function fetchClaims() {
    setLoading(true);
    try {
      const res = await listReimbursements(
        statusFilter === "all" ? undefined : statusFilter
      );
      setClaims(res.items);
    } catch {
      notify("Failed to load reimbursement claims", "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmitClaim(e: React.FormEvent) {
    e.preventDefault();
    if (!description.trim() || Number(amount) <= 0) {
      notify("Please provide a valid amount and description", "error");
      return;
    }
    setSubmitting(true);
    try {
      await submitReimbursement({
        type,
        amount,
        expense_date: expenseDate,
        description,
      });
      notify("Reimbursement claim submitted successfully", "success");
      setShowSubmitModal(false);
      setDescription("");
      fetchClaims();
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to submit claim", parsed.status === 409 ? "warning" : "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReview(action: "approve" | "reject") {
    if (!selectedClaim) return;
    if (action === "reject" && !rejectionReason.trim()) {
      notify("Please provide a rejection reason", "error");
      return;
    }
    setReviewing(true);
    try {
      await reviewReimbursement(selectedClaim.id, {
        action,
        rejection_reason: action === "reject" ? rejectionReason : undefined,
      });
      notify(`Claim ${action}d successfully`, "success");
      setSelectedClaim(null);
      setRejectionReason("");
      fetchClaims();
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      notify(parsed.message || `Failed to ${action} claim`, parsed.status === 409 ? "warning" : "error");
    } finally {
      setReviewing(false);
    }
  }

  // Calculate summary metrics for Zoho-style KPI cards
  const totalApproved = claims
    .filter((c) => c.status === "approved" || c.status === "paid")
    .reduce((sum, c) => sum + Number(c.amount || 0), 0);
  const totalPending = claims
    .filter((c) => c.status === "pending")
    .reduce((sum, c) => sum + Number(c.amount || 0), 0);
  const totalPaidInPayroll = claims
    .filter((c) => c.status === "paid")
    .reduce((sum, c) => sum + Number(c.amount || 0), 0);

  return (
    <div className="container">
      <div className="page-header flex justify-between align-center page-header-responsive">
        <div>
          <h1>Reimbursements</h1>
          <p className="text-muted">Submit official business expense claims and track payroll payout approvals</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowSubmitModal(true)}>
          + Submit Claim
        </button>
      </div>

      {/* Zoho Expense KPI Summary Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: "12px",
          marginBottom: "1rem",
        }}
      >
        <div className="card p-3" style={{ background: "#f8fafc" }}>
          <div className="text-muted text-xs uppercase font-semibold">Total Claims</div>
          <div className="text-xl font-bold mt-1" style={{ color: "#0f172a" }}>
            {claims.length}
          </div>
          <div className="text-xs text-muted mt-1">Submitted in record</div>
        </div>

        <div className="card p-3" style={{ background: "#fefce8", border: "1px solid #fef08a" }}>
          <div className="text-xs uppercase font-semibold" style={{ color: "#854d0e" }}>⏳ Pending Approval</div>
          <div className="text-xl font-bold mt-1" style={{ color: "#a16207" }}>
            ₹{totalPending.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="text-xs text-muted mt-1">Awaiting manager/HR review</div>
        </div>

        <div className="card p-3" style={{ background: "#f0fdf4", border: "1px solid #bbf7d0" }}>
          <div className="text-xs uppercase font-semibold" style={{ color: "#166534" }}>✓ Approved / Disbursed</div>
          <div className="text-xl font-bold mt-1 text-success">
            ₹{totalApproved.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
          </div>
          <div className="text-xs text-muted mt-1">₹{totalPaidInPayroll.toLocaleString("en-IN")} credited in payslips</div>
        </div>
      </div>

      {/* Filter Tabs */}
      <div
        className="flex gap-2 my-4"
        style={{
          overflowX: "auto",
          paddingBottom: "4px",
          WebkitOverflowScrolling: "touch",
        }}
      >
        {(["all", "pending", "approved", "rejected", "paid"] as const).map((st) => (
          <button
            key={st}
            className={`btn btn-sm ${statusFilter === st ? "btn-primary" : "btn-outline"}`}
            style={{ whiteSpace: "nowrap" }}
            onClick={() => setStatusFilter(st)}
          >
            {st.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="card mt-4" style={{ padding: "0" }}>
        {loading ? (
          <div className="p-6 text-center text-muted">Loading reimbursement claims...</div>
        ) : claims.length === 0 ? (
          <div className="p-8 text-center text-muted">
            <span style={{ fontSize: "2rem", display: "block", marginBottom: "8px" }}>🧾</span>
            No reimbursement claims found for this filter.
          </div>
        ) : (
          <div className="mobile-table-wrap">
            <table className="table" style={{ margin: 0 }}>
              <thead>
                <tr style={{ background: "#f8fafc" }}>
                  <th style={{ padding: "12px 16px" }}>Date</th>
                  <th style={{ padding: "12px 16px" }}>Type</th>
                  <th style={{ padding: "12px 16px" }}>Description</th>
                  <th style={{ padding: "12px 16px" }}>Amount</th>
                  <th style={{ padding: "12px 16px" }}>Status</th>
                  {canReview && <th style={{ padding: "12px 16px" }}>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {claims.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => setSelectedClaim(c)}
                    style={{ cursor: "pointer", transition: "background 0.15s ease" }}
                    title="Click to view full receipt and audit details"
                  >
                    <td style={{ padding: "12px 16px", whiteSpace: "nowrap" }}>{formatDate(c.expense_date)}</td>
                    <td style={{ padding: "12px 16px", whiteSpace: "nowrap" }}>
                      <span className="badge badge-outline" style={{ textTransform: "capitalize" }}>{c.type}</span>
                    </td>
                    <td style={{ padding: "12px 16px", maxWidth: "260px" }}>
                      <div style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {c.description}
                      </div>
                    </td>
                    <td style={{ padding: "12px 16px", whiteSpace: "nowrap" }} className="fw-bold font-mono">
                      ₹{Number(c.amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </td>
                    <td style={{ padding: "12px 16px", whiteSpace: "nowrap" }}>
                      {/* 3-state reimbursement lifecycle badges */}
                      {c.status === "paid" ? (
                        <span className="badge badge-success" title="Included and paid in a finalised payroll run">
                          ✅ Paid in Payroll
                        </span>
                      ) : c.status === "approved" && c.added_to_payroll_run_id ? (
                        <span
                          className="badge"
                          style={{ backgroundColor: "#fef3c7", color: "#92400e", border: "1px solid #fcd34d" }}
                          title="Locked into an active pay run — awaiting payroll finalization"
                        >
                          🔒 Locked in Pay Run
                        </span>
                      ) : c.status === "approved" ? (
                        <span
                          className="badge"
                          style={{ backgroundColor: "#ecfdf5", color: "#065f46", border: "1px solid #6ee7b7" }}
                          title="Approved — will roll into the next open pay run automatically"
                        >
                          ⏳ Pending Payroll
                        </span>
                      ) : c.status === "rejected" ? (
                        <span className="badge badge-danger text-red">Rejected</span>
                      ) : (
                        <span className="badge badge-warning">Pending Approval</span>
                      )}
                    </td>
                    {canReview && (
                      <td style={{ padding: "12px 16px", whiteSpace: "nowrap" }}>
                        {c.status === "pending" && (
                          <button
                            className="btn btn-sm btn-outline"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedClaim(c);
                            }}
                          >
                            Review
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal: Submit Claim */}
      {showSubmitModal && (
        <div className="modal-backdrop" onClick={() => setShowSubmitModal(false)}>
          <div className="modal card max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Submit Reimbursement Claim</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowSubmitModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleSubmitClaim} className="stack gap-4 my-2">
              <div className="grid-2">
                <div className="field">
                  <label>Expense Type</label>
                  <select value={type} onChange={(e) => setType(e.target.value as ReimbursementType)}>
                    <option value="travel">Travel</option>
                    <option value="food">Food & Meals</option>
                    <option value="medical">Medical</option>
                    <option value="telephone">Telephone / Internet</option>
                    <option value="other">Other</option>
                  </select>
                </div>
                <div className="field">
                  <label>Amount (₹) *</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    placeholder="0.00"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="field">
                <label>Expense Date *</label>
                <input
                  type="date"
                  value={expenseDate}
                  onChange={(e) => setExpenseDate(e.target.value)}
                  required
                />
              </div>

              <div className="field">
                <label>Description & Purpose *</label>
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Explain the expense details..."
                  required
                />
              </div>

              {/* Receipt Drag & Drop Zone */}
              <div className="field">
                <label>Receipt / Invoice Attachment (PDF / PNG / JPG)</label>
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setIsDragging(false);
                    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                      setReceiptFile(e.dataTransfer.files[0]);
                    }
                  }}
                  style={{
                    border: `2px dashed ${isDragging ? "var(--color-primary, #2563eb)" : "var(--color-border, #d1d5db)"}`,
                    borderRadius: "8px",
                    padding: "1.25rem",
                    textAlign: "center",
                    backgroundColor: isDragging ? "rgba(37, 99, 235, 0.04)" : "var(--color-surface, #f9fafb)",
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                  onClick={() => document.getElementById("receipt-file-input")?.click()}
                >
                  <input
                    id="receipt-file-input"
                    type="file"
                    accept=".pdf,image/png,image/jpeg,image/jpg"
                    style={{ display: "none" }}
                    onChange={(e) => {
                      if (e.target.files && e.target.files[0]) {
                        setReceiptFile(e.target.files[0]);
                      }
                    }}
                  />
                  {receiptFile ? (
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "8px" }}>
                      <span style={{ fontSize: "1.25rem" }}>📄</span>
                      <div style={{ textAlign: "left" }}>
                        <div style={{ fontWeight: 600, fontSize: "0.875rem" }}>{receiptFile.name}</div>
                        <div style={{ fontSize: "0.75rem", color: "var(--color-muted, #6b7280)" }}>
                          {(receiptFile.size / 1024).toFixed(1)} KB
                        </div>
                      </div>
                      <button
                        type="button"
                        className="btn btn-xs btn-ghost"
                        style={{ marginLeft: "8px", color: "#dc2626" }}
                        onClick={(e) => {
                          e.stopPropagation();
                          setReceiptFile(null);
                        }}
                      >
                        ✕ Remove
                      </button>
                    </div>
                  ) : (
                    <div>
                      <div style={{ fontSize: "1.5rem", marginBottom: "4px" }}>📎</div>
                      <div style={{ fontWeight: 500, fontSize: "0.875rem" }}>
                        Drag & drop receipt here, or <span style={{ color: "var(--color-primary, #2563eb)" }}>browse files</span>
                      </div>
                      <div style={{ fontSize: "0.75rem", color: "var(--color-muted, #6b7280)", marginTop: "2px" }}>
                        Supports PDF, PNG, JPG up to 10MB
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowSubmitModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? "Submitting..." : "Submit"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: View Claim Details & Manager/HR Review */}
      {selectedClaim && (
        <div className="modal-backdrop" onClick={() => setSelectedClaim(null)}>
          <div className="modal card max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{canReview && selectedClaim.status === "pending" ? "Review Reimbursement Claim" : "Reimbursement Claim Details"}</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setSelectedClaim(null)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <div className="stack gap-3 my-2">
              <div className="p-3 bg-muted rounded border stack gap-2">
                <div>
                  <span className="text-muted text-xs block">Expense Type & Amount</span>
                  <strong className="text-base">
                    {selectedClaim.type.toUpperCase()} — ₹{Number(selectedClaim.amount).toLocaleString()}
                  </strong>
                </div>
                <div>
                  <span className="text-muted text-xs block">Date & Description</span>
                  <p className="text-sm mt-1">{formatDate(selectedClaim.expense_date)}: {selectedClaim.description}</p>
                </div>
                <div>
                  <span className="text-muted text-xs block">Current Status</span>
                  <span className="mt-1 inline-block">
                    {selectedClaim.status === "paid" ? (
                      <span className="badge badge-success">✅ Paid in Payroll</span>
                    ) : selectedClaim.status === "approved" ? (
                      <span className="badge" style={{ backgroundColor: "#ecfdf5", color: "#065f46", border: "1px solid #6ee7b7" }}>
                        ⏳ Approved • Pending Payroll
                      </span>
                    ) : selectedClaim.status === "rejected" ? (
                      <span className="badge badge-danger text-red">Rejected</span>
                    ) : (
                      <span className="badge badge-warning">Pending Approval</span>
                    )}
                  </span>
                </div>
              </div>

              {canReview && selectedClaim.status === "pending" && (
                <div className="field">
                  <label>Rejection Reason (required if rejecting)</label>
                  <input
                    type="text"
                    placeholder="Enter reason if rejecting..."
                    value={rejectionReason}
                    onChange={(e) => setRejectionReason(e.target.value)}
                  />
                </div>
              )}
            </div>

            <div className="flex gap-2 justify-end mt-4">
              {canReview && selectedClaim.status === "pending" ? (
                <>
                  <button
                    className="btn btn-danger"
                    onClick={() => handleReview("reject")}
                    disabled={reviewing}
                  >
                    Reject
                  </button>
                  <button
                    className="btn btn-success"
                    onClick={() => handleReview("approve")}
                    disabled={reviewing}
                  >
                    Approve
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => setSelectedClaim(null)}
                >
                  Close
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
