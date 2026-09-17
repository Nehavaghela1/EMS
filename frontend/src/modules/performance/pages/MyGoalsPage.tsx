import { useState, useEffect } from "react";
import {
  listPerformanceCycles,
  listPerformanceGoals,
  setPerformanceGoals,
  updatePerformanceGoal,
  submitSelfReview,
  type PerformanceCycle,
  type PerformanceGoal,
  type GoalCreateItem,
  type GoalStatus,
} from "../api";
import { listEmployees, type Employee } from "../../hr/api";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { formatDate } from "../../../shared/utils/date";
import { parseApiError } from "../../../shared/api/errors";

export function MyGoalsPage() {
  const { user } = useAuth();
  const { notify } = useToast();

  const isHrOrManager = user?.role === "hr_admin" || user?.role === "super_admin" || user?.role === "manager";
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string>(user?.employee?.id || "");

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
  const newGoalTotalWeightage = goalInputs.reduce((acc, g) => acc + Number(g.weightage || 0), 0);

  useEffect(() => {
    init();
  }, [selectedEmployeeId]);

  async function init() {
    setLoading(true);
    try {
      if (isHrOrManager && employees.length === 0) {
        const empRes = await listEmployees({ page: 1, limit: 100 });
        setEmployees(empRes.items);
        if (!selectedEmployeeId && empRes.items.length > 0) {
          const firstEmpId = user?.employee?.id || empRes.items[0].id;
          setSelectedEmployeeId(firstEmpId);
        }
      }

      const res = await listPerformanceCycles("active");
      if (res.items.length > 0) {
        const cycle = res.items[0];
        setActiveCycle(cycle);

        const targetId = selectedEmployeeId || user?.employee?.id;
        if (targetId) {
          const empGoals = await listPerformanceGoals(targetId);
          setGoals(empGoals);
        } else {
          setGoals([]);
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
    const targetEmpId = selectedEmployeeId || user?.employee?.id;
    if (!targetEmpId) {
      notify("Please select an employee profile to set goals for.", "error");
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

  function openEditGoal(g: PerformanceGoal) {
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
      <div className="page-header flex justify-between align-center">
        <div>
          <h1>My Performance Goals</h1>
          <p className="text-muted">Set goals for the active performance cycle & submit self-evaluations</p>
        </div>
        {activeCycle && (
          <button className="btn btn-primary" onClick={() => setShowSetModal(true)}>
            + Add Goals
          </button>
        )}
      </div>

      {/* Admin Information Card when user is not linked to an employee profile */}
      {!user?.employee?.id && !isHrOrManager && (
        <div className="alert alert-info my-3">
          <strong>ℹ️ Employee Profile Required:</strong> Performance goals are tracked on employee profiles. Since your current account is not linked to an employee profile, you cannot submit personal goals.
        </div>
      )}

      {/* Employee Selector for HR Admin / Manager */}
      {isHrOrManager && (
        <div className="card p-4 my-3" style={{ background: "#f8fafc", border: "1px solid #e2e8f0" }}>
          <div className="row-between align-center" style={{ flexWrap: "wrap", gap: "10px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "1.1rem" }}>👤</span>
              <div>
                <span className="text-xs text-muted block" style={{ fontWeight: 600 }}>Viewing & Setting Goals For</span>
                <span style={{ fontSize: "0.9rem", fontWeight: 700 }}>
                  {employees.find((e) => e.id === selectedEmployeeId)
                    ? `${employees.find((e) => e.id === selectedEmployeeId)?.first_name} ${employees.find((e) => e.id === selectedEmployeeId)?.last_name || ""} (${employees.find((e) => e.id === selectedEmployeeId)?.employee_code})`
                    : employees.length === 0
                    ? "No employees in company"
                    : "Select an employee"}
                </span>
              </div>
            </div>
            {employees.length > 0 ? (
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <label className="text-xs text-muted">Switch Employee:</label>
                <select
                  value={selectedEmployeeId}
                  onChange={(e) => setSelectedEmployeeId(e.target.value)}
                  style={{ minWidth: "220px", padding: "6px 10px", fontSize: "0.85rem" }}
                >
                  {employees.map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.first_name} {emp.last_name || ""} ({emp.employee_code}) - {emp.position || "Staff"}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <span className="text-xs text-muted">Add employee records in Employee Directory first to assign goals.</span>
            )}
          </div>
          {!user?.employee?.id && (
            <div className="mt-2 pt-2 text-xs text-muted" style={{ borderTop: "1px dashed #cbd5e1" }}>
              💡 <em>You are managing goals as an Administrator. Goals are saved directly to the selected employee profile.</em>
            </div>
          )}
        </div>
      )}

      {/* Active Cycle Banner */}
      {activeCycle ? (
        <div className="p-4 bg-muted border rounded my-4 flex justify-between align-center">
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
        <div className="row-between align-center mb-3">
          <h3 style={{ margin: 0, fontSize: "1rem" }}>Submitted Goals</h3>
          <span className="text-xs text-muted">💡 Tip: Double-click on any goal to edit its details</span>
        </div>
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
                <th style={{ textAlign: "right" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {goals.map((g) => (
                <tr
                  key={g.id}
                  onDoubleClick={() => openEditGoal(g)}
                  style={{ cursor: "pointer" }}
                  title="Double-click to edit goal"
                >
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
                          Reviewed (Double-click to edit)
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal: Set Goals */}
      {showSetModal && (
        <div className="modal-backdrop" onClick={() => setShowSetModal(false)}>
          <div className="modal card" style={{ maxWidth: "640px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
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
                      <div className="grid-2">
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

                      <div className="grid-2">
                        <div className="field">
                          <label>Target Metric</label>
                          <input
                            type="text"
                            placeholder="e.g. 100% completed / 0 critical bugs"
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
                            placeholder="Brief description of deliverables..."
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

              <div className="row-between p-3 bg-muted rounded border align-center">
                <button type="button" className="btn btn-sm btn-outline" onClick={addGoalLine}>
                  + Add Goal
                </button>
                <div className="text-right text-sm">
                  <div>
                    Total Weightage:{" "}
                    <strong className={newGoalTotalWeightage === 100 ? "text-success font-mono" : "text-red font-mono"}>
                      {newGoalTotalWeightage}%
                    </strong>{" "}
                    <span className="text-muted">/ 100%</span>
                  </div>
                  <div style={{ fontSize: "0.75rem", marginTop: "2px" }}>
                    {newGoalTotalWeightage === 100 ? (
                      <span className="text-success" style={{ fontWeight: 600 }}>✓ Balanced (100% allocated)</span>
                    ) : newGoalTotalWeightage < 100 ? (
                      <span className="text-warning" style={{ fontWeight: 600 }}>
                        ⏳ {(100 - newGoalTotalWeightage).toFixed(2).replace(/\.00$/, "")}% remaining to allocate
                      </span>
                    ) : (
                      <span className="text-red" style={{ fontWeight: 600 }}>
                        ⚠️ Over by {(newGoalTotalWeightage - 100).toFixed(2).replace(/\.00$/, "")}% (must equal 100%)
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex gap-2 justify-end mt-2">
                <button type="button" className="btn btn-ghost" onClick={() => setShowSetModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingGoals}>
                  {submittingGoals ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Self Review */}
      {selectedGoal && (
        <div className="modal-backdrop" onClick={() => setSelectedGoal(null)}>
          <div className="modal card max-w-md" onClick={(e) => e.stopPropagation()}>
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
            <form onSubmit={handleSubmitSelfReview} className="stack gap-4 my-2">
              <div className="field">
                <label>Self Rating (1.0 to 5.0)</label>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", margin: "6px 0" }}>
                  {[1, 2, 3, 4, 5].map((star) => {
                    const currentVal = parseFloat(selfRating) || 0;
                    const isFilled = star <= currentVal;
                    return (
                      <button
                        key={star}
                        type="button"
                        onClick={() => setSelfRating(`${star}.0`)}
                        style={{
                          background: "none",
                          border: "none",
                          cursor: "pointer",
                          fontSize: "1.75rem",
                          lineHeight: 1,
                          padding: "2px",
                          color: isFilled ? "#eab308" : "#d1d5db",
                          transition: "transform 0.1s ease, color 0.1s ease",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.transform = "scale(1.2)")}
                        onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
                        title={`${star}.0 Stars`}
                      >
                        ★
                      </button>
                    );
                  })}
                  <span style={{ marginLeft: "10px", fontWeight: 600, fontSize: "0.95rem", color: "var(--color-heading, #111827)" }}>
                    {selfRating === "5.0"
                      ? "5.0 — Outstanding"
                      : selfRating === "4.0"
                      ? "4.0 — Exceeds Expectations"
                      : selfRating === "3.0"
                      ? "3.0 — Meets Expectations"
                      : selfRating === "2.0"
                      ? "2.0 — Needs Improvement"
                      : "1.0 — Unsatisfactory"}
                  </span>
                </div>
              </div>

              <div className="field">
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
          <div className="modal card" style={{ maxWidth: "520px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
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

              <div className="grid-2">
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
    </div>
  );
}
