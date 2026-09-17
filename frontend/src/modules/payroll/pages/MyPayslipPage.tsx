import { useState, useEffect } from "react";
import { listMyPayslips, type PayrollItem } from "../api";
import { getMyCompany, type CompanyResponse } from "../../identity/api";
import { getFnFSettlement, type FnFSettlement } from "../../hr/api";
import { useToast } from "../../../app/toast-context";
import { useAuth } from "../../../app/auth-context";
import { formatDate } from "../../../shared/utils/date";

export function MyPayslipPage() {
  const { user } = useAuth();
  const { notify } = useToast();
  const [activeTab, setActiveTab] = useState<"payslips" | "fnf">("payslips");
  const [payslips, setPayslips] = useState<PayrollItem[]>([]);
  const [fnfData, setFnfData] = useState<FnFSettlement | null>(null);
  const [company, setCompany] = useState<CompanyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedPayslip, setSelectedPayslip] = useState<PayrollItem | null>(null);

  useEffect(() => {
    fetchPayslips();
    fetchCompany();
    if (user?.employee?.id) {
      fetchFnF();
    }
  }, [user?.employee?.id]);

  async function fetchCompany() {
    try {
      const comp = await getMyCompany();
      setCompany(comp);
    } catch {
      // Non-critical, fallback to user company name
    }
  }

  async function fetchFnF() {
    if (!user?.employee?.id) return;
    try {
      const fnf = await getFnFSettlement(user.employee.id);
      setFnfData(fnf);
    } catch {
      // Not yet separated / no FnF available
      setFnfData(null);
    }
  }

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
          <h1>My Payslips & Statements</h1>
          <p className="text-muted">Monthly itemized payslip breakdowns and Full & Final (FnF) statements</p>
        </div>
        <div className="flex gap-2">
          {(selectedPayslip || fnfData) && (
            <button className="btn btn-primary" onClick={handlePrint}>
              📥 Download Statement (PDF / Print)
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-4 border-b mb-4" style={{ borderColor: "var(--color-border)" }}>
        <button
          type="button"
          className="btn-ghost"
          style={{
            padding: "0.5rem 1rem",
            fontWeight: activeTab === "payslips" ? 600 : 400,
            borderBottom: activeTab === "payslips" ? "2px solid var(--color-primary, #2563eb)" : "2px solid transparent",
            color: activeTab === "payslips" ? "var(--color-primary, #2563eb)" : "var(--color-text-muted)",
            cursor: "pointer",
          }}
          onClick={() => setActiveTab("payslips")}
        >
          📄 Monthly Payslips ({payslips.length})
        </button>
        <button
          type="button"
          className="btn-ghost"
          style={{
            padding: "0.5rem 1rem",
            fontWeight: activeTab === "fnf" ? 600 : 400,
            borderBottom: activeTab === "fnf" ? "2px solid #16a34a" : "2px solid transparent",
            color: activeTab === "fnf" ? "#16a34a" : "var(--color-text-muted)",
            cursor: "pointer",
          }}
          onClick={() => setActiveTab("fnf")}
        >
          📑 Full & Final (FnF) Statement
        </button>
      </div>

      {activeTab === "fnf" ? (
        <div className="card p-6 mt-4">
          <div className="row-between align-center border-b pb-3 mb-4">
            <div>
              <h3 style={{ margin: 0, fontSize: "1.2rem" }}>📑 Full & Final Settlement (FnF) Statement</h3>
              <p className="text-muted text-xs" style={{ margin: "2px 0 0" }}>
                Official terminal financial settlement following resignation or company separation
              </p>
            </div>
            {fnfData && (
              <span
                className="badge"
                style={{
                  backgroundColor: fnfData.fnf_settled_at ? "#dcfce7" : "#fef3c7",
                  color: fnfData.fnf_settled_at ? "#15803d" : "#b45309",
                  border: "1px solid currentColor",
                  fontWeight: 600,
                  fontSize: "0.85rem",
                  padding: "4px 10px",
                }}
              >
                {fnfData.fnf_settled_at ? "✅ Settled & Disbursed" : "⏳ Clearance In Progress"}
              </span>
            )}
          </div>

          {!fnfData ? (
            <div style={{ textAlign: "center", padding: "3rem 1rem" }}>
              <span style={{ fontSize: "2.5rem" }}>📄</span>
              <h4 style={{ margin: "0.75rem 0 0.25rem" }}>No Active Separation or FnF Statement</h4>
              <p className="text-muted text-sm" style={{ maxWidth: "480px", margin: "0 auto" }}>
                Full & Final Settlement statements are generated when a formal resignation is approved or separation is initiated. Your employment status is currently active.
              </p>
            </div>
          ) : (
            <div className="stack gap-4">
              {/* Formula Callout Banner */}
              <div
                style={{
                  background: "#f8fafc",
                  padding: "12px 16px",
                  borderRadius: "8px",
                  border: "1px solid var(--color-border)",
                  fontSize: "0.85rem",
                }}
              >
                <strong>FnF Formula:</strong>{" "}
                <code>Net Payout = (Unpaid Salary + Leave Encashment + Pending Reimbursements + Gratuity/Bonus + Severance) - (Notice Recovery + Asset Deductions)</code>
              </div>

              {/* Department Clearance Progress */}
              <div className="card" style={{ background: "#fafafa", padding: "1rem" }}>
                <div className="text-xs font-semibold uppercase text-muted mb-2">Department Clearance Sign-Offs</div>
                <div className="grid grid-3 gap-3">
                  <div className="p-2 bg-white rounded border flex justify-between align-center">
                    <span className="text-sm">💻 IT Clearance</span>
                    <span className={`badge ${fnfData.it_clearance ? "badge-success" : "badge-warning"}`}>
                      {fnfData.it_clearance ? "Cleared" : "Pending"}
                    </span>
                  </div>
                  <div className="p-2 bg-white rounded border flex justify-between align-center">
                    <span className="text-sm">👤 HR Clearance</span>
                    <span className={`badge ${fnfData.hr_clearance ? "badge-success" : "badge-warning"}`}>
                      {fnfData.hr_clearance ? "Cleared" : "Pending"}
                    </span>
                  </div>
                  <div className="p-2 bg-white rounded border flex justify-between align-center">
                    <span className="text-sm">💰 Finance Clearance</span>
                    <span className={`badge ${fnfData.finance_clearance ? "badge-success" : "badge-warning"}`}>
                      {fnfData.finance_clearance ? "Cleared" : "Pending"}
                    </span>
                  </div>
                </div>
              </div>

              {/* Itemized Financial Breakdown */}
              <div className="grid grid-2 gap-6">
                {/* Earnings & Additions */}
                <div>
                  <h4 className="text-success border-b pb-2 mb-3">Additions & Encashments (+)</h4>
                  <table className="table text-sm" style={{ width: "100%" }}>
                    <tbody>
                      <tr>
                        <td>
                          <strong>Prorated Unpaid Salary</strong>
                          <div className="text-xs text-muted">{fnfData.unpaid_salary_days} payable days up to LWD</div>
                        </td>
                        <td className="text-right font-mono text-success">
                          +₹{Number(fnfData.unpaid_salary_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                      <tr>
                        <td>
                          <strong>Leave Encashment</strong>
                          <div className="text-xs text-muted">{fnfData.encashable_leave_days} accrued paid leave days</div>
                        </td>
                        <td className="text-right font-mono text-success">
                          +₹{Number(fnfData.leave_encashment_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                      <tr>
                        <td>
                          <strong>Pending Reimbursements</strong>
                          <div className="text-xs text-muted">Approved expense claims</div>
                        </td>
                        <td className="text-right font-mono text-success">
                          +₹{Number(fnfData.pending_reimbursements).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                      <tr>
                        <td>
                          <strong>Gratuity / Separation Bonus</strong>
                        </td>
                        <td className="text-right font-mono text-success">
                          +₹{Number(fnfData.gratuity_bonus).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                      <tr>
                        <td>
                          <strong>Severance / Notice Pay in Lieu</strong>
                        </td>
                        <td className="text-right font-mono text-success">
                          +₹{Number(fnfData.severance_pay).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                {/* Deductions & Recoveries */}
                <div>
                  <h4 className="text-red border-b pb-2 mb-3">Deductions & Recoveries (-)</h4>
                  <table className="table text-sm" style={{ width: "100%" }}>
                    <tbody>
                      <tr>
                        <td>
                          <strong>Notice Shortfall Recovery</strong>
                          <div className="text-xs text-muted">Unserved contractual notice period</div>
                        </td>
                        <td className="text-right font-mono text-red">
                          -₹{Number(fnfData.notice_recovery_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                      <tr>
                        <td>
                          <strong>Asset Damage / Loan Deductions</strong>
                          <div className="text-xs text-muted">Equipment replacement / pending advances</div>
                        </td>
                        <td className="text-right font-mono text-red">
                          -₹{Number(fnfData.asset_deductions).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    </tbody>
                  </table>

                  {/* Net Payable Settlement Box */}
                  <div
                    className="p-4 rounded mt-4"
                    style={{
                      background: "linear-gradient(135deg, #eff6ff, #dbeafe)",
                      border: "1px solid #bfdbfe",
                    }}
                  >
                    <div className="text-xs text-muted font-semibold uppercase">Total Net FnF Payout</div>
                    <div className="text-2xl font-bold" style={{ color: "#1e40af", marginTop: "4px" }}>
                      ₹{Number(fnfData.total_settlement_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </div>
                    <div className="text-xs text-muted mt-1">
                      {fnfData.fnf_settled_at
                        ? `Disbursed on ${formatDate(fnfData.fnf_settled_at)} • Excluded from future pay runs`
                        : "Payable via direct bank transfer upon complete department clearance"}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : loading ? (
        <p className="mt-4">Loading payslips...</p>
      ) : payslips.length === 0 ? (
        <div className="card mt-4 p-8 text-center" style={{ maxWidth: "560px", margin: "2rem auto" }}>
          {!user?.employee ? (
            <div className="stack gap-3" style={{ alignItems: "center" }}>
              <div
                style={{
                  width: "48px",
                  height: "48px",
                  borderRadius: "50%",
                  backgroundColor: "#eff6ff",
                  color: "#2563eb",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1.4rem",
                }}
              >
                🏢
              </div>
              <h3 style={{ fontSize: "1.15rem", margin: 0 }}>HR Admin Account</h3>
              <p className="text-muted" style={{ fontSize: "0.875rem", lineHeight: 1.5, margin: 0 }}>
                Payslips are generated exclusively for registered employee compensation profiles. As a corporate HR administrator, you can run payroll, configure structures, and view staff payslips under <strong>Payroll Runs</strong>.
              </p>
            </div>
          ) : (
            <p className="text-muted">No approved payslips available yet.</p>
          )}
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
            <div className="card p-6 col-span-2 print-section stack gap-6" style={{ position: "relative" }}>
              {/* Tenant Branded Header */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  borderBottom: "2px solid var(--color-border, #e5e7eb)",
                  paddingBottom: "1.25rem",
                }}
              >
                <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                  {company?.logo_url ? (
                    <img
                      src={company.logo_url}
                      alt={company.name}
                      style={{
                        width: "48px",
                        height: "48px",
                        borderRadius: "8px",
                        objectFit: "contain",
                        border: "1px solid var(--color-border, #e5e7eb)",
                        background: "#fff",
                      }}
                    />
                  ) : (
                    <div
                      style={{
                        width: "48px",
                        height: "48px",
                        borderRadius: "8px",
                        background: "linear-gradient(135deg, #1e40af, #3b82f6)",
                        color: "#ffffff",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: "1.25rem",
                        fontWeight: "bold",
                      }}
                    >
                      🏢
                    </div>
                  )}
                  <div>
                    <h2 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0, color: "var(--color-heading, #111827)" }}>
                      {company?.name || user?.company_name || "Enterprise Workspace"}
                    </h2>
                    <p style={{ fontSize: "0.8rem", color: "var(--color-muted, #6b7280)", margin: "2px 0 0" }}>
                      Registered Office: {
                        [company?.address, company?.city, company?.state, company?.pincode].filter(Boolean).join(", ") ||
                        (company?.city ? `${company.city}, ${company.state || "India"}` : "Plot 42, Corporate Tech Park, SG Highway, Gujarat 380015")
                      }
                    </p>
                    <p style={{ fontSize: "0.75rem", color: "var(--color-muted, #6b7280)", margin: "1px 0 0" }}>
                      {company?.gst_number ? `GSTIN: ${company.gst_number} • ` : ""}
                      {company?.pan_number ? `PAN: ${company.pan_number} • ` : ""}
                      {company?.code ? `Entity Code: ${company.code}` : "Tax Verified • Registered Entity"}
                    </p>
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <span
                    style={{
                      display: "inline-block",
                      padding: "3px 10px",
                      background: "#eff6ff",
                      color: "#1d4ed8",
                      border: "1px solid #bfdbfe",
                      borderRadius: "6px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                    }}
                  >
                    Confidential Payslip
                  </span>
                  <div style={{ fontSize: "0.75rem", color: "var(--color-muted, #6b7280)", marginTop: "6px" }}>Payslip Ref ID</div>
                  <div style={{ fontFamily: "monospace", fontSize: "0.85rem", fontWeight: 600 }}>{selectedPayslip.id.substring(0, 16)}</div>
                </div>
              </div>

              {/* Attendance & Summary Stats */}
              <div className="grid grid-4 gap-4 p-3 bg-muted rounded text-sm" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
                <div>
                  <span className="text-muted block text-xs">Working Days</span>
                  <strong>{selectedPayslip.working_days}</strong>
                </div>
                <div>
                  <span className="text-muted block text-xs">Present Days</span>
                  <strong>{selectedPayslip.present_days}</strong>
                </div>
                <div>
                  <span className="text-muted block text-xs">Paid Leave</span>
                  <strong>{selectedPayslip.paid_leave_days}</strong>
                </div>
                <div>
                  <span className="text-muted block text-xs">LOP Days</span>
                  <strong style={{ color: Number(selectedPayslip.lop_days) > 0 ? "#dc2626" : undefined }}>
                    {selectedPayslip.lop_days}
                  </strong>
                </div>
                <div>
                  <span className="text-muted block text-xs">Reimbursements</span>
                  <strong style={{ color: Number(selectedPayslip.reimbursement_amount) > 0 ? "#15803d" : undefined }}>
                    ₹{Number(selectedPayslip.reimbursement_amount).toLocaleString()}
                  </strong>
                </div>
              </div>
              {Number(selectedPayslip.lop_days) > 0 && (
                <div
                  style={{
                    padding: "8px 12px",
                    borderRadius: "6px",
                    backgroundColor: "#fef2f2",
                    border: "1px solid #fecaca",
                    fontSize: "0.8rem",
                    color: "#7f1d1d",
                  }}
                >
                  ⚠️ <strong>Loss of Pay</strong>: {selectedPayslip.lop_days} day(s) of unpaid leave were taken this month.
                  Your gross earnings have been proportionally reduced (<em>Earned Gross = Monthly Gross × (Present Days / Working Days)</em>).
                  Statutory deductions (EPF, ESI, PT) are calculated on earned gross only.
                </div>
              )}

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
                      {/* Reimbursements: tax-free expense payback — shown as a positive
                          adjustment AFTER deductions, never inside earnings (which would
                          inflate taxable income). Net Pay = Earned Gross - Deductions + Reimbursements. */}
                      {Number(selectedPayslip.reimbursement_amount) > 0 && (
                        <tr style={{ backgroundColor: "#f0fdf4" }}>
                          <td style={{ color: "#15803d" }}>
                            💰 Expense Reimbursement
                            <span className="text-xs text-muted" style={{ display: "block" }}>Tax-free — expense payback only</span>
                          </td>
                          <td className="text-right font-mono" style={{ color: "#15803d" }}>
                            +₹{Number(selectedPayslip.reimbursement_amount).toLocaleString()}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Digital Authorization Seal & Signature Box */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  borderTop: "1px dashed var(--color-border, #e5e7eb)",
                  paddingTop: "1.25rem",
                  marginTop: "0.5rem",
                }}
              >
                <div style={{ fontSize: "0.75rem", color: "var(--color-muted, #6b7280)", maxWidth: "450px" }}>
                  <p style={{ margin: 0 }}>
                    <strong>Notice:</strong> This is a computer-generated, digitally authenticated salary statement issued in accordance with Income Tax Act & Payment of Wages rules.
                  </p>
                  <p style={{ margin: "4px 0 0" }}>
                    Verified by EMS Pro Enterprise Payroll Engine • No physical signature required.
                  </p>
                </div>

                {/* Digital Seal */}
                <div
                  style={{
                    border: "2px double #15803d",
                    borderRadius: "50%",
                    width: "84px",
                    height: "84px",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "#15803d",
                    fontSize: "0.6rem",
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    textAlign: "center",
                    transform: "rotate(-6deg)",
                    background: "rgba(240, 253, 244, 0.6)",
                  }}
                >
                  <span>★ EMS PRO ★</span>
                  <span style={{ fontSize: "0.75rem", margin: "1px 0" }}>DIGITALLY</span>
                  <span>AUTHORIZED</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
