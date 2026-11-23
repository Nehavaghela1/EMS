import { useState, useEffect } from "react";
import {
  listPerformanceCycles,
  listPerformanceGoals,
  setPerformanceGoals,
  updatePerformanceGoal,
  submitSelfReview,
  updateGoalProgress,
  getGoalProgressHistory,
  getActivePIP,
  type PerformanceCycle,
  type PerformanceGoal,
  type PerformancePIP,
  type GoalProgressHistoryItem,
  type GoalCreateItem,
  type GoalStatus,
} from "../api";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { formatDate } from "../../../shared/utils/date";
import { parseApiError } from "../../../shared/api/errors";

export function MyGoalsPage() {
  const { user } = useAuth();
  const { notify } = useToast();

  const [activeCycle, setActiveCycle] = useState<PerformanceCycle | null>(null);
  const [goals, setGoals] = useState<PerformanceGoal[]>([]);
  const [activePip, setActivePip] = useState<PerformancePIP | null>(null);
  const [loading, setLoading] = useState(true);

  // History Drawer state
  const [historyGoal, setHistoryGoal] = useState<PerformanceGoal | null>(null);
  const [historyItems, setHistoryItems] = useState<GoalProgressHistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

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

  // Edit Goal Modal state
  const [editingGoal, setEditingGoal] = useState<PerformanceGoal | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editTargetValue, setEditTargetValue] = useState("");
  const [editStatus, setEditStatus] = useState<GoalStatus>("in_progress");
  const [editWeightage, setEditWeightage] = useState("");
  const [submittingEdit, setSubmittingEdit] = useState(false);

  // Self Review Modal state
  const [selectedGoal, setSelectedGoal] = useState<PerformanceGoal | null>(null);
  const [selfRating, setSelfRating] = useState("4.0");
  const [selfComments, setSelfComments] = useState("");
  const [submittingReview, setSubmittingReview] = useState(false);

  const totalWeightage = goals.reduce((acc, g) => acc + Number(g.weightage), 0);
  const newGoalsOnly = goalInputs.reduce((acc, g) => acc + Number(g.weightage || 0), 0);
  // The server caps existing + new goals at 100%, so the form counts both (BUG-058).
  const newGoalTotalWeightage = Math.round((totalWeightage + newGoalsOnly) * 100) / 100;
  const remainingWeightage = Math.max(0, Math.round((100 - totalWeightage) * 100) / 100);

  async function openHistory(goal: PerformanceGoal) {
    setHistoryGoal(goal);
    setLoadingHistory(true);
    try {
      const items = await getGoalProgressHistory(goal.id);
      setHistoryItems(items);
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to load progress history", "error");
    } finally {
      setLoadingHistory(false);
    }
  }

  function openSetGoals() {
    if (remainingWeightage <= 0) {
      notify("Your goals already total 100%. Edit an existing goal to change the split.", "info");
      return;
    }
    setGoalInputs([{ title: "", description: "", weightage: remainingWeightage.toFixed(2), target_value: "" }]);
    setShowSetModal(true);
  }

  useEffect(() => {
    init();
  }, [user?.employee?.id]);

  async function init() {
    setGoals([]);
    setLoading(true);
    try {
      const res = await listPerformanceCycles("active");
      if (res.items.length > 0) {
        const cycle = res.items[0];
        setActiveCycle(cycle);

        const targetId = user?.employee?.id;
        if (targetId) {
          const empGoals = await listPerformanceGoals(targetId);
          setGoals(empGoals);
          try {
            const pip = await getActivePIP(targetId);
            setActivePip(pip);
          } catch {
            setActivePip(null);
          }
        } else {
          setGoals([]);
          setActivePip(null);
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
    const targetEmpId = user?.employee?.id;
    if (!targetEmpId) {
      notify("No employee profile found for your account.", "error");
      return;
    }

    setSubmittingGoals(true);
    try {
      await setPerformanceGoals({
        cycle_id: activeCycle.id,
        employee_id: targetEmpId,
        goals: goalInputs,
      });
      notify("Goals saved successfully", "success");
      setShowSetModal(false);
      init();
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to save goals", parsed.status === 409 ? "warning" : "error");
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
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to submit self-review", parsed.status === 409 ? "warning" : "error");
    } finally {
      setSubmittingReview(false);
    }
  }

  async function handleProgressSave(g: PerformanceGoal, raw: string) {
    const value = Number(raw);
    if (!Number.isInteger(value) || value < 0 || value > 100) {
      notify("Progress must be a whole number from 0 to 100.", "error");
      return;
    }
    if (value === (g.progress ?? 0)) return;
    try {
      const updated = await updateGoalProgress(g.id, value);
      setGoals((prev) => prev.map((x) => (x.id === g.id ? { ...x, progress: updated.progress ?? value } : x)));
      notify(`Progress saved: ${value}%`, "success");
    } catch (err) {
      notify(parseApiError(err).message, "error");
    }
  }

  function openEditGoal(g: PerformanceGoal) {
    // A goal with a self-review is locked; do not open edit modal and do not show toast (C5).
    if (g.self_rating !== null && g.self_rating !== undefined) {
      return;
    }
    setEditingGoal(g);
    setEditTitle(g.title);
    setEditDescription(g.description || "");
    setEditTargetValue(g.target_value || "");
    setEditStatus(g.status);
    setEditWeightage(String(g.weightage));
  }

  async function handleUpdateGoal(e: React.FormEvent) {
    e.preventDefault();
    if (!editingGoal) return;
    setSubmittingEdit(true);
    try {
      await updatePerformanceGoal(editingGoal.id, {
        title: editTitle,
        description: editDescription,
        target_value: editTargetValue,
        status: editStatus,
        weightage: editWeightage,
      });
      notify("Goal updated successfully", "success");
      setEditingGoal(null);
      init();
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to update goal", parsed.status === 409 ? "warning" : "error");
    } finally {
      setSubmittingEdit(false);
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
      <div className="page-header flex justify-between align-center page-header-responsive">
        <div>
          <h1>My Performance Goals</h1>
          <p className="text-muted">
            Your goals for this appraisal cycle. Weightages must total 100% before you can submit your self-review, which then goes to your reporting manager.
          </p>
        </div>
        {activeCycle && user?.employee?.id && (
          <button className="btn btn-sm btn-primary" onClick={openSetGoals}>
            + Add Goals
          </button>
        )}
      </div>

      {/* Admin Information Card when user is not linked to an employee profile */}
      {!user?.employee?.id && (
        <div className="alert alert-info my-3">
          <strong>ℹ️ Employee Profile Required:</strong> Performance goals are tracked on employee profiles. Since your current account is not linked to an employee profile, you cannot submit personal goals.
        </div>
      )}

      {/* Persistent Amber PIP Banner for Track C Warning Period */}
      {activePip && (
        <div
          className="card my-3 p-4"
          style={{
            backgroundColor: "#fffbeb",
            borderColor: "#f59e0b",
            borderLeft: "5px solid #d97706",
            boxShadow: "0 2px 8px rgba(217, 119, 6, 0.15)",
          }}
        >
          <div className="flex justify-between align-center" style={{ flexWrap: "wrap", gap: "10px" }}>
            <div>
              <div className="flex items-center gap-2">
                <span style={{ fontSize: "1.25rem" }}>⚠️</span>
                <strong style={{ color: "#92400e", fontSize: "1rem" }}>
                  Active Performance Improvement Plan (Ends {formatDate(activePip.end_date)})
                </strong>
                <span className="badge badge-warning" style={{ background: "#fef3c7", color: "#b45309", border: "1px solid #fde68a" }}>
                  WARNING PERIOD
                </span>
              </div>
              <p className="text-sm mt-1 mb-0" style={{ color: "#b45309" }}>
                You are currently in an active Performance Evaluation Plan (Ends {formatDate(activePip.end_date)}). Review targets and required KPIs below.
              </p>
            </div>
            <div className="text-right text-xs" style={{ color: "#92400e" }}>
              <div>Assigned Mentor: <b>{activePip.mentor_name || "Assigned Manager"}</b></div>
              <div>Deadline: <b>{formatDate(activePip.end_date)}</b></div>
            </div>
          </div>
          {activePip.milestones_kpis && (
            <div
              className="mt-3 p-3 rounded"
              style={{ background: "rgba(254, 243, 199, 0.6)", border: "1px dashed #f59e0b" }}
            >
              <div className="text-xs font-semibold uppercase" style={{ color: "#92400e", letterSpacing: "0.05em" }}>
                🎯 Required Improvement Milestones & Targets
              </div>
              <div className="text-sm mt-1" style={{ color: "#78350f", whiteSpace: "pre-wrap" }}>
                {activePip.milestones_kpis}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Active Cycle Banner */}
      {activeCycle ? (
        <div className="p-4 bg-muted border rounded my-4 flex justify-between align-center performance-cycle-banner">
          <div>
            <span className="text-xs text-muted block">Active Appraisal Period</span>
            <strong>{activeCycle.name}</strong> ({formatDate(activeCycle.start_date)} to {formatDate(activeCycle.end_date)})
          </div>
          <div>
            <span className="text-xs text-muted block">Self Review Deadline</span>
            <strong className="text-warning">{activeCycle.self_review_deadline ? formatDate(activeCycle.self_review_deadline) : "Not set"}</strong>
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
        <div className="row-between align-center mb-3" style={{ flexWrap: "wrap", gap: "6px" }}>
          <h3 style={{ margin: 0, fontSize: "1rem" }}>Submitted Goals</h3>
          <span className="text-xs text-muted">💡 Tip: Double-click on any unlocked goal to edit its details</span>
        </div>
        {loading ? (
          <p>Loading performance goals...</p>
        ) : goals.length === 0 ? (
          <p className="text-muted">No goals submitted yet for the current performance cycle.</p>
        ) : (
          <div className="mobile-table-wrap">
            <table className="table" style={{ minWidth: "600px" }}>
              <thead>
                <tr>
                  <th>Goal Title</th>
                  <th>Target / Metric</th>
                  <th>Weightage</th>
                  <th>Progress</th>
                  <th>Status</th>
                  <th>Self Rating</th>
                  <th style={{ textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {goals.map((g) => {
                  const isLocked = g.self_rating !== null && g.self_rating !== undefined;
                  return (
                    <tr
                      key={g.id}
                      onDoubleClick={() => openEditGoal(g)}
                      style={{ cursor: isLocked ? "default" : "pointer" }}
                      title={isLocked ? "Locked: self-review submitted" : "Double-click to edit goal"}
                    >
                      <td>
                        <div className="fw-bold flex items-center gap-1">
                          {isLocked && (
                            <span role="img" aria-label="Locked" title="Locked: self-review submitted">
                              🔒
                            </span>
                          )}
                          <span>{g.title}</span>
                        </div>
                        <div className="text-xs text-muted">{g.description || "No description"}</div>
                      </td>
                      <td>{g.target_value || "—"}</td>
                      <td className="fw-bold">{g.weightage}%</td>
                      <td onDoubleClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-1">
                          {Boolean(g.self_rating) ? (
                            <span title="Locked: self-review submitted">
                              {g.progress ?? 0}%
                            </span>
                          ) : (
                            <span style={{ position: "relative", display: "inline-block" }}>
                              <input
                                type="number"
                                min={0}
                                max={100}
                                step={5}
                                aria-label={`Progress for ${g.title}`}
                                defaultValue={g.progress ?? 0}
                                style={{ width: "80px", paddingRight: "22px" }}
                                onBlur={(e) => handleProgressSave(g, e.currentTarget.value)}
                              />
                              <span
                                style={{
                                  position: "absolute",
                                  right: "8px",
                                  top: "50%",
                                  transform: "translateY(-50%)",
                                  pointerEvents: "none",
                                  color: "var(--text-muted, #64748b)",
                                  fontSize: "0.85rem",
                                }}
                              >
                                %
                              </span>
                            </span>
                          )}
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm p-1"
                            title="View progress change history"
                            aria-label={`View history for ${g.title}`}
                            onClick={() => openHistory(g)}
                            style={{ fontSize: "0.9rem", color: "var(--color-primary, #3b82f6)", cursor: "pointer" }}
                          >
                            🕒
                          </button>
                        </div>
                      </td>
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
                      <td style={{ textAlign: "right" }}>
                        <div className="flex gap-2 justify-end">
                          {!g.self_rating ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedGoal(g);
                              }}
                            >
                              Self Review
                            </button>
                          ) : (
                            <span className="text-xs text-muted" style={{ fontStyle: "italic" }}>
                              Reviewed
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal: Set Goals */}
      {showSetModal && (
        <div className="modal-backdrop" onClick={() => setShowSetModal(false)}>
          <div className="modal card performance-goal-modal" style={{ maxWidth: "640px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Set Performance Goals</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowSetModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <p className="text-sm text-muted mb-3">
              Define goals for <strong>{activeCycle?.name}</strong>. Total weightages must equal 100.00%.
            </p>

            <form onSubmit={handleSaveGoals} className="stack gap-4">
              <div className="stack gap-3" style={{ maxHeight: "55vh", overflowY: "auto", paddingRight: "4px" }}>
                {goalInputs.map((item, idx) => (
                  <div key={idx} className="card" style={{ padding: "var(--space-3)", background: "var(--color-bg)", border: "1px solid var(--color-border)" }}>
                    <div className="row-between mb-2">
                      <strong className="text-sm">Goal #{idx + 1}</strong>
                      {idx > 1 && (
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost text-red"
                          onClick={() => removeGoalLine(idx)}
                          style={{ padding: "2px 6px" }}
                        >
                          ✕ Remove
                        </button>
                      )}
                    </div>

                    <div className="stack gap-2">
                      <div className="grid-2 performance-grid-2-mobile">
                        <div className="field">
                          <label>Title *</label>
                          <input
                            type="text"
                            placeholder="e.g. Complete quarterly deliverables"
                            value={item.title}
                            onChange={(e) => {
                              const updated = [...goalInputs];
                              updated[idx].title = e.target.value;
                              setGoalInputs(updated);
                            }}
                            required
                          />
                        </div>
                        <div className="field">
                          <label>Weightage (%) *</label>
                          <input
                            type="number"
                            step="0.01"
                            min="0"
                            max="100"
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

                      <div className="grid-2 performance-grid-2-mobile">
                        <div className="field">
                          <label>Target / Metric</label>
                          <input
                            type="text"
                            placeholder="e.g. 100% test pass rate"
                            value={item.target_value || ""}
                            onChange={(e) => {
                              const updated = [...goalInputs];
                              updated[idx].target_value = e.target.value;
                              setGoalInputs(updated);
                            }}
                          />
                        </div>
                        <div className="field">
                          <label>Description</label>
                          <input
                            type="text"
                            placeholder="Brief description of the goal"
                            value={item.description || ""}
                            onChange={(e) => {
                              const updated = [...goalInputs];
                              updated[idx].description = e.target.value;
                              setGoalInputs(updated);
                            }}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="row-between align-center">
                <button type="button" className="btn btn-outline" onClick={addGoalLine}>
                  + Add Goal
                </button>
                <div className="text-sm">
                  Total Allocated:{" "}
                  <strong className={newGoalTotalWeightage === 100 ? "text-success" : "text-danger"}>
                    {newGoalTotalWeightage}%
                  </strong>{" "}
                  / 100%
                </div>
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowSetModal(false)}>
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={submittingGoals || newGoalTotalWeightage !== 100}
                >
                  {submittingGoals ? "Saving..." : "Save Goals"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Self Review */}
      {selectedGoal && (
        <div className="modal-backdrop" onClick={() => setSelectedGoal(null)}>
          <div className="modal card performance-goal-modal" style={{ maxWidth: "520px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Self Evaluation: {selectedGoal.title}</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setSelectedGoal(null)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <p className="text-sm text-muted mb-3">
              Rate your achievement against this goal on a 1.0 to 5.0 scale.
            </p>

            <form onSubmit={handleSubmitSelfReview} className="stack gap-4">
              <div className="field">
                <label>Self Rating (1.0 – 5.0) *</label>
                <select value={selfRating} onChange={(e) => setSelfRating(e.target.value)}>
                  <option value="1.0">1.0 — Unsatisfactory</option>
                  <option value="2.0">2.0 — Needs Improvement</option>
                  <option value="3.0">3.0 — Meets Expectations</option>
                  <option value="4.0">4.0 — Exceeds Expectations</option>
                  <option value="5.0">5.0 — Outstanding</option>
                </select>
              </div>

              <div className="field">
                <label>Accomplishments & Self Comments</label>
                <textarea
                  rows={4}
                  placeholder="Detail your accomplishments, metrics delivered, and blockers faced..."
                  value={selfComments}
                  onChange={(e) => setSelfComments(e.target.value)}
                />
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setSelectedGoal(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingReview}>
                  {submittingReview ? "Submitting..." : "Submit Review"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Edit Goal */}
      {editingGoal && (
        <div className="modal-backdrop" onClick={() => setEditingGoal(null)}>
          <div className="modal card performance-goal-modal" style={{ maxWidth: "520px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Edit Goal</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setEditingGoal(null)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleUpdateGoal} className="stack gap-4 my-2">
              <div className="field">
                <label>Title *</label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  placeholder="Goal title..."
                  required
                />
              </div>

              <div className="field">
                <label>Description</label>
                <textarea
                  rows={3}
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  placeholder="Key deliverables or success factors..."
                />
              </div>

              <div className="grid-2 performance-grid-2-mobile">
                <div className="field">
                  <label>Target Metric</label>
                  <input
                    type="text"
                    value={editTargetValue}
                    onChange={(e) => setEditTargetValue(e.target.value)}
                    placeholder="e.g. 100% completed"
                  />
                </div>
                <div className="field">
                  <label>Status</label>
                  <select value={editStatus} onChange={(e) => setEditStatus(e.target.value as GoalStatus)}>
                    <option value="draft">Draft</option>
                    <option value="in_progress">In Progress</option>
                    <option value="completed">Completed</option>
                  </select>
                </div>
              </div>

              <div className="field">
                <label>Weightage (%)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  max="100"
                  value={editWeightage}
                  onChange={(e) => setEditWeightage(e.target.value)}
                  required
                />
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setEditingGoal(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingEdit}>
                  {submittingEdit ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Progress History Modal */}
      {historyGoal && (
        <div className="modal-backdrop">
          <div className="modal" style={{ maxWidth: "560px" }}>
            <div className="flex justify-between align-center mb-3">
              <h3 className="m-0">Progress Change History</h3>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setHistoryGoal(null)}
              >
                ✕
              </button>
            </div>
            <p className="text-sm text-muted mb-4">
              Audit trail of all progress changes recorded for <strong>{historyGoal.title}</strong>.
            </p>

            {loadingHistory ? (
              <p>Loading history...</p>
            ) : historyItems.length === 0 ? (
              <p className="text-muted">No progress changes recorded yet.</p>
            ) : (
              <div style={{ maxHeight: "350px", overflowY: "auto" }}>
                <table className="table text-sm" style={{ width: "100%" }}>
                  <thead>
                    <tr>
                      <th>Change</th>
                      <th>Notes</th>
                      <th>Updated At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyItems.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <span className="font-mono">{item.old_progress}%</span>
                          {" ➔ "}
                          <strong className="font-mono">{item.new_progress}%</strong>
                        </td>
                        <td>{item.notes || "—"}</td>
                        <td>{new Date(item.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="flex justify-end mt-4">
              <button type="button" className="btn btn-primary" onClick={() => setHistoryGoal(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
