import { useState, useEffect } from "react";
import {
  listPerformanceCycles,
  listPerformanceGoals,
  setPerformanceGoals,
  updatePerformanceGoal,
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
import { listEmployees, type Employee } from "../../hr/api";
import { useToast } from "../../../app/toast-context";
import { formatDate } from "../../../shared/utils/date";
import { parseApiError } from "../../../shared/api/errors";

export function TeamGoalsPage() {
  const { notify } = useToast();

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string>("");

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
  const [editReason, setEditReason] = useState("");
  const [submittingEdit, setSubmittingEdit] = useState(false);

  const totalWeightage = goals.reduce((acc, g) => acc + Number(g.weightage), 0);
  const newGoalsOnly = goalInputs.reduce((acc, g) => acc + Number(g.weightage || 0), 0);
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
      notify("Goals already total 100%. Edit an existing goal to change the split.", "info");
      return;
    }
    setGoalInputs([{ title: "", description: "", weightage: remainingWeightage.toFixed(2), target_value: "" }]);
    setShowSetModal(true);
  }

  // Load employee list on mount
  useEffect(() => {
    loadEmployees();
  }, []);

  async function loadEmployees() {
    try {
      const empRes = await listEmployees({ page: 1, limit: 100 });
      setEmployees(empRes.items);
      if (empRes.items.length > 0) {
        setSelectedEmployeeId(empRes.items[0].id);
      } else {
        setLoading(false);
      }
    } catch {
      notify("Failed to load employee list", "error");
      setLoading(false);
    }
  }

  // Reload goals whenever selected employee changes
  useEffect(() => {
    if (selectedEmployeeId) {
      loadGoalsForEmployee(selectedEmployeeId);
    }
  }, [selectedEmployeeId]);

  async function loadGoalsForEmployee(empId: string) {
    // C4: Stale data: clear previous goals and show loading state
    setGoals([]);
    setLoading(true);
    try {
      const res = await listPerformanceCycles("active");
      if (res.items.length > 0) {
        const cycle = res.items[0];
        setActiveCycle(cycle);

        const empGoals = await listPerformanceGoals(empId);
        setGoals(empGoals);
        try {
          const pip = await getActivePIP(empId);
          setActivePip(pip);
        } catch {
          setActivePip(null);
        }
      } else {
        setActiveCycle(null);
        setGoals([]);
        setActivePip(null);
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
    if (!selectedEmployeeId) {
      notify("Please select an employee profile to set goals for.", "error");
      return;
    }

    setSubmittingGoals(true);
    try {
      await setPerformanceGoals({
        cycle_id: activeCycle.id,
        employee_id: selectedEmployeeId,
        goals: goalInputs,
      });
      notify("Goals saved successfully", "success");
      setShowSetModal(false);
      loadGoalsForEmployee(selectedEmployeeId);
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to save goals", parsed.status === 409 ? "warning" : "error");
    } finally {
      setSubmittingGoals(false);
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
    setEditReason("");
  }

  async function handleUpdateGoal(e: React.FormEvent) {
    e.preventDefault();
    if (!editingGoal) return;
    if (editingGoal.status === "completed" && !editReason.trim()) {
      notify("A reason is required to modify a completed goal.", "warning");
      return;
    }
    setSubmittingEdit(true);
    try {
      await updatePerformanceGoal(editingGoal.id, {
        title: editTitle,
        description: editDescription,
        target_value: editTargetValue,
        status: editStatus,
        weightage: editWeightage,
        ...(editingGoal.status === "completed" ? { reason: editReason } : {}),
      });
      notify("Goal updated successfully", "success");
      setEditingGoal(null);
      if (selectedEmployeeId) {
        loadGoalsForEmployee(selectedEmployeeId);
      }
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

  // C3: Both header and dropdown read from this exact same employee object
  const currentEmployee = employees.find((e) => e.id === selectedEmployeeId);

  return (
    <div className="container">
      <div className="page-header flex justify-between align-center page-header-responsive">
        <div>
          <h1>Team Goals</h1>
          <p className="text-muted">
            Rate each goal your team member has self-rated. Your rating stays hidden from them until you submit it.
          </p>
        </div>
        {activeCycle && selectedEmployeeId && (
          <span
            title={
              totalWeightage >= 100
                ? "Weightages already total 100%; lower an existing goal first."
                : undefined
            }
          >
            <button
              className="btn btn-sm btn-primary"
              onClick={openSetGoals}
              disabled={totalWeightage >= 100}
            >
              + Add Goals
            </button>
          </span>
        )}
      </div>

      {/* Employee Selector Card */}
      <div className="card p-4 my-3" style={{ background: "#f8fafc", border: "1px solid #e2e8f0" }}>
        <div className="row-between align-center" style={{ flexWrap: "wrap", gap: "10px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "1.1rem" }}>👤</span>
            <div>
              <span className="text-xs text-muted block" style={{ fontWeight: 600 }}>Viewing & Setting Goals For</span>
              <span style={{ fontSize: "0.9rem", fontWeight: 700 }}>
                {currentEmployee
                  ? `${currentEmployee.first_name} ${currentEmployee.last_name || ""} (${currentEmployee.employee_code})`
                  : employees.length === 0
                  ? "No employees found"
                  : "Select an employee"}
              </span>
            </div>
          </div>
          {employees.length > 0 ? (
            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
              <label htmlFor="team-goals-employee-select" className="text-xs text-muted">Switch Employee:</label>
              <select
                id="team-goals-employee-select"
                aria-label="Switch Employee"
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
            <span className="text-xs text-muted">No employees found in the directory.</span>
          )}
        </div>
      </div>

      {/* Persistent Amber PIP Banner if active for this employee */}
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
                Employee is currently in an active Performance Improvement Plan (Ends {formatDate(activePip.end_date)}).
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
            <span className="text-xs text-muted block">Manager Review Deadline</span>
            <strong className="text-warning">
              {activeCycle.manager_review_deadline ? formatDate(activeCycle.manager_review_deadline) : "Not set"}
            </strong>
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
            ⚠️ Warning: Total goal weightage is {totalWeightage}%. Weightages must sum to exactly 100.00%.
          </span>
        </div>
      )}

      {/* Goals List */}
      <div className="card mt-4">
        <div className="row-between align-center mb-3" style={{ flexWrap: "wrap", gap: "6px" }}>
          <h3 style={{ margin: 0, fontSize: "1rem" }}>
            {currentEmployee ? `${currentEmployee.first_name}'s Goals` : "Submitted Goals"}
          </h3>
          <span className="text-xs text-muted">💡 Tip: Double-click on any unlocked goal to edit its details</span>
        </div>
        {loading ? (
          <p>Loading performance goals...</p>
        ) : goals.length === 0 ? (
          <p className="text-muted">No goals submitted yet for this employee in the current performance cycle.</p>
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
              Define goals for <strong>{currentEmployee ? `${currentEmployee.first_name} ${currentEmployee.last_name || ""}` : "Employee"}</strong> in <strong>{activeCycle?.name}</strong>. Total weightages must equal 100.00%.
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

              {editingGoal.status === "completed" && (
                <div className="field" style={{ background: "#fffbeb", padding: "12px", borderRadius: "8px", border: "1px solid #fde68a" }}>
                  <label style={{ color: "#92400e", fontWeight: 600 }}>Reason for Modifying Completed Goal <span style={{ color: "#dc2626" }}>*</span></label>
                  <input
                    type="text"
                    value={editReason}
                    onChange={(e) => setEditReason(e.target.value)}
                    placeholder="Explain why this completed goal is being modified..."
                    required
                    style={{ borderColor: "#f59e0b" }}
                  />
                  <span className="field-hint" style={{ fontSize: "0.75rem", color: "#b45309" }}>
                    Company policy requires a reason when updating goals that were already marked completed.
                  </span>
                </div>
              )}

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
