import { useState, useEffect, useMemo } from "react";
import {
  listMyPayslips,
  getMyTaxWorksheet,
  downloadMyPayslipPdf,
  downloadMyTaxWorksheetPdf,
  type PayrollItem,
  type TaxWorksheetResponse,
} from "../api";
import { getMyCompany, type CompanyResponse } from "../../identity/api";
import { useAuth } from "../../../app/auth-context";
import { parseApiError } from "../../../shared/api/errors";
import { PayslipDocumentModal } from "../components/PayslipDocumentModal";
import { TaxWorksheetModal } from "../components/TaxWorksheetModal";
import { formatMonthYear, triggerBlobDownload } from "../utils";

type DocumentFolder = "payslips" | "form16" | "salary_revision";

export function PayrollDocumentsPage() {
  const { user } = useAuth();
  const [payslips, setPayslips] = useState<PayrollItem[]>([]);
  const [company, setCompany] = useState<CompanyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // View state: top-level card/list or inside a folder
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [activeFolder, setActiveFolder] = useState<DocumentFolder | null>(null);
  const [financialYear, setFinancialYear] = useState("2026-2027");

  // Document modals
  const [selectedPayslip, setSelectedPayslip] = useState<PayrollItem | null>(null);
  const [isDocModalOpen, setIsDocModalOpen] = useState(false);
  const [selectedTaxPayslip, setSelectedTaxPayslip] = useState<PayrollItem | null>(null);
  const [taxWorksheet, setTaxWorksheet] = useState<TaxWorksheetResponse | null>(null);
  const [isTaxModalOpen, setIsTaxModalOpen] = useState(false);

  // Downloading state
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const [payslipData, companyData] = await Promise.all([
          listMyPayslips(),
          getMyCompany().catch(() => null),
        ]);
        setPayslips(payslipData);
        setCompany(companyData);
      } catch (err) {
        setError(parseApiError(err).message);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const handleDownloadPayslip = async (item: PayrollItem) => {
    setDownloadingId(item.id);
    try {
      const blob = await downloadMyPayslipPdf(item.id);
      const empName = user?.employee
        ? `${user.employee.first_name}_${user.employee.last_name || ""}`.trim()
        : "Employee";
      const label = formatMonthYear(item).replace(/\s+/g, "_");
      triggerBlobDownload(blob, `Payslip_${empName}_${label}.pdf`);
    } catch (err) {
      alert("Failed to download payslip: " + parseApiError(err).message);
    } finally {
      setDownloadingId(null);
    }
  };

  const handleDownloadTaxWorksheet = async (item: PayrollItem) => {
    const m = item.month || 10;
    const y = item.year || 2026;
    setDownloadingId(`tax-${item.id}`);
    try {
      const blob = await downloadMyTaxWorksheetPdf(m, y);
      const empName = user?.employee
        ? `${user.employee.first_name}_${user.employee.last_name || ""}`.trim()
        : "Employee";
      const label = formatMonthYear(item).replace(/\s+/g, "_");
      triggerBlobDownload(blob, `Tax_Worksheet_${empName}_${label}.pdf`);
    } catch (err) {
      alert("Failed to download tax worksheet: " + parseApiError(err).message);
    } finally {
      setDownloadingId(null);
    }
  };

  // Filter payslips by financial year
  const filteredPayslips = useMemo(() => {
    const isFy25 = financialYear.includes("2025");
    return payslips.filter((p) => {
      if (p.year) {
        return isFy25 ? p.year === 2025 : p.year === 2026;
      }
      return true;
    });
  }, [payslips, financialYear]);

  const formatINR = (val: number | string | null | undefined) =>
    "₹" +
    Number(val || 0).toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });

  // Folders metadata
  const folders = [
    {
      id: "payslips" as DocumentFolder,
      icon: "📄",
      title: "Payslips",
      desc: "Find salary-related documents from Payroll.",
    },
    {
      id: "form16" as DocumentFolder,
      icon: "📋",
      title: "Form 16",
      desc: "Find documents related to your salary earned during the financial year and the amount of tax deducted by the employer.",
    },
    {
      id: "salary_revision" as DocumentFolder,
      icon: "📈",
      title: "Salary Revision",
      desc: "Find documents related to your salary revision.",
    },
  ];

  // -------------------------------------------------------------------------
  // Inside Folder View (Screen 8 & 9)
  // -------------------------------------------------------------------------
  if (activeFolder) {
    const currentFolderMeta = folders.find((f) => f.id === activeFolder) || folders[0];

    return (
      <div style={{ maxWidth: "1200px", margin: "0 auto", padding: "1.5rem" }}>
        {/* Top Header: Back button, Title & Financial Year Dropdown */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "1rem",
            marginBottom: "1.5rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button
              type="button"
              onClick={() => setActiveFolder(null)}
              style={{
                background: "none",
                border: "none",
                color: "#2563eb",
                fontWeight: 600,
                fontSize: "0.92rem",
                cursor: "pointer",
                padding: 0,
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
              }}
            >
              ← Back
            </button>
            <h1 style={{ fontSize: "1.4rem", fontWeight: 700, margin: 0, color: "#0f172a" }}>
              {currentFolderMeta.title}
            </h1>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              background: "#ffffff",
              padding: "6px 14px",
              borderRadius: "8px",
              border: "1px solid #e2e8f0",
              fontSize: "0.85rem",
              color: "#334155",
              fontWeight: 500,
            }}
          >
            <span style={{ color: "#2563eb" }}>▼</span>
            <span>Financial Year :</span>
            <select
              value={financialYear}
              onChange={(e) => setFinancialYear(e.target.value)}
              style={{
                border: "none",
                fontWeight: 600,
                outline: "none",
                background: "transparent",
                cursor: "pointer",
                fontSize: "0.85rem",
              }}
            >
              <option value="2026-2027">2026 - 27</option>
              <option value="2025-2026">2025 - 26</option>
            </select>
          </div>
        </div>

        {/* Content Table */}
        {activeFolder === "payslips" ? (
          filteredPayslips.length === 0 ? (
            <div
              style={{
                padding: "3rem 1rem",
                textAlign: "center",
                background: "#ffffff",
                borderRadius: "10px",
                border: "1px solid #e2e8f0",
              }}
            >
              <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📄</div>
              <div style={{ fontWeight: 600, color: "#0f172a" }}>No payslips for {financialYear}</div>
              <div style={{ color: "#64748b", fontSize: "0.875rem", marginTop: "4px" }}>
                No released payslips were found for this financial year.
              </div>
            </div>
          ) : (
            <div
              style={{
                background: "#ffffff",
                borderRadius: "10px",
                border: "1px solid #e2e8f0",
                overflow: "hidden",
                boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
              }}
            >
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  textAlign: "left",
                  fontSize: "0.875rem",
                }}
              >
                <thead>
                  <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                    <th style={{ padding: "14px 16px", fontWeight: 600, color: "#475569" }}>
                      Month
                    </th>
                    <th style={{ padding: "14px 16px", fontWeight: 600, color: "#475569" }}>
                      Gross Pay
                    </th>
                    <th style={{ padding: "14px 16px", fontWeight: 600, color: "#475569" }}>
                      Reimbursements
                    </th>
                    <th style={{ padding: "14px 16px", fontWeight: 600, color: "#475569" }}>
                      Deductions
                    </th>
                    <th style={{ padding: "14px 16px", fontWeight: 600, color: "#475569" }}>
                      Take Home
                    </th>
                    <th style={{ padding: "14px 16px", fontWeight: 600, color: "#475569" }}>
                      Payslip
                    </th>
                    <th style={{ padding: "14px 16px", fontWeight: 600, color: "#475569" }}>
                      Tax Worksheet
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPayslips.map((item) => {
                    const periodLabel = formatMonthYear(item);
                    return (
                      <tr
                        key={item.id}
                        style={{
                          borderBottom: "1px solid #f1f5f9",
                          transition: "background 0.15s ease",
                        }}
                      >
                        <td style={{ padding: "14px 16px", fontWeight: 600, color: "#0284c7" }}>
                          {periodLabel}
                        </td>
                        <td style={{ padding: "14px 16px", color: "#334155" }}>
                          {formatINR(Number(item.gross_salary))}
                        </td>
                        <td style={{ padding: "14px 16px", color: "#334155" }}>
                          {formatINR(Number(item.reimbursement_amount || 0))}
                        </td>
                        <td style={{ padding: "14px 16px", color: "#334155" }}>
                          {formatINR(Number(item.total_deductions))}
                        </td>
                        <td style={{ padding: "14px 16px", fontWeight: 700, color: "#0f172a" }}>
                          {formatINR(Number(item.net_salary))}
                        </td>
                        <td style={{ padding: "14px 16px" }}>
                          <div style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedPayslip(item);
                                setIsDocModalOpen(true);
                              }}
                              style={{
                                background: "none",
                                border: "none",
                                color: "#0284c7",
                                fontWeight: 600,
                                fontSize: "0.85rem",
                                cursor: "pointer",
                                padding: 0,
                              }}
                            >
                              View
                            </button>
                            <span style={{ color: "#cbd5e1" }}>•</span>
                            <button
                              type="button"
                              onClick={() => handleDownloadPayslip(item)}
                              disabled={downloadingId === item.id}
                              style={{
                                background: "none",
                                border: "none",
                                color: "#0284c7",
                                fontWeight: 600,
                                fontSize: "0.85rem",
                                cursor: downloadingId === item.id ? "not-allowed" : "pointer",
                                padding: 0,
                              }}
                            >
                              {downloadingId === item.id ? "Downloading..." : "Download"}
                            </button>
                          </div>
                        </td>
                        <td style={{ padding: "14px 16px" }}>
                          <div style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
                            <button
                              type="button"
                              onClick={async () => {
                                setSelectedTaxPayslip(item);
                                const m = item.month || 10;
                                const y = item.year || 2026;
                                try {
                                  const ws = await getMyTaxWorksheet(m, y);
                                  setTaxWorksheet(ws);
                                } catch {
                                  setTaxWorksheet(null);
                                }
                                setIsTaxModalOpen(true);
                              }}
                              style={{
                                background: "none",
                                border: "none",
                                color: "#0284c7",
                                fontWeight: 600,
                                fontSize: "0.85rem",
                                cursor: "pointer",
                                padding: 0,
                              }}
                            >
                              View
                            </button>
                            <span style={{ color: "#cbd5e1" }}>•</span>
                            <button
                              type="button"
                              onClick={() => handleDownloadTaxWorksheet(item)}
                              disabled={downloadingId === `tax-${item.id}`}
                              style={{
                                background: "none",
                                border: "none",
                                color: "#0284c7",
                                fontWeight: 600,
                                fontSize: "0.85rem",
                                cursor: downloadingId === `tax-${item.id}` ? "not-allowed" : "pointer",
                                padding: 0,
                              }}
                            >
                              {downloadingId === `tax-${item.id}` ? "Downloading..." : "Download"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        ) : (
          /* Form 16 & Salary Revision empty state */
          <div
            style={{
              padding: "3.5rem 1rem",
              textAlign: "center",
              background: "#ffffff",
              borderRadius: "10px",
              border: "1px solid #e2e8f0",
            }}
          >
            <div style={{ fontSize: "2.2rem", marginBottom: "0.5rem" }}>
              {currentFolderMeta.icon}
            </div>
            <div style={{ fontWeight: 600, fontSize: "1rem", color: "#0f172a" }}>
              No {currentFolderMeta.title} documents for {financialYear}
            </div>
            <div style={{ color: "#64748b", fontSize: "0.875rem", marginTop: "4px" }}>
              Official records will appear here once released by the finance and payroll teams.
            </div>
          </div>
        )}

        {/* Payslip Modal */}
        {selectedPayslip && (
          <PayslipDocumentModal
            isOpen={isDocModalOpen}
            onClose={() => {
              setIsDocModalOpen(false);
              setSelectedPayslip(null);
            }}
            item={selectedPayslip}
            employee={(user?.employee as any) || undefined}
            company={company}
            monthName={formatMonthYear(selectedPayslip)}
            year={selectedPayslip.year || 2026}
          />
        )}

        {/* Tax Worksheet Modal */}
        {selectedTaxPayslip && (
          <TaxWorksheetModal
            isOpen={isTaxModalOpen}
            onClose={() => {
              setIsTaxModalOpen(false);
              setSelectedTaxPayslip(null);
            }}
            worksheet={taxWorksheet}
            company={company}
            monthName={formatMonthYear(selectedTaxPayslip)}
            year={selectedTaxPayslip.year || 2026}
          />
        )}
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Top-Level Documents View (Screen 1 & 2)
  // -------------------------------------------------------------------------
  return (
    <div style={{ maxWidth: "680px", margin: "2rem auto", padding: "0 1rem" }}>
      <div
        style={{
          background: "#ffffff",
          borderRadius: "14px",
          border: "1px solid #e2e8f0",
          padding: "24px",
          boxShadow: "0 1px 4px rgba(0,0,0,0.03)",
        }}
      >
        {/* Header with Title and Card/List switcher */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "1.5rem",
          }}
        >
          <h1 style={{ fontSize: "1.4rem", fontWeight: 700, margin: 0, color: "#0f172a" }}>
            Documents
          </h1>

          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              background: "#f1f5f9",
              padding: "3px",
              borderRadius: "8px",
              border: "1px solid #e2e8f0",
            }}
          >
            <button
              type="button"
              onClick={() => setViewMode("card")}
              style={{
                background: viewMode === "card" ? "#ffffff" : "transparent",
                color: viewMode === "card" ? "#0f172a" : "#64748b",
                border: "none",
                borderRadius: "6px",
                padding: "4px 12px",
                fontSize: "0.82rem",
                fontWeight: viewMode === "card" ? 600 : 500,
                cursor: "pointer",
                boxShadow: viewMode === "card" ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
                transition: "all 0.15s ease",
              }}
            >
              Card
            </button>
            <button
              type="button"
              onClick={() => setViewMode("list")}
              style={{
                background: viewMode === "list" ? "#ffffff" : "transparent",
                color: viewMode === "list" ? "#0f172a" : "#64748b",
                border: "none",
                borderRadius: "6px",
                padding: "4px 12px",
                fontSize: "0.82rem",
                fontWeight: viewMode === "list" ? 600 : 500,
                cursor: "pointer",
                boxShadow: viewMode === "list" ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
                transition: "all 0.15s ease",
              }}
            >
              List
            </button>
          </div>
        </div>

        {loading ? (
          <div style={{ padding: "2rem", textAlign: "center", color: "#64748b" }}>
            Loading documents...
          </div>
        ) : error ? (
          <div
            style={{
              padding: "1rem",
              background: "#fef2f2",
              border: "1px solid #fecaca",
              borderRadius: "8px",
              color: "#991b1b",
              fontSize: "0.875rem",
            }}
          >
            {error}
          </div>
        ) : viewMode === "card" ? (
          /* Card View: Exactly matches Screen 1 */
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {folders.map((folder) => (
              <div
                key={folder.id}
                style={{
                  background: "#ffffff",
                  borderRadius: "12px",
                  border: "1px solid #e2e8f0",
                  padding: "18px 20px",
                  boxShadow: "0 1px 2px rgba(0,0,0,0.02)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "10px",
                }}
              >
                <div
                  style={{
                    width: "36px",
                    height: "36px",
                    borderRadius: "8px",
                    background: "#f8fafc",
                    border: "1px solid #f1f5f9",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "1.1rem",
                  }}
                >
                  {folder.icon}
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>
                    {folder.title}
                  </h3>
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      width: "15px",
                      height: "15px",
                      borderRadius: "50%",
                      border: "1px solid #cbd5e1",
                      fontSize: "0.68rem",
                      color: "#94a3b8",
                      fontWeight: 600,
                    }}
                  >
                    i
                  </span>
                </div>

                <div>
                  <button
                    type="button"
                    onClick={() => setActiveFolder(folder.id)}
                    style={{
                      background: "none",
                      border: "none",
                      color: "#2563eb",
                      fontSize: "0.85rem",
                      fontWeight: 600,
                      cursor: "pointer",
                      padding: 0,
                    }}
                  >
                    View Now ›
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          /* List View: Exactly matches Screen 2 */
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                textAlign: "left",
                fontSize: "0.875rem",
              }}
            >
              <thead>
                <tr style={{ borderBottom: "1px solid #e2e8f0" }}>
                  <th
                    style={{
                      padding: "12px 14px",
                      fontWeight: 600,
                      color: "#475569",
                      width: "140px",
                    }}
                  >
                    Folder
                  </th>
                  <th style={{ padding: "12px 14px", fontWeight: 600, color: "#475569" }}>
                    Folder Description
                  </th>
                </tr>
              </thead>
              <tbody>
                {folders.map((folder) => (
                  <tr key={folder.id} style={{ borderBottom: "1px solid #f8fafc" }}>
                    <td style={{ padding: "16px 14px", verticalAlign: "top" }}>
                      <button
                        type="button"
                        onClick={() => setActiveFolder(folder.id)}
                        style={{
                          background: "none",
                          border: "none",
                          color: "#0284c7",
                          fontWeight: 700,
                          fontSize: "0.88rem",
                          cursor: "pointer",
                          padding: 0,
                          textAlign: "left",
                        }}
                      >
                        {folder.title}
                      </button>
                    </td>
                    <td
                      style={{
                        padding: "16px 14px",
                        color: "#475569",
                        fontSize: "0.84rem",
                        lineHeight: 1.5,
                      }}
                    >
                      {folder.desc}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
