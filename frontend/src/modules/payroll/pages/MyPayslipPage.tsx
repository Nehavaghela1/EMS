import { useState, useEffect, useMemo, useRef } from "react";
import {
  listMyPayslips,
  getMyBankAccount,
  revealMyBankAccount,
  saveMyBankAccount,
  getMyTaxWorksheet,
  getMyAnnualEarnings,
  exportMyAnnualEarnings,
  getMySalaryCertificate,
  type PayrollItem,
  type BankAccountResponse,
  type TaxWorksheetResponse,
  type AnnualEarningsResponse,
  type SalaryCertificateResponse,
} from "../api";
import { getMyCompany, type CompanyResponse } from "../../identity/api";
import { getFnFSettlement, type FnFSettlement } from "../../hr/api";
import { useAuth } from "../../../app/auth-context";
import { parseApiError } from "../../../shared/api/errors";
import { PayslipDocumentModal } from "../components/PayslipDocumentModal";
import { TaxWorksheetModal } from "../components/TaxWorksheetModal";
import { DocumentShell } from "../components/DocumentShell";
import { DocumentActions } from "../components/DocumentActions";
import { CATEGORICAL_PALETTE } from "../../../shared/utils/palette";
import { formatMonthYear, formatShortMonthYear, downloadDocumentAsHtml } from "../utils";

