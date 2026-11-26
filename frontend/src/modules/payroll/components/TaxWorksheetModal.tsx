import React, { useRef } from "react";
import { type TaxWorksheetResponse } from "../api";
import { type CompanyResponse } from "../../identity/api";
import { DocumentShell } from "./DocumentShell";
import { DocumentActions } from "./DocumentActions";
import { downloadDocumentAsHtml } from "../utils";

interface TaxWorksheetModalProps {
  isOpen: boolean;
  onClose: () => void;
  worksheet: TaxWorksheetResponse | null;
  company?: CompanyResponse | null;
  monthName: string;
  year: number;
}

export const TaxWorksheetModal: React.FC<TaxWorksheetModalProps> = ({
  isOpen,
  onClose,
  worksheet,
  company,
  monthName,
  year,
}) => {
  const contentRef = useRef<HTMLDivElement>(null);
  if (!isOpen) return null;

  const handlePrint = () => {
    window.print();
  };

  const handleDownload = () => {
    if (!contentRef.current) return;
    const cleanMonth = monthName.replace(String(year), "").trim();
    const periodStr = `${cleanMonth}_${year}`.trim();
    downloadDocumentAsHtml(
      contentRef.current,
      `Tax_Worksheet_${periodStr || "Document"}.html`
    );
  };

  const formatINR = (val: string | number | null | undefined) =>
    "₹" + Number(val || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

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
            <span style={{ fontSize: "1.1rem" }}>📋</span>
            <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "#0f172a" }}>
              Income Tax Computation Worksheet
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
          {worksheet ? (
            <DocumentShell
              title="INCOME TAX COMPUTATION WORKSHEET"
              subtitle={`${monthName} ${year} • ${worksheet.financial_year} (${worksheet.regime.toUpperCase()})`}
              company={company}
              footerNote="— This is a system-generated official tax worksheet based on your payroll earnings and statutory tax slabs. —"
            >
              {/* Employee & Tax Summary Header */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: "10px",
                  background: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  borderRadius: "8px",
                  padding: "12px",
                  marginBottom: "16px",
                  fontSize: "0.78rem",
                }}
              >
                <div>
                  <div style={{ color: "#64748b" }}>Employee Name</div>
                  <div style={{ fontWeight: 700, color: "#0f172a", marginTop: "2px" }}>
                    {worksheet.employee_name || "—"}
                  </div>
                </div>
                <div>
                  <div style={{ color: "#64748b" }}>Designation</div>
                  <div style={{ fontWeight: 600, color: "#0f172a", marginTop: "2px" }}>
                    {worksheet.designation || "—"}
                  </div>
                </div>
                <div>
                  <div style={{ color: "#64748b" }}>PAN</div>
                  <div style={{ fontWeight: 700, fontFamily: "monospace", color: "#0f172a", marginTop: "2px" }}>
                    {worksheet.pan_number || "—"}
                  </div>
                </div>
                <div>
                  <div style={{ color: "#64748b" }}>Tax Regime</div>
                  <div style={{ fontWeight: 700, color: "#0284c7", marginTop: "2px" }}>
                    {worksheet.regime.toUpperCase()}
                  </div>
                </div>
              </div>

              {/* Status Note if no payroll run */}
              {worksheet.status === "no_payroll" && (
                <div
                  style={{
                    padding: "8px 12px",
                    background: "#fef2f2",
                    border: "1px solid #fecaca",
                    borderRadius: "6px",
                    color: "#991b1b",
                    fontSize: "0.78rem",
                    marginBottom: "14px",
                  }}
                >
                  ℹ️ No finalized payroll run recorded for this month. All actual income values are ₹0.00.
                </div>
              )}

              {/* 3-Column Breakdown: Item | Actual | Projected | Total */}
              <div style={{ marginBottom: "16px" }}>
                <h4 style={{ margin: "0 0 8px", fontSize: "0.85rem", fontWeight: 700, color: "#0f172a", textTransform: "uppercase" }}>
                  Gross Income & Exemption Breakdown
                </h4>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
                  <thead>
                    <tr style={{ borderBottom: "1.5px solid #cbd5e1", background: "#f8fafc" }}>
                      <th style={{ textAlign: "left", padding: "6px 8px", color: "#475569" }}>Component</th>
                      <th style={{ textAlign: "right", padding: "6px 8px", color: "#475569" }}>Actual</th>
                      <th style={{ textAlign: "right", padding: "6px 8px", color: "#475569" }}>Projected</th>
                      <th style={{ textAlign: "right", padding: "6px 8px", color: "#475569" }}>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {worksheet.gross_earnings.map((e, idx) => (
                      <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "6px 8px", color: "#334155" }}>{e.name}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>{formatINR(e.actual)}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>{formatINR(e.projection)}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right", fontWeight: 600 }}>{formatINR(e.total)}</td>
                      </tr>
                    ))}
                    <tr style={{ borderBottom: "1.5px solid #cbd5e1", fontWeight: 700, background: "#f8fafc" }}>
                      <td style={{ padding: "7px 8px", color: "#0f172a" }}>Total Gross Salary</td>
                      <td style={{ padding: "7px 8px", textAlign: "right" }}>{formatINR(worksheet.total_gross?.actual)}</td>
                      <td style={{ padding: "7px 8px", textAlign: "right" }}>{formatINR(worksheet.total_gross?.projection)}</td>
                      <td style={{ padding: "7px 8px", textAlign: "right" }}>{formatINR(worksheet.total_gross?.total)}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td style={{ padding: "6px 8px", color: "#334155" }}>Less: Standard Deduction under Section 16(ia)</td>
                      <td style={{ padding: "6px 8px", textAlign: "right", color: "#dc2626" }}>- {formatINR(worksheet.standard_deduction?.actual)}</td>
                      <td style={{ padding: "6px 8px", textAlign: "right", color: "#dc2626" }}>- {formatINR(worksheet.standard_deduction?.projection)}</td>
                      <td style={{ padding: "6px 8px", textAlign: "right", color: "#dc2626", fontWeight: 600 }}>- {formatINR(worksheet.standard_deduction?.total)}</td>
                    </tr>
                    <tr style={{ borderTop: "2px solid #cbd5e1", fontWeight: 800, background: "#f0fdf4" }}>
                      <td style={{ padding: "8px 8px", color: "#166534" }}>Net Taxable Income</td>
                      <td style={{ padding: "8px 8px", textAlign: "right", color: "#166534" }}>{formatINR(worksheet.income_chargeable_salaries?.actual)}</td>
                      <td style={{ padding: "8px 8px", textAlign: "right", color: "#166534" }}>{formatINR(worksheet.income_chargeable_salaries?.projection)}</td>
                      <td style={{ padding: "8px 8px", textAlign: "right", color: "#166534" }}>{formatINR(worksheet.total_taxable_income)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Tax Liability Calculation */}
              <div style={{ marginBottom: "16px" }}>
                <h4 style={{ margin: "0 0 8px", fontSize: "0.85rem", fontWeight: 700, color: "#0f172a", textTransform: "uppercase" }}>
                  Tax Liability Calculation
                </h4>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
                  <thead>
                    <tr style={{ borderBottom: "1.5px solid #cbd5e1", background: "#f8fafc" }}>
                      <th style={{ textAlign: "left", padding: "6px 8px", color: "#475569" }}>Slab Range</th>
                      <th style={{ textAlign: "center", padding: "6px 8px", color: "#475569" }}>Rate</th>
                      <th style={{ textAlign: "right", padding: "6px 8px", color: "#475569" }}>Taxable Amount</th>
                      <th style={{ textAlign: "right", padding: "6px 8px", color: "#475569" }}>Tax</th>
                    </tr>
                  </thead>
                  <tbody>
                    {worksheet.slab_breakdowns.map((sb, idx) => (
                      <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "6px 8px", color: "#334155" }}>{sb.slab_range}</td>
                        <td style={{ padding: "6px 8px", textAlign: "center", color: "#64748b" }}>{sb.rate_percent}%</td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>{formatINR(sb.taxable_amount)}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right", fontWeight: 600 }}>{formatINR(sb.tax_amount)}</td>
                      </tr>
                    ))}
                    <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td colSpan={3} style={{ padding: "6px 8px", color: "#334155" }}>Gross Tax Liability</td>
                      <td style={{ padding: "6px 8px", textAlign: "right", fontWeight: 600 }}>{formatINR(worksheet.gross_tax_liability)}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td colSpan={3} style={{ padding: "6px 8px", color: "#334155" }}>Less: Tax Rebate under Section 87A</td>
                      <td style={{ padding: "6px 8px", textAlign: "right", color: "#16a34a", fontWeight: 600 }}>- {formatINR(worksheet.rebate_87a)}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td colSpan={3} style={{ padding: "6px 8px", color: "#334155" }}>Health & Education Cess (4%)</td>
                      <td style={{ padding: "6px 8px", textAlign: "right", fontWeight: 600 }}>{formatINR(worksheet.health_education_cess)}</td>
                    </tr>
                    <tr style={{ borderTop: "2px solid #cbd5e1", fontWeight: 800, background: "#fef3c7" }}>
                      <td colSpan={3} style={{ padding: "8px 8px", color: "#92400e" }}>Total Annual Tax Payable</td>
                      <td style={{ padding: "8px 8px", textAlign: "right", color: "#92400e" }}>{formatINR(worksheet.total_tax_payable)}</td>
                    </tr>
                    <tr style={{ borderTop: "1px solid #cbd5e1", fontWeight: 700, background: "#f8fafc" }}>
                      <td colSpan={3} style={{ padding: "8px 8px", color: "#0f172a" }}>Monthly TDS Deduction</td>
                      <td style={{ padding: "8px 8px", textAlign: "right", color: "#0284c7" }}>{formatINR(worksheet.monthly_tds_remaining)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </DocumentShell>
          ) : (
            <div style={{ padding: "40px 0", textAlign: "center", color: "#64748b" }}>
              Loading tax worksheet...
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
