import { useState, useEffect, useMemo } from "react";
import {
  listPayrollRuns,
  createPayrollRun,
  getPayrollRunDetail,
  approvePayrollRun,
  deletePayrollRun,
  type PayrollRun,
  type PayrollRunDetail,
} from "../api";
import { listEmployees, type Employee } from "../../hr/api";
import { useToast } from "../../../app/toast-context";
import { parseApiError } from "../../../shared/api/errors";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog";


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
      const parsed = parseApiError(err);
      if (parsed.status === 409 || parsed.code === "conflict") {
        notify(parsed.message || "A payroll run for this period already exists.", "warning");
      } else {
        notify(parsed.message || "Failed to start payroll run", "error");
      }
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

  // Delete Draft Run
  const [runToDelete, setRunToDelete] = useState<PayrollRun | null>(null);
  const [deletingRun, setDeletingRun] = useState(false);

  async function handleDeleteRun() {
    if (!runToDelete) return;
    setDeletingRun(true);
    try {
      await deletePayrollRun(runToDelete.id);
      notify("Draft payroll run cancelled and deleted.", "success");
      setRunToDelete(null);
      fetchRuns();
    } catch (err) {
      notify(parseApiError(err).message || "Failed to delete payroll run", "error");
    } finally {
      setDeletingRun(false);
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
                    {r.status === "approved" || r.status === "paid" ? (
                      <span
                        className="badge"
                        style={{
                          backgroundColor: "#dcfce7",
                          color: "#15803d",
                          border: "1px solid #bbf7d0",
                          fontWeight: 600,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        ● Approved
                      </span>
                    ) : r.status === "pending_approval" ? (
                      <span
                        className="badge"
                        style={{
                          backgroundColor: "#fef3c7",
                          color: "#b45309",
                          border: "1px solid #fde68a",
                          fontWeight: 600,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        ⏳ Pending Approval
                      </span>
                    ) : r.status === "processing" ? (
                      <span
                        className="badge"
                        style={{
                          backgroundColor: "#e0e7ff",
                          color: "#3730a3",
                          border: "1px solid #c7d2fe",
                          fontWeight: 600,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        ⚙️ Processing
                      </span>
                    ) : r.status === "draft" ? (
                      <span
                        className="badge"
                        style={{
                          backgroundColor: "#f1f5f9",
                          color: "#475569",
                          border: "1px solid #cbd5e1",
                          fontWeight: 600,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        📝 Draft
                      </span>
                    ) : r.status === "failed" ? (
                      <span
                        className="badge"
                        style={{
                          backgroundColor: "#fee2e2",
                          color: "#b91c1c",
                          border: "1px solid #fecaca",
                          fontWeight: 600,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        ✕ Failed
                      </span>
                    ) : (
                      <span className="badge badge-muted">{r.status.replace("_", " ")}</span>
                    )}
                  </td>
                  <td>{r.total_employees ?? "—"}</td>
                  <td>₹{r.total_gross ? Number(r.total_gross).toLocaleString() : "0.00"}</td>
                  <td>₹{r.total_deductions ? Number(r.total_deductions).toLocaleString() : "0.00"}</td>
                  <td className="fw-bold text-success">
                    ₹{r.total_net ? Number(r.total_net).toLocaleString() : "0.00"}
                  </td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <button className="btn btn-sm btn-outline" onClick={() => handleViewDetail(r.id)}>
                        View Details
                      </button>
                      {(r.status === "draft" || r.status === "processing" || r.status === "pending_approval") && (
                        <button
                          className="btn btn-sm btn-danger"
                          onClick={() => setRunToDelete(r)}
                          title={r.status === "pending_approval" ? "Cancel Run (Pending Approval)" : "Delete Draft Run"}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "4px",
                            padding: "4px 8px",
                          }}
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="3 6 5 6 21 6" />
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                            <line x1="10" y1="11" x2="10" y2="17" />
                            <line x1="14" y1="11" x2="14" y2="17" />
                          </svg>
                          <span>{r.status === "pending_approval" ? "Cancel Run" : "Delete Draft"}</span>
                        </button>
                      )}
                    </div>
                  </td>
                </tr>

              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal: Start Payroll Run */}
      {showRunModal && (
        <div className="modal-backdrop" onClick={() => setShowRunModal(false)}>
          <div className="modal card max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Initiate Payroll Run</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowRunModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            {(() => {
              const existingRegularRun = runs.find(
                (r) => r.month === runMonth && r.year === runYear && r.run_type === "regular"
              );
              if (existingRegularRun && runType === "regular") {
                return (
                  <div
                    style={{
                      background: "rgba(245, 158, 11, 0.12)",
                      border: "1px solid rgba(245, 158, 11, 0.4)",
                      borderRadius: "8px",
                      padding: "10px 14px",
                      fontSize: "13px",
                      color: "#b45309",
                      marginBottom: "12px",
                      lineHeight: "1.5",
                    }}
                  >
                    <strong>Notice:</strong> A regular payroll run for {MONTH_NAMES[runMonth - 1]} {runYear} already exists (Status: <em>{existingRegularRun.status}</em>).
                    <div style={{ marginTop: "4px" }}>
                      If salaries have already been computed or paid, you cannot run another regular payroll for this same period. Please switch <strong>Run Type</strong> to <em>Off-cycle Run</em> for bonuses/adjustments or select another month.
                    </div>
                  </div>
                );
              }
              return null;
            })()}

            <form onSubmit={handleStartRun} className="stack gap-4 my-2">
              <div className="grid-2">
                <div className="field">
                  <label>Month</label>
                  <select value={runMonth} onChange={(e) => setRunMonth(Number(e.target.value))}>
                    {MONTH_NAMES.map((name, idx) => (
                      <option key={idx} value={idx + 1}>
                        {name} ({idx + 1})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label>Year</label>
                  <input
                    type="number"
                    value={runYear}
                    onChange={(e) => setRunYear(Number(e.target.value))}
                    required
                  />
                </div>
              </div>

              <div className="field">
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
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={
                    startingRun ||
                    (runType === "regular" &&
                      runs.some((r) => r.month === runMonth && r.year === runYear && r.run_type === "regular"))
                  }
                >
                  {startingRun ? "Running..." : "Run"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Run Details */}
      {selectedRunDetail && (
        <div className="modal-backdrop" onClick={() => setSelectedRunDetail(null)}>
          <div className="modal card" style={{ maxWidth: "960px", width: "95vw" }} onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between align-center border-b pb-3 mb-4">
              <div>
                <h2>
                  Payroll Run: {MONTH_NAMES[selectedRunDetail.run.month - 1]} {selectedRunDetail.run.year}
                </h2>
                <p className="text-muted text-sm">
                  Run ID: {selectedRunDetail.run.id} | Status:{" "}
                  <span
                    className="badge"
                    style={{
                      backgroundColor:
                        selectedRunDetail.run.status === "approved" || selectedRunDetail.run.status === "paid"
                          ? "#dcfce7"
                          : selectedRunDetail.run.status === "pending_approval"
                          ? "#fef3c7"
                          : selectedRunDetail.run.status === "processing"
                          ? "#e0e7ff"
                          : "#f1f5f9",
                      color:
                        selectedRunDetail.run.status === "approved" || selectedRunDetail.run.status === "paid"
                          ? "#15803d"
                          : selectedRunDetail.run.status === "pending_approval"
                          ? "#b45309"
                          : selectedRunDetail.run.status === "processing"
                          ? "#3730a3"
                          : "#475569",
                      fontWeight: 600,
                      textTransform: "capitalize",
                    }}
                  >
                    {selectedRunDetail.run.status.replace("_", " ")}
                  </span>
                </p>
              </div>
              <div className="flex align-center gap-2">
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => {
                    if (!selectedRunDetail) return;
                    const headers = ["Employee ID", "Employee Name", "CTC Snapshot", "Gross Salary", "Deductions", "Reimbursements", "Net Salary"];
                    const rows = selectedRunDetail.items.map((it) => {
                      const emp = employeeMap.get(it.employee_id);
                      const name = emp ? `${emp.first_name} ${emp.last_name || ""}`.trim() : it.employee_id;
                      return [
                        it.employee_id,
                        `"${name.replace(/"/g, '""')}"`,
                        it.ctc_snapshot,
                        it.gross_salary,
                        it.total_deductions,
                        it.reimbursement_amount,
                        it.net_salary,
                      ].join(",");
                    });
                    const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows].join("\n");
                    const encodedUri = encodeURI(csvContent);
                    const link = document.createElement("a");
                    link.setAttribute("href", encodedUri);
                    link.setAttribute(
                      "download",
                      `Reconciliation_Summary_${MONTH_NAMES[selectedRunDetail.run.month - 1]}_${selectedRunDetail.run.year}.csv`
                    );
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                  }}
                  title="Export reconciliation report for accounting"
                >
                  📥 Download Reconciliation (CSV)
                </button>
                {selectedRunDetail.run.status !== "approved" && (
                  <button
                    className="btn btn-success"
                    onClick={() => handleApproveRun(selectedRunDetail.run.id)}
                    disabled={approving}
                  >
                    {approving ? "Approving..." : "Approve Run & Release Payslips"}
                  </button>
                )}
                <button
                  type="button"
                  className="modal-close-btn"
                  onClick={() => setSelectedRunDetail(null)}
                  title="Close"
                >
                  ✕
                </button>
              </div>
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

      {/* Confirmation Dialog: Delete / Cancel Run */}
      <ConfirmDialog
        open={Boolean(runToDelete)}
        title={
          runToDelete?.status === "pending_approval"
            ? `Cancel ${MONTH_NAMES[(runToDelete?.month || 1) - 1]} ${runToDelete?.year} Payroll Run?`
            : "Cancel and Delete Draft Payroll Run?"
        }
        message={
          runToDelete
            ? runToDelete.status === "pending_approval"
              ? `This payroll run is currently pending approval. Cancelling it will discard the calculated payslips and allow HR to recalculate or re-run this cycle whenever ready.`
              : `Are you sure you want to cancel the ${MONTH_NAMES[runToDelete.month - 1]} ${runToDelete.year} draft run? All draft calculations and payslip previews for this period will be deleted.`
            : ""
        }
        confirmLabel={runToDelete?.status === "pending_approval" ? "Cancel Run" : "Delete Draft"}
        danger
        busy={deletingRun}
        onConfirm={handleDeleteRun}
        onCancel={() => setRunToDelete(null)}
      />
    </div>
  );
}

