import React from "react";
import { type PayrollItem } from "../api";
import { type Employee } from "../../hr/api";
import { type CompanyResponse } from "../../identity/api";

interface TaxWorksheetModalProps {
  isOpen: boolean;
  onClose: () => void;
  item: PayrollItem;
  employee?: Employee;
  company?: CompanyResponse | null;
  monthName: string;
  year: number;
}

export const TaxWorksheetModal: React.FC<TaxWorksheetModalProps> = ({
  isOpen,
  onClose,
  item,
  employee,
  company,
  monthName,
  year,
}) => {
  if (!isOpen) return null;

  const cleanPeriod = monthName.includes(String(year)) ? monthName : `${monthName} ${year}`;
  const empName = employee ? `${employee.first_name} ${employee.last_name || ""}`.trim() : "Employee";
  const designation = (employee as any)?.position || (employee as any)?.job_title || "Senior Staff";
  const pan = (employee as any)?.pan_number || "CVTPV3190C";

  const grossMonthly = Number(item.gross_salary || 0);
  const grossAnnual = grossMonthly * 12;
  const standardDeduction = 75000;
  const taxableIncome = Math.max(0, grossAnnual - standardDeduction);

  // FY 2026-2027 New Tax Regime (Section 115BAC statutory slabs matching database):
  // Up to ₹4,00,000 : Nil (0%)
  // ₹4,00,001 - ₹8,00,000 : 5%
  // ₹8,00,001 - ₹12,00,000 : 10%
  // ₹12,00,001 - ₹16,00,000 : 15%
  // ₹16,00,001 - ₹20,00,000 : 20%
  // ₹20,00,001 - ₹24,00,000 : 25%
  // Above ₹24,00,000 : 30%
  // Full rebate under Section 87A if taxable income <= ₹12,00,000 (Tax payable = ₹0).
  let computedTax = 0;
  if (taxableIncome > 400000) {
    computedTax += Math.min(taxableIncome - 400000, 400000) * 0.05;
  }
  if (taxableIncome > 800000) {
    computedTax += Math.min(taxableIncome - 800000, 400000) * 0.10;
  }
  if (taxableIncome > 1200000) {
    computedTax += Math.min(taxableIncome - 1200000, 400000) * 0.15;
  }
  if (taxableIncome > 1600000) {
    computedTax += Math.min(taxableIncome - 1600000, 400000) * 0.20;
  }
  if (taxableIncome > 2000000) {
    computedTax += Math.min(taxableIncome - 2000000, 400000) * 0.25;
  }
  if (taxableIncome > 2400000) {
    computedTax += (taxableIncome - 2400000) * 0.30;
  }

  // Rebate under Section 87A for New Regime (up to ₹12,00,000 taxable income, max rebate ₹60,000)
  const rebate87A = taxableIncome <= 1200000 ? computedTax : 0;
  const taxAfterRebate = Math.max(0, computedTax - rebate87A);
  const healthEducationCess = taxAfterRebate * 0.04;
  const totalTaxPayable = taxAfterRebate + healthEducationCess;
  const monthlyTDS = Math.round(totalTaxPayable / 12);

  const formatINR = (val: number) =>
    "₹" + Number(val || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const companyLogoUrl = company?.logo_url;
  const companyDisplayName = company?.name || "Infiria AI Private Limited";
  const companyAddressLine = [company?.address, company?.city, company?.pincode, company?.country].filter(Boolean).join(", ") ||
    "B704 Shapath Hexa, Opp. Gujarat Highcourt, SG Highway, Ahmedabad 380060, India";

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
            <span style={{ fontSize: "1.1rem" }}>📋</span>
            <span style={{ fontWeight: 700, color: "#0f172a", fontSize: "0.95rem" }}>
              Tax Computation Worksheet — {cleanPeriod}
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

        {/* Tax Worksheet Document Body */}
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
          {/* Company Header */}
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
              {companyLogoUrl ? (
                <img
                  src={companyLogoUrl}
                  alt={companyDisplayName}
                  style={{
                    maxHeight: "65px",
                    maxWidth: "160px",
                    objectFit: "contain",
                    display: "block",
                  }}
                />
              ) : (
                <div
                  style={{
                    width: "48px",
                    height: "48px",
                    borderRadius: "10px",
                    background: "linear-gradient(135deg, #0284c7, #2563eb)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "#ffffff",
                    fontWeight: 800,
                    fontSize: "1.5rem",
                  }}
                >
                  🏢
                </div>
              )}
              <div>
                <h1 style={{ margin: "0 0 4px", fontSize: "1.25rem", fontWeight: 800, color: "#0f172a" }}>
                  {companyDisplayName}
                </h1>
                <div style={{ fontSize: "0.78rem", color: "#64748b", maxWidth: "440px" }}>
                  {companyAddressLine}
                </div>
              </div>
            </div>

            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase", fontWeight: 600 }}>
                Income Tax Computation
              </div>
              <div style={{ fontSize: "1.1rem", fontWeight: 800, color: "#0f172a", marginTop: "2px" }}>
                FY {year} - {year + 1}
              </div>
              <div style={{ fontSize: "0.78rem", color: "#0284c7", fontWeight: 600 }}>
                New Tax Regime
              </div>
            </div>
          </div>

          {/* Employee Summary Card */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: "16px",
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              borderRadius: "8px",
              padding: "1rem 1.25rem",
              marginBottom: "1.5rem",
            }}
          >
            <div>
              <span style={{ fontSize: "0.75rem", color: "#64748b" }}>Employee Name</span>
              <div style={{ fontWeight: 700, color: "#0f172a" }}>{empName}</div>
            </div>
            <div>
              <span style={{ fontSize: "0.75rem", color: "#64748b" }}>Designation</span>
              <div style={{ fontWeight: 700, color: "#0f172a" }}>{designation}</div>
            </div>
            <div>
              <span style={{ fontSize: "0.75rem", color: "#64748b" }}>Permanent Account Number (PAN)</span>
              <div style={{ fontWeight: 700, color: "#0f172a" }}>{pan}</div>
            </div>
          </div>

          {/* Tax Computation Table */}
          <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "12px", color: "#0f172a" }}>
            Gross Income & Exemption Breakdown
          </h3>
          <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "20px" }}>
            <tbody>
              <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "8px 0", color: "#475569" }}>Monthly Gross Salary</td>
                <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 600 }}>{formatINR(grossMonthly)}</td>
              </tr>
              <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "8px 0", color: "#475569" }}>Gross Salary (Annualized: 12 Months)</td>
                <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 600 }}>{formatINR(grossAnnual)}</td>
              </tr>
              <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "8px 0", color: "#475569" }}>Income from Other Sources</td>
                <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 600 }}>₹0.00</td>
              </tr>
              <tr style={{ borderBottom: "2px solid #e2e8f0", fontWeight: 700, backgroundColor: "#f8fafc" }}>
                <td style={{ padding: "10px 8px" }}>Gross Total Income</td>
                <td style={{ padding: "10px 8px", textAlign: "right" }}>{formatINR(grossAnnual)}</td>
              </tr>
              <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "8px 0", color: "#475569" }}>Less: Standard Deduction under Section 16(ia)</td>
                <td style={{ padding: "8px 0", textAlign: "right", color: "#dc2626", fontWeight: 600 }}>
                  - {formatINR(standardDeduction)}
                </td>
              </tr>
              <tr style={{ borderBottom: "2px solid #cbd5e1", fontWeight: 800, backgroundColor: "#f0fdf4", color: "#166534" }}>
                <td style={{ padding: "10px 8px" }}>Net Taxable Income</td>
                <td style={{ padding: "10px 8px", textAlign: "right" }}>{formatINR(taxableIncome)}</td>
              </tr>
            </tbody>
          </table>

          {/* Tax Slab Calculation */}
          <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "12px", color: "#0f172a" }}>
            Tax Liability Calculation
          </h3>
          <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "20px" }}>
            <tbody>
              <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "8px 0", color: "#475569" }}>Tax as per Slabs (New Regime)</td>
                <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 600 }}>{formatINR(computedTax)}</td>
              </tr>
              <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "8px 0", color: "#475569" }}>Less: Tax Rebate under Section 87A (Up to ₹12,00,000 Taxable Income)</td>
                <td style={{ padding: "8px 0", textAlign: "right", color: "#16a34a", fontWeight: 600 }}>
                  - {formatINR(rebate87A)}
                </td>
              </tr>
              <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "8px 0", color: "#475569" }}>Net Tax before Cess</td>
                <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 600 }}>{formatINR(taxAfterRebate)}</td>
              </tr>
              <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "8px 0", color: "#475569" }}>Health & Education Cess (4%)</td>
                <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 600 }}>{formatINR(healthEducationCess)}</td>
              </tr>
              <tr style={{ borderBottom: "2px solid #e2e8f0", fontWeight: 800, backgroundColor: "#f8fafc" }}>
                <td style={{ padding: "10px 8px" }}>Total Annual Tax Payable</td>
                <td style={{ padding: "10px 8px", textAlign: "right" }}>{formatINR(totalTaxPayable)}</td>
              </tr>
              <tr style={{ borderBottom: "2px solid #cbd5e1", fontWeight: 800, backgroundColor: "#eff6ff", color: "#1e40af" }}>
                <td style={{ padding: "10px 8px" }}>Monthly TDS Deduction</td>
                <td style={{ padding: "10px 8px", textAlign: "right" }}>{formatINR(monthlyTDS)}</td>
              </tr>
            </tbody>
          </table>

          {taxableIncome <= 1200000 && (
            <div
              style={{
                background: "#f0fdf4",
                border: "1px solid #bbf7d0",
                borderRadius: "8px",
                padding: "12px 16px",
                display: "flex",
                alignItems: "center",
                gap: "12px",
                marginBottom: "20px",
              }}
            >
              <span style={{ fontSize: "1.5rem" }}>🎉</span>
              <div style={{ fontSize: "0.82rem", color: "#166534" }}>
                <strong>Zero Tax Status:</strong> Since your net taxable income ({formatINR(taxableIncome)}) is within the statutory limit of ₹12,00,000 under the New Regime, full rebate under Section 87A applies and no income tax is deductible.
              </div>
            </div>
          )}

          <div style={{ borderTop: "1px solid #f1f5f9", paddingTop: "1rem", textAlign: "center", fontSize: "0.75rem", color: "#94a3b8" }}>
            — This is a system-generated official tax worksheet based on your payroll earnings and statutory tax slabs. —
          </div>
        </div>
      </div>
    </div>
  );
};
