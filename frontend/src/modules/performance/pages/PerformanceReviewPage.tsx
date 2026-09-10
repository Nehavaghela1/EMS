import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import {
  listPerformanceCycles,
  listPerformanceGoals,
  submitManagerReview,
  getPerformanceSummary,
  finalizePerformanceSummary,
  type PerformanceCycle,
  type PerformanceGoal,
  type PerformanceSummary,
} from "../api";
import { getEmployee, type Employee } from "../../hr/api";
import { useToast } from "../../../app/toast-context";

export function PerformanceReviewPage() {
  const { employeeId } = useParams<{ employeeId: string }>();
  const { notify } = useToast();

  const [employee, setEmployee] = useState<Employee | null>(null);
  const [activeCycle, setActiveCycle] = useState<PerformanceCycle | null>(null);
  const [goals, setGoals] = useState<PerformanceGoal[]>([]);
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [loading, setLoading] = useState(true);

  // Review Modal state
  const [selectedGoal, setSelectedGoal] = useState<PerformanceGoal | null>(null);
  const [mgrRating, setMgrRating] = useState("4.0");
  const [mgrComments, setMgrComments] = useState("");
  const [submittingReview, setSubmittingReview] = useState(false);

  // Finalize Summary Form state
  const [overallComments, setOverallComments] = useState("");
  const [salaryRevision, setSalaryRevision] = useState(true);
  const [incrementPercent, setIncrementPercent] = useState("10.00");
  const [finalizing, setFinalizing] = useState(false);

  useEffect(() => {
    if (employeeId) {
      fetchData(employeeId);
    }
  }, [employeeId]);

  async function fetchData(empId: string) {
    setLoading(true);
    try {
      const [empRes, cyclesRes, empGoals, sumRes] = await Promise.all([
        getEmployee(empId),
        listPerformanceCycles("active"),
        listPerformanceGoals(empId),
        getPerformanceSummary(empId),
      ]);
      setEmployee(empRes);
      if (cyclesRes.items.length > 0) {
        setActiveCycle(cyclesRes.items[0]);
      }
      setGoals(empGoals);
      setSummary(sumRes);
    } catch {
      notify("Failed to load employee evaluation data", "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmitManagerReview(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedGoal) return;
    setSubmittingReview(true);
    try {
      await submitManagerReview(selectedGoal.id, {
        rating: mgrRating,
        comments: mgrComments,
      });
      notify("Manager evaluation submitted successfully", "success");
      setSelectedGoal(null);
      setMgrComments("");
      if (employeeId) fetchData(employeeId);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to submit manager rating";
      notify(msg, "error");
    } finally {
      setSubmittingReview(false);
    }
  }

  async function handleFinalizeSummary(e: React.FormEvent) {
    e.preventDefault();
    if (!employeeId || !activeCycle) return;
    setFinalizing(true);
    try {
      const res = await finalizePerformanceSummary(employeeId, {
        cycle_id: activeCycle.id,
        overall_comments: overallComments,
        salary_revision_recommended: salaryRevision,
        recommended_increment_percent: salaryRevision ? incrementPercent : null,
      });
      setSummary(res);
      notify("Performance evaluation finalized successfully", "success");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to finalize summary";
      notify(msg, "error");
    } finally {
      setFinalizing(false);
    }
  }

  return (
    <div className="container">
      <div className="page-header">
        <h1>Performance Review & Rating</h1>
        <p className="text-muted">
          Evaluating: <strong>{employee ? `${employee.first_name} ${employee.last_name || ""}` : "Employee"}</strong> ({employee?.employee_code})
        </p>
      </div>

      {loading ? (
        <p className="mt-4">Loading appraisal review...</p>
      ) : (
        <div className="grid grid-3 gap-6 mt-4">
          {/* Goals & Reviews Column */}
          <div className="col-span-2 stack gap-4">
            <div className="card">
              <h3 className="mb-3">Assigned Goals & Self Evaluations</h3>
              {goals.length === 0 ? (
                <p className="text-muted">No goals set for this employee in the active cycle.</p>
              ) : (
                <div className="stack gap-4">
                  {goals.map((g) => (
                    <div key={g.id} className="p-4 border rounded stack gap-2">
                      <div className="flex justify-between align-center">
                        <strong className="text-base">{g.title}</strong>
                        <span className="badge badge-outline">Weightage: {g.weightage}%</span>
                      </div>
                      <p className="text-sm text-muted">{g.description || "No description"}</p>
                      <div className="text-xs">
                        Target Metric: <strong>{g.target_value || "N/A"}</strong>
                      </div>

                      {/* Self Rating */}
                      <div className="p-3 bg-muted rounded flex justify-between align-center mt-2">
                        <div>
                          <span className="text-xs text-muted block">Self Evaluation</span>
                          <span className="text-sm">{g.self_comments || "No comments"}</span>
                        </div>
                        {g.self_rating ? (
                          <span className="badge badge-success font-mono">{g.self_rating} / 5.0</span>
                        ) : (
                          <span className="text-muted text-xs">Self rating pending</span>
                        )}
                      </div>

                      {/* Action */}
                      <div className="flex justify-end mt-2">
                        <button
                          className="btn btn-sm btn-primary"
                          onClick={() => setSelectedGoal(g)}
                        >
                          Rate Goal as Manager
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Final Summary Column */}
          <div className="stack gap-4">
            <div className="card p-6 stack gap-4">
              <h3>Evaluation Summary</h3>

              {summary ? (
                <div className="stack gap-3 p-4 bg-success-subtle border border-success rounded">
                  <div>
                    <span className="text-xs text-muted block">FINAL WEIGHTED RATING</span>
                    <span className="text-3xl fw-bold text-success">{summary.final_rating} / 5.0</span>
                  </div>
                  {summary.overall_comments && (
                    <div>
                      <span className="text-xs text-muted block">Manager / HR Comments</span>
                      <p className="text-sm">{summary.overall_comments}</p>
                    </div>
                  )}
                  {summary.salary_revision_recommended && (
                    <div className="p-2 bg-white rounded border text-xs">
                      ✅ Recommended Increment: <strong>{summary.recommended_increment_percent}%</strong>
                    </div>
                  )}
                </div>
              ) : (
                <form onSubmit={handleFinalizeSummary} className="stack gap-4">
                  <p className="text-sm text-muted">
                    Finalize evaluation rating for the cycle based on weighted goal scores.
                  </p>

                  <div>
                    <label>Overall Comments</label>
                    <textarea
                      rows={3}
                      placeholder="Overall performance summary..."
                      value={overallComments}
                      onChange={(e) => setOverallComments(e.target.value)}
                    />
                  </div>

                  <label className="flex gap-2 align-center text-sm">
                    <input
                      type="checkbox"
                      checked={salaryRevision}
                      onChange={(e) => setSalaryRevision(e.target.checked)}
                    />
                    Recommend Salary Increment / Revision
                  </label>

                  {salaryRevision && (
                    <div>
                      <label>Recommended Increment (%)</label>
                      <input
                        type="number"
                        step="0.01"
                        value={incrementPercent}
                        onChange={(e) => setIncrementPercent(e.target.value)}
                        required
                      />
                    </div>
                  )}

                  <button type="submit" className="btn btn-primary" disabled={finalizing}>
                    {finalizing ? "Finalizing..." : "Finalize Evaluation"}
                  </button>
                </form>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Modal: Rate Goal */}
      {selectedGoal && (
        <div className="modal-backdrop" onClick={() => setSelectedGoal(null)}>
          <div className="modal card max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Rate Goal: {selectedGoal.title}</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setSelectedGoal(null)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleSubmitManagerReview} className="stack gap-4 my-2">
              <div className="field">
                <label>Manager Rating (1.0 to 5.0)</label>
                <select value={mgrRating} onChange={(e) => setMgrRating(e.target.value)}>
                  <option value="5.0">5.0 — Outstanding / Exceeds All Expectations</option>
                  <option value="4.0">4.0 — Exceeds Expectations</option>
                  <option value="3.0">3.0 — Meets Expectations</option>
                  <option value="2.0">2.0 — Needs Improvement</option>
                  <option value="1.0">1.0 — Unsatisfactory</option>
                </select>
              </div>

              <div className="field">
                <label>Manager Feedback & Comments</label>
                <textarea
                  rows={4}
                  placeholder="Feedback on employee's achievements and performance..."
                  value={mgrComments}
                  onChange={(e) => setMgrComments(e.target.value)}
                  required
                />
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setSelectedGoal(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingReview}>
                  {submittingReview ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
