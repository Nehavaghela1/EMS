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

  // Review Modal state
  const [selectedClaim, setSelectedClaim] = useState<Reimbursement | null>(null);
  const [rejectionReason, setRejectionReason] = useState("");
  const [reviewing, setReviewing] = useState(false);

  const isHR = user?.role === "hr_admin" || user?.role === "super_admin";
  const isManager = user?.role === "manager";
  const canReview = isHR || isManager;

  useEffect(() => {
    fetchClaims();
  }, [statusFilter]);

  async function fetchClaims() {
    setLoading(true);
    try {
      const filterArg = statusFilter === "all" ? undefined : statusFilter;
      const res = await listReimbursements(filterArg);
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
      const msg = err instanceof Error ? err.message : "Failed to submit claim";
      notify(msg, "error");
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
      const msg = err instanceof Error ? err.message : `Failed to ${action} claim`;
      notify(msg, "error");
    } finally {
      setReviewing(false);
    }
  }

  return (
    <div className="container">
      <div className="page-header flex justify-between align-center">
        <div>
          <h1>Reimbursements</h1>
          <p className="text-muted">Submit expense claims and manage approvals</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowSubmitModal(true)}>
          + Submit Claim
        </button>
      </div>

      {/* Filter Tabs */}
      <div className="flex gap-2 my-4">
        {(["all", "pending", "approved", "rejected", "paid"] as const).map((st) => (
          <button
            key={st}
            className={`btn btn-sm ${statusFilter === st ? "btn-primary" : "btn-outline"}`}
            onClick={() => setStatusFilter(st)}
          >
            {st.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="card mt-4">
        {loading ? (
          <p>Loading reimbursement claims...</p>
        ) : claims.length === 0 ? (
          <p className="text-muted">No reimbursement claims found for this filter.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Type</th>
                <th>Description</th>
                <th>Amount</th>
                <th>Status</th>
                {canReview && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {claims.map((c) => (
                <tr key={c.id}>
                  <td>{c.expense_date}</td>
                  <td>
                    <span className="badge badge-outline">{c.type}</span>
                  </td>
                  <td>{c.description}</td>
                  <td className="fw-bold">₹{Number(c.amount).toLocaleString()}</td>
                  <td>
                    <span
                      className={`badge ${
                        c.status === "approved" || c.status === "paid"
                          ? "badge-success"
                          : c.status === "rejected"
                          ? "badge-danger text-red"
                          : "badge-warning"
                      }`}
                    >
                      {c.status}
                    </span>
                  </td>
                  {canReview && (
                    <td>
                      {c.status === "pending" && (
                        <button
                          className="btn btn-sm btn-outline"
                          onClick={() => setSelectedClaim(c)}
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
            <form onSubmit={handleSubmitClaim} className="stack gap-4">
              <div className="grid grid-2 gap-4">
                <div>
                  <label>Expense Type</label>
                  <select value={type} onChange={(e) => setType(e.target.value as ReimbursementType)}>
                    <option value="travel">Travel</option>
                    <option value="food">Food & Meals</option>
                    <option value="medical">Medical</option>
                    <option value="telephone">Telephone / Internet</option>
                    <option value="other">Other</option>
                  </select>
                </div>
                <div>
                  <label>Amount (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div>
                <label>Expense Date</label>
                <input
                  type="date"
                  value={expenseDate}
                  onChange={(e) => setExpenseDate(e.target.value)}
                  required
                />
              </div>

              <div>
                <label>Description & Purpose</label>
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Explain the expense details..."
                  required
                />
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowSubmitModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? "Submitting..." : "Submit Claim"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Review Claim */}
      {selectedClaim && (
        <div className="modal-backdrop" onClick={() => setSelectedClaim(null)}>
          <div className="modal card max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Review Reimbursement Claim</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setSelectedClaim(null)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <div className="stack gap-3 my-4">
              <div>
                <span className="text-muted text-xs block">Expense Type & Amount</span>
                <strong>
                  {selectedClaim.type.toUpperCase()} — ₹{Number(selectedClaim.amount).toLocaleString()}
                </strong>
              </div>
              <div>
                <span className="text-muted text-xs block">Date & Description</span>
                <p className="text-sm">{selectedClaim.expense_date}: {selectedClaim.description}</p>
              </div>

              <div>
                <label>Rejection Reason (required if rejecting)</label>
                <input
                  type="text"
                  placeholder="Enter reason if rejecting..."
                  value={rejectionReason}
                  onChange={(e) => setRejectionReason(e.target.value)}
                />
              </div>
            </div>

            <div className="flex gap-3 justify-end mt-4">
              <button
                className="btn btn-danger"
                onClick={() => handleReview("reject")}
                disabled={reviewing}
              >
                Reject Claim
              </button>
              <button
                className="btn btn-success"
                onClick={() => handleReview("approve")}
                disabled={reviewing}
              >
                Approve Claim
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
