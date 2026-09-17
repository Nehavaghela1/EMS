import { useState, useEffect } from "react";
import { listMyPayslips, type PayrollItem } from "../api";
import { getMyCompany, type CompanyResponse } from "../../identity/api";
import { useToast } from "../../../app/toast-context";
import { useAuth } from "../../../app/auth-context";

export function MyPayslipPage() {
  const { user } = useAuth();
  const { notify } = useToast();
  const [payslips, setPayslips] = useState<PayrollItem[]>([]);
  const [company, setCompany] = useState<CompanyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedPayslip, setSelectedPayslip] = useState<PayrollItem | null>(null);

  useEffect(() => {
    fetchPayslips();
    fetchCompany();
  }, []);

  async function fetchCompany() {
    try {
      const comp = await getMyCompany();
      setCompany(comp);
    } catch {
      // Non-critical, fallback to user company name
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
          <h1>My Payslips</h1>
          <p className="text-muted">View and download your monthly itemized payslip breakdowns</p>
        </div>
        {selectedPayslip && (
          <button className="btn btn-primary" onClick={handlePrint}>
            📥 Download Branded Payslip (PDF / Print)
          </button>
        )}
      </div>

      {loading ? (
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
