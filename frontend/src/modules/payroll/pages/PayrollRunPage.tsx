import { useState, useEffect, useMemo } from "react";
import {
  listPayrollRuns,
  createPayrollRun,
  getPayrollRunDetail,
  approvePayrollRun,
  type PayrollRun,
  type PayrollRunDetail,
} from "../api";
import { listEmployees, type Employee } from "../../hr/api";
import { useToast } from "../../../app/toast-context";

export function PayrollRunPage() {
  const { notify } = useToast();
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);

  // Trigger Run Modal
  const [showRunModal, setShowRunModal] = useState(false);
  const [runMonth, setRunMonth] = useState<number>(new Date().getMonth() + 1);
  const [runYear, setRunYear] = useState<number>(new Date().getFullYear());
  const [runType, setRunType] = useState<string>("regular");
  const [startingRun, setStartingRun] = useState(false);

  // Detail View Modal
  const [selectedRunDetail, setSelectedRunDetail] = useState<PayrollRunDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [approving, setApproving] = useState(false);

  const employeeMap = useMemo(() => {
    const map = new Map<string, Employee>();
    for (const emp of employees) {
      map.set(emp.id, emp);
    }
    return map;
  }, [employees]);

  useEffect(() => {
    fetchRuns();
    fetchEmployees();
  }, []);

  async function fetchEmployees() {
    try {
      const res = await listEmployees({ page: 1, limit: 100 });
      setEmployees(res.items);
    } catch {
      // Non-critical, fallback to truncated IDs
    }
  }

  async function fetchRuns() {
    setLoading(true);
    try {
      const res = await listPayrollRuns();
      setRuns(res.items);
    } catch {
      notify("Failed to load payroll runs", "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleStartRun(e: React.FormEvent) {
    e.preventDefault();
    setStartingRun(true);
    try {
      await createPayrollRun(runMonth, runYear, runType);
      notify("Payroll run created successfully", "success");
      setShowRunModal(false);
      fetchRuns();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to start payroll run";
      notify(msg, "error");
    } finally {
      setStartingRun(false);
    }
  }

  async function handleViewDetail(runId: string) {
    setLoadingDetail(true);
    try {
      const detail = await getPayrollRunDetail(runId);
      setSelectedRunDetail(detail);
    } catch {
      notify("Failed to load run details", "error");
    } finally {
      setLoadingDetail(false);
    }
  }

  async function handleApproveRun(runId: string) {
    setApproving(true);
    try {
      const updatedRun = await approvePayrollRun(runId);
      notify("Payroll run approved! Payslips are now visible to employees.", "success");
      if (selectedRunDetail) {
        setSelectedRunDetail({ ...selectedRunDetail, run: updatedRun });
      }
      fetchRuns();
    } catch {
      notify("Failed to approve payroll run", "error");
    } finally {
      setApproving(false);
    }
  }

  const MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ];

  return (
    <div className="container">
      <div className="page-header flex justify-between align-center">
        <div>
          <h1>Payroll Runs</h1>
          <p className="text-muted">Execute monthly payroll runs, review breakdowns & approve payslips</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowRunModal(true)}>
          + Run Payroll
        </button>
      </div>

      <div className="card mt-4">
        {loading ? (
          <p>Loading payroll runs...</p>
        ) : runs.length === 0 ? (
          <p className="text-muted">No payroll runs found. Click "+ Run Payroll" to initiate a run.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Period</th>
                <th>Type</th>
                <th>Status</th>
                <th>Employees</th>
                <th>Total Gross</th>
                <th>Total Deductions</th>
                <th>Total Net Salary</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td className="fw-bold">
                    {MONTH_NAMES[r.month - 1]} {r.year}
                  </td>
                  <td>
                    <span className="badge badge-outline">{r.run_type}</span>
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        r.status === "approved"
                          ? "badge-success"
                          : r.status === "processing"
                          ? "badge-warning"
                          : "badge-muted"
                      }`}
                    >
                      {r.status}
                    </span>
                  </td>
                  <td>{r.total_employees ?? "—"}</td>
                  <td>₹{r.total_gross ? Number(r.total_gross).toLocaleString() : "0.00"}</td>
                  <td>₹{r.total_deductions ? Number(r.total_deductions).toLocaleString() : "0.00"}</td>
                  <td className="fw-bold text-success">
                    ₹{r.total_net ? Number(r.total_net).toLocaleString() : "0.00"}
                  </td>
                  <td>
                    <button className="btn btn-sm btn-outline" onClick={() => handleViewDetail(r.id)}>
                      View Details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal: Start Payroll Run */}
      {showRunModal && (
        <div className="modal-backdrop">
          <div className="modal card max-w-md">
            <h2>Initiate Payroll Run</h2>
            <form onSubmit={handleStartRun} className="stack gap-4">
              <div className="grid grid-2 gap-4">
                <div>
                  <label>Month</label>
                  <select value={runMonth} onChange={(e) => setRunMonth(Number(e.target.value))}>
                    {MONTH_NAMES.map((name, idx) => (
                      <option key={idx} value={idx + 1}>
                        {name} ({idx + 1})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label>Year</label>
                  <input
                    type="number"
                    value={runYear}
                    onChange={(e) => setRunYear(Number(e.target.value))}
                    required
                  />
                </div>
              </div>

              <div>
                <label>Run Type</label>
                <select value={runType} onChange={(e) => setRunType(e.target.value)}>
                  <option value="regular">Regular Monthly Run</option>
                  <option value="off_cycle">Off-cycle Run</option>
                </select>
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowRunModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={startingRun}>
                  {startingRun ? "Processing..." : "Start Run"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Run Details */}
      {selectedRunDetail && (
        <div className="modal-backdrop">
          <div className="modal card" style={{ maxWidth: "960px", width: "95vw" }}>
            <div className="flex justify-between align-center border-b pb-3 mb-4">
              <div>
                <h2>
                  Payroll Run: {MONTH_NAMES[selectedRunDetail.run.month - 1]} {selectedRunDetail.run.year}
                </h2>
                <p className="text-muted text-sm">
                  Run ID: {selectedRunDetail.run.id} | Status:{" "}
                  <strong className="text-primary">{selectedRunDetail.run.status}</strong>
                </p>
              </div>
              {selectedRunDetail.run.status !== "approved" && (
                <button
                  className="btn btn-success"
                  onClick={() => handleApproveRun(selectedRunDetail.run.id)}
                  disabled={approving}
                >
                  {approving ? "Approving..." : "Approve Run & Release Payslips"}
                </button>
              )}
            </div>

            {loadingDetail ? (
              <p>Loading employee payslip items...</p>
            ) : (
              <div className="stack gap-4">
                <div style={{ overflowX: "auto" }}>
                  <table className="table text-sm" style={{ width: "100%" }}>
                    <thead>
                      <tr>
                        <th>Employee</th>
                        <th>CTC Snapshot</th>
                        <th>Gross</th>
                        <th>Deductions</th>
                        <th>Reimbursements</th>
                        <th>Net Salary</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedRunDetail.items.map((item) => {
                        const emp = employeeMap.get(item.employee_id);
                        const empName = emp
                          ? `${emp.first_name} ${emp.last_name || ""}`.trim()
                          : `ID: ${item.employee_id.substring(0, 8)}...`;
                        const empSubtitle = emp
                          ? `${emp.employee_code} • ${emp.position || "Staff"}`
                          : null;

                        return (
                          <tr key={item.id}>
                            <td>
                              <div className="fw-semibold text-primary">{empName}</div>
                              {empSubtitle && (
                                <div className="text-muted text-xs">{empSubtitle}</div>
                              )}
                            </td>
                            <td>₹{Number(item.ctc_snapshot).toLocaleString()}</td>
                            <td>₹{Number(item.gross_salary).toLocaleString()}</td>
                            <td className="text-red">-₹{Number(item.total_deductions).toLocaleString()}</td>
                            <td className="text-blue">+₹{Number(item.reimbursement_amount).toLocaleString()}</td>
                            <td className="fw-bold text-success">
                              ₹{Number(item.net_salary).toLocaleString()}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="flex justify-end mt-4">
                  <button className="btn btn-ghost" onClick={() => setSelectedRunDetail(null)}>
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
