import React, { useRef } from "react";
import { type PayrollItem } from "../api";
import { type Employee } from "../../hr/api";
import { type CompanyResponse } from "../../identity/api";
import { DocumentShell } from "./DocumentShell";
import { DocumentActions } from "./DocumentActions";
import { downloadDocumentAsHtml } from "../utils";

interface PayslipDocumentModalProps {
  isOpen: boolean;
  onClose: () => void;
  item: PayrollItem;
  employee?: Employee;
  company?: CompanyResponse | null;
  monthName: string;
  year: number;
}

// Number to Indian Words converter
function numberToWords(num: number): string {
  if (isNaN(num) || num <= 0) return "Zero Only";
  const a = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
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
  const empCode = employee?.employee_code || "—";
  const designation = (employee as any)?.position || (employee as any)?.job_title || "—";
  const department = employee?.department_name || "—";
  const dateOfJoining = employee?.hire_date ? new Date(employee.hire_date).toLocaleDateString("en-GB") : "—";
  const bankAccount: string = item.payout_account_number ?? "—";

  const netPayNum = Number(item.net_salary) || 0;
  const grossPayNum = Number(item.gross_salary) || 0;
  const totalDeductionsNum = Number(item.total_deductions) || 0;
  const reimbursementNum = Number(item.reimbursement_amount) || 0;

  const cleanPeriod = monthName.includes(String(year)) ? monthName : `${monthName} ${year}`;
  const contentRef = useRef<HTMLDivElement>(null);

  const handlePrint = () => {
    window.print();
  };

  const handleDownload = () => {
    if (!contentRef.current) return;
    const periodStr = cleanPeriod.replace(/\s+/g, "_");
    downloadDocumentAsHtml(
      contentRef.current,
      `Payslip_${empName.replace(/\s+/g, "_")}_${periodStr}.html`
    );
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
            <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "#0f172a" }}>
              Payslip — {cleanPeriod}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <DocumentActions onDownload={handleDownload} onPrint={handlePrint} />
            <button
              type="button"
              onClick={onClose}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "32px",
                height: "32px",
                border: "1px solid #cbd5e1",
                borderRadius: "6px",
                backgroundColor: "#ffffff",
                cursor: "pointer",
                color: "#64748b",
                fontSize: "1rem",
              }}
            >
              ✕
            </button>
          </div>
        </div>

        {/* Modal Printable Content */}
        <div
          ref={contentRef}
          data-print-content="true"
          style={{
            overflowY: "auto",
            padding: "16px",
            flex: 1,
            backgroundColor: "#ffffff",
          }}
        >
          <DocumentShell
            title="PAYSLIP"
            subtitle={`Payslip for the month of ${cleanPeriod}`}
            company={company}
            footerNote="— This is a computer-generated payroll document and requires no signature. —"
          >
            {/* Employee Metadata */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(3, 1fr)",
                gap: "10px 16px",
                border: "1px solid #e2e8f0",
                borderRadius: "8px",
                padding: "12px 16px",
                marginBottom: "16px",
                background: "#f8fafc",
                fontSize: "0.78rem",
              }}
            >
              <div>
                <span style={{ color: "#64748b" }}>Employee Name:</span>
                <strong style={{ display: "block", color: "#0f172a" }}>{empName}</strong>
              </div>
              <div>
                <span style={{ color: "#64748b" }}>Employee Code:</span>
                <strong style={{ display: "block", color: "#0f172a" }}>{empCode}</strong>
              </div>
              <div>
                <span style={{ color: "#64748b" }}>Designation:</span>
                <strong style={{ display: "block", color: "#0f172a" }}>{designation}</strong>
              </div>
              <div>
                <span style={{ color: "#64748b" }}>Department:</span>
                <strong style={{ display: "block", color: "#0f172a" }}>{department}</strong>
              </div>
              <div>
                <span style={{ color: "#64748b" }}>Date of Joining:</span>
                <strong style={{ display: "block", color: "#0f172a" }}>{dateOfJoining}</strong>
              </div>
              <div>
                <span style={{ color: "#64748b" }}>Bank Account:</span>
                <strong style={{ display: "block", color: "#0f172a", fontFamily: "monospace" }}>{bankAccount}</strong>
              </div>
            </div>

            {/* Attendance Strip */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-around",
                border: "1px solid #e2e8f0",
                borderRadius: "8px",
                padding: "8px 12px",
                marginBottom: "16px",
                background: "#ffffff",
                fontSize: "0.78rem",
                textAlign: "center",
              }}
            >
              <div>
                <span style={{ color: "#64748b" }}>Working Days</span>
                <strong style={{ display: "block", color: "#0f172a" }}>{item.working_days || "—"}</strong>
              </div>
              <div>
                <span style={{ color: "#64748b" }}>Present Days</span>
                <strong style={{ display: "block", color: "#16a34a" }}>{item.present_days || "—"}</strong>
              </div>
              <div>
                <span style={{ color: "#64748b" }}>Paid Leave</span>
                <strong style={{ display: "block", color: "#0284c7" }}>{item.paid_leave_days || "0.0"}</strong>
              </div>
              <div>
                <span style={{ color: "#64748b" }}>Loss of Pay (LOP)</span>
                <strong style={{ display: "block", color: "#dc2626" }}>{item.lop_days || "0.0"}</strong>
              </div>
            </div>

            {/* Earnings & Deductions Tables */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "16px",
                marginBottom: "16px",
              }}
            >
              {/* Earnings */}
              <div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
                  <thead>
                    <tr style={{ borderBottom: "1.5px solid #cbd5e1" }}>
                      <th style={{ textAlign: "left", padding: "6px 0", color: "#475569", textTransform: "uppercase" }}>EARNINGS</th>
                      <th style={{ textAlign: "right", padding: "6px 0", color: "#475569", textTransform: "uppercase" }}>AMOUNT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {item.earnings_json && item.earnings_json.length > 0 ? (
                      item.earnings_json.map((e, idx) => (
                        <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "6px 0", color: "#334155" }}>{e.name}</td>
                          <td style={{ padding: "6px 0", textAlign: "right", fontWeight: 600 }}>
                            ₹{Number(e.amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "6px 0", color: "#334155" }}>Gross Salary</td>
                        <td style={{ padding: "6px 0", textAlign: "right", fontWeight: 600 }}>
                          ₹{grossPayNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    )}
                    <tr style={{ borderTop: "1.5px solid #cbd5e1", fontWeight: 700 }}>
                      <td style={{ padding: "8px 0", color: "#0f172a" }}>Total Earnings</td>
                      <td style={{ padding: "8px 0", textAlign: "right", color: "#16a34a" }}>
                        ₹{grossPayNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Deductions */}
              <div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
                  <thead>
                    <tr style={{ borderBottom: "1.5px solid #cbd5e1" }}>
                      <th style={{ textAlign: "left", padding: "6px 0", color: "#475569", textTransform: "uppercase" }}>DEDUCTIONS</th>
                      <th style={{ textAlign: "right", padding: "6px 0", color: "#475569", textTransform: "uppercase" }}>AMOUNT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {item.deductions_json && item.deductions_json.length > 0 ? (
                      item.deductions_json.map((d, idx) => (
                        <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "6px 0", color: "#334155" }}>{d.name}</td>
                          <td style={{ padding: "6px 0", textAlign: "right", fontWeight: 600, color: "#dc2626" }}>
                            ₹{Number(d.amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "6px 0", color: "#334155" }}>Deductions</td>
                        <td style={{ padding: "6px 0", textAlign: "right", fontWeight: 600, color: "#dc2626" }}>
                          ₹{totalDeductionsNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    )}
                    <tr style={{ borderTop: "1.5px solid #cbd5e1", fontWeight: 700 }}>
                      <td style={{ padding: "8px 0", color: "#0f172a" }}>Total Deductions</td>
                      <td style={{ padding: "8px 0", textAlign: "right", color: "#dc2626" }}>
                        ₹{totalDeductionsNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* Total Net Payable Bar */}
            <div
              style={{
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: "8px",
                padding: "10px 16px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "10px",
              }}
            >
              <div>
                <div style={{ fontWeight: 800, color: "#0f172a", fontSize: "0.88rem" }}>
                  TOTAL NET PAYABLE
                </div>
                <div style={{ fontSize: "0.72rem", color: "#64748b" }}>
                  Gross Earnings - Total Deductions {reimbursementNum > 0 ? `+ Reimbursements (₹${reimbursementNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })})` : ""}
                </div>
              </div>

              <div style={{ fontSize: "1.25rem", fontWeight: 800, color: "#0f172a" }}>
                ₹{netPayNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </div>
            </div>

            {/* Amount in words */}
            <div style={{ textAlign: "right", fontSize: "0.75rem", color: "#475569" }}>
              <strong>Amount In Words: </strong> {numberToWords(netPayNum)}
            </div>
          </DocumentShell>
        </div>
      </div>
    </div>
  );
};
