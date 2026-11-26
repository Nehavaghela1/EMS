import { useState, useEffect, useRef } from "react";
import { listMyPayslips, type PayrollItem } from "../api";
import { getMyCompany, type CompanyResponse } from "../../identity/api";
import { useAuth } from "../../../app/auth-context";
import { parseApiError } from "../../../shared/api/errors";
import { PayslipDocumentModal } from "../components/PayslipDocumentModal";
import { DocumentActions } from "../components/DocumentActions";
import { formatMonthYear, downloadDocumentAsHtml } from "../utils";

export function PayrollDocumentsPage() {
  const { user } = useAuth();
  const [payslips, setPayslips] = useState<PayrollItem[]>([]);
  const [company, setCompany] = useState<CompanyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPayslip, setSelectedPayslip] = useState<PayrollItem | null>(null);
  const [isDocModalOpen, setIsDocModalOpen] = useState(false);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");

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

  const handleOpenPayslip = (item: PayrollItem) => {
    setSelectedPayslip(item);
    setIsDocModalOpen(true);
  };

  const handlePrintItem = (item: PayrollItem) => {
    setSelectedPayslip(item);
    setIsDocModalOpen(true);
    setTimeout(() => {
      window.print();
    }, 100);
  };

  const handleDownloadItem = (item: PayrollItem) => {
    setSelectedPayslip(item);
    setIsDocModalOpen(true);
    setTimeout(() => {
      const modalDoc = document.querySelector(".modal-backdrop [data-print-content='true']") as HTMLElement;
      const empName = user?.employee ? `${user.employee.first_name}_${user.employee.last_name || ""}`.trim() : "Employee";
      const label = formatMonthYear(item).replace(/\s+/g, "_");
      if (modalDoc) {
        downloadDocumentAsHtml(modalDoc, `Payslip_${empName}_${label}.html`);
      }
    }, 150);
  };

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto", padding: "1.5rem" }}>
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
        <div>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: 0, color: "#0f172a" }}>
            Documents
          </h1>
          <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: "0.875rem" }}>
            View and download your monthly payslips and official payroll records.
          </p>
        </div>

        {/* Card / List View Switcher */}
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
              padding: "5px 12px",
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
              padding: "5px 12px",
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
          Loading payroll documents...
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
      ) : payslips.length === 0 ? (
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
          <div style={{ fontWeight: 600, color: "#0f172a" }}>No documents available</div>
          <div style={{ color: "#64748b", fontSize: "0.875rem", marginTop: "4px" }}>
            No payslips have been released yet.
          </div>
        </div>
      ) : viewMode === "card" ? (
        /* Card View */
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: "1.25rem",
          }}
        >
          {payslips.map((item) => {
            const periodLabel = formatMonthYear(item);
            return (
              <div
                key={item.id}
                style={{
                  background: "#ffffff",
                  borderRadius: "12px",
                  border: "1px solid #e2e8f0",
                  padding: "1.25rem",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                  transition: "transform 0.15s ease, box-shadow 0.15s ease",
                }}
              >
                <div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: "0.75rem",
                    }}
                  >
                    <div
                      style={{
                        width: "36px",
                        height: "36px",
                        borderRadius: "8px",
                        background: "#eff6ff",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: "1.1rem",
                      }}
                    >
                      📄
                    </div>
                    <span
                      style={{
                        fontSize: "0.74rem",
                        fontWeight: 600,
                        color: "#0284c7",
                        background: "#f0f9ff",
                        padding: "2px 8px",
                        borderRadius: "4px",
                      }}
                    >
                      Payslip
                    </span>
                  </div>

                  <h3 style={{ margin: "0 0 4px", fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>
                    Payslip — {periodLabel}
                  </h3>
                  <div style={{ fontSize: "0.8rem", color: "#64748b", marginBottom: "1rem" }}>
                    Period: {periodLabel}
                  </div>

                  <div
                    style={{
                      background: "#f8fafc",
                      borderRadius: "8px",
                      padding: "8px 12px",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "1rem",
                    }}
                  >
                    <span style={{ fontSize: "0.78rem", color: "#64748b" }}>Take Home:</span>
                    <strong style={{ fontSize: "0.95rem", color: "#0f172a" }}>
                      ₹{Number(item.net_salary || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </strong>
                  </div>
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    borderTop: "1px solid #f1f5f9",
                    paddingTop: "0.75rem",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => handleOpenPayslip(item)}
                    style={{
                      background: "none",
                      border: "none",
                      color: "#2563eb",
                      fontSize: "0.82rem",
                      fontWeight: 600,
                      cursor: "pointer",
                      padding: 0,
                    }}
                  >
                    View Details
                  </button>
                  <DocumentActions
                    onDownload={() => handleDownloadItem(item)}
                    onPrint={() => handlePrintItem(item)}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* List View */
        <div
          style={{
            background: "#ffffff",
            borderRadius: "10px",
            border: "1px solid #e2e8f0",
            overflow: "hidden",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.875rem" }}>
            <thead>
              <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                <th style={{ padding: "12px 16px", fontWeight: 600, color: "#475569" }}>Document</th>
                <th style={{ padding: "12px 16px", fontWeight: 600, color: "#475569" }}>Period</th>
                <th style={{ padding: "12px 16px", fontWeight: 600, color: "#475569" }}>Net Pay</th>
                <th style={{ padding: "12px 16px", fontWeight: 600, color: "#475569", textAlign: "right" }}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {payslips.map((item) => {
                const periodLabel = formatMonthYear(item);
                return (
                  <tr
                    key={item.id}
                    style={{
                      borderBottom: "1px solid #f1f5f9",
                      transition: "background 0.15s ease",
                    }}
                  >
                    <td style={{ padding: "12px 16px", fontWeight: 500, color: "#0f172a" }}>
                      Payslip — {periodLabel}
                    </td>
                    <td style={{ padding: "12px 16px", color: "#64748b" }}>{periodLabel}</td>
                    <td style={{ padding: "12px 16px", fontWeight: 600, color: "#0f172a" }}>
                      ₹{Number(item.net_salary || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </td>
                    <td style={{ padding: "12px 16px", textAlign: "right" }}>
                      <div style={{ display: "inline-flex", alignItems: "center", gap: "12px" }}>
                        <button
                          type="button"
                          onClick={() => handleOpenPayslip(item)}
                          style={{
                            background: "#f1f5f9",
                            border: "1px solid #cbd5e1",
                            borderRadius: "6px",
                            padding: "4px 10px",
                            fontSize: "0.8rem",
                            fontWeight: 500,
                            color: "#1e293b",
                            cursor: "pointer",
                          }}
                        >
                          View
                        </button>
                        <DocumentActions
                          onDownload={() => handleDownloadItem(item)}
                          onPrint={() => handlePrintItem(item)}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

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
          year={selectedPayslip.year || new Date().getFullYear()}
        />
      )}
    </div>
  );
}
