import { useState, useEffect } from "react";
import {
  listPerformanceCycles,
  createPerformanceCycle,
  updatePerformanceCycle,
  getPerformanceReport,
  type PerformanceCycle,
  type PerformanceReport,
  type CycleType,
  type CycleStatus,
} from "../api";
import { useToast } from "../../../app/toast-context";

export function PerformanceCyclesPage() {
  const { notify } = useToast();
  const [cycles, setCycles] = useState<PerformanceCycle[]>([]);
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<PerformanceReport | null>(null);

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
  }, []);

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

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      notify("Please enter cycle name", "error");
      return;
    }
    setSubmitting(true);
    try {
      await createPerformanceCycle({
        name,
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
      const msg = err instanceof Error ? err.message : "Failed to create cycle";
      notify(msg, "error");
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
    } catch {
      notify("Failed to update cycle status", "error");
    }
  }

  return (
    <div className="container">
      <div className="page-header flex justify-between align-center">
        <div>
          <h1>Performance Cycles</h1>
          <p className="text-muted">Configure evaluation periods, review deadlines & company performance metrics</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
          + Create Cycle
        </button>
      </div>

      {/* Report Dashboard Card */}
      {report && report.active_cycle && (
        <div className="card my-4 p-6 bg-muted border rounded stack gap-4">
          <div className="flex justify-between align-center">
            <div>
              <h3 className="text-lg fw-bold">Active Cycle: {report.active_cycle.name}</h3>
              <p className="text-xs text-muted">
                Period: {report.active_cycle.start_date} to {report.active_cycle.end_date}
              </p>
            </div>
            <span className="badge badge-success">ACTIVE</span>
          </div>

          <div className="grid grid-3 gap-4">
            <div className="p-3 bg-white rounded border">
              <span className="text-xs text-muted block">Total Headcount</span>
              <strong className="text-xl">{report.total_employees} employees</strong>
            </div>
            <div className="p-3 bg-white rounded border">
              <span className="text-xs text-muted block">Reviews Completed</span>
              <strong className="text-xl text-primary">{report.completed_reviews}</strong>
            </div>
            <div className="p-3 bg-white rounded border">
              <span className="text-xs text-muted block">Completion Rate</span>
              <strong className="text-xl text-success">{report.completion_rate_percent}%</strong>
            </div>
          </div>
        </div>
      )}

      {/* Cycles Table */}
      <div className="card mt-4">
        {loading ? (
          <p>Loading cycles...</p>
        ) : cycles.length === 0 ? (
          <p className="text-muted">No performance cycles created yet.</p>
        ) : (
          <table className="table">
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
              {cycles.map((c) => (
                <tr key={c.id}>
                  <td className="fw-bold">{c.name}</td>
                  <td>
                    <span className="badge badge-outline">{c.cycle_type}</span>
                  </td>
                  <td>{c.start_date} to {c.end_date}</td>
                  <td>{c.self_review_deadline || "—"}</td>
                  <td>{c.manager_review_deadline || "—"}</td>
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
                      {c.status}
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
        )}
      </div>

      {/* Modal: Create Cycle */}
      {showCreateModal && (
        <div className="modal-backdrop">
          <div className="modal card max-w-lg">
            <h2>Create Performance Cycle</h2>
            <form onSubmit={handleCreate} className="stack gap-4">
              <div>
                <label>Cycle Name</label>
                <input
                  type="text"
                  placeholder="e.g. FY 2026-27 Annual Performance Appraisal"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>

              <div className="grid grid-2 gap-4">
                <div>
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
                <div>
                  <label>Start Date</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="grid grid-2 gap-4">
                <div>
                  <label>End Date</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label>Self Review Deadline</label>
                  <input
                    type="date"
                    value={selfDeadline}
                    onChange={(e) => setSelfDeadline(e.target.value)}
                  />
                </div>
              </div>

              <div>
                <label>Manager Review Deadline</label>
                <input
                  type="date"
                  value={mgrDeadline}
                  onChange={(e) => setMgrDeadline(e.target.value)}
                />
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowCreateModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? "Creating..." : "Save Cycle"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
