import { useState, useEffect } from "react";
import { listMyPayslips, type PayrollItem } from "../api";
import { useToast } from "../../../app/toast-context";

export function MyPayslipPage() {
  const { notify } = useToast();
  const [payslips, setPayslips] = useState<PayrollItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPayslip, setSelectedPayslip] = useState<PayrollItem | null>(null);

  useEffect(() => {
    fetchPayslips();
  }, []);

  async function fetchPayslips() {
    setLoading(true);
    try {
      const data = await listMyPayslips();
      setPayslips(data);
      if (data.length > 0) {
        setSelectedPayslip(data[0]);
      }
    } catch {
      notify("Failed to load payslips", "error");
    } finally {
      setLoading(false);
    }
  }

  function handlePrint() {
    window.print();
  }

  return (
    <div className="container">
      <div className="page-header flex justify-between align-center">
        <div>
          <h1>My Payslips</h1>
          <p className="text-muted">View and download your monthly itemized payslip breakdowns</p>
        </div>
        {selectedPayslip && (
          <button className="btn btn-outline" onClick={handlePrint}>
            🖨️ Print / Download PDF
          </button>
        )}
      </div>

      {loading ? (
        <p className="mt-4">Loading payslips...</p>
      ) : payslips.length === 0 ? (
        <div className="card mt-4 p-8 text-center">
          <p className="text-muted">No approved payslips available yet.</p>
        </div>
      ) : (
        <div className="grid grid-3 gap-6 mt-4">
          {/* Left Column: Payslip History List */}
          <div className="card p-4">
            <h3 className="mb-3">Payslip History</h3>
            <div className="stack gap-2">
              {payslips.map((item) => (
                <button
                  key={item.id}
                  className={`p-3 rounded border text-left flex justify-between align-center ${
                    selectedPayslip?.id === item.id ? "bg-muted border-primary fw-bold" : ""
                  }`}
                  onClick={() => setSelectedPayslip(item)}
                >
                  <div>
                    <div>Payslip #{item.id.substring(0, 8)}</div>
                    <div className="text-xs text-muted">
                      Days: {item.present_days} present / {item.lop_days} LOP
                    </div>
                  </div>
                  <div className="text-success fw-bold">₹{Number(item.net_salary).toLocaleString()}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Right Column: Payslip Detail Breakdown */}
          {selectedPayslip && (
            <div className="card p-6 col-span-2 print-section stack gap-6">
              <div className="border-b pb-4 flex justify-between align-center">
                <div>
                  <h2 className="text-xl fw-bold">PAYSLIP</h2>
                  <p className="text-muted text-sm">Monthly Salary Statement</p>
                </div>
                <div className="text-right">
                  <div className="text-xs text-muted">Payslip ID</div>
                  <div className="font-mono text-sm">{selectedPayslip.id}</div>
                </div>
              </div>

              {/* Attendance & Summary Stats */}
              <div className="grid grid-4 gap-4 p-3 bg-muted rounded text-sm">
                <div>
                  <span className="text-muted block text-xs">Working Days</span>
                  <strong>{selectedPayslip.working_days}</strong>
                </div>
                <div>
                  <span className="text-muted block text-xs">Present Days</span>
                  <strong>{selectedPayslip.present_days}</strong>
                </div>
                <div>
                  <span className="text-muted block text-xs">LOP Days</span>
                  <strong>{selectedPayslip.lop_days}</strong>
                </div>
                <div>
                  <span className="text-muted block text-xs">Reimbursements</span>
                  <strong>₹{Number(selectedPayslip.reimbursement_amount).toLocaleString()}</strong>
                </div>
              </div>

              {/* Breakdown Tables: Earnings & Deductions */}
              <div className="grid grid-2 gap-6">
                {/* Earnings */}
                <div>
                  <h4 className="border-b pb-2 mb-2 text-success">Earnings</h4>
                  <table className="table text-sm">
                    <thead>
                      <tr>
                        <th>Component</th>
                        <th className="text-right">Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedPayslip.earnings_json.map((e, idx) => (
                        <tr key={idx}>
                          <td>{e.name}</td>
                          <td className="text-right font-mono">₹{Number(e.amount).toLocaleString()}</td>
                        </tr>
                      ))}
                      <tr className="fw-bold border-t">
                        <td>Total Gross Salary</td>
                        <td className="text-right font-mono">
                          ₹{Number(selectedPayslip.gross_salary).toLocaleString()}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                {/* Deductions */}
                <div>
                  <h4 className="border-b pb-2 mb-2 text-red">Deductions</h4>
                  <table className="table text-sm">
                    <thead>
                      <tr>
                        <th>Component</th>
                        <th className="text-right">Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedPayslip.deductions_json.map((d, idx) => (
                        <tr key={idx}>
                          <td>{d.name}</td>
                          <td className="text-right font-mono text-red">
                            -₹{Number(d.amount).toLocaleString()}
                          </td>
                        </tr>
                      ))}
                      <tr className="fw-bold border-t">
                        <td>Total Deductions</td>
                        <td className="text-right font-mono text-red">
                          -₹{Number(selectedPayslip.total_deductions).toLocaleString()}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Net Salary Banner */}
              <div className="p-4 bg-success-subtle border border-success rounded flex justify-between align-center">
                <div>
                  <div className="text-xs text-muted">NET SALARY PAYABLE</div>
                  <div className="text-2xl fw-bold text-success">
                    ₹{Number(selectedPayslip.net_salary).toLocaleString()}
                  </div>
                </div>
                <div className="text-xs text-muted text-right">
                  Formula: Gross (₹{Number(selectedPayslip.gross_salary).toLocaleString()}) - Deductions (₹
                  {Number(selectedPayslip.total_deductions).toLocaleString()}) + Reimbursements (₹
                  {Number(selectedPayslip.reimbursement_amount).toLocaleString()})
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
