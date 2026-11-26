import { useState, useEffect } from "react";
import { listMyPayslips, type PayrollItem } from "../api";
import { getMyCompany, type CompanyResponse } from "../../identity/api";
import { useAuth } from "../../../app/auth-context";
import { parseApiError } from "../../../shared/api/errors";
import { PayslipDocumentModal } from "../components/PayslipDocumentModal";
import { formatMonthYear } from "../utils";

export function PayrollDocumentsPage() {
  const { user } = useAuth();
  const [payslips, setPayslips] = useState<PayrollItem[]>([]);
  const [company, setCompany] = useState<CompanyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPayslip, setSelectedPayslip] = useState<PayrollItem | null>(null);
  const [isDocModalOpen, setIsDocModalOpen] = useState(false);

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

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto", padding: "1.5rem" }}>
      <div style={{ marginBottom: "1.5rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: 0, color: "#0f172a" }}>
          Payroll Documents
        </h1>
        <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: "0.875rem" }}>
          View and download your monthly payslips and payroll records.
        </p>
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
      ) : (
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
                  Action
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
                      Payslip - {periodLabel}
                    </td>
                    <td style={{ padding: "12px 16px", color: "#64748b" }}>{periodLabel}</td>
                    <td style={{ padding: "12px 16px", fontWeight: 600, color: "#0f172a" }}>
                      ₹{Number(item.net_salary || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </td>
                    <td style={{ padding: "12px 16px", textAlign: "right" }}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedPayslip(item);
                          setIsDocModalOpen(true);
                        }}
                        style={{
                          background: "#f1f5f9",
                          border: "1px solid #cbd5e1",
                          borderRadius: "6px",
                          padding: "6px 12px",
                          fontSize: "0.8rem",
                          fontWeight: 500,
                          color: "#1e293b",
                          cursor: "pointer",
                        }}
                      >
                        View
                      </button>
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
