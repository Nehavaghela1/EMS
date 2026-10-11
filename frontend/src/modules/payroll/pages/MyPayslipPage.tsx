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
  const [showDaysAuditModal, setShowDaysAuditModal] = useState(false);
  const [showFnfFormulaModal, setShowFnfFormulaModal] = useState(false);

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

  // Determine whether FnF applies to this employee:
  // In Zoho People & Payroll: FnF Statement is only relevant if employee is in exit/separation
  // or has a settlement record. For active employees without separation, only regular payslips show.
  const hasSeparationOrFnF = Boolean(
    fnfData &&
    (fnfData.fnf_settled_at ||
     (fnfData.resignation_status && fnfData.resignation_status !== "none") ||
     fnfData.is_active === false ||
     Number(fnfData.notice_recovery_amount || 0) > 0 ||
     Number(fnfData.severance_pay || 0) > 0)
  );

  return (
    <div className="container">
      <div className="page-header flex justify-between align-center page-header-responsive no-print">
        <div>
          <h1>My Payslips & Statements</h1>
          <p className="text-muted">
            {hasSeparationOrFnF
              ? "Monthly itemized payslip breakdowns and official exit settlement statements"
              : "Monthly itemized salary breakdown, attendance credits, and statutory deductions"}
          </p>
        </div>
        <div className="flex gap-2 no-print">
          {(selectedPayslip || (activeTab === "fnf" && fnfData)) && (
            <button className="btn btn-primary no-print" onClick={handlePrint}>
              📥 Download Statement (PDF / Print)
            </button>
          )}
        </div>
      </div>

      {/* Tabs - In Zoho People, FnF Statement only shows when an employee has an active separation/settlement */}
      <div className="flex gap-4 border-b mb-4 no-print" style={{ borderColor: "var(--color-border)" }}>
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

        {hasSeparationOrFnF ? (
          <button
            type="button"
            className="btn-ghost"
            style={{
              padding: "0.5rem 1rem",
              fontWeight: activeTab === "fnf" ? 600 : 400,
              borderBottom: activeTab === "fnf" ? "2px solid #16a34a" : "2px solid transparent",
              color: activeTab === "fnf" ? "#16a34a" : "var(--color-text-muted)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
            onClick={() => setActiveTab("fnf")}
          >
            <span>📑 Full & Final (FnF) Statement</span>
            <span
              style={{
                fontSize: "0.7rem",
                padding: "2px 6px",
                borderRadius: "4px",
                backgroundColor: fnfData?.fnf_settled_at ? "#dcfce7" : "#fef3c7",
                color: fnfData?.fnf_settled_at ? "#15803d" : "#b45309",
                fontWeight: 600,
              }}
            >
              {fnfData?.fnf_settled_at ? "Settled" : "Exit In-Progress"}
            </span>
          </button>
        ) : null}
      </div>

      {activeTab === "fnf" ? (
        <div
          id="print-section"
          data-print-content="true"
          className="card p-6 mt-4 print-section fnf-statement-card"
        >
          <div className="row-between align-center border-b pb-3 mb-4">
            <div>
              <h3 style={{ margin: 0, fontSize: "1.2rem" }}>📑 Full & Final Settlement (FnF) Statement</h3>
              <p className="text-muted text-xs" style={{ margin: "2px 0 0" }}>
                Official terminal financial settlement following resignation or company separation
              </p>
            </div>
            {fnfData && (() => {
              const isFullyCleared = Boolean(fnfData.it_clearance && fnfData.hr_clearance && fnfData.finance_clearance);
              const isSettled = Boolean(fnfData.fnf_settled_at);
              const label = isSettled
                ? "✅ Settled & Disbursed"
                : isFullyCleared
                ? "✓ Clearance Completed"
                : "⏳ Clearance In Progress";
              const bgColor = isSettled || isFullyCleared ? "#dcfce7" : "#fef3c7";
              const color = isSettled || isFullyCleared ? "#15803d" : "#b45309";
              return (
                <span
                  className="badge"
                  style={{
                    backgroundColor: bgColor,
                    color: color,
                    border: "1px solid currentColor",
                    fontWeight: 600,
                    fontSize: "0.85rem",
                    padding: "4px 10px",
                  }}
                >
                  {label}
                </span>
              );
            })()}
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
              {/* Formula Callout Banner with Interactive Breakdown Modal Button */}
              <div
                style={{
                  background: "#f8fafc",
                  padding: "12px 16px",
                  borderRadius: "8px",
                  border: "1px solid var(--color-border)",
                  fontSize: "0.85rem",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "8px",
                }}
              >
                <div>
                  <strong>FnF Formula:</strong>{" "}
                  <code>Net = (Unpaid Salary + Leave Encashment + Reimbursements + Gratuity + Severance) - (Notice Shortfall + Asset Deductions)</code>
                </div>
                <button
                  type="button"
                  className="btn-ghost text-xs"
                  style={{
                    color: "var(--color-primary, #2563eb)",
                    fontWeight: 600,
                    cursor: "pointer",
                    padding: "4px 8px",
                  }}
                  onClick={() => setShowFnfFormulaModal(true)}
                >
                  🔍 View Detailed Calculation Math
                </button>
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
                  {(() => {
                    const netAmount = Number(fnfData.total_settlement_amount || 0);
                    const isPositive = netAmount >= 0;
                    return (
                      <div
                        className="p-4 rounded mt-4"
                        style={{
                          background: isPositive
                            ? "linear-gradient(135deg, #eff6ff, #dbeafe)"
                            : "linear-gradient(135deg, #fef2f2, #fee2e2)",
                          border: `1px solid ${isPositive ? "#bfdbfe" : "#fecaca"}`,
                        }}
                      >
                        <div className="text-xs font-semibold uppercase" style={{ color: isPositive ? "#64748b" : "#991b1b" }}>
                          {isPositive ? "Total Net FnF Payout (Payable to Employee)" : "Total Net Recovery (Payable by Employee to Company)"}
                        </div>
                        <div
                          className="text-2xl font-bold"
                          style={{ color: isPositive ? "#1e40af" : "#dc2626", marginTop: "4px" }}
                        >
                          {isPositive
                            ? `₹${netAmount.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`
                            : `-₹${Math.abs(netAmount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                        </div>
                        <div className="text-xs text-muted mt-1">
                          {fnfData.fnf_settled_at
                            ? `Settled on ${formatDate(fnfData.fnf_settled_at)} • Excluded from future pay runs`
                            : isPositive
                            ? "Payable via direct bank transfer upon complete department clearance"
                            : "Pending collection via invoice/demand note before issuing relieving letter."}
                        </div>
                      </div>
                    );
                  })()}
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
                className="payslip-detail-header"
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

              {/* Employee Information & Net Pay Hero Banner (Zoho People Standard) */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: "1rem",
                  padding: "1rem",
                  borderRadius: "8px",
                  backgroundColor: "#f8fafc",
                  border: "1px solid #e2e8f0",
                }}
              >
                <div>
                  <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                    Employee Name
                  </div>
                  <div style={{ fontSize: "1rem", fontWeight: 700, color: "#0f172a", marginTop: "2px" }}>
                    {user?.employee ? `${user.employee.first_name} ${user.employee.last_name || ""}`.trim() : user?.email}
                  </div>
                  {user?.employee?.employee_code && (
                    <div style={{ fontSize: "0.75rem", color: "#64748b", fontFamily: "monospace", marginTop: "2px" }}>
                      Emp ID: {user.employee.employee_code}
                    </div>
                  )}
                </div>

                <div>
                  <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                    Department & Role
                  </div>
                  <div style={{ fontSize: "0.95rem", fontWeight: 600, color: "#334155", marginTop: "2px" }}>
                    {user?.employee?.department_id ? "Staff Member" : "Engineering / Operations"}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "2px" }}>
                    Pay Period: {new Date().toLocaleDateString("en-US", { month: "long", year: "numeric" })}
                  </div>
                </div>

                <div
                  style={{
                    backgroundColor: "#ecfdf5",
                    border: "1px solid #a7f3d0",
                    borderRadius: "8px",
                    padding: "0.75rem 1rem",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "center",
                  }}
                >
                  <div style={{ fontSize: "0.72rem", fontWeight: 700, color: "#065f46", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Net Take-Home Pay
                  </div>
                  <div style={{ fontSize: "1.45rem", fontWeight: 800, color: "#047857", marginTop: "2px" }}>
                    ₹{Number(selectedPayslip.net_salary).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                  </div>
                </div>
              </div>

              {/* Attendance & Summary Stats with Calculation Breakdown Trigger */}
              <div>
                <div className="flex justify-between align-center mb-2">
                  <span className="text-xs font-semibold uppercase text-muted">Attendance & Pay Days Summary</span>
                  <button
                    type="button"
                    className="btn-ghost text-xs"
                    style={{
                      color: "var(--color-primary, #2563eb)",
                      padding: "2px 8px",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "4px",
                    }}
                    onClick={() => setShowDaysAuditModal(true)}
                  >
                    <span>ℹ️ How payable days & salary are calculated</span>
                  </button>
                </div>

                <div className="grid grid-4 gap-4 p-3 bg-muted rounded text-sm payslip-summary-grid" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
                  <div>
                    <span className="text-muted block text-xs">Calendar Working Days</span>
                    <strong>{selectedPayslip.working_days}</strong>
                  </div>
                  <div>
                    <span className="text-muted block text-xs">Prorated Present Days</span>
                    <strong className="text-success">{selectedPayslip.present_days}</strong>
                  </div>
                  <div>
                    <span className="text-muted block text-xs">Paid Leaves</span>
                    <strong>{selectedPayslip.paid_leave_days}</strong>
                  </div>
                  <div>
                    <span className="text-muted block text-xs">Unpaid (LOP) Days</span>
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
              </div>

              {Number(selectedPayslip.lop_days) > 0 ? (
                <div
                  style={{
                    padding: "10px 14px",
                    borderRadius: "6px",
                    backgroundColor: "#fef2f2",
                    border: "1px solid #fecaca",
                    fontSize: "0.825rem",
                    color: "#7f1d1d",
                  }}
                >
                  <div style={{ fontWeight: 600, marginBottom: "2px" }}>
                    ⚠️ Loss of Pay (LOP): {selectedPayslip.lop_days} Day(s) Deducted
                  </div>
                  <div>
                    Your monthly fixed earnings were prorated: <code>Earned Gross = (Monthly Fixed Gross ÷ {selectedPayslip.working_days}) × {selectedPayslip.present_days}</code>.
                    No statutory deductions (PF/ESI) were charged on unearned LOP days.
                  </div>
                </div>
              ) : (
                <div
                  style={{
                    padding: "8px 12px",
                    borderRadius: "6px",
                    backgroundColor: "#f0fdf4",
                    border: "1px solid #bbf7d0",
                    fontSize: "0.8rem",
                    color: "#166534",
                  }}
                >
                  ✓ <strong>Full Pay Period Credited:</strong> All {selectedPayslip.present_days} working days were served with 0 LOP deductions.
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

      {/* Modal 1: Attendance & Pay Days Audit Calculation Modal */}
      {showDaysAuditModal && selectedPayslip && (
        <div className="modal-backdrop no-print" onClick={() => setShowDaysAuditModal(false)}>
          <div
            className="card p-6"
            style={{ maxWidth: "560px", width: "90%", margin: "auto", position: "relative" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between align-center border-b pb-3 mb-4">
              <h3 style={{ margin: 0, fontSize: "1.15rem" }}>ℹ️ Attendance & Pay Days Calculation Audit</h3>
              <button
                type="button"
                className="btn-ghost"
                style={{ fontSize: "1.2rem", cursor: "pointer", border: "none", background: "none" }}
                onClick={() => setShowDaysAuditModal(false)}
              >
                ✕
              </button>
            </div>

            <div className="stack gap-3 text-sm">
              <p className="text-muted" style={{ margin: 0 }}>
                Here is the verified audit trail explaining how your payable days and monthly earnings were calculated for this pay cycle:
              </p>

              <div className="p-3 bg-muted rounded border stack gap-2">
                <div className="flex justify-between">
                  <span>1. Total Calendar Working Days in Month:</span>
                  <strong>{selectedPayslip.working_days} days</strong>
                </div>
                <div className="flex justify-between">
                  <span>2. Actual Days Present & Punched:</span>
                  <strong className="text-success">{selectedPayslip.present_days} days</strong>
                </div>
                <div className="flex justify-between">
                  <span>3. Approved Paid Leaves (Sick / Casual / Annual):</span>
                  <strong>{selectedPayslip.paid_leave_days} days</strong>
                </div>
                <div className="flex justify-between border-t pt-2" style={{ color: Number(selectedPayslip.lop_days) > 0 ? "#dc2626" : undefined }}>
                  <span>4. Unapproved / Loss of Pay (LOP) Days:</span>
                  <strong>{selectedPayslip.lop_days} days</strong>
                </div>
              </div>

              <div
                style={{
                  background: "#eff6ff",
                  padding: "12px",
                  borderRadius: "6px",
                  border: "1px solid #bfdbfe",
                  fontSize: "0.85rem",
                }}
              >
                <div style={{ fontWeight: 600, color: "#1e40af", marginBottom: "4px" }}>
                  📐 Zoho Standard Salary Proration Formula:
                </div>
                <code>Earned Gross = Monthly Fixed CTC × (Present Days ÷ Calendar Working Days)</code>
                <div style={{ marginTop: "6px", color: "#334155", fontSize: "0.8rem" }}>
                  {Number(selectedPayslip.lop_days) > 0
                    ? `Because you had ${selectedPayslip.lop_days} day(s) of Loss of Pay, your gross salary was proportionally computed for ${selectedPayslip.present_days} days.`
                    : `No Loss of Pay (LOP) was recorded. You received 100% of your fixed gross CTC.`}
                </div>
              </div>

              <div className="flex justify-end mt-2">
                <button type="button" className="btn btn-secondary" onClick={() => setShowDaysAuditModal(false)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal 2: FnF Calculation Formula & Mathematics Audit Modal */}
      {showFnfFormulaModal && fnfData && (
        <div className="modal-backdrop no-print" onClick={() => setShowFnfFormulaModal(false)}>
          <div
            className="card p-6"
            style={{ maxWidth: "620px", width: "92%", margin: "auto", position: "relative" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between align-center border-b pb-3 mb-4">
              <div>
                <h3 style={{ margin: 0, fontSize: "1.15rem" }}>📑 FnF Settlement Breakdown Audit</h3>
                <p className="text-muted text-xs" style={{ margin: "2px 0 0" }}>
                  Legal & financial calculation basis according to employment contract and statutory norms
                </p>
              </div>
              <button
                type="button"
                className="btn-ghost"
                style={{ fontSize: "1.2rem", cursor: "pointer", border: "none", background: "none" }}
                onClick={() => setShowFnfFormulaModal(false)}
              >
                ✕
              </button>
            </div>

            <div className="stack gap-3 text-sm">
              <div className="stack gap-2 border p-3 rounded bg-muted">
                <div className="font-semibold text-xs text-muted uppercase">Base Compensation Figures</div>
                <div className="flex justify-between">
                  <span>Monthly Gross Salary:</span>
                  <strong className="font-mono">₹{Number(fnfData.monthly_gross_salary || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
                </div>
                <div className="flex justify-between">
                  <span>Per-Day Salary Rate (Monthly Gross ÷ 30):</span>
                  <strong className="font-mono text-primary">₹{Number(fnfData.per_day_salary || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })} / day</strong>
                </div>
              </div>

              <div className="stack gap-2 border p-3 rounded">
                <div className="font-semibold text-xs text-success uppercase">1. Additions & Credits Breakdown</div>
                <div className="flex justify-between">
                  <span>• Prorated Unpaid Salary ({fnfData.unpaid_salary_days} days × ₹{Number(fnfData.per_day_salary || 0).toFixed(2)}):</span>
                  <span className="font-mono text-success">+₹{Number(fnfData.unpaid_salary_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
                <div className="flex justify-between">
                  <span>• Leave Encashment ({fnfData.encashable_leave_days} balance leaves × Basic Daily Rate):</span>
                  <span className="font-mono text-success">+₹{Number(fnfData.leave_encashment_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
                <div className="flex justify-between">
                  <span>• Approved Expense Reimbursements:</span>
                  <span className="font-mono text-success">+₹{Number(fnfData.pending_reimbursements).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
                {Number(fnfData.severance_pay || 0) > 0 && (
                  <div className="flex justify-between">
                    <span>• Severance / Notice Pay in Lieu:</span>
                    <span className="font-mono text-success">+₹{Number(fnfData.severance_pay).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                  </div>
                )}
              </div>

              <div className="stack gap-2 border p-3 rounded">
                <div className="font-semibold text-xs text-red uppercase">2. Deductions & Recoveries Breakdown</div>
                <div className="flex justify-between">
                  <div>
                    <div>• Notice Shortfall Recovery:</div>
                    <div className="text-xs text-muted">
                      Required: {fnfData.notice_days_required}d | Served: {fnfData.notice_days_served}d | Shortfall: {fnfData.notice_recovery_days} days
                      {fnfData.notice_waived ? " (Waived by Management)" : ` (${fnfData.notice_recovery_days}d × ₹${Number(fnfData.per_day_salary || 0).toFixed(2)})`}
                    </div>
                  </div>
                  <span className="font-mono text-red">-₹{Number(fnfData.notice_recovery_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
                <div className="flex justify-between">
                  <span>• Asset Damage / Unreturned Assets / Advance Loans:</span>
                  <span className="font-mono text-red">-₹{Number(fnfData.asset_deductions).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
              </div>

              <div
                className="p-3 rounded flex justify-between align-center"
                style={{
                  background: Number(fnfData.total_settlement_amount || 0) >= 0 ? "#eff6ff" : "#fef2f2",
                  border: `1px solid ${Number(fnfData.total_settlement_amount || 0) >= 0 ? "#bfdbfe" : "#fecaca"}`,
                }}
              >
                <div>
                  <div style={{ fontWeight: 700, fontSize: "0.9rem" }}>
                    Net FnF Balance = Total Additions - Total Deductions
                  </div>
                  <div className="text-xs text-muted">
                    {Number(fnfData.total_settlement_amount || 0) >= 0
                      ? "Payable to employee upon complete department clearance sign-off"
                      : "Payable by employee to company prior to issuance of Relieving Letter"}
                  </div>
                </div>
                <div
                  className="font-mono font-bold"
                  style={{
                    fontSize: "1.15rem",
                    color: Number(fnfData.total_settlement_amount || 0) >= 0 ? "#1e40af" : "#dc2626",
                  }}
                >
                  {Number(fnfData.total_settlement_amount || 0) >= 0
                    ? `+₹${Number(fnfData.total_settlement_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`
                    : `-₹${Math.abs(Number(fnfData.total_settlement_amount)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                </div>
              </div>

              <div className="flex justify-end mt-2">
                <button type="button" className="btn btn-secondary" onClick={() => setShowFnfFormulaModal(false)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
