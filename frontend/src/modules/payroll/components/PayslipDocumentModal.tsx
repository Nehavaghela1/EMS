import React from "react";
import { type PayrollItem } from "../api";
import { type Employee } from "../../hr/api";
import { type CompanyResponse } from "../../identity/api";

interface PayslipDocumentModalProps {
  isOpen: boolean;
  onClose: () => void;
  item: PayrollItem;
  employee?: Employee;
  company?: CompanyResponse | null;
  monthName: string;
  year: number;
}

// Helper to convert number to Indian words
function numberToWords(num: number): string {
  if (isNaN(num) || num <= 0) return "Zero Only";
  const a = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen"
  ];
  const b = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];

  function inWords(n: number): string {
    if (n < 20) return a[n];
    if (n < 100) return b[Math.floor(n / 10)] + (n % 10 !== 0 ? " " + a[n % 10] : "");
    if (n < 1000) return a[Math.floor(n / 100)] + " Hundred" + (n % 100 !== 0 ? " " + inWords(n % 100) : "");
    if (n < 100000) return inWords(Math.floor(n / 1000)) + " Thousand" + (n % 1000 !== 0 ? " " + inWords(n % 1000) : "");
    if (n < 10000000) return inWords(Math.floor(n / 100000)) + " Lakh" + (n % 100000 !== 0 ? " " + inWords(n % 100000) : "");
    return inWords(Math.floor(n / 10000000)) + " Crore" + (n % 10000000 !== 0 ? " " + inWords(n % 10000000) : "");
  }

  const intPart = Math.floor(num);
  return `Indian Rupee ${inWords(intPart)} Only`;
}

