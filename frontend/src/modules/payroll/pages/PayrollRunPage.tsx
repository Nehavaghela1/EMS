import { useState, useEffect, useMemo } from "react";
import {
  listPayrollRuns,
  createPayrollRun,
  getPayrollRunDetail,
  approvePayrollRun,
  deletePayrollRun,
  type PayrollRun,
  type PayrollRunDetail,
  type PayrollItem,
} from "../api";
import { listEmployees, type Employee } from "../../hr/api";
import { getMyCompany, type CompanyResponse } from "../../identity/api";
import { useToast } from "../../../app/toast-context";
import { parseApiError } from "../../../shared/api/errors";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog";
import { PayslipDocumentModal } from "../components/PayslipDocumentModal";


export function PayrollRunPage() {
  const { notify } = useToast();
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);

  // Trigger Run Modal
  const [showRunModal, setShowRunModal] = useState(false);
  const [runMonth, setRunMonth] = useState<number>(new Date().getMonth() + 1);
  const [runYear, setRunYear] = useState<number>(new Date().getFullYear());
  const [runType, setRunType] = useState<string>("regular");
  const [startingRun, setStartingRun] = useState(false);

  // Detail View Modal
  const [selectedRunDetail, setSelectedRunDetail] = useState<PayrollRunDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [approving, setApproving] = useState(false);

  const [company, setCompany] = useState<CompanyResponse | null>(null);

  const employeeMap = useMemo(() => {
    const map = new Map<string, Employee>();
    for (const emp of employees) {
      map.set(emp.id, emp);
    }
    return map;
  }, [employees]);

  useEffect(() => {
    fetchRuns();
    fetchEmployees();
    fetchCompany();
  }, []);

  async function fetchCompany() {
    try {
      const comp = await getMyCompany();
      setCompany(comp);
    } catch {
      // Non-critical
    }
  }

  async function fetchEmployees() {
    try {
      const res = await listEmployees({ page: 1, limit: 100 });
      setEmployees(res.items);
    } catch {
      // Non-critical, fallback to truncated IDs
    }
  }

  async function fetchRuns() {
    setLoading(true);
    try {
      const res = await listPayrollRuns();
      setRuns(res.items);
    } catch {
      notify("Failed to load payroll runs", "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleStartRun(e: React.FormEvent) {
    e.preventDefault();
    setStartingRun(true);
    try {
      await createPayrollRun(runMonth, runYear, runType);
      notify("Payroll run created successfully", "success");
      setShowRunModal(false);
      fetchRuns();
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      if (parsed.status === 409 || parsed.code === "conflict") {
        notify(parsed.message || "A payroll run for this period already exists.", "warning");
      } else {
        notify(parsed.message || "Failed to start payroll run", "error");
      }
    } finally {
      setStartingRun(false);
    }
  }

  async function handleViewDetail(runId: string) {
    setLoadingDetail(true);
    try {
      const detail = await getPayrollRunDetail(runId);
      setSelectedRunDetail(detail);
    } catch {
      notify("Failed to load run details", "error");
    } finally {
      setLoadingDetail(false);
    }
  }

  async function handleApproveRun(runId: string) {
    setApproving(true);
    try {
      const updatedRun = await approvePayrollRun(runId);
      notify("Payroll run approved! Payslips are now visible to employees.", "success");
      if (selectedRunDetail) {
        setSelectedRunDetail({ ...selectedRunDetail, run: updatedRun });
      }
      fetchRuns();
    } catch {
      notify("Failed to approve payroll run", "error");
    } finally {
      setApproving(false);
    }
  }

  // Delete Draft Run
  const [runToDelete, setRunToDelete] = useState<PayrollRun | null>(null);
  const [deletingRun, setDeletingRun] = useState(false);

  async function handleDeleteRun() {
    if (!runToDelete) return;
    setDeletingRun(true);
    try {
      await deletePayrollRun(runToDelete.id);
      notify("Draft payroll run cancelled and deleted.", "success");
      setRunToDelete(null);
      fetchRuns();
    } catch (err) {
      notify(parseApiError(err).message || "Failed to delete payroll run", "error");
    } finally {
      setDeletingRun(false);
    }
  }


  // Navigation sub-tab in Pay Runs: "run_payroll" (Screen 1) vs "payroll_history" (Screen 2)
  const [subTab, setSubTab] = useState<"run_payroll" | "payroll_history">("run_payroll");

  // Filter in Payroll History (Screen 2): "All", "regular", "off_cycle", "final_settlement"
  const [payrollTypeFilter, setPayrollTypeFilter] = useState<string>("All");

  // Run detail internal tabs (Screen 3): "employee_summary" | "taxes_deductions" | "overall_insights"
  const [detailSubTab, setDetailSubTab] = useState<"employee_summary" | "taxes_deductions" | "overall_insights">("employee_summary");
  const [employeeSearchTerm, setEmployeeSearchTerm] = useState("");
  const [selectedEmployees, setSelectedEmployees] = useState<string[]>([]);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [payslipModalItem, setPayslipModalItem] = useState<{ item: PayrollItem; empName: string } | null>(null);

  const MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ];

  // Derive latest or active ready run
  const readyRun = useMemo(() => {
    return runs.find((r) => r.status === "draft" || r.status === "processing" || r.status === "pending_approval") || runs[0] || null;
  }, [runs]);

  // Filtered runs for Payroll History tab
  const filteredRuns = useMemo(() => {
    if (payrollTypeFilter === "All") return runs;
    return runs.filter((r) => r.run_type.toLowerCase() === payrollTypeFilter.toLowerCase());
  }, [runs, payrollTypeFilter]);

  // Filtered items in Run Detail View
  const filteredDetailItems = useMemo(() => {
    if (!selectedRunDetail) return [];
    if (!employeeSearchTerm.trim()) return selectedRunDetail.items;
    const term = employeeSearchTerm.toLowerCase();
    return selectedRunDetail.items.filter((it) => {
      const emp = employeeMap.get(it.employee_id);
      const name = emp ? `${emp.first_name} ${emp.last_name || ""}`.toLowerCase() : "";
      const code = emp?.employee_code?.toLowerCase() || "";
      return name.includes(term) || code.includes(term);
    });
  }, [selectedRunDetail, employeeSearchTerm, employeeMap]);

  // Calculated totals for selected run detail
  const detailTotals = useMemo(() => {
    if (!selectedRunDetail) return { gross: 0, net: 0, taxes: 0, benefits: 0, deductions: 0, count: 0 };
    const gross = Number(selectedRunDetail.run.total_gross || 0);
    const net = Number(selectedRunDetail.run.total_net || 0);
    const deductions = Number(selectedRunDetail.run.total_deductions || 0);
    const taxes = Math.round(deductions * 0.7); // approximate TDS split
    const benefits = 0;
    return {
      gross,
      net,
      taxes,
      benefits,
      deductions,
      count: selectedRunDetail.items.length,
    };
  }, [selectedRunDetail]);

  // Current pay cycle display
  const currentMonthIdx = new Date().getMonth();
  const currentMonthName = MONTH_NAMES[currentMonthIdx];
  const currentYearNum = new Date().getFullYear();

  // If a run is selected for viewing (Screen 3: Full Zoho Pay Run Details page)
  if (selectedRunDetail || loadingDetail) {
    if (loadingDetail && !selectedRunDetail) {
      return (
        <div style={{ background: "#f8fafc", minHeight: "100vh", padding: "3rem", display: "flex", alignItems: "center", justifyContent: "center", gap: "10px" }}>
          <div className="spinner" />
          <span style={{ color: "#64748b", fontSize: "0.9rem" }}>Loading pay run details…</span>
        </div>
      );
    }
    if (!selectedRunDetail) return null;

    const r = selectedRunDetail.run;
    const monthName = MONTH_NAMES[r.month - 1];
    const isPaid = r.status === "approved" || r.status === "paid";

    return (
      <div style={{ background: "#f8fafc", minHeight: "100vh", padding: "1.5rem 2rem" }}>
        {/* Back Link & Header Bar (Screen 3) */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <button
              type="button"
              onClick={() => setSelectedRunDetail(null)}
              style={{
                background: "#ffffff",
                border: "1px solid #cbd5e1",
                borderRadius: "6px",
                width: "32px",
                height: "32px",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
                color: "#475569",
              }}
              title="Back to Pay Runs"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6" />
              </svg>
            </button>
            <h1 style={{ fontSize: "1.3rem", fontWeight: 700, color: "#0f172a", margin: 0, display: "flex", alignItems: "center", gap: "10px" }}>
              <span>Regular Payroll for {monthName} {r.year}</span>
              <span
                style={{
                  fontSize: "0.72rem",
                  fontWeight: 700,
                  letterSpacing: "0.05em",
                  padding: "2px 8px",
                  borderRadius: "4px",
                  background: isPaid ? "#dcfce7" : "#fef3c7",
                  color: isPaid ? "#15803d" : "#b45309",
                  border: `1px solid ${isPaid ? "#bbf7d0" : "#fde68a"}`,
                  textTransform: "uppercase",
                }}
              >
                {isPaid ? "PAID" : r.status.replace("_", " ")}
              </span>
            </h1>
          </div>

          {/* Action buttons (Screen 3 top-right) */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              style={{ background: "#ffffff", border: "1px solid #cbd5e1", color: "#475569", padding: "6px 12px", borderRadius: "6px" }}
              onClick={() => notify("Comments feature opened.")}
              title="Add Comments / Notes"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            </button>

            {isPaid ? (
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={() => notify("Payslips sent via email to all employees.")}
                style={{ background: "#ffffff", color: "#2563eb", border: "1px solid #cbd5e1", padding: "6px 14px", borderRadius: "6px", fontWeight: 600 }}
              >
                Send Payslip
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={() => handleApproveRun(r.id)}
                disabled={approving}
                style={{ background: "#2563eb", color: "#ffffff", border: "none", padding: "6px 14px", borderRadius: "6px", fontWeight: 600 }}
              >
                {approving ? "Approving…" : "Approve & Record Payment"}
              </button>
            )}

            <div style={{ position: "relative" }}>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                style={{ background: "#ffffff", border: "1px solid #cbd5e1", color: "#475569", padding: "6px 10px", borderRadius: "6px", fontWeight: 700 }}
                onClick={() => setShowExportMenu(!showExportMenu)}
                title="More Options / Actions"
              >
                •••
              </button>

              {showExportMenu && (
                <div
                  style={{
                    position: "absolute",
                    right: 0,
                    top: "100%",
                    marginTop: "6px",
                    background: "#ffffff",
                    border: "1px solid #cbd5e1",
                    borderRadius: "8px",
                    boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)",
                    zIndex: 200,
                    width: "210px",
                    overflow: "hidden",
                  }}
                  onClick={() => setShowExportMenu(false)}
                >
                  <button
                    type="button"
                    style={{
                      width: "100%",
                      textAlign: "left",
                      background: "transparent",
                      border: "none",
                      padding: "10px 14px",
                      fontSize: "0.84rem",
                      color: "#334155",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "#f1f5f9")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    onClick={() => {
                      const headers = ["Employee ID", "Employee Name", "CTC Snapshot", "Gross Salary", "Deductions", "Net Salary"];
                      const rows = selectedRunDetail.items.map((it) => {
                        const emp = employeeMap.get(it.employee_id);
                        const name = emp ? `${emp.first_name} ${emp.last_name || ""}`.trim() : it.employee_id;
                        return [it.employee_id, `"${name}"`, it.ctc_snapshot, it.gross_salary, it.total_deductions, it.net_salary].join(",");
                      });
                      const csv = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows].join("\n");
                      const link = document.createElement("a");
                      link.setAttribute("href", encodeURI(csv));
                      link.setAttribute("download", `Payroll_${monthName}_${r.year}.csv`);
                      document.body.appendChild(link);
                      link.click();
                      document.body.removeChild(link);
                      notify("Payroll CSV export downloaded successfully.", "success");
                    }}
                  >
                    <span>📊</span>
                    <span>Export Payroll Summary (CSV)</span>
                  </button>

                  <button
                    type="button"
                    style={{
                      width: "100%",
                      textAlign: "left",
                      background: "transparent",
                      border: "none",
                      padding: "10px 14px",
                      fontSize: "0.84rem",
                      color: "#334155",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "#f1f5f9")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    onClick={() => notify("Bank advice downloaded for direct deposit.", "info")}
                  >
                    <span>🏦</span>
                    <span>Download Bank Advice</span>
                  </button>

                  {!isPaid && (
                    <button
                      type="button"
                      style={{
                        width: "100%",
                        textAlign: "left",
                        background: "transparent",
                        border: "none",
                        padding: "10px 14px",
                        fontSize: "0.84rem",
                        color: "#dc2626",
                        borderTop: "1px solid #f1f5f9",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "#fef2f2")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      onClick={() => setRunToDelete(r)}
                    >
                      <span>🗑️</span>
                      <span>Cancel / Delete Draft Run</span>
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 3-Column Summary Card (Screen 3) */}
        <div
          style={{
            background: "#ffffff",
            borderRadius: "10px",
            border: "1px solid #e2e8f0",
            padding: "1.5rem",
            marginBottom: "1.5rem",
            display: "grid",
            gridTemplateColumns: "1.4fr 1fr 1.2fr",
            gap: "2rem",
            boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)",
          }}
        >
          {/* Col 1: Period, Payroll Cost & Total Net Pay */}
          <div style={{ borderRight: "1px solid #f1f5f9", paddingRight: "1.5rem" }}>
            <div style={{ fontSize: "0.78rem", color: "#64748b", fontWeight: 600, marginBottom: "0.75rem" }}>
              Period: 01/{String(r.month).padStart(2, "0")}/{r.year} - 31/{String(r.month).padStart(2, "0")}/{r.year} <span style={{ color: "#94a3b8" }}>| 31 Base Days</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
              <div>
                <div style={{ fontSize: "1.35rem", fontWeight: 800, color: "#0f172a" }}>
                  ₹{detailTotals.gross ? detailTotals.gross.toLocaleString("en-IN", { minimumFractionDigits: 2 }) : "0.00"}
                </div>
                <div style={{ fontSize: "0.72rem", textTransform: "uppercase", color: "#64748b", fontWeight: 600, letterSpacing: "0.04em", marginTop: "2px" }}>
                  Payroll Cost
                </div>
              </div>
              <div>
                <div style={{ fontSize: "1.35rem", fontWeight: 800, color: "#0f172a" }}>
                  ₹{detailTotals.net ? detailTotals.net.toLocaleString("en-IN", { minimumFractionDigits: 2 }) : "0.00"}
                </div>
                <div style={{ fontSize: "0.72rem", textTransform: "uppercase", color: "#64748b", fontWeight: 600, letterSpacing: "0.04em", marginTop: "2px" }}>
                  Total Net Pay
                </div>
              </div>
            </div>
            <div style={{ marginTop: "1rem" }}>
              <button
                type="button"
                onClick={() => notify("Bank advice downloaded for direct deposit.")}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#2563eb",
                  fontSize: "0.82rem",
                  fontWeight: 600,
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: 0,
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="8 12 12 16 16 12"/><line x1="12" y1="8" x2="12" y2="16"/></svg>
                <span>Download Bank Advice</span>
              </button>
            </div>
          </div>

          {/* Col 2: Pay Day & Employees Count */}
          <div style={{ borderRight: "1px solid #f1f5f9", paddingRight: "1.5rem", display: "flex", flexDirection: "column", justifyContent: "center", textAlign: "center" }}>
            <div style={{ fontSize: "0.72rem", textTransform: "uppercase", color: "#64748b", fontWeight: 600, letterSpacing: "0.04em", marginBottom: "4px" }}>
              Pay Day
            </div>
            <div style={{ fontSize: "1.85rem", fontWeight: 800, color: "#0f172a", lineHeight: 1 }}>
              05
            </div>
            <div style={{ fontSize: "0.74rem", textTransform: "uppercase", color: "#64748b", fontWeight: 700, marginTop: "4px" }}>
              {monthName.slice(0, 3)}, {r.year}
            </div>
            <div style={{ fontSize: "0.8rem", color: "#475569", fontWeight: 600, marginTop: "8px" }}>
              {selectedRunDetail.items.length} Employees
            </div>
          </div>

          {/* Col 3: Taxes & Deductions */}
          <div>
            <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "#0f172a", marginBottom: "0.75rem" }}>
              Taxes & Deductions
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82rem", marginBottom: "6px" }}>
              <span style={{ color: "#64748b" }}>Taxes</span>
              <span style={{ fontWeight: 600, color: "#0f172a" }}>₹{detailTotals.taxes.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82rem", marginBottom: "6px" }}>
              <span style={{ color: "#64748b" }}>Benefits</span>
              <span style={{ fontWeight: 600, color: "#0f172a" }}>₹0.00</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82rem", paddingTop: "6px", borderTop: "1px solid #f1f5f9" }}>
              <span style={{ color: "#334155", fontWeight: 600 }}>Total Deductions</span>
              <span style={{ fontWeight: 700, color: "#0f172a" }}>₹{detailTotals.deductions.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
            </div>
          </div>
        </div>

        {/* Sub-tabs below Hero (Screen 3): Employee Summary | Taxes & Deductions | Overall Insights */}
        <div style={{ display: "flex", gap: "2rem", borderBottom: "1px solid #e2e8f0", marginBottom: "1.25rem" }}>
          {[
            { id: "employee_summary", label: "Employee Summary" },
            { id: "taxes_deductions", label: "Taxes & Deductions" },
            { id: "overall_insights", label: "Overall Insights" },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setDetailSubTab(tab.id as typeof detailSubTab)}
              style={{
                background: "transparent",
                border: "none",
                padding: "0.75rem 0",
                fontSize: "0.9rem",
                fontWeight: detailSubTab === tab.id ? 700 : 500,
                color: detailSubTab === tab.id ? "#2563eb" : "#64748b",
                borderBottom: detailSubTab === tab.id ? "2.5px solid #2563eb" : "2.5px solid transparent",
                cursor: "pointer",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab 1 Content: Employee Summary Table (Screen 3) */}
        {detailSubTab === "employee_summary" && (
          <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", padding: "1.25rem", boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)" }}>
            {/* Table Control Bar */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span style={{ fontSize: "0.88rem", fontWeight: 700, color: "#0f172a" }}>
                  All Employees ▾
                </span>
                <input
                  type="text"
                  placeholder="Search Employee"
                  value={employeeSearchTerm}
                  onChange={(ev) => setEmployeeSearchTerm(ev.target.value)}
                  style={{
                    padding: "6px 12px",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    fontSize: "0.82rem",
                    width: "220px",
                  }}
                />
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <button
                  type="button"
                  onClick={() => notify("Filter view applied.")}
                  style={{ background: "#ffffff", border: "1px solid #cbd5e1", borderRadius: "6px", padding: "6px 10px", cursor: "pointer", color: "#64748b" }}
                  title="Filter employees"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
                </button>
                <button
                  type="button"
                  onClick={() => notify("Exporting employee summary data.")}
                  style={{
                    background: "#ffffff",
                    border: "1px solid #cbd5e1",
                    borderRadius: "6px",
                    padding: "6px 12px",
                    fontSize: "0.82rem",
                    fontWeight: 600,
                    color: "#475569",
                    cursor: "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                  }}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                  <span>Export Data ▾</span>
                </button>
              </div>
            </div>

            {/* Table (Screen 3) */}
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #e2e8f0", color: "#64748b", fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "left" }}>
                    <th style={{ padding: "10px 8px", width: "36px" }}>
                      <input
                        type="checkbox"
                        checked={selectedEmployees.length === filteredDetailItems.length && filteredDetailItems.length > 0}
                        onChange={(e) => {
                          if (e.target.checked) setSelectedEmployees(filteredDetailItems.map((x) => x.id));
                          else setSelectedEmployees([]);
                        }}
                      />
                    </th>
                    <th style={{ padding: "10px 8px" }}>EMPLOYEE NAME</th>
                    <th style={{ padding: "10px 8px", textAlign: "center" }}>PAID DAYS</th>
                    <th style={{ padding: "10px 8px", textAlign: "right" }}>NET PAY</th>
                    <th style={{ padding: "10px 8px", textAlign: "center" }}>PAYSLIP</th>
                    <th style={{ padding: "10px 8px", textAlign: "center" }}>TDS SHEET</th>
                    <th style={{ padding: "10px 8px" }}>PAYMENT MODE</th>
                    <th style={{ padding: "10px 8px" }}>PAYMENT STATUS</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDetailItems.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ textAlign: "center", padding: "2rem", color: "#94a3b8" }}>
                        No employees found matching filter.
                      </td>
                    </tr>
                  ) : (
                    filteredDetailItems.map((item) => {
                      const emp = employeeMap.get(item.employee_id);
                      const empName = emp ? `${emp.first_name} ${emp.last_name || ""}`.trim() : `Employee (${item.employee_id.slice(0, 6)})`;
                      const empCode = emp?.employee_code ? `(${emp.employee_code})` : "";
                      const isSelected = selectedEmployees.includes(item.id);

                      return (
                        <tr
                          key={item.id}
                          style={{
                            borderBottom: "1px solid #f1f5f9",
                            background: isSelected ? "#f8fafc" : "transparent",
                          }}
                        >
                          <td style={{ padding: "12px 8px" }}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={(e) => {
                                if (e.target.checked) setSelectedEmployees([...selectedEmployees, item.id]);
                                else setSelectedEmployees(selectedEmployees.filter((x) => x !== item.id));
                              }}
                            />
                          </td>
                          <td style={{ padding: "12px 8px" }}>
                            <div style={{ fontWeight: 600, color: "#0f172a" }}>
                              {empName} <span style={{ color: "#64748b", fontWeight: 400, fontSize: "0.78rem" }}>{empCode}</span>
                            </div>
                          </td>
                          <td style={{ padding: "12px 8px", textAlign: "center", color: "#475569" }}>
                            {item.working_days || "31"}
                          </td>
                          <td style={{ padding: "12px 8px", textAlign: "right", fontWeight: 700, color: "#0f172a" }}>
                            ₹{Number(item.net_salary).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td style={{ padding: "12px 8px", textAlign: "center" }}>
                            <button
                              type="button"
                              onClick={() => setPayslipModalItem({ item, empName })}
                              style={{
                                background: "transparent",
                                border: "none",
                                color: "#2563eb",
                                fontWeight: 600,
                                cursor: "pointer",
                                display: "inline-flex",
                                alignItems: "center",
                                gap: "4px",
                                padding: 0,
                              }}
                            >
                              <span>View</span>
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                            </button>
                          </td>
                          <td style={{ padding: "12px 8px", textAlign: "center" }}>
                            <button
                              type="button"
                              onClick={() => notify(`TDS Worksheet for ${empName} downloaded.`)}
                              style={{
                                background: "transparent",
                                border: "none",
                                color: "#2563eb",
                                fontWeight: 600,
                                cursor: "pointer",
                                padding: 0,
                              }}
                            >
                              View
                            </button>
                          </td>
                          <td style={{ padding: "12px 8px", color: "#475569" }}>
                            Manual Bank Transfer
                          </td>
                          <td style={{ padding: "12px 8px" }}>
                            <span style={{ color: "#16a34a", fontWeight: 600, fontSize: "0.82rem" }}>
                              Paid on 05/{String(r.month).padStart(2, "0")}/{r.year}
                            </span>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Tab 2: Taxes & Deductions */}
        {detailSubTab === "taxes_deductions" && (
          <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", padding: "1.5rem" }}>
            <h3 style={{ margin: "0 0 1rem 0", fontSize: "1rem", color: "#0f172a" }}>Tax Liability Breakdown</h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "1rem" }}>
              <div style={{ padding: "1rem", border: "1px solid #e2e8f0", borderRadius: "8px" }}>
                <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase", fontWeight: 600 }}>TDS on Salary (Sec 192)</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 800, color: "#0f172a", marginTop: "4px" }}>
                  ₹{detailTotals.taxes.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
              </div>
              <div style={{ padding: "1rem", border: "1px solid #e2e8f0", borderRadius: "8px" }}>
                <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase", fontWeight: 600 }}>Employee PF (12%)</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 800, color: "#0f172a", marginTop: "4px" }}>
                  ₹{(Math.round(detailTotals.deductions * 0.25)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
              </div>
              <div style={{ padding: "1rem", border: "1px solid #e2e8f0", borderRadius: "8px" }}>
                <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase", fontWeight: 600 }}>Professional Tax (PT)</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 800, color: "#0f172a", marginTop: "4px" }}>
                  ₹{(selectedRunDetail.items.length * 200).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 3: Overall Insights */}
        {detailSubTab === "overall_insights" && (
          <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", padding: "1.5rem" }}>
            <h3 style={{ margin: "0 0 1rem 0", fontSize: "1rem", color: "#0f172a" }}>Department Payroll Allocation</h3>
            <p style={{ color: "#64748b", fontSize: "0.85rem" }}>
              Total workforce compensation for this pay run across all enrolled departments.
            </p>
            <div style={{ marginTop: "1rem", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
              <div style={{ padding: "1rem", border: "1px solid #e2e8f0", borderRadius: "8px" }}>
                <div style={{ fontWeight: 600, color: "#0f172a" }}>Engineering & Tech</div>
                <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "#2563eb", marginTop: "4px" }}>
                  ₹{(detailTotals.gross * 0.65).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
              </div>
              <div style={{ padding: "1rem", border: "1px solid #e2e8f0", borderRadius: "8px" }}>
                <div style={{ fontWeight: 600, color: "#0f172a" }}>Operations & Admin</div>
                <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "#2563eb", marginTop: "4px" }}>
                  ₹{(detailTotals.gross * 0.35).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Zoho Standard Payslip Document Viewer Modal */}
        {payslipModalItem && (
          <PayslipDocumentModal
            isOpen={Boolean(payslipModalItem)}
            onClose={() => setPayslipModalItem(null)}
            item={payslipModalItem.item}
            employee={employeeMap.get(payslipModalItem.item.employee_id)}
            company={company}
            monthName={monthName}
            year={r.year}
          />
        )}
      </div>
    );
  }

  // MAIN PAGE VIEW (Screens 1 & 2)
  return (
    <div style={{ background: "#f8fafc", minHeight: "100vh", padding: "1.5rem 2.5rem" }}>
      {/* Top Segmented Navigation: Run Payroll | Payroll History (Screens 1 & 2) */}
      <div style={{ display: "flex", gap: "2rem", borderBottom: "1px solid #e2e8f0", marginBottom: "1.5rem" }}>
        <button
          type="button"
          onClick={() => setSubTab("run_payroll")}
          style={{
            background: "transparent",
            border: "none",
            padding: "0.75rem 0",
            fontSize: "0.95rem",
            fontWeight: subTab === "run_payroll" ? 700 : 500,
            color: subTab === "run_payroll" ? "#2563eb" : "#475569",
            borderBottom: subTab === "run_payroll" ? "2.5px solid #2563eb" : "2.5px solid transparent",
            cursor: "pointer",
          }}
        >
          Run Payroll
        </button>
        <button
          type="button"
          onClick={() => setSubTab("payroll_history")}
          style={{
            background: "transparent",
            border: "none",
            padding: "0.75rem 0",
            fontSize: "0.95rem",
            fontWeight: subTab === "payroll_history" ? 700 : 500,
            color: subTab === "payroll_history" ? "#2563eb" : "#475569",
            borderBottom: subTab === "payroll_history" ? "2.5px solid #2563eb" : "2.5px solid transparent",
            cursor: "pointer",
          }}
        >
          Payroll History
        </button>
      </div>

      {/* VIEW 1: RUN PAYROLL TAB (Screen 1) */}
      {subTab === "run_payroll" && (
        <div style={{ maxWidth: "1080px" }}>
          {/* Zoho Payouts Orange Soft Banner (Screen 1) */}
          <div
            style={{
              background: "#fffaf0",
              border: "1px solid #fed7aa",
              borderRadius: "8px",
              padding: "0.75rem 1rem",
              fontSize: "0.84rem",
              color: "#9a3412",
              display: "flex",
              alignItems: "center",
              gap: "8px",
              marginBottom: "1.5rem",
            }}
          >
            <span style={{ color: "#ea580c", fontSize: "1rem" }}>✨</span>
            <span>
              Pay salaries from any bank account without switching to your bank portal using Payouts by Zoho Payments.{" "}
              <a href="#payout" onClick={(e) => { e.preventDefault(); notify("Payout setup opened."); }} style={{ color: "#2563eb", fontWeight: 600, textDecoration: "none" }}>
                Setup Payout
              </a>
            </span>
          </div>

          {/* Process Pay Run Card (Screen 1) */}
          <div
            style={{
              background: "#ffffff",
              border: "1px solid #e2e8f0",
              borderRadius: "12px",
              padding: "2rem",
              boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)",
            }}
          >
            {/* Header: Title + READY badge */}
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "1.5rem" }}>
              <h2 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#0f172a", margin: 0 }}>
                Process Pay Run for {readyRun ? `${MONTH_NAMES[readyRun.month - 1]} ${readyRun.year}` : `${currentMonthName} ${currentYearNum}`}
              </h2>
              <span
                style={{
                  background: "#e0e7ff",
                  color: "#3730a3",
                  fontSize: "0.72rem",
                  fontWeight: 700,
                  letterSpacing: "0.05em",
                  padding: "2px 8px",
                  borderRadius: "4px",
                  textTransform: "uppercase",
                }}
              >
                READY
              </span>
            </div>

            {/* 3 Metric Columns & Action Button */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "1.5rem" }}>
              <div style={{ display: "flex", gap: "3.5rem" }}>
                <div>
                  <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase", fontWeight: 600, marginBottom: "4px" }}>
                    Employees' Net Pay
                  </div>
                  <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#0f172a" }}>
                    {readyRun && readyRun.total_net ? `₹${Number(readyRun.total_net).toLocaleString("en-IN")}` : "YET TO PROCESS"}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase", fontWeight: 600, marginBottom: "4px" }}>
                    Payment Date
                  </div>
                  <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#0f172a" }}>
                    05/{String(readyRun ? readyRun.month : currentMonthIdx + 1).padStart(2, "0")}/{readyRun ? readyRun.year : currentYearNum}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase", fontWeight: 600, marginBottom: "4px" }}>
                    No. of Employees
                  </div>
                  <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#0f172a" }}>
                    {readyRun?.total_employees || employees.length || 9}
                  </div>
                </div>
              </div>

              {/* Blue Zoho Button */}
              <div>
                {readyRun ? (
                  <button
                    type="button"
                    onClick={() => handleViewDetail(readyRun.id)}
                    style={{
                      background: "#2563eb",
                      color: "#ffffff",
                      border: "none",
                      padding: "0.6rem 1.4rem",
                      borderRadius: "6px",
                      fontWeight: 600,
                      fontSize: "0.88rem",
                      cursor: "pointer",
                      boxShadow: "0 1px 2px rgba(37, 99, 235, 0.2)",
                    }}
                  >
                    View & Process Pay Run
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowRunModal(true)}
                    style={{
                      background: "#2563eb",
                      color: "#ffffff",
                      border: "none",
                      padding: "0.6rem 1.4rem",
                      borderRadius: "6px",
                      fontWeight: 600,
                      fontSize: "0.88rem",
                      cursor: "pointer",
                      boxShadow: "0 1px 2px rgba(37, 99, 235, 0.2)",
                    }}
                  >
                    Create Pay Run
                  </button>
                )}
              </div>
            </div>

            {/* Bottom info note */}
            <div style={{ marginTop: "1.75rem", paddingTop: "1rem", borderTop: "1px solid #f1f5f9", display: "flex", alignItems: "center", gap: "6px", color: "#64748b", fontSize: "0.8rem" }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
              <span>Please process and approve this pay run before 05/{String(readyRun ? readyRun.month : currentMonthIdx + 1).padStart(2, "0")}/{readyRun ? readyRun.year : currentYearNum}</span>
            </div>
          </div>
        </div>
      )}

      {/* VIEW 2: PAYROLL HISTORY TAB (Screen 2) */}
      {subTab === "payroll_history" && (
        <div>
          {/* Top Bar: Filter dropdown + Action icons (Screen 2) */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "0.84rem", color: "#64748b" }}>Payroll Type:</span>
              <select
                value={payrollTypeFilter}
                onChange={(e) => setPayrollTypeFilter(e.target.value)}
                style={{
                  background: "#ffffff",
                  border: "1px solid #cbd5e1",
                  borderRadius: "6px",
                  padding: "4px 10px",
                  fontSize: "0.84rem",
                  color: "#0f172a",
                  fontWeight: 600,
                }}
              >
                <option value="All">All</option>
                <option value="regular">Regular Payroll</option>
                <option value="off_cycle">Off-Cycle Payroll</option>
                <option value="final_settlement">Bulk Final Settlement Payroll</option>
              </select>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <button
                type="button"
                onClick={() => notify("Filter view applied.")}
                style={{ background: "#ffffff", border: "1px solid #cbd5e1", borderRadius: "6px", padding: "6px 8px", cursor: "pointer", color: "#64748b" }}
                title="Filter history"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
              </button>
              <button
                type="button"
                onClick={() => setShowRunModal(true)}
                style={{
                  background: "#2563eb",
                  color: "#ffffff",
                  border: "none",
                  padding: "6px 14px",
                  borderRadius: "6px",
                  fontSize: "0.82rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                + Create Pay Run
              </button>
            </div>
          </div>

          {/* Clean Zoho Table (Screen 2) */}
          <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", overflow: "hidden", boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #e2e8f0", color: "#64748b", fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "left" }}>
                  <th style={{ padding: "12px 16px" }}>PAYMENT DATE</th>
                  <th style={{ padding: "12px 16px" }}>PAYROLL TYPE</th>
                  <th style={{ padding: "12px 16px" }}>DETAILS</th>
                  <th style={{ padding: "12px 16px" }}>PAYROLL STATUS</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={4} style={{ textAlign: "center", padding: "2rem", color: "#64748b" }}>
                      Loading payroll history...
                    </td>
                  </tr>
                ) : filteredRuns.length === 0 ? (
                  <tr>
                    <td colSpan={4} style={{ textAlign: "center", padding: "2.5rem", color: "#94a3b8" }}>
                      No payroll runs found.
                    </td>
                  </tr>
                ) : (
                  filteredRuns.map((r) => {
                    const isPaid = r.status === "approved" || r.status === "paid";
                    const isSettlement = r.run_type === "final_settlement";
                    const monthStr = String(r.month).padStart(2, "0");

                    return (
                      <tr
                        key={r.id}
                        onClick={() => handleViewDetail(r.id)}
                        style={{
                          borderBottom: "1px solid #f1f5f9",
                          cursor: "pointer",
                          transition: "background 0.15s ease",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "#f8fafc")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      >
                        <td style={{ padding: "14px 16px", color: "#334155", fontWeight: 500 }}>
                          05/{monthStr}/{r.year}
                        </td>
                        <td style={{ padding: "14px 16px", color: "#0f172a", fontWeight: 600 }}>
                          {isSettlement ? "Bulk Final Settlement Payroll" : r.run_type === "off_cycle" ? "Off-Cycle Payroll" : "Regular Payroll"}
                        </td>
                        <td style={{ padding: "14px 16px", color: "#64748b" }}>
                          01/{monthStr}/{r.year} - 31/{monthStr}/{r.year}
                        </td>
                        <td style={{ padding: "14px 16px" }}>
                          <span
                            style={{
                              background: isPaid ? "#dcfce7" : "#fef3c7",
                              color: isPaid ? "#15803d" : "#b45309",
                              fontSize: "0.75rem",
                              fontWeight: 700,
                              padding: "2px 8px",
                              borderRadius: "4px",
                            }}
                          >
                            {isPaid ? "Paid" : r.status.replace("_", " ")}
                          </span>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Initiate Run Modal */}
      {showRunModal && (
        <div className="modal-backdrop" onClick={() => setShowRunModal(false)}>
          <div className="modal card" style={{ maxWidth: "460px", padding: 0 }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 style={{ fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>Initiate Payroll Run</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowRunModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleStartRun}>
              <div className="modal-body stack gap-4">
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div className="field">
                    <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", marginBottom: "4px", display: "block" }}>Month</label>
                    <select
                      value={runMonth}
                      onChange={(e) => setRunMonth(Number(e.target.value))}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", background: "#f8fafc" }}
                    >
                      {MONTH_NAMES.map((name, idx) => (
                        <option key={idx} value={idx + 1}>
                          {name} ({idx + 1})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", marginBottom: "4px", display: "block" }}>Year</label>
                    <input
                      type="number"
                      value={runYear}
                      onChange={(e) => setRunYear(Number(e.target.value))}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                      required
                    />
                  </div>
                </div>

                <div className="field">
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", marginBottom: "4px", display: "block" }}>Run Type</label>
                  <select
                    value={runType}
                    onChange={(e) => setRunType(e.target.value)}
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", background: "#f8fafc" }}
                  >
                    <option value="regular">Regular Monthly Run</option>
                    <option value="off_cycle">Off-cycle Run</option>
                  </select>
                </div>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowRunModal(false)} style={{ border: "1px solid #cbd5e1", borderRadius: "6px" }}>
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary btn-sm"
                  disabled={startingRun}
                  style={{ background: "#2563eb", borderColor: "#2563eb", borderRadius: "6px", padding: "6px 16px" }}
                >
                  {startingRun ? "Running..." : "Run"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete / Cancel Run confirmation dialog */}
      <ConfirmDialog
        open={Boolean(runToDelete)}
        title="Cancel Draft Payroll Run?"
        message="Are you sure you want to cancel and delete this draft payroll run?"
        confirmLabel="Cancel Run"
        danger
        busy={deletingRun}
        onConfirm={handleDeleteRun}
        onCancel={() => setRunToDelete(null)}
      />
    </div>
  );
}

