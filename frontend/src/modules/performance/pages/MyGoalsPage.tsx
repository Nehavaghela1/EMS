import { useState, useEffect } from "react";
import {
  listPerformanceCycles,
  listPerformanceGoals,
  setPerformanceGoals,
  submitSelfReview,
  type PerformanceCycle,
  type PerformanceGoal,
  type GoalCreateItem,
} from "../api";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";

export function MyGoalsPage() {
  const { user } = useAuth();
  const { notify } = useToast();

  const [activeCycle, setActiveCycle] = useState<PerformanceCycle | null>(null);
  const [goals, setGoals] = useState<PerformanceGoal[]>([]);
  const [loading, setLoading] = useState(true);

  // Set Goals Modal state
  const [showSetModal, setShowSetModal] = useState(false);
  const [goalInputs, setGoalInputs] = useState<GoalCreateItem[]>([
    {
      title: "Deliver Feature Goals",
      description: "Complete key deliverables for the quarter",
      weightage: "50.00",
      target_value: "100% completed",
    },
    {
      title: "Quality & System Improvement",
      description: "Maintain 100% automated test pass rate",
      weightage: "50.00",
      target_value: "0 production bugs",
    },
  ]);
  const [submittingGoals, setSubmittingGoals] = useState(false);

  // Self Review Modal state
  const [selectedGoal, setSelectedGoal] = useState<PerformanceGoal | null>(null);
  const [selfRating, setSelfRating] = useState("4.0");
  const [selfComments, setSelfComments] = useState("");
  const [submittingReview, setSubmittingReview] = useState(false);

  const totalWeightage = goals.reduce((acc, g) => acc + Number(g.weightage), 0);
  const newGoalTotalWeightage = goalInputs.reduce((acc, g) => acc + Number(g.weightage || 0), 0);

  useEffect(() => {
    init();
  }, []);

  async function init() {
    setLoading(true);
    try {
      const res = await listPerformanceCycles("active");
      if (res.items.length > 0) {
        const cycle = res.items[0];
        setActiveCycle(cycle);
        // If user profile is available, fetch employee's goals
        if (user) {
          const targetId = user.employee?.id || user.id;
          const empGoals = await listPerformanceGoals(targetId);
          setGoals(empGoals);
        }
      }
    } catch {
      notify("Failed to load goals for active cycle", "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveGoals(e: React.FormEvent) {
    e.preventDefault();
    if (!activeCycle) return;
    if (newGoalTotalWeightage !== 100) {
      notify(`Goal weightages must sum to exactly 100% (currently ${newGoalTotalWeightage}%)`, "error");
      return;
    }
    setSubmittingGoals(true);
    try {
      await setPerformanceGoals({
        cycle_id: activeCycle.id,
        goals: goalInputs,
      });
      notify("Goals saved successfully", "success");
      setShowSetModal(false);
      init();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save goals";
      notify(msg, "error");
    } finally {
      setSubmittingGoals(false);
    }
  }

  async function handleSubmitSelfReview(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedGoal) return;
    if (totalWeightage !== 100) {
      notify(`Goal weightages must sum to exactly 100% before self-review can be submitted (currently ${totalWeightage}%)`, "error");
      return;
    }
    setSubmittingReview(true);
    try {
      await submitSelfReview(selectedGoal.id, {
        rating: selfRating,
        comments: selfComments,
      });
      notify("Self-review rating submitted successfully", "success");
      setSelectedGoal(null);
      setSelfComments("");
      init();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to submit self-review";
      notify(msg, "error");
    } finally {
      setSubmittingReview(false);
    }
  }

  function addGoalLine() {
    setGoalInputs([
      ...goalInputs,
      { title: "", description: "", weightage: "0.00", target_value: "" },
    ]);
  }

  function removeGoalLine(index: number) {
    setGoalInputs(goalInputs.filter((_, i) => i !== index));
  }

  return (
    <div className="container">
      <div className="page-header flex justify-between align-center">
        <div>
          <h1>My Performance Goals</h1>
          <p className="text-muted">Set goals for the active performance cycle & submit self-evaluations</p>
        </div>
        {activeCycle && goals.length === 0 && (
          <button className="btn btn-primary" onClick={() => setShowSetModal(true)}>
            + Set Goals for Active Cycle
          </button>
        )}
      </div>

      {/* Active Cycle Banner */}
      {activeCycle ? (
        <div className="p-4 bg-muted border rounded my-4 flex justify-between align-center">
          <div>
            <span className="text-xs text-muted block">Active Appraisal Period</span>
            <strong>{activeCycle.name}</strong> ({activeCycle.start_date} to {activeCycle.end_date})
          </div>
          <div>
            <span className="text-xs text-muted block">Self Review Deadline</span>
            <strong className="text-warning">{activeCycle.self_review_deadline || "Not set"}</strong>
          </div>
        </div>
      ) : (
        <div className="card my-4 p-6 text-center">
          <p className="text-muted">No active performance cycle currently open.</p>
        </div>
      )}

      {/* Weightage Warning if total != 100 */}
      {goals.length > 0 && totalWeightage !== 100 && (
        <div className="p-3 bg-warning-subtle border border-warning rounded my-4 flex justify-between align-center">
          <span className="text-warning-dark fw-bold text-sm">
            ⚠️ Warning: Total goal weightage is {totalWeightage}%. Weightages must sum to exactly 100.00% to enable self-review submission.
          </span>
        </div>
      )}

      {/* Goals List */}
      <div className="card mt-4">
        {loading ? (
          <p>Loading performance goals...</p>
        ) : goals.length === 0 ? (
          <p className="text-muted">No goals submitted yet for the current performance cycle.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Goal Title</th>
                <th>Target / Metric</th>
                <th>Weightage</th>
                <th>Status</th>
                <th>Self Rating</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {goals.map((g) => (
                <tr key={g.id}>
                  <td>
                    <div className="fw-bold">{g.title}</div>
                    <div className="text-xs text-muted">{g.description || "No description"}</div>
                  </td>
                  <td>{g.target_value || "—"}</td>
                  <td className="fw-bold">{g.weightage}%</td>
                  <td>
                    <span className="badge badge-outline">{g.status}</span>
                  </td>
                  <td>
                    {g.self_rating ? (
                      <span className="badge badge-success font-mono">{g.self_rating} / 5.0</span>
                    ) : (
                      <span className="text-muted text-xs">Not submitted</span>
                    )}
                  </td>
                  <td>
                    {!g.self_rating && (
                      <button
                        className="btn btn-sm btn-outline"
                        onClick={() => setSelectedGoal(g)}
                      >
                        Submit Self Review
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal: Set Goals */}
      {showSetModal && (
        <div className="modal-backdrop">
          <div className="modal card max-w-2xl">
            <h2>Set Goals for {activeCycle?.name}</h2>
            <p className="text-sm text-muted mb-4">
              Enter individual goals. Total weightages must sum to exactly 100.00%.
            </p>

            <form onSubmit={handleSaveGoals} className="stack gap-4">
              {goalInputs.map((item, idx) => (
                <div key={idx} className="p-3 border rounded stack gap-2">
                  <div className="flex justify-between align-center">
                    <strong className="text-sm">Goal #{idx + 1}</strong>
                    {idx > 1 && (
                      <button
                        type="button"
                        className="btn btn-xs btn-ghost text-red"
                        onClick={() => removeGoalLine(idx)}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  <div className="grid grid-3 gap-2">
                    <div className="col-span-2">
                      <label className="text-xs">Title</label>
                      <input
                        type="text"
                        placeholder="Goal title..."
                        value={item.title}
                        onChange={(e) => {
                          const updated = [...goalInputs];
                          updated[idx].title = e.target.value;
                          setGoalInputs(updated);
                        }}
                        required
                      />
                    </div>
                    <div>
                      <label className="text-xs">Weightage (%)</label>
                      <input
                        type="number"
                        step="0.01"
                        placeholder="50.00"
                        value={item.weightage}
                        onChange={(e) => {
                          const updated = [...goalInputs];
                          updated[idx].weightage = e.target.value;
                          setGoalInputs(updated);
                        }}
                        required
                      />
                    </div>
                  </div>
                  <div className="grid grid-2 gap-2">
                    <div>
                      <label className="text-xs">Description</label>
                      <input
                        type="text"
                        placeholder="Goal description..."
                        value={item.description || ""}
                        onChange={(e) => {
                          const updated = [...goalInputs];
                          updated[idx].description = e.target.value;
                          setGoalInputs(updated);
                        }}
                      />
                    </div>
                    <div>
                      <label className="text-xs">Target Metric</label>
                      <input
                        type="text"
                        placeholder="e.g. 100% accuracy"
                        value={item.target_value || ""}
                        onChange={(e) => {
                          const updated = [...goalInputs];
                          updated[idx].target_value = e.target.value;
                          setGoalInputs(updated);
                        }}
                      />
                    </div>
                  </div>
                </div>
              ))}

              <div className="flex justify-between align-center p-3 bg-muted rounded">
                <button type="button" className="btn btn-sm btn-outline" onClick={addGoalLine}>
                  + Add Goal
                </button>
                <div className="text-sm">
                  Total Weightage:{" "}
                  <strong className={newGoalTotalWeightage === 100 ? "text-success" : "text-red"}>
                    {newGoalTotalWeightage}%
                  </strong>{" "}
                  / 100%
                </div>
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowSetModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingGoals}>
                  {submittingGoals ? "Saving..." : "Save Goals"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Self Review */}
      {selectedGoal && (
        <div className="modal-backdrop">
          <div className="modal card max-w-md">
            <h2>Self Evaluation: {selectedGoal.title}</h2>
            <form onSubmit={handleSubmitSelfReview} className="stack gap-4 my-4">
              <div>
                <label>Self Rating (1.0 to 5.0)</label>
                <select value={selfRating} onChange={(e) => setSelfRating(e.target.value)}>
                  <option value="5.0">5.0 — Outstanding / Exceeds All Expectations</option>
                  <option value="4.0">4.0 — Exceeds Expectations</option>
                  <option value="3.0">3.0 — Meets Expectations</option>
                  <option value="2.0">2.0 — Needs Improvement</option>
                  <option value="1.0">1.0 — Unsatisfactory</option>
                </select>
              </div>

              <div>
                <label>Self Review Comments & Achievements</label>
                <textarea
                  rows={4}
                  placeholder="Detail your accomplishments and results for this goal..."
                  value={selfComments}
                  onChange={(e) => setSelfComments(e.target.value)}
                  required
                />
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setSelectedGoal(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingReview}>
                  {submittingReview ? "Submitting..." : "Submit Self Rating"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