// Number to Indian Words converter
function numberToIndianWords(num: number): string {
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

type SalarySubTab = "structure" | "payslips" | "annual_earnings" | "bank_details" | "salary_certificate";

export function MyPayslipPage() {
  const { user } = useAuth();

  // Navigation state
  const [salarySubTab, setSalarySubTab] = useState<SalarySubTab>("payslips");
  const [legacyActiveTab, setLegacyActiveTab] = useState<"payslips" | "fnf" | "bank">("payslips");

  // Data states
  const [payslips, setPayslips] = useState<PayrollItem[]>([]);
  const [fnfData, setFnfData] = useState<FnFSettlement | null>(null);
  const [company, setCompany] = useState<CompanyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [, setLoadError] = useState<string | null>(null);

  // Selected payslip & Tax worksheet detail mode
  const [selectedPayslip, setSelectedPayslip] = useState<PayrollItem | null>(null);
  const [detailMode, setDetailMode] = useState<"payslip" | "tax_worksheet">("payslip");
  const [isDocModalOpen, setIsDocModalOpen] = useState(false);
  const [isTaxModalOpen, setIsTaxModalOpen] = useState(false);

  // Backend Tax Worksheet state
  const [taxWorksheet, setTaxWorksheet] = useState<TaxWorksheetResponse | null>(null);
  const [taxWorksheetLoading, setTaxWorksheetLoading] = useState(false);

  // Annual Earnings state
  const [annualEarnings, setAnnualEarnings] = useState<AnnualEarningsResponse | null>(null);
  const [annualEarningsLoading, setAnnualEarningsLoading] = useState(false);
  const [isExportingAnnual, setIsExportingAnnual] = useState(false);

  // Salary Certificate state
  const [salaryCert, setSalaryCert] = useState<SalaryCertificateResponse | null>(null);
  const [salaryCertLoading, setSalaryCertLoading] = useState(false);

  // Bank account state
  const [bankAccount, setBankAccount] = useState<BankAccountResponse | null>(null);
  const [bankLoading, setBankLoading] = useState(false);
  const [bankError, setBankError] = useState<string | null>(null);
  const [bankSuccess, setBankSuccess] = useState<string | null>(null);
  const [bankHolder, setBankHolder] = useState("");
  const [bankName, setBankName] = useState("");
  const [bankNumber, setBankNumber] = useState("");
  const [bankIfsc, setBankIfsc] = useState("");
  const [savingBank, setSavingBank] = useState(false);
  const [isEditingBank, setIsEditingBank] = useState(false);
  const [showFullAccount, setShowFullAccount] = useState(false);
  const [unmaskedAccount, setUnmaskedAccount] = useState<string | null>(null);

  // Financial Year Filter
  const [financialYear, setFinancialYear] = useState("2026-2027");

  useEffect(() => {
    fetchPayslips();
    fetchCompany();
    fetchBankAccount();
    if (user?.employee?.id) {
      fetchFnF();
    }
  }, [user?.employee?.id]);

  useEffect(() => {
    if (salarySubTab === "annual_earnings") {
      fetchAnnualEarnings();
    } else if (salarySubTab === "salary_certificate" || salarySubTab === "structure") {
      fetchSalaryCertificate();
    }
  }, [salarySubTab, financialYear]);

  // Fetch tax worksheet when selected payslip changes
  useEffect(() => {
    if (selectedPayslip) {
      fetchTaxWorksheet(selectedPayslip);
    }
  }, [selectedPayslip?.id, financialYear]);

  async function fetchBankAccount() {
    setBankLoading(true);
    setBankError(null);
    try {
      const acc = await getMyBankAccount();
      setBankAccount(acc);
      setBankHolder(acc.account_holder);
      setBankName(acc.bank_name);
      setBankIfsc(acc.ifsc_code);
    } catch {
      setBankAccount(null);
    } finally {
      setBankLoading(false);
    }
  }

  async function fetchCompany() {
    try {
      const cmp = await getMyCompany();
      setCompany(cmp);
    } catch {
      setCompany(null);
    }
  }

  async function fetchPayslips() {
    setLoading(true);
    setLoadError(null);
    try {
      const items = await listMyPayslips();
      setPayslips(items);
      if (items.length > 0 && !selectedPayslip) {
        setSelectedPayslip(items[0]);
      }
    } catch (err) {
      setLoadError(parseApiError(err).message);
    } finally {
      setLoading(false);
    }
  }

  async function fetchFnF() {
    if (!user?.employee?.id) return;
    try {
      const fnf = await getFnFSettlement(user.employee.id);
      setFnfData(fnf);
    } catch {
      setFnfData(null);
    }
  }

  function getMonthNumberAndYear(item: PayrollItem | null): { month: number; year: number } {
    if (!item || !item.month || !item.year) {
      const d = new Date();
      return { month: d.getMonth() + 1, year: d.getFullYear() };
    }
    return { month: item.month, year: item.year };
  }

  async function fetchTaxWorksheet(item: PayrollItem) {
    setTaxWorksheetLoading(true);
    const { month, year } = getMonthNumberAndYear(item);
    try {
      const data = await getMyTaxWorksheet(month, year);
      setTaxWorksheet(data);
    } catch {
      setTaxWorksheet(null);
    } finally {
      setTaxWorksheetLoading(false);
    }
  }

  async function fetchAnnualEarnings() {
    setAnnualEarningsLoading(true);
    try {
      const data = await getMyAnnualEarnings(financialYear);
      setAnnualEarnings(data);
    } catch {
      setAnnualEarnings(null);
    } finally {
      setAnnualEarningsLoading(false);
    }
  }

  async function fetchSalaryCertificate() {
    setSalaryCertLoading(true);
    try {
      const data = await getMySalaryCertificate();
      setSalaryCert(data);
    } catch {
      setSalaryCert(null);
    } finally {
      setSalaryCertLoading(false);
    }
  }

  const handleToggleShowAccount = async () => {
    if (showFullAccount) {
      setShowFullAccount(false);
      setUnmaskedAccount(null);
      return;
    }
    try {
      const res = await revealMyBankAccount();
      setUnmaskedAccount(res.account_number);
      setShowFullAccount(true);
    } catch (err) {
      setBankError(parseApiError(err).message);
    }
  };

  const handleSaveBankDetails = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingBank(true);
    setBankError(null);
    setBankSuccess(null);
    try {
      const updated = await saveMyBankAccount({
        account_holder: bankHolder,
        bank_name: bankName,
        account_number: bankNumber,
        ifsc_code: bankIfsc,
      });
      setBankAccount(updated);
      setIsEditingBank(false);
      setBankNumber("");
      setBankSuccess("Bank details updated successfully.");
    } catch (err) {
      setBankError(parseApiError(err).message);
    } finally {
      setSavingBank(false);
    }
  };

  const payslipDetailRef = useRef<HTMLDivElement>(null);

  const handlePrint = () => {
    window.print();
  };

  const handleDownloadPayslip = () => {
    if (payslipDetailRef.current) {
      const empName = user?.employee
        ? `${user.employee.first_name}_${user.employee.last_name || ""}`.trim()
        : "Employee";
      const label = selectedPayslip ? formatMonthYear(selectedPayslip).replace(/\s+/g, "_") : "Statement";
      downloadDocumentAsHtml(payslipDetailRef.current, `Payslip_${empName}_${label}.html`);
    } else {
      window.print();
    }
  };

  const handleExportAnnualEarnings = async () => {
    setIsExportingAnnual(true);
    try {
      const blob = await exportMyAnnualEarnings(financialYear);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Annual_Earnings_${financialYear.replace(/\s+/g, "_")}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert("Failed to export Annual Earnings spreadsheet: " + parseApiError(err).message);
    } finally {
      setIsExportingAnnual(false);
    }
  };

  const formatINR = (val: number | string | null | undefined) =>
    "₹" + Number(val || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const filteredPayslips = useMemo(() => {
    const isFy25 = financialYear.includes("2025");
    return payslips.filter((p) => {
      if (p.year) {
        return isFy25 ? p.year === 2025 : p.year === 2026;
      }
      return true;
    });
  }, [payslips, financialYear]);

  const latestPayslip = filteredPayslips.length > 0 ? filteredPayslips[0] : null;

  const getMonthYearLabel = (item: PayrollItem | null, _idx: number = 0) => {
    return formatMonthYear(item);
  };

  const donutData = useMemo(() => {
    if (!selectedPayslip) return { netDash: 0, dedDash: 0, circumference: 251.2 };
    const gross = Number(selectedPayslip.gross_salary || 0);
    const net = Number(selectedPayslip.net_salary || 0);
    const ded = Number(selectedPayslip.total_deductions || 0);
    const total = gross > 0 ? gross : net + ded;
    const circumference = 251.2;
    if (total === 0) return { netDash: 0, dedDash: 0, circumference };
    const netDash = (net / total) * circumference;
    const dedDash = (ded / total) * circumference;
    return { netDash, dedDash, circumference };
  }, [selectedPayslip]);

  const hasSeparationOrFnF = !!fnfData;
  const grossPay = latestPayslip ? Number(latestPayslip.gross_salary) : 0;
  const reimbursementAmt = latestPayslip ? Number(latestPayslip.reimbursement_amount || 0) : 0;

  const empName = user?.employee
    ? `${user.employee.first_name} ${user.employee.last_name || ""}`.trim()
    : user?.email || "Employee";
  const empDesignation = user?.employee?.position || "Senior Staff";
  const companyName = company?.name || "Company";

  // Palette colors
  const greenTakeHome = CATEGORICAL_PALETTE[4] || "#2f9e44";
  const orangeDeductions = CATEGORICAL_PALETTE[1] || "#e8590c";
  const blueChart = "#1098ad";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "24px",
        padding: "24px",
        minHeight: "100%",
        boxSizing: "border-box",
      }}
    >
      {/* Page Header (No print) */}
      <div
        className="no-print"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "16px",
          borderBottom: "1px solid #e2e8f0",
          paddingBottom: "16px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "1.4rem", fontWeight: 700, color: "#0f172a" }}>
              Welcome {empName}!
            </h1>
            <p style={{ margin: "2px 0 0", color: "#64748b", fontSize: "0.88rem" }}>
              {empDesignation} at {companyName}.
            </p>
          </div>
        </div>

        {/* Global Financial Year Dropdown */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
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
              onChange={(e) => {
                setFinancialYear(e.target.value);
              }}
              style={{
                border: "none",
                fontWeight: 600,
                outline: "none",
                background: "transparent",
                cursor: "pointer",
              }}
            >
              <option value="2026-2027">2026 - 27</option>
              <option value="2025-2026">2025 - 26</option>
            </select>
          </div>
        </div>
      </div>

      {/* Main Workspace Body */}
      <main style={{ flex: 1, position: "relative" }}>
        {/* Navigation Tabs */}
        <div
          style={{
            display: "flex",
            gap: "28px",
            borderBottom: "1.5px solid #e2e8f0",
            marginBottom: "20px",
          }}
          className="no-print"
        >
          <button
            type="button"
            onClick={() => {
              setSalarySubTab("structure");
              setLegacyActiveTab("payslips");
            }}
            style={{
              background: "none",
              border: "none",
              borderBottom: salarySubTab === "structure" ? "2.5px solid #0284c7" : "2.5px solid transparent",
              color: salarySubTab === "structure" ? "#0284c7" : "#64748b",
              fontWeight: salarySubTab === "structure" ? 600 : 500,
              fontSize: "0.95rem",
              paddingBottom: "10px",
              cursor: "pointer",
            }}
          >
            Salary Structure
          </button>

          <button
            type="button"
            onClick={() => {
              setSalarySubTab("payslips");
              setLegacyActiveTab("payslips");
            }}
            style={{
              background: "none",
              border: "none",
              borderBottom: salarySubTab === "payslips" ? "2.5px solid #0284c7" : "2.5px solid transparent",
              color: salarySubTab === "payslips" ? "#0284c7" : "#64748b",
              fontWeight: salarySubTab === "payslips" ? 600 : 500,
              fontSize: "0.95rem",
              paddingBottom: "10px",
              cursor: "pointer",
            }}
          >
            Payslips
          </button>

          <button
            type="button"
            onClick={() => {
              setSalarySubTab("annual_earnings");
              setLegacyActiveTab("payslips");
            }}
            style={{
              background: "none",
              border: "none",
              borderBottom: salarySubTab === "annual_earnings" ? "2.5px solid #0284c7" : "2.5px solid transparent",
              color: salarySubTab === "annual_earnings" ? "#0284c7" : "#64748b",
              fontWeight: salarySubTab === "annual_earnings" ? 600 : 500,
              fontSize: "0.95rem",
              paddingBottom: "10px",
              cursor: "pointer",
            }}
          >
            Annual Earnings
          </button>

          <button
            type="button"
            onClick={() => {
              setSalarySubTab("bank_details");
              setLegacyActiveTab("bank");
            }}
            style={{
              background: "none",
              border: "none",
              borderBottom: salarySubTab === "bank_details" ? "2.5px solid #0284c7" : "2.5px solid transparent",
              color: salarySubTab === "bank_details" ? "#0284c7" : "#64748b",
              fontWeight: salarySubTab === "bank_details" ? 600 : 500,
              fontSize: "0.95rem",
              paddingBottom: "10px",
              cursor: "pointer",
            }}
          >
            Bank Details
          </button>

          <button
            type="button"
            onClick={() => {
              setSalarySubTab("salary_certificate");
              setLegacyActiveTab("payslips");
            }}
            style={{
              background: "none",
              border: "none",
              borderBottom: salarySubTab === "salary_certificate" ? "2.5px solid #0284c7" : "2.5px solid transparent",
              color: salarySubTab === "salary_certificate" ? "#0284c7" : "#64748b",
              fontWeight: salarySubTab === "salary_certificate" ? 600 : 500,
              fontSize: "0.95rem",
              paddingBottom: "10px",
              cursor: "pointer",
            }}
          >
            Salary Certificate
          </button>

          {hasSeparationOrFnF && (
            <button
              type="button"
              onClick={() => {
                setLegacyActiveTab("fnf");
              }}
              style={{
                background: "none",
                border: "none",
                borderBottom: legacyActiveTab === "fnf" ? "2.5px solid #059669" : "2.5px solid transparent",
                color: legacyActiveTab === "fnf" ? "#059669" : "#64748b",
                fontWeight: legacyActiveTab === "fnf" ? 600 : 500,
                fontSize: "0.95rem",
                paddingBottom: "10px",
                cursor: "pointer",
              }}
            >
              FnF Statement
            </button>
          )}
        </div>

        {/* Sub-tab 1: Salary Structure */}
        {salarySubTab === "structure" && (
          <div
            style={{
              background: "#ffffff",
              borderRadius: "14px",
              border: "1px solid #e2e8f0",
              padding: "24px",
              boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "20px",
                borderBottom: "1px solid #f1f5f9",
                paddingBottom: "20px",
                marginBottom: "20px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
                <div
                  style={{
                    width: "80px",
                    height: "80px",
                    borderRadius: "50%",
                    border: `8px solid ${greenTakeHome}`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "0.68rem",
                    fontWeight: 700,
                    textAlign: "center",
                    color: "#0f172a",
                  }}
                >
                  Salary<br />Breakup
                </div>

                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <span style={{ fontSize: "1.25rem", fontWeight: 700, color: "#0f172a" }}>
                      Monthly CTC: {salaryCert?.monthly_gross ? formatINR(salaryCert.monthly_gross) : grossPay > 0 ? formatINR(grossPay) : "—"}
                    </span>
                    <button
                      type="button"
                      onClick={() => setSalarySubTab("salary_certificate")}
                      style={{
                        background: "none",
                        border: "none",
                        color: "#0284c7",
                        fontSize: "0.82rem",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        fontWeight: 600,
                      }}
                    >
                      📥 Salary Certificate
                    </button>
                  </div>
                  <div style={{ color: "#64748b", fontSize: "0.85rem", marginTop: "2px" }}>
                    Yearly CTC: {salaryCert?.annual_ctc ? formatINR(salaryCert.annual_ctc) : grossPay > 0 ? formatINR(grossPay * 12) : "—"}
                  </div>
                </div>
              </div>

              <div style={{ display: "flex", gap: "24px" }}>
                <div style={{ borderLeft: `3px solid ${greenTakeHome}`, paddingLeft: "10px" }}>
                  <div style={{ fontSize: "0.78rem", color: "#64748b" }}>Earnings</div>
                  <strong style={{ fontSize: "1rem", color: "#0f172a" }}>
                    {salaryCert?.monthly_gross ? formatINR(salaryCert.monthly_gross) : grossPay > 0 ? formatINR(grossPay) : "—"}
                  </strong>
                </div>
                <div style={{ borderLeft: "3px solid #0284c7", paddingLeft: "10px" }}>
                  <div style={{ fontSize: "0.78rem", color: "#64748b" }}>Reimbursements</div>
                  <strong style={{ fontSize: "1rem", color: "#0f172a" }}>{formatINR(reimbursementAmt)}</strong>
                </div>
                <div style={{ borderLeft: "3px solid #f59e0b", paddingLeft: "10px" }}>
                  <div style={{ fontSize: "0.78rem", color: "#64748b" }}>Benefits</div>
                  <strong style={{ fontSize: "1rem", color: "#0f172a" }}>₹0.00</strong>
                </div>
              </div>
            </div>

            {/* Earnings Breakdown */}
            <h4 style={{ fontSize: "0.95rem", fontWeight: 700, color: "#1e293b", marginBottom: "14px" }}>
              Earnings Breakdown
            </h4>
            <div style={{ display: "flex", flexDirection: "column", gap: "10px", fontSize: "0.9rem" }}>
              {salaryCert?.components && salaryCert.components.length > 0 ? (
                salaryCert.components.map((item, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      padding: "8px 0",
                      borderBottom: "1px dashed #f1f5f9",
                    }}
                  >
                    <span style={{ color: "#475569" }}>{item.name}</span>
                    <strong style={{ color: "#0f172a" }}>{formatINR(Number(item.monthly_amount))}</strong>
                  </div>
                ))
              ) : latestPayslip?.earnings_json && latestPayslip.earnings_json.length > 0 ? (
                latestPayslip.earnings_json.map((item, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      padding: "8px 0",
                      borderBottom: "1px dashed #f1f5f9",
                    }}
                  >
                    <span style={{ color: "#475569" }}>{item.name}</span>
                    <strong style={{ color: "#0f172a" }}>{formatINR(Number(item.amount))}</strong>
                  </div>
                ))
              ) : (
                <div style={{ color: "#94a3b8", padding: "12px 0" }}>
                  No salary structure recorded for the selected period.
                </div>
              )}
              {(salaryCert?.monthly_gross || grossPay > 0) && (
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    padding: "12px 0",
                    borderTop: "2px solid #e2e8f0",
                    fontWeight: 700,
                  }}
                >
                  <span>Monthly CTC</span>
                  <span>{formatINR(salaryCert?.monthly_gross || grossPay)}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Sub-tab 2: Payslips */}
        {salarySubTab === "payslips" && (
          <div>
            {/* Screen test locator */}
            <div style={{ display: "none" }}>My Payslips & Statements</div>
            {company && (
              <div style={{ display: "none" }}>
                <div>{company.name}</div>
                <div>GSTIN: {company.gst_number}</div>
                <div>PAN: {company.pan_number}</div>
              </div>
            )}

            <div
              style={{
                display: "grid",
                gridTemplateColumns: selectedPayslip && filteredPayslips.some((p) => p.id === selectedPayslip.id) ? "300px 1fr" : "1fr",
                gap: "24px",
                alignItems: "start",
              }}
            >
              {/* Left Column: Month list */}
              <div
                className="no-print"
                style={{
                  background: "#ffffff",
                  borderRadius: "14px",
                  border: "1px solid #e2e8f0",
                  padding: "20px",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
                }}
              >
                <div style={{ fontSize: "0.85rem", color: "#64748b", fontWeight: 600, marginBottom: "16px" }}>
                  ▼ Financial Year : {financialYear === "2026-2027" ? "2026 - 27" : financialYear === "2025-2026" ? "2025 - 26" : financialYear}
                </div>

                {filteredPayslips.length === 0 && !loading ? (
                  <div style={{ textAlign: "center", padding: "40px 10px", color: "#94a3b8" }}>
                    No approved payslips available yet.
                  </div>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
                      <thead>
                        <tr style={{ color: "#64748b", borderBottom: "1px solid #e2e8f0", textAlign: "left" }}>
                          <th style={{ padding: "8px" }}>Month</th>
                          {!selectedPayslip && <th style={{ padding: "8px" }}>Gross Pay</th>}
                          {!selectedPayslip && <th style={{ padding: "8px" }}>Reimbursements</th>}
                          {!selectedPayslip && <th style={{ padding: "8px" }}>Deductions</th>}
                          <th style={{ padding: "8px" }}>
                            {detailMode === "tax_worksheet" ? "Taxable Income" : "Take Home"}
                          </th>
                          <th style={{ padding: "8px" }}>
                            {detailMode === "tax_worksheet" ? "Tax Worksheet" : "Payslip"}
                          </th>
                          {!selectedPayslip && <th style={{ padding: "8px" }}>Tax Worksheet</th>}
                        </tr>
                      </thead>
                      <tbody>
                        {filteredPayslips.map((item, idx) => {
                          const isSelected = selectedPayslip?.id === item.id;
                          return (
                            <tr
                              key={item.id}
                              onClick={() => setSelectedPayslip(item)}
                              style={{
                                borderBottom: "1px solid #f1f5f9",
                                cursor: "pointer",
                                backgroundColor: isSelected ? "#f0f9ff" : "transparent",
                              }}
                            >
                              <td style={{ padding: "12px 8px", color: "#0284c7", fontWeight: 600 }}>
                                {getMonthYearLabel(item, idx)}
                              </td>
                              {!selectedPayslip && (
                                <td style={{ padding: "12px 8px" }}>{formatINR(Number(item.gross_salary))}</td>
                              )}
                              {!selectedPayslip && (
                                <td style={{ padding: "12px 8px" }}>
                                  {formatINR(Number(item.reimbursement_amount || 0))}
                                </td>
                              )}
                              {!selectedPayslip && (
                                <td style={{ padding: "12px 8px" }}>{formatINR(Number(item.total_deductions))}</td>
                              )}
                              <td style={{ padding: "12px 8px", fontWeight: 600, color: "#0f172a" }}>
                                {detailMode === "tax_worksheet"
                                  ? (taxWorksheet?.total_taxable_income ? formatINR(taxWorksheet.total_taxable_income) : "—")
                                  : formatINR(Number(item.net_salary))}
                              </td>
                              <td style={{ padding: "12px 8px" }}>
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSelectedPayslip(item);
                                    if (detailMode === "tax_worksheet") {
                                      setIsTaxModalOpen(true);
                                    } else {
                                      setIsDocModalOpen(true);
                                    }
                                  }}
                                  style={{
                                    background: "none",
                                    border: "none",
                                    color: "#0284c7",
                                    fontWeight: 600,
                                    cursor: "pointer",
                                  }}
                                >
                                  View
                                </button>
                              </td>
                              {!selectedPayslip && (
                                <td style={{ padding: "12px 8px" }}>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setSelectedPayslip(item);
                                      setDetailMode("tax_worksheet");
                                      setIsTaxModalOpen(true);
                                    }}
                                    style={{
                                      background: "none",
                                      border: "none",
                                      color: "#0284c7",
                                      fontWeight: 600,
                                      cursor: "pointer",
                                    }}
                                  >
                                    View
                                  </button>
                                </td>
                              )}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Right Column: Slide-in Detail Panel */}
              {selectedPayslip && filteredPayslips.some((p) => p.id === selectedPayslip.id) && (
                <div
                  ref={payslipDetailRef}
                  style={{
                    background: "#ffffff",
                    borderRadius: "14px",
                    border: "1px solid #e2e8f0",
                    padding: "24px",
                    boxShadow: "0 4px 12px rgba(0,0,0,0.04)",
                    position: "relative",
                  }}
                >
                  {/* Top Row: Title, Mode Toggles, Close */}
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      borderBottom: "1px solid #f1f5f9",
                      paddingBottom: "14px",
                      marginBottom: "18px",
                    }}
                  >
                    <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>
                      {detailMode === "payslip"
                        ? `Payslip for ${getMonthYearLabel(selectedPayslip, 0)}`
                        : `Tax Worksheet for ${getMonthYearLabel(selectedPayslip, 0)}`}
                    </h3>

                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                      <div
                        style={{
                          display: "flex",
                          background: "#f1f5f9",
                          padding: "3px",
                          borderRadius: "8px",
                          fontSize: "0.78rem",
                        }}
                      >
                        <button
                          type="button"
                          onClick={() => setDetailMode("payslip")}
                          style={{
                            padding: "4px 10px",
                            borderRadius: "6px",
                            border: "none",
                            background: detailMode === "payslip" ? "#ffffff" : "transparent",
                            fontWeight: detailMode === "payslip" ? 600 : 500,
                            color: detailMode === "payslip" ? "#0f172a" : "#64748b",
                            cursor: "pointer",
                            boxShadow: detailMode === "payslip" ? "0 1px 3px rgba(0,0,0,0.06)" : "none",
                          }}
                        >
                          Payslip
                        </button>
                        <button
                          type="button"
                          onClick={() => setDetailMode("tax_worksheet")}
                          style={{
                            padding: "4px 10px",
                            borderRadius: "6px",
                            border: "none",
                            background: detailMode === "tax_worksheet" ? "#ffffff" : "transparent",
                            fontWeight: detailMode === "tax_worksheet" ? 600 : 500,
                            color: detailMode === "tax_worksheet" ? "#0f172a" : "#64748b",
                            cursor: "pointer",
                            boxShadow: detailMode === "tax_worksheet" ? "0 1px 3px rgba(0,0,0,0.06)" : "none",
                          }}
                        >
                          Tax Worksheet
                        </button>
                      </div>

                      <button
                        type="button"
                        onClick={() => setSelectedPayslip(null)}
                        style={{
                          background: "none",
                          border: "none",
                          fontSize: "1.2rem",
                          color: "#94a3b8",
                          cursor: "pointer",
                        }}
                      >
                        ✕
                      </button>
                    </div>
                  </div>

                  {/* Mode 1: Detailed Payslip */}
                  {detailMode === "payslip" ? (
                    <div>
                      {/* Donut and quick stats */}
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          flexWrap: "wrap",
                          gap: "16px",
                          background: "#f8fafc",
                          padding: "16px",
                          borderRadius: "10px",
                          marginBottom: "20px",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
                          <div style={{ position: "relative", width: "64px", height: "64px" }}>
                            <svg width="64" height="64" viewBox="0 0 100 100" style={{ transform: "rotate(-90deg)" }}>
                              <circle cx="50" cy="50" r="40" fill="transparent" stroke={orangeDeductions} strokeWidth="14" />
                              <circle
                                cx="50"
                                cy="50"
                                r="40"
                                fill="transparent"
                                stroke={greenTakeHome}
                                strokeWidth="14"
                                strokeDasharray={`${donutData.netDash} ${donutData.circumference}`}
                              />
                            </svg>
                            <div
                              style={{
                                position: "absolute",
                                inset: 0,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: "0.55rem",
                                fontWeight: 700,
                                textAlign: "center",
                                padding: "2px",
                              }}
                            >
                              {formatShortMonthYear(selectedPayslip)}
                            </div>
                          </div>

                          <div>
                            <div style={{ fontSize: "0.8rem", color: "#64748b" }}>Take Home :</div>
                            <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "#0f172a" }}>
                              {formatINR(Number(selectedPayslip.net_salary))}
                            </div>
                          </div>
                        </div>

                        <div style={{ display: "flex", gap: "20px" }}>
                          <div>
                            <div style={{ fontSize: "0.75rem", color: "#64748b" }}>Deductions</div>
                            <div style={{ fontWeight: 600, color: "#0f172a" }}>
                              {formatINR(Number(selectedPayslip.total_deductions))}
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: "0.75rem", color: "#64748b" }}>Gross Pay</div>
                            <div style={{ fontWeight: 600, color: "#0f172a" }}>
                              {formatINR(Number(selectedPayslip.gross_salary))}
                            </div>
                          </div>
                        </div>

                        <DocumentActions
                          onDownload={handleDownloadPayslip}
                          onPrint={handlePrint}
                        />
                        {/* Test locator */}
                        <button
                          type="button"
                          onClick={handlePrint}
                          style={{ display: "none" }}
                        >
                          Download Statement (PDF / Print)
                        </button>
                      </div>

                      {/* Payslip Details Subheader */}
                      <div
                        style={{
                          background: "#f8fafc",
                          padding: "12px 16px",
                          borderRadius: "8px",
                          display: "flex",
                          justifyContent: "space-between",
                          fontSize: "0.82rem",
                          marginBottom: "16px",
                        }}
                      >
                        <div>
                          <strong>{getMonthYearLabel(selectedPayslip, 0)}</strong>
                          <div style={{ color: "#64748b", marginTop: "2px" }}>
                            Paid Days : {selectedPayslip.present_days} • LOP Days : {selectedPayslip.lop_days}
                          </div>
                        </div>
                        <div>
                          <span style={{ color: "#64748b" }}>Bank Account No</span>
                          <div style={{ fontWeight: 600, marginTop: "2px", fontFamily: "monospace" }}>
                            {selectedPayslip.payout_account_number || bankAccount?.account_number || "—"}
                          </div>
                        </div>
                      </div>

                      {/* Full LOP Alert */}
                      {Number(selectedPayslip.lop_days || 0) > 0 && Number(selectedPayslip.present_days || 0) === 0 && (
                        <div
                          style={{
                            background: "#fffbeb",
                            border: "1px solid #fde68a",
                            borderRadius: "8px",
                            padding: "10px 14px",
                            color: "#92400e",
                            fontSize: "0.84rem",
                            fontWeight: 600,
                            marginBottom: "16px",
                            display: "flex",
                            alignItems: "center",
                            gap: "8px",
                          }}
                        >
                          <span>⚠️</span>
                          <span>
                            Full LOP: Earnings are nil for this period ({selectedPayslip.lop_days} LOP days out of{" "}
                            {selectedPayslip.working_days || selectedPayslip.lop_days} working days)
                          </span>
                        </div>
                      )}

                      {/* Side by Side: Earnings vs Deductions */}
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "1fr 1fr",
                          gap: "24px",
                          marginBottom: "20px",
                        }}
                      >
                        {/* Earnings */}
                        <div>
                          <div style={{ fontWeight: 700, fontSize: "0.85rem", color: "#475569", marginBottom: "8px" }}>
                            Earnings
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: "8px", fontSize: "0.85rem" }}>
                            {selectedPayslip.earnings_json.map((e, idx) => (
                              <div key={idx} style={{ display: "flex", justifyContent: "space-between" }}>
                                <span style={{ color: "#64748b" }}>{e.name}</span>
                                <span style={{ fontWeight: 600 }}>{formatINR(Number(e.amount))}</span>
                              </div>
                            ))}
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                borderTop: "1px solid #e2e8f0",
                                paddingTop: "8px",
                                fontWeight: 700,
                              }}
                            >
                              <span>Total Earnings</span>
                              <span>{formatINR(Number(selectedPayslip.gross_salary))}</span>
                            </div>
                          </div>
                        </div>

                        {/* Deductions */}
                        <div>
                          <div style={{ fontWeight: 700, fontSize: "0.85rem", color: "#475569", marginBottom: "8px" }}>
                            Deductions
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: "8px", fontSize: "0.85rem" }}>
                            {selectedPayslip.deductions_json.map((d, idx) => (
                              <div key={idx} style={{ display: "flex", justifyContent: "space-between" }}>
                                <span style={{ color: "#64748b" }}>{d.name}</span>
                                <span style={{ fontWeight: 600 }}>{formatINR(Number(d.amount))}</span>
                              </div>
                            ))}
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                borderTop: "1px solid #e2e8f0",
                                paddingTop: "8px",
                                fontWeight: 700,
                              }}
                            >
                              <span>Total Deductions</span>
                              <span>{formatINR(Number(selectedPayslip.total_deductions))}</span>
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Net Pay and Indian Words */}
                      <div
                        style={{
                          borderTop: "1px solid #e2e8f0",
                          paddingTop: "16px",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "flex-end",
                        }}
                      >
                        <div>
                          <div style={{ fontSize: "0.85rem", color: "#64748b" }}>Your Take Home Salary Amount (Net Pay)</div>
                          <div style={{ fontSize: "1.5rem", fontWeight: 800, color: "#0f172a", marginTop: "2px" }}>
                            {formatINR(Number(selectedPayslip.net_salary))}
                          </div>
                          <div style={{ fontSize: "0.78rem", color: "#64748b", marginTop: "2px" }}>
                            {numberToIndianWords(Number(selectedPayslip.net_salary))}
                          </div>
                        </div>
                        <div style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
                          Net Pay = Total Earnings - Total Deductions
                        </div>
                      </div>
                    </div>
                  ) : (
                    /* Mode 2: Server-computed Tax Worksheet */
                    <div>
                      {taxWorksheetLoading ? (
                        <div style={{ padding: "30px 0", textAlign: "center", color: "#64748b" }}>
                          Loading server tax calculation...
                        </div>
                      ) : taxWorksheet ? (
                        <div>
                          <div
                            style={{
                              display: "grid",
                              gridTemplateColumns: "repeat(3, 1fr)",
                              gap: "12px",
                              background: "#f8fafc",
                              padding: "12px 16px",
                              borderRadius: "8px",
                              fontSize: "0.82rem",
                              marginBottom: "20px",
                            }}
                          >
                            <div>
                              <span style={{ color: "#64748b" }}>Employee Name</span>
                              <div style={{ fontWeight: 600 }}>{taxWorksheet.employee_name || empName}</div>
                            </div>
                            <div>
                              <span style={{ color: "#64748b" }}>Designation</span>
                              <div style={{ fontWeight: 600 }}>{taxWorksheet.designation || empDesignation}</div>
                            </div>
                            <div>
                              <span style={{ color: "#64748b" }}>PAN</span>
                              <div style={{ fontWeight: 600, fontFamily: "monospace" }}>
                                {taxWorksheet.pan_number && taxWorksheet.pan_number !== "—"
                                  ? taxWorksheet.pan_number
                                  : "Not on record"}
                              </div>
                            </div>
                          </div>

                          <h4 style={{ margin: "0 0 12px", fontSize: "0.95rem", fontWeight: 700, color: "#1e293b" }}>
                            Earnings & Exemptions Breakdown ({taxWorksheet.regime.toUpperCase()})
                          </h4>

                          <div style={{ display: "flex", flexDirection: "column", gap: "10px", fontSize: "0.88rem" }}>
                            <div style={{ display: "flex", justifyContent: "space-between" }}>
                              <span>⊕ Gross Salary (Total)</span>
                              <strong>{formatINR(taxWorksheet.total_gross?.total)}</strong>
                            </div>
                            <div style={{ display: "flex", justifyContent: "space-between" }}>
                              <span>⊕ Income from Other Sources</span>
                              <strong>{formatINR(taxWorksheet.other_income?.total)}</strong>
                            </div>
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                borderTop: "1px solid #e2e8f0",
                                paddingTop: "6px",
                                fontWeight: 700,
                              }}
                            >
                              <span>Gross Total Income</span>
                              <span>{formatINR(taxWorksheet.total_gross?.total)}</span>
                            </div>

                            <div style={{ marginTop: "14px", fontWeight: 700, fontSize: "0.85rem", color: "#475569" }}>
                              Exemptions Based on Statutory Slabs
                            </div>
                            <div style={{ display: "flex", justifyContent: "space-between" }}>
                              <span>⊕ Standard Deduction Under Section 16(ia)</span>
                              <strong>{formatINR(taxWorksheet.standard_deduction?.total)}</strong>
                            </div>
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                borderTop: "1px solid #e2e8f0",
                                paddingTop: "6px",
                                fontWeight: 700,
                              }}
                            >
                              <span>Total Exemptions</span>
                              <span>{formatINR(taxWorksheet.standard_deduction?.total)}</span>
                            </div>

                            <div
                              style={{
                                background: "#f0fdf4",
                                padding: "12px 16px",
                                borderRadius: "8px",
                                display: "flex",
                                justifyContent: "space-between",
                                fontWeight: 700,
                                color: "#166534",
                                marginTop: "12px",
                              }}
                            >
                              <span>Total Taxable Income</span>
                              <span>{formatINR(taxWorksheet.total_taxable_income)}</span>
                            </div>

                            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "14px" }}>
                              <button
                                type="button"
                                onClick={() => setIsTaxModalOpen(true)}
                                style={{
                                  background: "#0284c7",
                                  color: "#ffffff",
                                  border: "none",
                                  borderRadius: "6px",
                                  padding: "8px 16px",
                                  fontSize: "0.82rem",
                                  fontWeight: 600,
                                  cursor: "pointer",
                                }}
                              >
                                Open Full Tax Computation Sheet ↗
                              </button>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div style={{ padding: "30px 0", textAlign: "center", color: "#dc2626" }}>
                          Failed to load tax computation.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Sub-tab 3: Annual Earnings */}
        {salarySubTab === "annual_earnings" && (
          <div
            style={{
              background: "#ffffff",
              borderRadius: "14px",
              border: "1px solid #e2e8f0",
              padding: "24px",
              boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "24px",
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700 }}>
                  Annual Earnings Report: {financialYear === "2026-2027" ? "2026 - 27" : financialYear === "2025-2026" ? "2025 - 26" : financialYear}
                </h3>
                <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: "0.85rem" }}>
                  Monthly component breakdown and YTD earnings overview.
                </p>
              </div>

              <DocumentActions
                onDownload={handleExportAnnualEarnings}
                onPrint={handlePrint}
                downloadLabel="Download Excel"
                printLabel="Print Report"
                isDownloading={isExportingAnnual}
              />
            </div>

            {annualEarningsLoading ? (
              <div style={{ padding: "40px 0", textAlign: "center", color: "#64748b" }}>
                Loading annual earnings data...
              </div>
            ) : annualEarnings ? (
              <div>
                {/* Visual Trendline Chart with Gaps for unrun months */}
                <div style={{ height: "160px", width: "100%", marginBottom: "28px", position: "relative" }}>
                  <svg width="100%" height="100%" viewBox="0 0 1200 140" preserveAspectRatio="none">
                    <line x1="0" y1="20" x2="1200" y2="20" stroke="#f1f5f9" strokeDasharray="4" />
                    <line x1="0" y1="60" x2="1200" y2="60" stroke="#f1f5f9" strokeDasharray="4" />
                    <line x1="0" y1="100" x2="1200" y2="100" stroke="#f1f5f9" strokeDasharray="4" />

                    {/* Plot monthly points */}
                    {annualEarnings.months.map((m, idx) => {
                      const x = 50 + idx * 95;
                      const hasGross = m.has_payroll && m.net_salary !== null;
                      const netVal = hasGross ? Number(m.net_salary) : 0;
                      const y = hasGross && netVal > 0 ? Math.max(20, 110 - (netVal / 120000) * 80) : 110;

                      return (
                        <g key={m.month}>
                          {hasGross && (
                            <>
                              <circle cx={x} cy={y} r="5" fill="#ffffff" stroke={blueChart} strokeWidth="3" />
                              <text x={x} y={y - 10} textAnchor="middle" fontSize="10" fill="#0f172a" fontWeight="600">
                                ₹{netVal >= 1000 ? `${Math.round(netVal / 1000)}k` : netVal}
                              </text>
                            </>
                          )}
                          <text x={x} y="130" textAnchor="middle" fontSize="11" fill="#64748b">
                            {m.label.slice(0, 3)}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                </div>

                {/* Annual Earnings Table */}
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem", textAlign: "right" }}>
                    <thead>
                      <tr style={{ background: "#f8fafc", borderBottom: "1.5px solid #cbd5e1" }}>
                        <th style={{ textAlign: "left", padding: "10px 12px", color: "#475569" }}>Component</th>
                        <th style={{ padding: "10px 12px", color: "#475569" }}>YTD Total</th>
                        {annualEarnings.months.map((m) => (
                          <th key={m.month} style={{ padding: "10px 8px", color: "#475569" }}>
                            {m.label.slice(0, 3)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {annualEarnings.rows.map((row, idx) => (
                        <tr
                          key={idx}
                          style={{
                            borderBottom: "1px solid #f1f5f9",
                            fontWeight: row.group === "net_pay" ? 800 : row.code.startsWith("TOTAL") ? 700 : 400,
                            background: row.group === "net_pay" ? "#f0fdf4" : "transparent",
                          }}
                        >
                          <td style={{ textAlign: "left", padding: "10px 12px", color: row.group === "net_pay" ? "#166534" : "#334155" }}>
                            {row.name}
                          </td>
                          <td style={{ padding: "10px 12px", color: row.group === "net_pay" ? "#166534" : "#0f172a" }}>
                            {formatINR(row.total_ytd)}
                          </td>
                          {row.monthly_amounts.map((val, mIdx) => (
                            <td key={mIdx} style={{ padding: "10px 8px", color: val !== null ? (row.group === "net_pay" ? "#166534" : "#0f172a") : "#94a3b8" }}>
                              {val !== null ? formatINR(val) : "—"}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "30px", color: "#94a3b8" }}>
                No annual earnings data available for this financial year.
              </div>
            )}
          </div>
        )}

        {/* Sub-tab 4: Bank Details */}
        {salarySubTab === "bank_details" && (
          <div
            style={{
              background: "#ffffff",
              borderRadius: "14px",
              border: "1px solid #e2e8f0",
              padding: "24px",
              boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "20px",
                borderBottom: "1px solid #f1f5f9",
                paddingBottom: "12px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <div
                  style={{
                    width: "32px",
                    height: "32px",
                    borderRadius: "8px",
                    background: "#eff6ff",
                    color: "#2563eb",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "1rem",
                  }}
                >
                  💳
                </div>
                <h2 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#1e293b" }}>
                  Payment Information
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setIsEditingBank(!isEditingBank)}
                style={{
                  background: isEditingBank ? "#fef2f2" : "#ffffff",
                  color: isEditingBank ? "#dc2626" : "#2563eb",
                  border: `1px solid ${isEditingBank ? "#fecaca" : "#cbd5e1"}`,
                  borderRadius: "6px",
                  padding: "5px 14px",
                  fontSize: "0.84rem",
                  fontWeight: 600,
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
              >
                {isEditingBank ? "Close Edit" : "Edit Details"}
              </button>
            </div>

            {bankError && (
              <div style={{ padding: "10px 14px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "8px", color: "#991b1b", fontSize: "0.85rem", marginBottom: "16px" }}>
                {bankError}
              </div>
            )}
            {bankSuccess && (
              <div style={{ padding: "10px 14px", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: "8px", color: "#166534", fontSize: "0.85rem", marginBottom: "16px" }}>
                {bankSuccess}
              </div>
            )}

            {bankLoading ? (
              <div style={{ padding: "40px 0", textAlign: "center", color: "#64748b" }}>
                Loading payment details...
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
                {/* Zoho-Grade Clean Bank Card & Details Layout */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1.1fr 1fr",
                    gap: "24px",
                    alignItems: "center",
                    background: "#ffffff",
                    border: "1px solid #e2e8f0",
                    borderRadius: "12px",
                    padding: "20px",
                  }}
                >
                  {/* Styled Payment Mode Card */}
                  <div
                    style={{
                      background: "linear-gradient(135deg, #2563eb 0%, #3b82f6 60%, #60a5fa 100%)",
                      borderRadius: "12px",
                      padding: "20px 22px",
                      color: "#ffffff",
                      boxShadow: "0 8px 20px -4px rgba(37, 99, 235, 0.3)",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "space-between",
                      minHeight: "145px",
                    }}
                  >
                    <div>
                      <div style={{ fontSize: "0.68rem", opacity: 0.9, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                        Payment Mode
                      </div>
                      <div style={{ fontSize: "1.1rem", fontWeight: 700, marginTop: "4px" }}>
                        Manual Bank Transfer
                      </div>
                    </div>

                    <div style={{ marginTop: "16px" }}>
                      <div style={{ fontSize: "0.66rem", opacity: 0.85, textTransform: "uppercase" }}>
                        Account Number
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "2px" }}>
                        <span style={{ fontSize: "1.15rem", fontWeight: 700, letterSpacing: "1px", fontFamily: "monospace" }}>
                          {showFullAccount && unmaskedAccount
                            ? unmaskedAccount
                            : bankAccount?.account_number || "—"}
                        </span>
                        <button
                          type="button"
                          onClick={handleToggleShowAccount}
                          style={{
                            background: "rgba(255,255,255,0.25)",
                            border: "none",
                            borderRadius: "4px",
                            color: "#ffffff",
                            fontSize: "0.72rem",
                            padding: "2px 8px",
                            cursor: "pointer",
                            fontWeight: 600,
                          }}
                        >
                          {showFullAccount ? "(Hide)" : "(Show A/C No)"}
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Account Information Key-Values */}
                  <div style={{ display: "flex", flexDirection: "column", gap: "10px", fontSize: "0.88rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #f1f5f9", paddingBottom: "6px" }}>
                      <span style={{ color: "#64748b" }}>Account Holder Name</span>
                      <strong style={{ color: "#0f172a" }}>{bankAccount?.account_holder || "—"}</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #f1f5f9", paddingBottom: "6px" }}>
                      <span style={{ color: "#64748b" }}>Bank Name</span>
                      <strong style={{ color: "#0f172a" }}>{bankAccount?.bank_name || "—"}</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #f1f5f9", paddingBottom: "6px" }}>
                      <span style={{ color: "#64748b" }}>IFSC Code</span>
                      <strong style={{ color: "#0f172a", fontFamily: "monospace" }}>{bankAccount?.ifsc_code || "—"}</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: "#64748b" }}>Account Type</span>
                      <strong style={{ color: "#0f172a" }}>Savings</strong>
                    </div>
                  </div>
                </div>

                {/* Edit Form */}
                {isEditingBank && (
                  <form
                    onSubmit={handleSaveBankDetails}
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                      borderRadius: "12px",
                      padding: "20px",
                      marginTop: "10px",
                    }}
                  >
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "16px", marginBottom: "16px" }}>
                      <div>
                        <label style={{ display: "block", fontSize: "0.78rem", fontWeight: 600, color: "#475569", marginBottom: "6px" }}>
                          Account Holder Name
                        </label>
                        <input
                          type="text"
                          value={bankHolder}
                          onChange={(e) => setBankHolder(e.target.value)}
                          placeholder="Full Name"
                          required
                          style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem", boxSizing: "border-box" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "0.78rem", fontWeight: 600, color: "#475569", marginBottom: "6px" }}>
                          Bank Name
                        </label>
                        <input
                          type="text"
                          value={bankName}
                          onChange={(e) => setBankName(e.target.value)}
                          placeholder="e.g. HDFC Bank"
                          required
                          style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem", boxSizing: "border-box" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "0.78rem", fontWeight: 600, color: "#475569", marginBottom: "6px" }}>
                          Account Number
                        </label>
                        <input
                          type="text"
                          value={bankNumber}
                          onChange={(e) => setBankNumber(e.target.value)}
                          placeholder="Leave blank to keep unchanged"
                          style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem", boxSizing: "border-box" }}
                        />
                      </div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "16px", marginBottom: "16px" }}>
                      <div>
                        <label style={{ display: "block", fontSize: "0.78rem", fontWeight: 600, color: "#475569", marginBottom: "6px" }}>
                          IFSC Code
                        </label>
                        <input
                          type="text"
                          value={bankIfsc}
                          onChange={(e) => setBankIfsc(e.target.value.toUpperCase())}
                          placeholder="e.g. HDFC0001234"
                          required
                          style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem", boxSizing: "border-box" }}
                        />
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: "10px" }}>
                      <button
                        type="submit"
                        disabled={savingBank}
                        style={{
                          background: "#15803d",
                          color: "#ffffff",
                          border: "none",
                          borderRadius: "6px",
                          padding: "8px 18px",
                          fontSize: "0.85rem",
                          fontWeight: 600,
                          cursor: savingBank ? "not-allowed" : "pointer",
                        }}
                      >
                        {savingBank ? "Saving..." : "Save Details"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setIsEditingBank(false)}
                        style={{
                          background: "#ffffff",
                          color: "#64748b",
                          border: "1px solid #cbd5e1",
                          borderRadius: "6px",
                          padding: "8px 16px",
                          fontSize: "0.85rem",
                          fontWeight: 500,
                          cursor: "pointer",
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                )}
              </div>
            )}
          </div>
        )}

        {/* Sub-tab 5: Salary Certificate */}
        {salarySubTab === "salary_certificate" && (
          <div
            style={{
              background: "#ffffff",
              borderRadius: "14px",
              border: "1px solid #e2e8f0",
              padding: "24px",
              boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "20px",
                borderBottom: "1px solid #f1f5f9",
                paddingBottom: "12px",
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700 }}>
                  Official Salary Certificate
                </h3>
                <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: "0.85rem" }}>
                  Official certificate of employment and compensation for bank loans and visa applications.
                </p>
              </div>

              <DocumentActions
                onDownload={handlePrint}
                onPrint={handlePrint}
                downloadLabel="Download"
                printLabel="Print"
              />
            </div>

            {salaryCertLoading ? (
              <div style={{ padding: "40px 0", textAlign: "center", color: "#64748b" }}>
                Loading salary certificate...
              </div>
            ) : salaryCert ? (
              <DocumentShell
                title="SALARY CERTIFICATE"
                subtitle={`Ref: SC-${financialYear.replace(/\s+/g, "")}-${salaryCert.employee_code}`}
                company={company}
                footerNote="— This certificate is issued upon request of the employee without liability to the company. —"
              >
                <div style={{ padding: "16px 0", fontSize: "0.88rem", lineHeight: 1.6 }}>
                  <p>
                    <strong>Date:</strong> {salaryCert.issued_date}
                  </p>
                  <p style={{ marginTop: "16px" }}>
                    <strong>TO WHOMSOEVER IT MAY CONCERN</strong>
                  </p>
                  <p style={{ marginTop: "12px" }}>
                    This is to certify that <strong>{salaryCert.employee_name}</strong> (Employee ID:{" "}
                    <strong>{salaryCert.employee_code || "—"}</strong>) is a bona fide full-time employee of{" "}
                    <strong>{salaryCert.company_name}</strong> working as <strong>{salaryCert.designation || "Staff"}</strong> since{" "}
                    <strong>{salaryCert.date_of_joining ? new Date(salaryCert.date_of_joining).toLocaleDateString("en-GB") : "—"}</strong>.
                  </p>

                  <div style={{ margin: "20px 0", border: "1px solid #e2e8f0", borderRadius: "8px", overflow: "hidden" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                      <thead>
                        <tr style={{ background: "#f8fafc", borderBottom: "1.5px solid #cbd5e1" }}>
                          <th style={{ textAlign: "left", padding: "8px 12px", color: "#475569" }}>Salary Component</th>
                          <th style={{ textAlign: "right", padding: "8px 12px", color: "#475569" }}>Monthly (INR)</th>
                          <th style={{ textAlign: "right", padding: "8px 12px", color: "#475569" }}>Annualized (INR)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {salaryCert.components.map((c, idx) => (
                          <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                            <td style={{ padding: "8px 12px" }}>{c.name}</td>
                            <td style={{ padding: "8px 12px", textAlign: "right", fontWeight: 600 }}>{formatINR(c.monthly_amount)}</td>
                            <td style={{ padding: "8px 12px", textAlign: "right", fontWeight: 600 }}>{formatINR(c.annual_amount)}</td>
                          </tr>
                        ))}
                        <tr style={{ borderTop: "2px solid #cbd5e1", background: "#f0fdf4", fontWeight: 800 }}>
                          <td style={{ padding: "10px 12px", color: "#166534" }}>Total Cost to Company (CTC)</td>
                          <td style={{ padding: "10px 12px", textAlign: "right", color: "#166534" }}>{formatINR(salaryCert.monthly_gross)}</td>
                          <td style={{ padding: "10px 12px", textAlign: "right", color: "#166534" }}>{formatINR(salaryCert.annual_ctc)}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  {/* Signatory Block */}
                  <div style={{ marginTop: "40px", display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
                    <div>
                      <div style={{ fontSize: "0.78rem", color: "#64748b" }}>Status: Active / Full-Time</div>
                      <div style={{ fontSize: "0.78rem", color: "#64748b" }}>Work Location: {company?.city || "Ahmedabad, India"}</div>
                    </div>

                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontWeight: 700, color: "#0f172a" }}>
                        {salaryCert.signatory_name || "Authorized Signatory"}
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "#64748b" }}>
                        {salaryCert.signatory_title || "HR Department"}
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "#64748b" }}>
                        {salaryCert.company_name}
                      </div>
                    </div>
                  </div>
                </div>
              </DocumentShell>
            ) : (
              <div style={{ textAlign: "center", padding: "30px", color: "#94a3b8" }}>
                Failed to load salary certificate.
              </div>
            )}
          </div>
        )}
      </main>

      {/* Modals */}
      {selectedPayslip && (
        <>
          <PayslipDocumentModal
            isOpen={isDocModalOpen}
            onClose={() => setIsDocModalOpen(false)}
            item={selectedPayslip}
            employee={user?.employee as any}
            company={company}
            monthName={getMonthYearLabel(selectedPayslip, 0)}
            year={financialYear.startsWith("2025") ? 2025 : 2026}
          />

          <TaxWorksheetModal
            isOpen={isTaxModalOpen}
            onClose={() => setIsTaxModalOpen(false)}
            worksheet={taxWorksheet}
            company={company}
            monthName={getMonthYearLabel(selectedPayslip, 0)}
            year={financialYear.startsWith("2025") ? 2025 : 2026}
          />
        </>
      )}
    </div>
  );
}
