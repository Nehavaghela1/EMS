import { useState, useEffect } from "react";
import {
  listPerformanceCycles,
  createPerformanceCycle,
  updatePerformanceCycle,
  getPerformanceReport,
  listPIPs,
  initiatePIP,
  activatePIP,
  evaluatePIP,
  decidePIPSeparation,
  type PerformanceCycle,
  type PerformanceReport,
  type PerformancePIP,
  type CycleType,
  type CycleStatus,
} from "../api";
import { listEmployees, type Employee } from "../../hr/api";
import { useToast } from "../../../app/toast-context";
import { useAuth } from "../../../app/auth-context";
import { formatDate } from "../../../shared/utils/date";
import { parseApiError } from "../../../shared/api/errors";

export function PerformanceCyclesPage() {
  const { notify } = useToast();
  const [cycles, setCycles] = useState<PerformanceCycle[]>([]);
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<PerformanceReport | null>(null);
  const [statusFilter, setStatusFilter] = useState<CycleStatus | "all">("all");

  // PIP State
  const [pips, setPips] = useState<PerformancePIP[]>([]);
  const [pipsLoading, setPipsLoading] = useState(false);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [showPipCreateModal, setShowPipCreateModal] = useState(false);
  const [pipEmployeeId, setPipEmployeeId] = useState("");
  const [pipMentorId, setPipMentorId] = useState("");
  const [pipTitle, setPipTitle] = useState("30-Day Performance Improvement Plan");
  const [pipDescription, setPipDescription] = useState("");
  const [pipMilestones, setPipMilestones] = useState("");
  const [pipStartDate, setPipStartDate] = useState(new Date().toISOString().split("T")[0]);
  const [pipEndDate, setPipEndDate] = useState(new Date(Date.now() + 30 * 86400000).toISOString().split("T")[0]);
  const [submittingPip, setSubmittingPip] = useState(false);

  // Evaluate PIP Modal State
  const [evaluatingPip, setEvaluatingPip] = useState<PerformancePIP | null>(null);
  const [pipOutcome, setPipOutcome] = useState<"passed" | "failed" | "cancelled">("passed");
  const [pipOutcomeNotes, setPipOutcomeNotes] = useState("");
  const [submittingEval, setSubmittingEval] = useState(false);

  // Separation Decision Modal State (F2)
  const [decisionPip, setDecisionPip] = useState<PerformancePIP | null>(null);
  const [decisionAction, setDecisionAction] = useState<"separate" | "extend" | "retain">("separate");
  const [decisionLwd, setDecisionLwd] = useState(new Date().toISOString().split("T")[0]);
  const [decisionNoticeChoice, setDecisionNoticeChoice] = useState<"served" | "waived" | "pay_in_lieu">("served");
  const [decisionNewEndDate, setDecisionNewEndDate] = useState("");
  const [decisionReason, setDecisionReason] = useState("");
  const [submittingDecision, setSubmittingDecision] = useState(false);

  // Modal State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [name, setName] = useState("");
  const [cycleType, setCycleType] = useState<CycleType>("annual");
  const [startDate, setStartDate] = useState(new Date().toISOString().split("T")[0]);
  const [endDate, setEndDate] = useState("2027-03-31");
  const [selfDeadline, setSelfDeadline] = useState("2027-03-15");
  const [mgrDeadline, setMgrDeadline] = useState("2027-03-25");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchCycles();
    fetchReport();
    fetchPIPs();
    fetchEmployeesList();
  }, []);

  async function fetchPIPs() {
    setPipsLoading(true);
    try {
      const data = await listPIPs();
      setPips(data);
    } catch {
      // Non-critical
    } finally {
      setPipsLoading(false);
    }
  }

  async function fetchEmployeesList() {
    try {
      const res = await listEmployees({ page: 1, limit: 100 });
      setEmployees(res.items);
    } catch {
      // Non-critical
    }
  }

  async function fetchCycles() {
    setLoading(true);
    try {
      const res = await listPerformanceCycles();
      setCycles(res.items);
    } catch {
      notify("Failed to load performance cycles", "error");
    } finally {
      setLoading(false);
    }
  }

  async function fetchReport() {
    try {
      const rep = await getPerformanceReport();
      setReport(rep);
    } catch {
      // ignore
    }
  }

  const CYCLE_TYPE_LABELS: Record<CycleType, string> = {
    annual: "Annual",
    half_yearly: "Half Yearly",
    quarterly: "Quarterly",
  };

  const CYCLE_STATUS_LABELS: Record<CycleStatus, string> = {
    draft: "Draft",
    active: "Active",
    closed: "Closed",
  };

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      notify("Please enter cycle name", "error");
      return;
    }
    if (startDate && endDate && new Date(startDate) >= new Date(endDate)) {
      notify("Cycle End Date must be after Start Date.", "error");
      return;
    }
    if (selfDeadline && endDate && new Date(selfDeadline) > new Date(endDate)) {
      notify("Self-Review Deadline cannot be after the overall Cycle End Date.", "error");
      return;
    }
    if (mgrDeadline && endDate && new Date(mgrDeadline) > new Date(endDate)) {
      notify("Manager Review Deadline cannot be after the overall Cycle End Date.", "error");
      return;
    }
    if (selfDeadline && mgrDeadline && new Date(selfDeadline) > new Date(mgrDeadline)) {
      notify("Self-Review Deadline cannot be set later than the Manager Review Deadline.", "error");
      return;
    }
    setSubmitting(true);
    try {
      await createPerformanceCycle({
        name: name.trim(),
        cycle_type: cycleType,
        start_date: startDate,
        end_date: endDate,
        self_review_deadline: selfDeadline || null,
        manager_review_deadline: mgrDeadline || null,
      });
      notify("Performance cycle created successfully", "success");
      setShowCreateModal(false);
      setName("");
      fetchCycles();
      fetchReport();
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to create cycle", parsed.status === 409 ? "warning" : "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleStatusChange(id: string, newStatus: CycleStatus) {
    try {
      await updatePerformanceCycle(id, newStatus);
      notify(`Cycle status updated to ${newStatus}`, "success");
      fetchCycles();
      fetchReport();
    } catch (err) {
      // e.g. 409 "another cycle is already active" (BUG-055)
      notify(parseApiError(err).message, "error");
    }
  }

  async function handleCreatePip(e: React.FormEvent) {
    e.preventDefault();
    if (!pipEmployeeId) {
      notify("Please select an employee to place on PIP.", "error");
      return;
    }
    if (pipStartDate && pipEndDate && new Date(pipStartDate) >= new Date(pipEndDate)) {
      notify("PIP End Date must be after Start Date.", "error");
      return;
    }
    setSubmittingPip(true);
    try {
      await initiatePIP({
        employee_id: pipEmployeeId,
        mentor_id: pipMentorId || null,
        title: pipTitle.trim(),
        description: pipDescription.trim() || null,
        milestones_kpis: pipMilestones.trim() || null,
        start_date: pipStartDate,
        end_date: pipEndDate,
      });
      notify("Performance Improvement Plan (PIP) successfully initiated.", "success");
      setShowPipCreateModal(false);
      setPipEmployeeId("");
      setPipDescription("");
      setPipMilestones("");
      fetchPIPs();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setSubmittingPip(false);
    }
  }

  async function handleActivatePip(pipId: string) {
    setActivatingPipId(pipId);
    try {
      await activatePIP(pipId);
      notify("PIP activated. The plan is now running and can be evaluated at its end.", "success");
      fetchPIPs();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setActivatingPipId(null);
    }
  }

  async function handleEvaluatePip(e: React.FormEvent) {
    e.preventDefault();
    if (!evaluatingPip) return;
    setSubmittingEval(true);
    try {
      await evaluatePIP(evaluatingPip.id, {
        outcome: pipOutcome,
        outcome_notes: pipOutcomeNotes.trim() || null,
      });
      if (pipOutcome === "failed") {
        notify("PIP marked as Failed: Awaiting HR separation decision.", "warning");
      } else if (pipOutcome === "passed") {
        notify("PIP marked as Passed: Employee returned to regular status.", "success");
      } else {
        notify("PIP evaluation updated.", "info");
      }
      setEvaluatingPip(null);
      setPipOutcomeNotes("");
      fetchPIPs();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setSubmittingEval(false);
    }
  }

  async function handleSeparationDecision(e: React.FormEvent) {
    e.preventDefault();
    if (!decisionPip) return;
    setSubmittingDecision(true);
    try {
      if (decisionAction === "separate") {
        await decidePIPSeparation(decisionPip.id, {
          decision: "separate",
          last_working_date: decisionLwd,
          notice_choice: decisionNoticeChoice,
        });
        notify("Separation confirmed for employee.", "success");
      } else if (decisionAction === "extend") {
        if (!decisionNewEndDate) {
          notify("New PIP End Date is required.", "error");
          setSubmittingDecision(false);
          return;
        }
        if (new Date(decisionNewEndDate) <= new Date(decisionPip.end_date)) {
          notify("New end date must be later than the current PIP end date.", "error");
          setSubmittingDecision(false);
          return;
        }
        if (!decisionReason.trim()) {
          notify("Reason is required to extend PIP.", "error");
          setSubmittingDecision(false);
          return;
        }
        await decidePIPSeparation(decisionPip.id, {
          decision: "extend",
          new_end_date: decisionNewEndDate,
          reason: decisionReason.trim(),
        });
        notify("PIP extended with new end date.", "success");
      } else if (decisionAction === "retain") {
        if (!decisionReason.trim()) {
          notify("Reason is required to retain employee.", "error");
          setSubmittingDecision(false);
          return;
        }
        await decidePIPSeparation(decisionPip.id, {
          decision: "retain",
          reason: decisionReason.trim(),
        });
        notify("Employee retained. Pending separation cleared.", "success");
      }
      setDecisionPip(null);
      setDecisionReason("");
      setDecisionNewEndDate("");
      fetchPIPs();
    } catch (err) {
      notify(parseApiError(err).message, "error");
    } finally {
      setSubmittingDecision(false);
    }
  }

  const { user } = useAuth();
  const [activatingPipId, setActivatingPipId] = useState<string | null>(null);
  // Appraisal cycles belong to HR; PIPs are run by the employee's own manager,
  // which is what the API already allows, so a manager lands on the PIP tab and
  // never sees the cycles tab.
  const canSeeCycles = ["hr_admin", "owner"].includes(user?.role ?? "");
  const [viewTab, setViewTab] = useState<"cycles" | "pips" | "pending_separations">(canSeeCycles ? "cycles" : "pips");

  return (
    <div className="container">
      <div className="page-header flex justify-between align-center page-header-responsive">
        <div>
          <h1>Performance & Evaluation</h1>
          <p className="text-muted">Appraisal cycles, review deadlines & Performance Improvement Plans (PIP)</p>
        </div>
        <div className="flex gap-2" style={{ flexWrap: "wrap", width: "100%" }}>
          {viewTab === "cycles" && canSeeCycles ? (
            <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
              + Create Cycle
            </button>
          ) : (
            <button className="btn btn-primary" style={{ backgroundColor: "#d97706", borderColor: "#b45309" }} onClick={() => setShowPipCreateModal(true)}>
              + Initiate PIP
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-4 border-b mb-4" style={{ borderColor: "var(--color-border)" }}>
        {canSeeCycles && (
        <button
          type="button"
          className="btn-ghost"
          style={{
            padding: "0.5rem 1rem",
            fontWeight: viewTab === "cycles" ? 600 : 400,
            borderBottom: viewTab === "cycles" ? "2px solid var(--color-primary, #2563eb)" : "2px solid transparent",
            color: viewTab === "cycles" ? "var(--color-primary, #2563eb)" : "var(--color-text-muted)",
            cursor: "pointer",
          }}
          onClick={() => setViewTab("cycles")}
        >
          🔄 Appraisal Cycles
        </button>
        )}
        <button
          type="button"
          className="btn-ghost"
          style={{
            padding: "0.5rem 1rem",
            fontWeight: viewTab === "pips" ? 600 : 400,
            borderBottom: viewTab === "pips" ? "2px solid #d97706" : "2px solid transparent",
            color: viewTab === "pips" ? "#d97706" : "var(--color-text-muted)",
            cursor: "pointer",
          }}
          onClick={() => setViewTab("pips")}
        >
          ⚠️ Performance Improvement Plans (PIP)
        </button>
        {canSeeCycles && (
          <button
            type="button"
            className="btn-ghost"
            style={{
              padding: "0.5rem 1rem",
              fontWeight: viewTab === "pending_separations" ? 600 : 400,
              borderBottom: viewTab === "pending_separations" ? "2px solid #dc2626" : "2px solid transparent",
              color: viewTab === "pending_separations" ? "#dc2626" : "var(--color-text-muted)",
              cursor: "pointer",
            }}
            onClick={() => setViewTab("pending_separations")}
          >
            📋 Separations pending decision
            {pips.filter((p) => p.status === "failed").length > 0 && (
              <span
                style={{
                  marginLeft: "6px",
                  padding: "2px 6px",
                  borderRadius: "10px",
                  fontSize: "0.75rem",
                  background: "#fee2e2",
                  color: "#dc2626",
                  fontWeight: 700,
                }}
              >
                {pips.filter((p) => p.status === "failed").length}
              </span>
            )}
          </button>
        )}
      </div>

      {/* VIEW TAB 1: CYCLES */}
      {viewTab === "cycles" && canSeeCycles && (
        <>
          {/* Report Dashboard Card */}
          {report && report.active_cycle && (
            <div className="card my-4 p-6 bg-muted border rounded stack gap-4">
              <div className="flex justify-between align-center">
                <div>
                  <h3 className="text-lg fw-bold">Active Cycle: {report.active_cycle.name}</h3>
                  <p className="text-xs text-muted">
                    Period: {formatDate(report.active_cycle.start_date)} to {formatDate(report.active_cycle.end_date)}
                  </p>
                </div>
                <span className="badge badge-success">ACTIVE</span>
              </div>

              <div className="grid grid-3 gap-4">
                <div
                  className="p-3 bg-white rounded border"
                  style={{ cursor: "pointer", transition: "all 0.15s ease" }}
                  onClick={() => setStatusFilter("all")}
                  title="View all cycles"
                >
                  <span className="text-xs text-muted block">Total Headcount</span>
                  <strong className="text-xl">{report.total_employees} employees</strong>
                </div>
                <div
                  className="p-3 bg-white rounded border"
                  style={{ cursor: "pointer", transition: "all 0.15s ease" }}
                  onClick={() => setStatusFilter("active")}
                  title="Filter by active cycles"
                >
                  <span className="text-xs text-muted block">Reviews Completed</span>
                  <strong className="text-xl text-primary">{report.completed_reviews}</strong>
                </div>
                <div
                  className="p-3 bg-white rounded border"
                  style={{ cursor: "pointer", transition: "all 0.15s ease" }}
                  onClick={() => setStatusFilter("closed")}
                  title="Filter by closed cycles"
                >
                  <span className="text-xs text-muted block">Completion Rate</span>
                  <strong className="text-xl text-success">{report.completion_rate_percent}%</strong>
                </div>
              </div>
            </div>
          )}

          {/* Cycles Table */}
          <div className="card mt-4">
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "12px" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.85rem" }}>
                Show
                <select
                  aria-label="Filter cycles by status"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as CycleStatus | "all")}
                >
                  <option value="all">All cycles</option>
                  <option value="active">Active</option>
                  <option value="draft">Draft</option>
                  <option value="closed">Closed</option>
                </select>
              </label>
            </div>
            {loading ? (
              <p>Loading cycles...</p>
            ) : cycles.length === 0 ? (
              <p className="text-muted">No performance cycles created yet.</p>
            ) : (
              <div className="mobile-table-wrap">
                <table className="table" style={{ minWidth: "640px" }}>
                  <thead>
                    <tr>
                      <th>Cycle Name</th>
                      <th>Type</th>
                      <th>Period</th>
                      <th>Self Deadline</th>
                      <th>Manager Deadline</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cycles
                      .filter((c) => statusFilter === "all" || c.status === statusFilter)
                      .map((c) => (
                      <tr key={c.id}>
                        <td
                          className="fw-bold"
                          style={{ maxWidth: "260px", overflowWrap: "anywhere", wordBreak: "break-word" }}
                          title={c.name}
                        >
                          {c.name}
                        </td>
                        <td>
                          <span className="badge badge-outline">
                            {CYCLE_TYPE_LABELS[c.cycle_type] || c.cycle_type}
                          </span>
                        </td>
                        <td>{formatDate(c.start_date)} to {formatDate(c.end_date)}</td>
                        <td>{formatDate(c.self_review_deadline)}</td>
                        <td>{formatDate(c.manager_review_deadline)}</td>
                        <td>
                          <span
                            className={`badge ${
                              c.status === "active"
                                ? "badge-success"
                                : c.status === "closed"
                                ? "badge-muted"
                                : "badge-warning"
                            }`}
                          >
                            {CYCLE_STATUS_LABELS[c.status] || c.status}
                          </span>
                        </td>
                        <td>
                          {c.status === "draft" && (
                            <button
                              className="btn btn-sm btn-success"
                              onClick={() => handleStatusChange(c.id, "active")}
                            >
                              Activate
                            </button>
                          )}
                          {c.status === "active" && (
                            <button
                              className="btn btn-sm btn-outline text-red"
                              onClick={() => handleStatusChange(c.id, "closed")}
                            >
                              Close Cycle
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* VIEW TAB 2: PERFORMANCE IMPROVEMENT PLANS (PIP) */}
      {viewTab === "pips" && (
        <div className="stack gap-4 mt-2">
          <div className="p-4 rounded border" style={{ background: "#fffbeb", borderColor: "#fde68a" }}>
            <div className="flex justify-between items-center" style={{ flexWrap: "wrap", gap: "10px" }}>
              <div>
                <h3 style={{ margin: "0 0 4px 0", color: "#92400e", fontSize: "1rem" }}>
                  ⚠️ Performance Improvement & Warning Lifecycle
                </h3>
                <p className="text-xs" style={{ margin: 0, color: "#b45309", maxWidth: "780px" }}>
                  When an employee underperforms, a formal documented PIP warning period (30, 60, or 90 days) defines measurable KPIs and assigns a dedicated mentor.
                  Employees view an amber warning banner. At the conclusion, HR marks the outcome as <b>Passed</b> (regular status retained) or <b>Failed</b> (automatically triggers involuntary separation & routes into FnF settlement).
                </p>
              </div>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                style={{ backgroundColor: "#d97706", borderColor: "#b45309" }}
                onClick={() => setShowPipCreateModal(true)}
              >
                + Put Employee on PIP
              </button>
            </div>
          </div>

          <div className="card">
            <h3 style={{ margin: "0 0 1rem 0", fontSize: "1.05rem" }}>Active & Historical PIP Records</h3>
            {pipsLoading ? (
              <p>Loading PIP records...</p>
            ) : pips.length === 0 ? (
              <div style={{ textAlign: "center", padding: "2rem 1rem" }}>
                <span style={{ fontSize: "2rem" }}>🎯</span>
                <h4 style={{ margin: "0.5rem 0 0.25rem" }}>No Active PIPs</h4>
                <p className="text-muted text-sm" style={{ margin: 0 }}>
                  There are currently no employees in a formal Performance Improvement Plan warning period.
                </p>
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="table text-sm" style={{ width: "100%" }}>
                  <thead>
                    <tr>
                      <th>Employee</th>
                      <th>Plan Title & Objectives</th>
                      <th>Timeline</th>
                      <th>Assigned Mentor</th>
                      <th>Status</th>
                      <th style={{ textAlign: "right" }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pips.map((pip) => (
                      <tr key={pip.id}>
                        <td>
                          <strong>{pip.employee_name || pip.employee_id}</strong>
                          {pip.employee_code && (
                            <span className="text-xs text-muted block">{pip.employee_code}</span>
                          )}
                        </td>
                        <td>
                          <div className="fw-bold">{pip.title}</div>
                          {pip.milestones_kpis && (
                            <div className="text-xs text-muted" style={{ maxWidth: "320px", whiteSpace: "normal" }}>
                              🎯 <strong>KPIs:</strong> {pip.milestones_kpis}
                            </div>
                          )}
                        </td>
                        <td>
                          <div>{formatDate(pip.start_date)} to {formatDate(pip.end_date)}</div>
                          <span className="text-xs text-muted">
                            {Math.round((new Date(pip.end_date).getTime() - new Date(pip.start_date).getTime()) / 86400000)} days
                          </span>
                        </td>
                        <td>{pip.mentor_name || "Not assigned"}</td>
                        <td>
                          <span
                            className={`badge ${
                              pip.status === "active" || pip.status === "extended"
                                ? "badge-warning"
                                : pip.status === "passed"
                                ? "badge-success"
                                : pip.status === "draft"
                                ? "badge-muted"
                                : pip.status === "failed"
                                ? "badge-warning"
                                : "badge-danger"
                            }`}
                            style={
                              pip.status === "active" || pip.status === "failed"
                                ? { background: "#fef3c7", color: "#b45309", border: "1px solid #fde68a" }
                                : undefined
                            }
                          >
                            {pip.status === "failed" ? "Awaiting HR decision" : pip.status.toUpperCase()}
                          </span>
                        </td>
                        <td style={{ textAlign: "right" }}>
                          {/* A draft plan has not started yet: it is activated
                              here rather than only through the API, and it is
                              never described as concluded. */}
                          {pip.status === "draft" ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              disabled={activatingPipId === pip.id}
                              onClick={() => handleActivatePip(pip.id)}
                            >
                              {activatingPipId === pip.id ? "Activating..." : "Activate"}
                            </button>
                          ) : pip.status === "active" || pip.status === "extended" ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              onClick={() => {
                                setEvaluatingPip(pip);
                                setPipOutcome("passed");
                                setPipOutcomeNotes("");
                              }}
                            >
                              Evaluate Outcome
                            </button>
                          ) : (
                            <span className="text-xs text-muted" style={{ fontStyle: "italic" }}>
                              {pip.outcome_notes || "Concluded"}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* VIEW TAB 3: SEPARATIONS PENDING DECISION (F2) */}
      {viewTab === "pending_separations" && canSeeCycles && (
        <div className="stack gap-4 mt-2">
          <div className="p-4 rounded border" style={{ background: "#fff1f2", borderColor: "#fecdd3" }}>
            <div className="flex justify-between items-center" style={{ flexWrap: "wrap", gap: "10px" }}>
              <div>
                <h3 style={{ margin: "0 0 4px 0", color: "#9f1239", fontSize: "1rem" }}>
                  📋 Failed PIP Separations Pending HR Decision
                </h3>
                <p className="text-xs" style={{ margin: 0, color: "#be123c", maxWidth: "780px" }}>
                  These employees have failed their Performance Improvement Plan. Employment does not end automatically: HR must review and choose to <b>Separate</b> (with notice terms & last working date), <b>Extend</b> (set new PIP end date), or <b>Retain</b> (clear pending separation).
                  Note: The manager who evaluated the PIP cannot confirm the separation (maker-checker rule).
                </p>
              </div>
            </div>
          </div>

          <div className="card">
            <h3 style={{ margin: "0 0 1rem 0", fontSize: "1.05rem" }}>Failed PIP Records Requiring Action</h3>
            {pipsLoading ? (
              <p>Loading records...</p>
            ) : pips.filter((p) => p.status === "failed").length === 0 ? (
              <div style={{ textAlign: "center", padding: "2rem 1rem" }}>
                <span style={{ fontSize: "2rem" }}>✅</span>
                <h4 style={{ margin: "0.5rem 0 0.25rem" }}>No Pending Separation Decisions</h4>
                <p className="text-muted text-sm" style={{ margin: 0 }}>
                  There are currently no failed PIPs awaiting an HR separation decision.
                </p>
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="table text-sm" style={{ width: "100%" }}>
                  <thead>
                    <tr>
                      <th>Employee</th>
                      <th>Plan Title</th>
                      <th>Evaluated By</th>
                      <th>Evaluated At</th>
                      <th>Evaluation Notes</th>
                      <th style={{ textAlign: "right" }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pips
                      .filter((p) => p.status === "failed")
                      .map((pip) => (
                        <tr key={pip.id}>
                          <td>
                            <strong>{pip.employee_name || pip.employee_id}</strong>
                            {pip.employee_code && (
                              <span className="text-xs text-muted block">{pip.employee_code}</span>
                            )}
                          </td>
                          <td>
                            <div className="fw-bold">{pip.title}</div>
                            <span className="badge badge-warning text-xs mt-1" style={{ background: "#fef3c7", color: "#b45309" }}>
                              Awaiting HR decision
                            </span>
                          </td>
                          <td>
                            <span className="text-sm">{pip.evaluated_by || "Manager"}</span>
                          </td>
                          <td>
                            <span className="text-sm">{pip.evaluated_at ? formatDate(pip.evaluated_at) : "Recently"}</span>
                          </td>
                          <td style={{ maxWidth: "260px" }}>
                            <span className="text-xs text-muted" style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                              {pip.outcome_notes || "—"}
                            </span>
                          </td>
                          <td style={{ textAlign: "right" }}>
                            <div className="flex gap-2 justify-end" style={{ flexWrap: "wrap" }}>
                              <button
                                type="button"
                                className="btn btn-sm btn-danger"
                                onClick={() => {
                                  setDecisionPip(pip);
                                  setDecisionAction("separate");
                                  setDecisionLwd(new Date().toISOString().split("T")[0]);
                                  setDecisionNoticeChoice("served");
                                  setDecisionReason("");
                                }}
                              >
                                Separate
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm btn-outline"
                                onClick={() => {
                                  setDecisionPip(pip);
                                  setDecisionAction("extend");
                                  const currentEnd = new Date(pip.end_date);
                                  const extended = new Date(currentEnd.getTime() + 30 * 86400000);
                                  setDecisionNewEndDate(extended.toISOString().split("T")[0]);
                                  setDecisionReason("");
                                }}
                              >
                                Extend
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm btn-success"
                                onClick={() => {
                                  setDecisionPip(pip);
                                  setDecisionAction("retain");
                                  setDecisionReason("");
                                }}
                              >
                                Retain
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* MODAL: SEPARATION DECISION (F2) */}
      {decisionPip && (
        <div className="modal-backdrop" onClick={() => setDecisionPip(null)}>
          <div className="modal card" style={{ maxWidth: "560px", width: "95%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>
                {decisionAction === "separate"
                  ? `Confirm Separation: ${decisionPip.employee_name || decisionPip.employee_id}`
                  : decisionAction === "extend"
                  ? `Extend PIP: ${decisionPip.employee_name || decisionPip.employee_id}`
                  : `Retain Employee: ${decisionPip.employee_name || decisionPip.employee_id}`}
              </h3>
              <button type="button" className="modal-close-btn" onClick={() => setDecisionPip(null)}>✕</button>
            </div>
            <form onSubmit={handleSeparationDecision} className="stack gap-3 mt-3">
              <div className="field">
                <label>Decision Action</label>
                <div className="flex gap-3 mt-1">
                  <label className="flex items-center gap-1" style={{ cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="decisionAction"
                      value="separate"
                      checked={decisionAction === "separate"}
                      onChange={() => setDecisionAction("separate")}
                    />
                    <span>Separate</span>
                  </label>
                  <label className="flex items-center gap-1" style={{ cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="decisionAction"
                      value="extend"
                      checked={decisionAction === "extend"}
                      onChange={() => setDecisionAction("extend")}
                    />
                    <span>Extend</span>
                  </label>
                  <label className="flex items-center gap-1" style={{ cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="decisionAction"
                      value="retain"
                      checked={decisionAction === "retain"}
                      onChange={() => setDecisionAction("retain")}
                    />
                    <span>Retain</span>
                  </label>
                </div>
              </div>

              {decisionAction === "separate" && (
                <>
                  <div className="p-3 bg-muted rounded border text-xs text-muted">
                    <strong>Notice Policy:</strong> Notice is served by default. Waived notice or pay-in-lieu must be explicitly selected. Last working date cannot be in the past or more than 180 days ahead.
                  </div>
                  <div className="field">
                    <label>Last Working Date *</label>
                    <input
                      type="date"
                      value={decisionLwd}
                      onChange={(e) => setDecisionLwd(e.target.value)}
                      required
                    />
                  </div>
                  <div className="field">
                    <label>Notice Choice * (Default: Served)</label>
                    <select
                      value={decisionNoticeChoice}
                      onChange={(e) => setDecisionNoticeChoice(e.target.value as typeof decisionNoticeChoice)}
                      required
                    >
                      <option value="served">Notice Served (Employee works through last working date)</option>
                      <option value="waived">Notice Waived (No notice required/recovered)</option>
                      <option value="pay_in_lieu">Pay-in-Lieu (Company pays notice amount)</option>
                    </select>
                  </div>
                </>
              )}

              {decisionAction === "extend" && (
                <>
                  <div className="field">
                    <label>Current PIP End Date</label>
                    <input type="date" value={decisionPip.end_date} disabled className="bg-muted" />
                  </div>
                  <div className="field">
                    <label>New PIP End Date * (Must be later than current end date)</label>
                    <input
                      type="date"
                      value={decisionNewEndDate}
                      onChange={(e) => setDecisionNewEndDate(e.target.value)}
                      required
                    />
                  </div>
                  <div className="field">
                    <label>Reason for Extension * (1–500 characters)</label>
                    <textarea
                      rows={3}
                      maxLength={500}
                      value={decisionReason}
                      onChange={(e) => setDecisionReason(e.target.value)}
                      placeholder="Explain targets to achieve during extended period..."
                      required
                    />
                  </div>
                </>
              )}

              {decisionAction === "retain" && (
                <>
                  <div className="p-3 bg-muted rounded border text-xs text-muted">
                    Retaining will clear the pending separation status for the employee and keep them active in the organization.
                  </div>
                  <div className="field">
                    <label>Reason for Retention * (1–500 characters)</label>
                    <textarea
                      rows={3}
                      maxLength={500}
                      value={decisionReason}
                      onChange={(e) => setDecisionReason(e.target.value)}
                      placeholder="Explain justification for retaining the employee..."
                      required
                    />
                  </div>
                </>
              )}

              <div className="row-end gap-2 mt-2">
                <button type="button" className="btn btn-ghost" onClick={() => setDecisionPip(null)}>
                  Cancel
                </button>
                <button
                  type="submit"
                  className={`btn ${decisionAction === "separate" ? "btn-danger" : "btn-primary"}`}
                  disabled={submittingDecision}
                >
                  {submittingDecision ? "Saving..." : `Confirm ${decisionAction.charAt(0).toUpperCase() + decisionAction.slice(1)}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {showPipCreateModal && (
        <div className="modal-backdrop" onClick={() => setShowPipCreateModal(false)}>
          <div className="modal card performance-goal-modal" style={{ maxWidth: "560px", width: "95%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 style={{ margin: 0, color: "#d97706" }}>⚠️ Put Employee on Performance Improvement Plan (PIP)</h3>
              <button type="button" className="modal-close-btn" onClick={() => setShowPipCreateModal(false)}>✕</button>
            </div>
            <form onSubmit={handleCreatePip} className="stack gap-3 mt-3">
              <div className="field">
                <label>Select Underperforming Employee *</label>
                <select
                  value={pipEmployeeId}
                  onChange={(e) => setPipEmployeeId(e.target.value)}
                  required
                >
                  <option value="">Select an employee...</option>
                  {employees.filter((emp) => emp.is_active).map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.first_name} {emp.last_name || ""} ({emp.employee_code}) — {emp.position || "Staff"}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label>Assigned Mentor / Evaluator</label>
                <select
                  value={pipMentorId}
                  onChange={(e) => setPipMentorId(e.target.value)}
                >
                  <option value="">Select mentor (optional, defaults to manager/HR)...</option>
                  {employees.filter((emp) => emp.is_active).map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.first_name} {emp.last_name || ""} ({emp.employee_code})
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label>PIP Plan Title *</label>
                <input
                  type="text"
                  value={pipTitle}
                  onChange={(e) => setPipTitle(e.target.value)}
                  placeholder="e.g. 30-Day Engineering Improvement Plan"
                  required
                />
              </div>

              <div className="form-grid">
                <div className="field">
                  <label>Start Date *</label>
                  <input
                    type="date"
                    value={pipStartDate}
                    onChange={(e) => setPipStartDate(e.target.value)}
                    required
                  />
                </div>
                <div className="field">
                  <label>End Date (Evaluation Deadline) *</label>
                  <input
                    type="date"
                    value={pipEndDate}
                    onChange={(e) => setPipEndDate(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="field">
                <label>Improvement Milestones & Measurable KPIs *</label>
                <textarea
                  rows={3}
                  value={pipMilestones}
                  onChange={(e) => setPipMilestones(e.target.value)}
                  placeholder="Specify clear objective metrics: e.g. Deliver sprint tasks on time, 0 production regressions, weekly progress reviews with mentor..."
                  required
                />
              </div>

              <div className="field">
                <label>Context / Performance Concerns</label>
                <textarea
                  rows={2}
                  value={pipDescription}
                  onChange={(e) => setPipDescription(e.target.value)}
                  placeholder="Summary of underperformance concerns discussed with employee..."
                />
              </div>

              <div className="row-end gap-2 mt-2">
                <button type="button" className="btn btn-ghost" onClick={() => setShowPipCreateModal(false)}>
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  style={{ backgroundColor: "#d97706", borderColor: "#b45309" }}
                  disabled={submittingPip}
                >
                  {submittingPip ? "Initiating..." : "Confirm & Place on PIP"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: EVALUATE PIP */}
      {evaluatingPip && (
        <div className="modal-backdrop" onClick={() => setEvaluatingPip(null)}>
          <div className="modal card performance-goal-modal" style={{ maxWidth: "520px", width: "95%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>Evaluate PIP: {evaluatingPip.employee_name || evaluatingPip.title}</h3>
              <button type="button" className="modal-close-btn" onClick={() => setEvaluatingPip(null)}>✕</button>
            </div>
            <form onSubmit={handleEvaluatePip} className="stack gap-3 mt-3">
              <div className="field">
                <label>Evaluation Decision *</label>
                <select
                  value={pipOutcome}
                  onChange={(e) => setPipOutcome(e.target.value as typeof pipOutcome)}
                  required
                >
                  <option value="passed">✅ Passed — Employee met all targets (Retain regular status)</option>
                  <option value="failed">❌ Failed — Targets missed (Triggers Involuntary Separation & FnF)</option>
                  <option value="cancelled">🚫 Cancelled — Plan closed without penalty</option>
                </select>
              </div>

              {pipOutcome === "failed" && (
                <div className="alert alert-warning text-xs" style={{ margin: 0 }}>
                  <strong>⚠️ Two-Step Separation:</strong> Marking this PIP as Failed will place <b>{evaluatingPip.employee_name}</b> in <code>Pending Separation</code> status. An HR administrator (different from the evaluating manager) will confirm the final separation decision.
                </div>
              )}

              <div className="field">
                <label>Evaluation Notes & Final Feedback *</label>
                <textarea
                  rows={3}
                  value={pipOutcomeNotes}
                  onChange={(e) => setPipOutcomeNotes(e.target.value)}
                  placeholder="Detail observations, mentor recommendations, and final metrics achieved..."
                  required
                />
              </div>

              <div className="row-end gap-2 mt-2">
                <button type="button" className="btn btn-ghost" onClick={() => setEvaluatingPip(null)}>
                  Cancel
                </button>
                <button
                  type="submit"
                  className={`btn ${pipOutcome === "failed" ? "btn-danger" : "btn-primary"}`}
                  disabled={submittingEval}
                >
                  {submittingEval ? "Saving Evaluation..." : "Submit PIP Evaluation"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Create Cycle */}
      {showCreateModal && (
        <div className="modal-backdrop" onClick={() => setShowCreateModal(false)}>
          <div className="modal card max-w-lg performance-goal-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Create Performance Cycle</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowCreateModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreate} className="stack gap-4 my-2">
              <div className="field">
                <label>Cycle Name *</label>
                <input
                  type="text"
                  placeholder="e.g. FY 2026–27 Annual Review, Q3 2026 Engineering Appraisal"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
                <span className="field-hint">Use a descriptive title including fiscal year or quarter.</span>
              </div>

              <div className="grid-2">
                <div className="field">
                  <label>Type</label>
                  <select
                    value={cycleType}
                    onChange={(e) => setCycleType(e.target.value as CycleType)}
                  >
                    <option value="annual">Annual</option>
                    <option value="half_yearly">Half Yearly</option>
                    <option value="quarterly">Quarterly</option>
                  </select>
                </div>
                <div className="field">
                  <label>Start Date *</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="grid-2">
                <div className="field">
                  <label>Cycle End Date *</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    required
                  />
                </div>
                <div className="field">
                  <label>Self Review Deadline</label>
                  <input
                    type="date"
                    value={selfDeadline}
                    onChange={(e) => setSelfDeadline(e.target.value)}
                  />
                  <span className="field-hint">Must be on or before Manager Review Deadline.</span>
                </div>
              </div>

              <div className="field">
                <label>Manager Review Deadline</label>
                <input
                  type="date"
                  value={mgrDeadline}
                  onChange={(e) => setMgrDeadline(e.target.value)}
                />
                <span className="field-hint">Must be on or before overall Cycle End Date.</span>
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowCreateModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
