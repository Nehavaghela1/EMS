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

type DocumentFolder = "payslips" | "tax_worksheet" | "form16" | "salary_revision";

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

  // Folders metadata
  const folders = [
    {
      id: "payslips" as DocumentFolder,
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
          <line x1="16" y1="13" x2="8" y2="13"></line>
          <line x1="16" y1="17" x2="8" y2="17"></line>
          <line x1="10" y1="9" x2="8" y2="9"></line>
        </svg>
      ),
      title: "Payslips",
      desc: "Find salary-related documents from Payroll.",
    },
    {
      id: "tax_worksheet" as DocumentFolder,
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
          <line x1="3" y1="9" x2="21" y2="9"></line>
          <line x1="9" y1="21" x2="9" y2="9"></line>
        </svg>
      ),
      title: "Tax Worksheet",
      desc: "Income Tax computation worksheet based on salary and statutory deductions.",
    },
    {
      id: "form16" as DocumentFolder,
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#ea580c" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
          <path d="M10 12h4"></path>
          <path d="M10 16h4"></path>
        </svg>
      ),
      title: "Form 16",
      desc: "Find documents related to your salary earned during the financial year and the amount of tax deducted by the employer.",
    },
    {
      id: "salary_revision" as DocumentFolder,
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#9333ea" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline>
          <polyline points="17 6 23 6 23 12"></polyline>
        </svg>
      ),
      title: "Salary Revision",
      desc: "Find documents related to your salary revision.",
    },
  ];

  // -------------------------------------------------------------------------
  // Inside Folder View (Matching Screen 5 / Screenshot 87348cf4)
  // -------------------------------------------------------------------------
  if (activeFolder) {
    const currentFolderMeta = folders.find((f) => f.id === activeFolder) || folders[0];

    return (
      <div style={{ width: "100%", minHeight: "100vh", display: "flex", background: "#ffffff" }}>
        {/* Left Sidebar Navigation */}
        <aside
          style={{
            width: "250px",
            minWidth: "250px",
            background: "#ffffff",
            borderRight: "1px solid #e2e8f0",
            padding: "24px 16px",
            display: "flex",
            flexDirection: "column",
            gap: "24px",
          }}
        >
          {/* Back All Documents */}
          <button
            type="button"
            onClick={() => setActiveFolder(null)}
            style={{
              background: "none",
              border: "none",
              display: "flex",
              alignItems: "center",
              gap: "8px",
              cursor: "pointer",
              padding: "6px 8px",
              borderRadius: "6px",
              textAlign: "left",
            }}
          >
            <span style={{ color: "#2563eb", fontSize: "0.88rem", fontWeight: 600 }}>← Back</span>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "#1e293b", fontWeight: 700, fontSize: "1rem" }}>
              <span style={{ fontSize: "1.2rem" }}>📁</span>
              <span>All Documents</span>
            </div>
          </button>

          {/* FOLDERS List */}
          <div>
            <div
              style={{
                fontSize: "0.75rem",
                fontWeight: 700,
                color: "#64748b",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
                padding: "0 10px 10px 10px",
              }}
            >
              Folders
            </div>
            <nav style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              {folders.map((f) => {
                const isActive = f.id === activeFolder;
                return (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => setActiveFolder(f.id)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "10px",
                      padding: "10px 12px",
                      borderRadius: "8px",
                      border: "none",
                      background: isActive ? "#eff6ff" : "transparent",
                      color: isActive ? "#2563eb" : "#475569",
                      fontWeight: isActive ? 600 : 500,
                      fontSize: "0.88rem",
                      cursor: "pointer",
                      textAlign: "left",
                      transition: "all 0.15s ease",
                    }}
                  >
                    <span style={{ fontSize: "1.05rem" }}>📁</span>
                    <span>{f.title}</span>
                  </button>
                );
              })}
            </nav>
          </div>
        </aside>

        {/* Right Main Content Area */}
        <main style={{ flex: 1, padding: "32px 40px", overflowY: "auto" }}>
          {/* Header Row: Folder Title & Financial Year Dropdown */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "24px",
              borderBottom: "1px solid #e2e8f0",
              paddingBottom: "16px",
            }}
          >
            <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: 0, color: "#0f172a" }}>
              {currentFolderMeta.title}
            </h1>

            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                background: "#ffffff",
                padding: "6px 14px",
                borderRadius: "8px",
                border: "1px solid #e2e8f0",
                fontSize: "0.86rem",
                color: "#334155",
                fontWeight: 500,
                boxShadow: "0 1px 2px rgba(0,0,0,0.02)",
              }}
            >
              <span style={{ color: "#2563eb", fontSize: "0.8rem" }}>▼</span>
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
                  fontSize: "0.86rem",
                  color: "#0f172a",
                }}
              >
                <option value="2026-2027">2026 - 27</option>
                <option value="2025-2026">2025 - 26</option>
              </select>
            </div>
          </div>

          {/* Folder Content: Payslips Table */}
          {activeFolder === "payslips" ? (
            filteredPayslips.length === 0 ? (
              <div
                style={{
                  padding: "4rem 2rem",
                  textAlign: "center",
                  background: "#ffffff",
                  borderRadius: "10px",
                  border: "1px solid #e2e8f0",
                }}
              >
                <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📄</div>
                <div style={{ fontWeight: 600, color: "#0f172a" }}>No payslips found for {financialYear}</div>
                <div style={{ color: "#64748b", fontSize: "0.875rem", marginTop: "4px" }}>
                  Official payslips for this period have not been released yet.
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
                    <tr style={{ background: "#ffffff", borderBottom: "1px solid #e2e8f0" }}>
                      <th style={{ padding: "16px 20px", fontWeight: 600, color: "#64748b" }}>
                        Month &amp; Year
                      </th>
                      <th style={{ padding: "16px 20px", fontWeight: 600, color: "#64748b" }}>
                        File Type
                      </th>
                      <th style={{ padding: "16px 20px", fontWeight: 600, color: "#64748b", textAlign: "right" }}>
                        Action
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
                          <td style={{ padding: "16px 20px", fontWeight: 600, color: "#2563eb" }}>
                            {periodLabel}
                          </td>
                          <td style={{ padding: "16px 20px", color: "#475569" }}>
                            Payslips
                          </td>
                          <td style={{ padding: "16px 20px", textAlign: "right" }}>
                            <div style={{ display: "inline-flex", alignItems: "center", gap: "14px" }}>
                              <button
                                type="button"
                                onClick={() => {
                                  setSelectedPayslip(item);
                                  setIsDocModalOpen(true);
                                }}
                                style={{
                                  background: "none",
                                  border: "none",
                                  color: "#2563eb",
                                  fontWeight: 600,
                                  fontSize: "0.875rem",
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
                                  color: "#2563eb",
                                  fontWeight: 600,
                                  fontSize: "0.875rem",
                                  cursor: downloadingId === item.id ? "not-allowed" : "pointer",
                                  padding: 0,
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: "5px",
                                }}
                              >
                                <span>📥</span>
                                <span>{downloadingId === item.id ? "Downloading..." : "Download"}</span>
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
          ) : activeFolder === "tax_worksheet" ? (
            /* Tax Worksheet Table (Separated from Payslip!) */
            filteredPayslips.length === 0 ? (
              <div
                style={{
                  padding: "4rem 2rem",
                  textAlign: "center",
                  background: "#ffffff",
                  borderRadius: "10px",
                  border: "1px solid #e2e8f0",
                }}
              >
                <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📑</div>
                <div style={{ fontWeight: 600, color: "#0f172a" }}>No tax worksheets for {financialYear}</div>
                <div style={{ color: "#64748b", fontSize: "0.875rem", marginTop: "4px" }}>
                  Monthly tax computation worksheets will appear here once payroll is processed.
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
                    <tr style={{ background: "#ffffff", borderBottom: "1px solid #e2e8f0" }}>
                      <th style={{ padding: "16px 20px", fontWeight: 600, color: "#64748b" }}>
                        Month &amp; Year
                      </th>
                      <th style={{ padding: "16px 20px", fontWeight: 600, color: "#64748b" }}>
                        File Type
                      </th>
                      <th style={{ padding: "16px 20px", fontWeight: 600, color: "#64748b", textAlign: "right" }}>
                        Action
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
                          <td style={{ padding: "16px 20px", fontWeight: 600, color: "#059669" }}>
                            {periodLabel}
                          </td>
                          <td style={{ padding: "16px 20px", color: "#475569" }}>
                            Tax Worksheet
                          </td>
                          <td style={{ padding: "16px 20px", textAlign: "right" }}>
                            <div style={{ display: "inline-flex", alignItems: "center", gap: "14px" }}>
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
                                  color: "#059669",
                                  fontWeight: 600,
                                  fontSize: "0.875rem",
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
                                  color: "#059669",
                                  fontWeight: 600,
                                  fontSize: "0.875rem",
                                  cursor: downloadingId === `tax-${item.id}` ? "not-allowed" : "pointer",
                                  padding: 0,
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: "5px",
                                }}
                              >
                                <span>📥</span>
                                <span>{downloadingId === `tax-${item.id}` ? "Downloading..." : "Download"}</span>
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
                padding: "4rem 2rem",
                textAlign: "center",
                background: "#ffffff",
                borderRadius: "10px",
                border: "1px solid #e2e8f0",
              }}
            >
              <div style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>
                📁
              </div>
              <div style={{ fontWeight: 600, fontSize: "1rem", color: "#0f172a" }}>
                No {currentFolderMeta.title} documents for {financialYear}
              </div>
              <div style={{ color: "#64748b", fontSize: "0.875rem", marginTop: "4px" }}>
                Official records will appear here once released by the finance and payroll teams.
              </div>
            </div>
          )}
        </main>

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
  // Top-Level Documents View (Full Width matching Image 3 & Image 4)
  // -------------------------------------------------------------------------
  return (
    <div style={{ width: "100%", minHeight: "100vh", background: "#ffffff", padding: "32px 48px" }}>
      {/* Top Header: Documents title & Card / List toggle pills */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "28px",
          borderBottom: "1px solid #e2e8f0",
          paddingBottom: "16px",
        }}
      >
        <h1 style={{ fontSize: "1.65rem", fontWeight: 700, margin: 0, color: "#1e293b" }}>
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
              padding: "6px 16px",
              fontSize: "0.85rem",
              fontWeight: viewMode === "card" ? 600 : 500,
              cursor: "pointer",
              boxShadow: viewMode === "card" ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
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
              padding: "6px 16px",
              fontSize: "0.85rem",
              fontWeight: viewMode === "list" ? 600 : 500,
              cursor: "pointer",
              boxShadow: viewMode === "list" ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              transition: "all 0.15s ease",
            }}
          >
            List
          </button>
        </div>
      </div>

      {loading ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "#64748b" }}>
          Loading documents...
        </div>
      ) : error ? (
        <div
          style={{
            padding: "1rem 1.25rem",
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
        /* Full-width Responsive Grid matching Screen 3 (cfdb8156.png) */
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: "24px",
          }}
        >
          {folders.map((folder) => (
            <div
              key={folder.id}
              onClick={() => setActiveFolder(folder.id)}
              style={{
                position: "relative",
                background: "#f8fafc",
                borderRadius: "14px",
                border: "1px solid #e2e8f0",
                padding: "24px 22px",
                boxShadow: "0 1px 4px rgba(0,0,0,0.02)",
                display: "flex",
                flexDirection: "column",
                gap: "14px",
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "#93c5fd";
                e.currentTarget.style.boxShadow = "0 4px 12px rgba(37,99,235,0.08)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "#e2e8f0";
                e.currentTarget.style.boxShadow = "0 1px 4px rgba(0,0,0,0.02)";
              }}
            >
              {/* Folder tab design top-accent */}
              <div
                style={{
                  width: "44px",
                  height: "44px",
                  borderRadius: "10px",
                  background: "#ffffff",
                  border: "1px solid #e2e8f0",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {folder.icon}
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <h3 style={{ margin: 0, fontSize: "1.08rem", fontWeight: 700, color: "#1e293b" }}>
                  {folder.title}
                </h3>
                <span
                  title={folder.desc}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: "16px",
                    height: "16px",
                    borderRadius: "50%",
                    border: "1px solid #cbd5e1",
                    fontSize: "0.7rem",
                    color: "#94a3b8",
                    fontWeight: 600,
                    cursor: "help",
                  }}
                >
                  i
                </span>
              </div>

              <p style={{ margin: 0, fontSize: "0.82rem", color: "#64748b", lineHeight: 1.4, minHeight: "2.5rem" }}>
                {folder.desc}
              </p>

              <div style={{ marginTop: "4px" }}>
                <span
                  style={{
                    color: "#2563eb",
                    fontSize: "0.88rem",
                    fontWeight: 600,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "4px",
                  }}
                >
                  View Now ›
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Full-width List View matching Screen 4 (e7727ad4.png) */
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
              <tr style={{ background: "#ffffff", borderBottom: "1px solid #e2e8f0" }}>
                <th
                  style={{
                    padding: "16px 24px",
                    fontWeight: 600,
                    color: "#64748b",
                    width: "220px",
                  }}
                >
                  Folder
                </th>
                <th style={{ padding: "16px 24px", fontWeight: 600, color: "#64748b" }}>
                  Folder Description
                </th>
              </tr>
            </thead>
            <tbody>
              {folders.map((folder) => (
                <tr
                  key={folder.id}
                  onClick={() => setActiveFolder(folder.id)}
                  style={{
                    borderBottom: "1px solid #f1f5f9",
                    cursor: "pointer",
                    transition: "background 0.15s ease",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "#f8fafc";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "#ffffff";
                  }}
                >
                  <td style={{ padding: "18px 24px", verticalAlign: "middle" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                      <span style={{ fontSize: "1.1rem" }}>📁</span>
                      <span
                        style={{
                          color: "#2563eb",
                          fontWeight: 700,
                          fontSize: "0.92rem",
                        }}
                      >
                        {folder.title}
                      </span>
                    </div>
                  </td>
                  <td
                    style={{
                      padding: "18px 24px",
                      color: "#475569",
                      fontSize: "0.86rem",
                      lineHeight: 1.5,
                      verticalAlign: "middle",
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
  );
}