export const PayslipDocumentModal: React.FC<PayslipDocumentModalProps> = ({
  isOpen,
  onClose,
  item,
  employee,
  company,
  monthName,
  year,
}) => {
  if (!isOpen) return null;

  const empName = employee ? `${employee.first_name} ${employee.last_name || ""}`.trim() : "Employee";
  const empCode = employee?.employee_code || "INF" + item.employee_id.substring(0, 4).toUpperCase();
  const designation = (employee as any)?.job_title || (employee as any)?.designation || "Software Engineer";
  const department = employee?.department_name || "Engineering";
  const dateOfJoining = employee?.hire_date ? new Date(employee.hire_date).toLocaleDateString("en-GB") : "01/08/2026";
  const bankAccount = (employee as any)?.bank_account_number || "33138340254";
  const workLocation = (employee as any)?.work_location || company?.city || "Corporate HQ";

  const netPayNum = Number(item.net_salary) || 0;
  const grossPayNum = Number(item.gross_salary) || 0;
  const totalDeductionsNum = Number(item.total_deductions) || 0;
  const reimbursementNum = Number(item.reimbursement_amount) || 0;

  // Custom logo width from company preferences
  const savedWidth = localStorage.getItem("ems_brand_logo_width") || "140";
  const logoWidthPx = Number(savedWidth) || 140;

  const handlePrint = () => {
    window.print();
  };

  return (
    <div
      className="modal-backdrop"
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(15, 23, 42, 0.7)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 99999,
        padding: "1rem",
        overflowY: "auto",
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{
          width: "100%",
          maxWidth: "840px",
          backgroundColor: "#ffffff",
          borderRadius: "12px",
          boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
          overflow: "hidden",
          maxHeight: "92vh",
          display: "flex",
          flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Control Bar (Hidden on print) */}
        <div
          className="no-print"
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "12px 24px",
            borderBottom: "1px solid #e2e8f0",
            backgroundColor: "#f8fafc",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "1.1rem" }}>📄</span>
            <span style={{ fontWeight: 700, color: "#0f172a", fontSize: "0.95rem" }}>
              Payslip for {monthName} {year} — {empName}
            </span>
          </div>

          <div style={{ display: "flex", gap: "8px" }}>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handlePrint}
              style={{
                background: "#2563eb",
                borderColor: "#2563eb",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                fontWeight: 600,
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="6 9 6 2 18 2 18 9" />
                <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
                <rect x="6" y="14" width="12" height="8" />
              </svg>
              <span>Print / Download PDF</span>
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onClose}
              style={{ border: "1px solid #cbd5e1" }}
            >
              Close
            </button>
          </div>
        </div>

        {/* Payslip Document Body (Matches Zoho / Reference Image) */}
        <div
          className="print-section"
          style={{
            padding: "2.5rem 3rem",
            backgroundColor: "#ffffff",
            overflowY: "auto",
            color: "#1e293b",
            fontFamily: "system-ui, -apple-system, sans-serif",
            fontSize: "0.85rem",
            lineHeight: 1.5,
          }}
        >
          {/* Header Row: Company Logo & Details (Left) + Payslip For (Right) */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              borderBottom: "1px solid #e2e8f0",
              paddingBottom: "1.5rem",
              marginBottom: "1.5rem",
            }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", gap: "16px" }}>
              {company?.logo_url ? (
                <img
                  src={company.logo_url}
                  alt={company.name}
                  style={{
                    width: `${logoWidthPx}px`,
                    maxHeight: "75px",
                    objectFit: "contain",
                    display: "block",
                  }}
                />
              ) : null}
              <div>
                <h1 style={{ margin: "0 0 4px", fontSize: "1.25rem", fontWeight: 800, color: "#0f172a" }}>
                  {company?.name || "Infiria AI Private Limited"}
                </h1>
                <div style={{ fontSize: "0.78rem", color: "#64748b", maxWidth: "420px" }}>
                  {company?.address ? `${company.address}, ` : "B704 Shapath Hexa, Opp. Gujarat Highcourt, SG Highway "}
                  {company?.city ? `${company.city} ` : "Ahmedabad "}
                  {company?.pincode ? `${company.pincode} ` : "380060 "}
                  {company?.country ? `${company.country}` : "India"}
                </div>
              </div>
            </div>

            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 600 }}>
                Payslip For the Month
              </div>
              <div style={{ fontSize: "1.1rem", fontWeight: 800, color: "#0f172a", marginTop: "2px" }}>
                {monthName} {year}
              </div>
            </div>
          </div>

          {/* Employee Summary & Net Pay Highlight Box */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1.4fr 1fr",
              gap: "2rem",
              marginBottom: "1.75rem",
            }}
          >
            {/* Left Column: Metadata list */}
            <div>
              <div
                style={{
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  color: "#64748b",
                  letterSpacing: "0.05em",
                  marginBottom: "0.75rem",
                }}
              >
                Employee Summary
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "130px 1fr", rowGap: "6px", fontSize: "0.82rem" }}>
                <span style={{ color: "#64748b" }}>Employee Name</span>
                <span style={{ fontWeight: 600, color: "#0f172a" }}>: {empName}</span>

                <span style={{ color: "#64748b" }}>Designation</span>
                <span style={{ color: "#334155" }}>: {designation}</span>

                <span style={{ color: "#64748b" }}>Employee ID</span>
                <span style={{ color: "#334155" }}>: {empCode}</span>

                <span style={{ color: "#64748b" }}>Department</span>
                <span style={{ color: "#334155" }}>: {department}</span>

                <span style={{ color: "#64748b" }}>Date of Joining</span>
                <span style={{ color: "#334155" }}>: {dateOfJoining}</span>

                <span style={{ color: "#64748b" }}>Pay Period</span>
                <span style={{ color: "#334155" }}>: {monthName} {year}</span>

                <span style={{ color: "#64748b" }}>Pay Date</span>
                <span style={{ color: "#334155" }}>: 05/{String(new Date().getMonth() + 1).padStart(2, "0")}/{year}</span>

                <span style={{ color: "#64748b" }}>Bank Account No</span>
                <span style={{ color: "#334155" }}>: {bankAccount}</span>

                <span style={{ color: "#64748b" }}>Work Location</span>
                <span style={{ color: "#334155" }}>: {workLocation}</span>
              </div>
            </div>

            {/* Right Column: Net Pay Highlight Card */}
            <div>
              <div
                style={{
                  background: "#f0fdf4",
                  border: "1px solid #bbf7d0",
                  borderRadius: "10px",
                  padding: "1.25rem 1.5rem",
                  marginBottom: "1rem",
                }}
              >
                <div style={{ fontSize: "1.75rem", fontWeight: 800, color: "#15803d" }}>
                  ₹{netPayNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
                <div style={{ fontSize: "0.75rem", color: "#166534", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", marginTop: "2px" }}>
                  Total Net Pay
                </div>
              </div>

              {/* Attendance metrics */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", fontSize: "0.82rem", background: "#f8fafc", padding: "10px 14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div>
                  <span style={{ color: "#64748b" }}>Paid Days : </span>
                  <span style={{ fontWeight: 700, color: "#0f172a" }}>{Number(item.working_days || 31) - Number(item.lop_days || 0)}</span>
                </div>
                <div>
                  <span style={{ color: "#64748b" }}>LOP Days : </span>
                  <span style={{ fontWeight: 700, color: "#dc2626" }}>{item.lop_days || 0}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Earnings & Deductions Tables */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "2rem",
              borderTop: "1px solid #e2e8f0",
              paddingTop: "1.25rem",
              marginBottom: "1.25rem",
            }}
          >
            {/* Earnings */}
            <div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
                <thead>
                  <tr style={{ borderBottom: "1.5px solid #cbd5e1" }}>
                    <th style={{ textAlign: "left", padding: "6px 0", color: "#475569", textTransform: "uppercase", fontSize: "0.72rem" }}>EARNINGS</th>
                    <th style={{ textAlign: "right", padding: "6px 0", color: "#475569", textTransform: "uppercase", fontSize: "0.72rem" }}>AMOUNT</th>
                    <th style={{ textAlign: "right", padding: "6px 0", color: "#475569", textTransform: "uppercase", fontSize: "0.72rem" }}>YTD</th>
                  </tr>
                </thead>
                <tbody>
                  {item.earnings_json && item.earnings_json.length > 0 ? (
                    item.earnings_json.map((e, idx) => (
                      <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "8px 0", color: "#334155" }}>{e.name}</td>
                        <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 600, color: "#0f172a" }}>
                          ₹{Number(e.amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                        <td style={{ padding: "8px 0", textAlign: "right", color: "#64748b" }}>
                          ₹{(Number(e.amount) * (new Date().getMonth() + 1)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td style={{ padding: "8px 0", color: "#334155" }}>Basic Pay</td>
                      <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 600, color: "#0f172a" }}>
                        ₹{grossPayNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                      <td style={{ padding: "8px 0", textAlign: "right", color: "#64748b" }}>
                        ₹{(grossPayNum * 3).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                    </tr>
                  )}
                  <tr style={{ borderTop: "1.5px solid #cbd5e1", fontWeight: 700 }}>
                    <td style={{ padding: "10px 0", color: "#0f172a" }}>Gross Earnings</td>
                    <td style={{ padding: "10px 0", textAlign: "right", color: "#16a34a" }}>
                      ₹{grossPayNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </td>
                    <td style={{ padding: "10px 0", textAlign: "right", color: "#64748b" }}>
                      —
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Deductions */}
            <div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
                <thead>
                  <tr style={{ borderBottom: "1.5px solid #cbd5e1" }}>
                    <th style={{ textAlign: "left", padding: "6px 0", color: "#475569", textTransform: "uppercase", fontSize: "0.72rem" }}>DEDUCTIONS</th>
                    <th style={{ textAlign: "right", padding: "6px 0", color: "#475569", textTransform: "uppercase", fontSize: "0.72rem" }}>AMOUNT</th>
                    <th style={{ textAlign: "right", padding: "6px 0", color: "#475569", textTransform: "uppercase", fontSize: "0.72rem" }}>YTD</th>
                  </tr>
                </thead>
                <tbody>
                  {item.deductions_json && item.deductions_json.length > 0 ? (
                    item.deductions_json.map((d, idx) => (
                      <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "8px 0", color: "#334155" }}>{d.name}</td>
                        <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 600, color: "#dc2626" }}>
                          ₹{Number(d.amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                        <td style={{ padding: "8px 0", textAlign: "right", color: "#64748b" }}>
                          ₹{(Number(d.amount) * (new Date().getMonth() + 1)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td style={{ padding: "8px 0", color: "#334155" }}>Professional Tax</td>
                      <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 600, color: "#dc2626" }}>
                        ₹{totalDeductionsNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                      <td style={{ padding: "8px 0", textAlign: "right", color: "#64748b" }}>
                        ₹{(totalDeductionsNum * 3).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                    </tr>
                  )}
                  <tr style={{ borderTop: "1.5px solid #cbd5e1", fontWeight: 700 }}>
                    <td style={{ padding: "10px 0", color: "#0f172a" }}>Total Deductions</td>
                    <td style={{ padding: "10px 0", textAlign: "right", color: "#dc2626" }}>
                      ₹{totalDeductionsNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </td>
                    <td style={{ padding: "10px 0", textAlign: "right", color: "#64748b" }}>
                      —
                    </td>
                  </tr>
                </tbody>
              </table>

              {reimbursementNum > 0 && (
                <div style={{ marginTop: "10px", padding: "6px 10px", background: "#f0fdf4", borderRadius: "6px", display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: "#166534" }}>
                  <span>+ Reimbursed Expenses (Tax-exempt)</span>
                  <span style={{ fontWeight: 700 }}>₹{reimbursementNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
              )}
            </div>
          </div>

          {/* Total Net Payable Bar */}
          <div
            style={{
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              borderRadius: "8px",
              padding: "1rem 1.5rem",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "1rem",
            }}
          >
            <div>
              <div style={{ fontWeight: 800, color: "#0f172a", fontSize: "0.95rem" }}>
                TOTAL NET PAYABLE
              </div>
              <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
                Gross Earnings - Total Deductions {reimbursementNum > 0 ? "+ Approved Reimbursements" : ""}
              </div>
            </div>

            <div style={{ fontSize: "1.4rem", fontWeight: 800, color: "#0f172a" }}>
              ₹{netPayNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
            </div>
          </div>

          {/* Amount in words */}
          <div style={{ textAlign: "right", fontSize: "0.8rem", color: "#475569", marginBottom: "2rem" }}>
            <strong>Amount In Words : </strong> {numberToWords(netPayNum)}
          </div>

          {/* Footer note */}
          <div
            style={{
              borderTop: "1px solid #f1f5f9",
              paddingTop: "1.5rem",
              textAlign: "center",
              fontSize: "0.75rem",
              color: "#94a3b8",
            }}
          >
            — This is a computer-generated payroll document and requires no signature. —
          </div>
        </div>
      </div>
    </div>
  );
};
