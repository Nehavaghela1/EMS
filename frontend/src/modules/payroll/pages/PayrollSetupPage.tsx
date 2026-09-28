import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import {
  listStructures,
  createStructure,
  assignEmployeeSalary,
  getStatutoryConfig,
  updateStatutoryConfig,
  listPtSlabs,
  listTaxSlabs,
  type SalaryStructureListItem,
  type SalaryComponentInput,
  type StatutoryConfig,
  type PtSlab,
  type TaxSlab,
} from "../api";
import { listEmployees, type Employee } from "../../hr/api";
import { useToast } from "../../../app/toast-context";
import { parseApiError } from "../../../shared/api/errors";

const SUPPORTED_COUNTRIES = [
  { code: "IN", name: "India" },
  { code: "US", name: "United States" },
  { code: "AU", name: "Australia" },
  { code: "GB", name: "United Kingdom" },
];

const SUPPORTED_LEVELS = [
  { code: "ALL", label: "All Levels" },
  { code: "L1", label: "L1 — Junior / Entry Level" },
  { code: "L2", label: "L2 — Mid Level" },
  { code: "L3", label: "L3 — Lead / Senior / Executive" },
];

export function PayrollSetupPage() {
  const { notify } = useToast();
  const [searchParams] = useSearchParams();
  const initialTab = (searchParams.get("tab") as "structures" | "statutory" | "pt_slabs" | "tax_slabs") || "structures";
  const [activeTab, setActiveTab] = useState<"structures" | "statutory" | "pt_slabs" | "tax_slabs">(initialTab);

  useEffect(() => {
    const tabParam = searchParams.get("tab") as any;
    if (tabParam && ["structures", "statutory", "pt_slabs", "tax_slabs"].includes(tabParam)) {
      setActiveTab(tabParam);
    }
  }, [searchParams]);

  // Structures state
  const [structures, setStructures] = useState<SalaryStructureListItem[]>([]);
  const [loadingStructures, setLoadingStructures] = useState(true);
  const [showStructureModal, setShowStructureModal] = useState(false);

  // Form for New Structure
  const [structName, setStructName] = useState("");
  const [structCountry, setStructCountry] = useState("IN");
  const [structLevel, setStructLevel] = useState("L1");
  const [components, setComponents] = useState<SalaryComponentInput[]>([
    {
      code: "BASIC",
      name: "Basic Pay",
      type: "earning",
      calculation_type: "percentage",
      value: "50.00",
      percentage_of: "ctc",
      is_taxable: true,
      is_statutory: true,
      display_order: 1,
    },
    {
      code: "HRA",
      name: "House Rent Allowance",
      type: "earning",
      calculation_type: "percentage",
      value: "50.00",
      percentage_of: "basic",
      is_taxable: true,
      is_statutory: false,
      display_order: 2,
    },
    {
      code: "SPECIAL",
      name: "Special Allowance",
      type: "earning",
      calculation_type: "balance",
      is_taxable: true,
      is_statutory: false,
      display_order: 3,
    },
  ]);

  // Salary Assignment Modal state
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [selectedEmpId, setSelectedEmpId] = useState("");
  const [selectedStructId, setSelectedStructId] = useState("");
  const [assignCtc, setAssignCtc] = useState("600000.00");
  const [assignEffectiveFrom, setAssignEffectiveFrom] = useState(
    new Date().toISOString().split("T")[0]
  );
  const [assigning, setAssigning] = useState(false);

  // Statutory state
  const [statConfig, setStatConfig] = useState<StatutoryConfig | null>(null);
  const [loadingStat, setLoadingStat] = useState(false);
  const [savingStat, setSavingStat] = useState(false);

  // Slabs state
  const [ptSlabs, setPtSlabs] = useState<PtSlab[]>([]);
  const [taxSlabs, setTaxSlabs] = useState<TaxSlab[]>([]);

  useEffect(() => {
    fetchStructures();
    fetchEmployees();
  }, []);

  useEffect(() => {
    if (activeTab === "statutory") {
      fetchStatutoryConfig();
    } else if (activeTab === "pt_slabs") {
      listPtSlabs("Gujarat").then(setPtSlabs);
    } else if (activeTab === "tax_slabs") {
      listTaxSlabs("IN", "2026-2027", "new").then(setTaxSlabs);
    }
  }, [activeTab]);

  async function fetchStructures() {
    setLoadingStructures(true);
    try {
      const res = await listStructures();
      setStructures(res.items);
    } catch {
      notify("Failed to load salary structures", "error");
    } finally {
      setLoadingStructures(false);
    }
  }

  async function fetchEmployees() {
    try {
      const res = await listEmployees({ page: 1, limit: 100 });
      setEmployees(res.items);
    } catch {
      // ignore
    }
  }

  async function fetchStatutoryConfig() {
    setLoadingStat(true);
    try {
      const data = await getStatutoryConfig();
      setStatConfig(data);
    } catch {
      notify("Failed to load statutory settings", "error");
    } finally {
      setLoadingStat(false);
    }
  }

  async function handleCreateStructure(e: React.FormEvent) {
    e.preventDefault();
    if (!structName.trim()) {
      notify("Please enter structure name", "error");
      return;
    }

    // Validate total percentage-based CTC allocation (direct + derived from Basic)
    const basicComp = components.find((c) => c.code === "BASIC");
    const basicVal = basicComp && basicComp.calculation_type === "percentage" && basicComp.percentage_of === "ctc"
      ? Number(basicComp.value) || 0
      : 0;

    let directCtcPercent = 0;
    let basicDerivedCtcPercent = 0;
    for (const c of components) {
      if (c.calculation_type === "percentage") {
        if (c.percentage_of === "ctc") {
          directCtcPercent += Number(c.value) || 0;
        } else if (c.percentage_of === "basic") {
          basicDerivedCtcPercent += ((Number(c.value) || 0) * basicVal) / 100;
        }
      }
    }
    const hasBalance = components.some((c) => c.calculation_type === "balance");
    const totalAllocated = directCtcPercent + basicDerivedCtcPercent;
    
    if (hasBalance) {
      if (totalAllocated > 100) {
        notify(`Total percentage allocation is ${totalAllocated.toFixed(1)}% of CTC, which exceeds 100%. Please adjust percentages.`, "error");
        return;
      }
    } else {
      // Custom structure without an auto-balance component must sum to exactly 100%
      if (Math.abs(totalAllocated - 100) > 0.05) {
        notify(`Total percentage allocation is ${totalAllocated.toFixed(1)}% of CTC. It must equal exactly 100.0% (or include a Special Allowance 'Balance of CTC' component).`, "error");
        return;
      }
    }

    try {
      await createStructure({
        name: structName,
        country: structCountry,
        level: structLevel,
        components,
      });
      notify("Salary structure created successfully", "success");
      setShowStructureModal(false);
      setStructName("");
      fetchStructures();
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to create structure", parsed.status === 409 ? "warning" : "error");
    }
  }

  async function handleAssignSalary(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedEmpId || !selectedStructId) {
      notify("Please select employee and structure", "error");
      return;
    }
    setAssigning(true);
    try {
      await assignEmployeeSalary(selectedEmpId, {
        structure_id: selectedStructId,
        ctc: assignCtc,
        effective_from: assignEffectiveFrom,
      });
      notify("Salary assigned successfully", "success");
      setShowAssignModal(false);
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to assign salary", parsed.status === 409 ? "warning" : "error");
    } finally {
      setAssigning(false);
    }
  }

  async function handleSaveStatutory(e: React.FormEvent) {
    e.preventDefault();
    if (!statConfig) return;
    setSavingStat(true);
    try {
      const updated = await updateStatutoryConfig(statConfig);
      setStatConfig(updated);
      notify("Statutory configuration updated successfully", "success");
    } catch {
      notify("Failed to update statutory configuration", "error");
    } finally {
      setSavingStat(false);
    }
  }

  function addComponentLine() {
    setComponents([
      ...components,
      {
        code: `COMP_${components.length + 1}`,
        name: "Allowance",
        type: "earning",
        calculation_type: "fixed",
        value: "1000.00",
        is_taxable: true,
        is_statutory: false,
        display_order: components.length + 1,
      },
    ]);
  }

  function removeComponentLine(index: number) {
    setComponents(components.filter((_, i) => i !== index));
  }

  // Dedicated Full-Page View for Creating / Editing Salary Structure (Zoho Payroll standard)
  if (showStructureModal) {
    const basicComp = components.find((c) => c.code === "BASIC");
    const basicVal = basicComp && basicComp.calculation_type === "percentage" && basicComp.percentage_of === "ctc"
      ? Number(basicComp.value) || 0
      : 0;

    let directCtcPercent = 0;
    let basicDerivedCtcPercent = 0;
    let hasBalance = false;

    for (const c of components) {
      if (c.calculation_type === "percentage") {
        if (c.percentage_of === "ctc") {
          directCtcPercent += Number(c.value) || 0;
        } else if (c.percentage_of === "basic") {
          const derived = ((Number(c.value) || 0) * basicVal) / 100;
          basicDerivedCtcPercent += derived;
        }
      } else if (c.calculation_type === "balance") {
        hasBalance = true;
      }
    }

    const totalAllocated = directCtcPercent + basicDerivedCtcPercent;
    const balanceRemaining = Math.max(0, 100 - totalAllocated);

    return (
      <div style={{ background: "#f8fafc", minHeight: "100vh", padding: "1.75rem 2.5rem" }}>
        {/* Top Breadcrumb & Header Bar */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button
              type="button"
              onClick={() => setShowStructureModal(false)}
              style={{
                background: "#ffffff",
                border: "1px solid #cbd5e1",
                borderRadius: "6px",
                width: "34px",
                height: "34px",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
                color: "#475569",
              }}
              title="Return to Payroll Setup"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6" />
              </svg>
            </button>
            <div>
              <h1 style={{ fontSize: "1.35rem", fontWeight: 700, color: "#0f172a", margin: 0 }}>
                Create Salary Structure
              </h1>
              <p style={{ margin: "2px 0 0", fontSize: "0.82rem", color: "#64748b" }}>
                Define annual CTC allocation, earnings, deductions, and statutory compliance components.
              </p>
            </div>
          </div>

          <div style={{ display: "flex", gap: "10px" }}>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setShowStructureModal(false)}
              style={{ border: "1px solid #cbd5e1", borderRadius: "6px", padding: "7px 16px", background: "#ffffff" }}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleCreateStructure}
              style={{ background: "#2563eb", borderColor: "#2563eb", borderRadius: "6px", padding: "7px 22px", fontWeight: 600 }}
            >
              Save Salary Structure
            </button>
          </div>
        </div>

        {/* 2-Column Structured Layout (Form on Left / Allocation Visualizer on Right) */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: "2rem", alignItems: "start", maxWidth: "1280px" }}>
          {/* Left Column: Form Details & Components */}
          <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
            {/* Basic Info Card */}
            <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", padding: "1.75rem", boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)" }}>
              <h3 style={{ margin: "0 0 1.25rem 0", fontSize: "1rem", fontWeight: 700, color: "#0f172a", borderBottom: "1px solid #f1f5f9", paddingBottom: "10px" }}>
                Basic Information
              </h3>
              <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "1rem" }}>
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "6px" }}>
                    Structure Name <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Standard Full-time India Structure"
                    value={structName}
                    onChange={(e) => setStructName(e.target.value)}
                    style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", width: "100%" }}
                    required
                  />
                </div>
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "6px" }}>
                    Country <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <select
                    value={structCountry}
                    onChange={(e) => setStructCountry(e.target.value)}
                    style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", width: "100%", background: "#f8fafc" }}
                  >
                    {SUPPORTED_COUNTRIES.map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.name} ({c.code})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "6px" }}>
                    Level (Band) <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <select
                    value={structLevel}
                    onChange={(e) => setStructLevel(e.target.value)}
                    style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", width: "100%", background: "#f8fafc" }}
                  >
                    {SUPPORTED_LEVELS.map((lvl) => (
                      <option key={lvl.code} value={lvl.code}>
                        {lvl.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {/* Components Breakdown Card */}
            <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", padding: "1.75rem", boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem", borderBottom: "1px solid #f1f5f9", paddingBottom: "10px" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>
                    Components Breakdown
                  </h3>
                  <p style={{ margin: "2px 0 0", fontSize: "0.78rem", color: "#64748b" }}>
                    Assign percentage or fixed values to calculate monthly salary breakdown from CTC.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={addComponentLine}
                  style={{
                    background: "#eff6ff",
                    color: "#2563eb",
                    border: "1px solid #bfdbfe",
                    borderRadius: "6px",
                    padding: "6px 14px",
                    fontSize: "0.82rem",
                    fontWeight: 600,
                    cursor: "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                  }}
                >
                  <span>+</span> Add Custom Allowance
                </button>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                {components.map((comp, idx) => (
                  <div
                    key={idx}
                    style={{
                      border: "1px solid #e2e8f0",
                      borderRadius: "8px",
                      padding: "1rem 1.25rem",
                      background: idx < 3 ? "#ffffff" : "#fafafa",
                      transition: "all 0.15s ease",
                    }}
                  >
                    <div style={{ display: "grid", gridTemplateColumns: "100px 1.5fr 1.2fr auto", gap: "12px", alignItems: "center" }}>
                      <div>
                        <label style={{ fontSize: "0.72rem", textTransform: "uppercase", fontWeight: 700, color: "#64748b", display: "block", marginBottom: "4px" }}>
                          Code
                        </label>
                        <input
                          type="text"
                          value={comp.code}
                          disabled={idx < 3}
                          onChange={(e) => {
                            const updated = [...components];
                            updated[idx].code = e.target.value.toUpperCase();
                            setComponents(updated);
                          }}
                          style={{
                            padding: "6px 10px",
                            borderRadius: "6px",
                            border: "1px solid #cbd5e1",
                            fontSize: "0.82rem",
                            background: idx < 3 ? "#f1f5f9" : "#ffffff",
                            fontWeight: 600,
                            fontFamily: "monospace",
                            width: "100%",
                          }}
                        />
                      </div>

                      <div>
                        <label style={{ fontSize: "0.72rem", textTransform: "uppercase", fontWeight: 700, color: "#64748b", display: "block", marginBottom: "4px" }}>
                          Component Name
                        </label>
                        <input
                          type="text"
                          value={comp.name}
                          onChange={(e) => {
                            const updated = [...components];
                            updated[idx].name = e.target.value;
                            setComponents(updated);
                          }}
                          style={{
                            padding: "6px 10px",
                            borderRadius: "6px",
                            border: "1px solid #cbd5e1",
                            fontSize: "0.84rem",
                            fontWeight: 600,
                            width: "100%",
                          }}
                        />
                      </div>

                      <div>
                        <label style={{ fontSize: "0.72rem", textTransform: "uppercase", fontWeight: 700, color: "#64748b", display: "block", marginBottom: "4px" }}>
                          Calculation Method
                        </label>
                        <select
                          value={comp.calculation_type}
                          onChange={(e) => {
                            const updated = [...components];
                            const newType = e.target.value as any;
                            updated[idx].calculation_type = newType;
                            if (newType === "balance") {
                              updated[idx].value = null;
                              updated[idx].percentage_of = null;
                            } else if (newType === "percentage") {
                              updated[idx].value = updated[idx].value || "50.00";
                              updated[idx].percentage_of = updated[idx].percentage_of || "ctc";
                            } else {
                              updated[idx].value = updated[idx].value || "1000.00";
                              updated[idx].percentage_of = null;
                            }
                            setComponents(updated);
                          }}
                          style={{
                            padding: "6px 10px",
                            borderRadius: "6px",
                            border: "1px solid #cbd5e1",
                            fontSize: "0.84rem",
                            width: "100%",
                            background: "#ffffff",
                          }}
                        >
                          <option value="percentage">% Percentage</option>
                          <option value="fixed">Fixed Rupee (₹)</option>
                          <option value="balance">Balance of CTC</option>
                        </select>
                      </div>

                      {idx > 2 ? (
                        <div style={{ paddingTop: "18px" }}>
                          <button
                            type="button"
                            onClick={() => removeComponentLine(idx)}
                            style={{
                              background: "#fee2e2",
                              color: "#dc2626",
                              border: "1px solid #fecaca",
                              borderRadius: "6px",
                              padding: "6px 10px",
                              fontSize: "0.78rem",
                              cursor: "pointer",
                              fontWeight: 600,
                            }}
                            title="Remove allowance component"
                          >
                            Remove
                          </button>
                        </div>
                      ) : (
                        <div style={{ width: "32px" }} />
                      )}
                    </div>

                    {/* Method details row */}
                    {comp.calculation_type === "percentage" && (
                      <div
                        style={{
                          marginTop: "10px",
                          display: "grid",
                          gridTemplateColumns: "1fr 1fr",
                          gap: "1rem",
                          background: "#f0f7ff",
                          padding: "8px 12px",
                          borderRadius: "6px",
                          border: "1px solid #dbeafe",
                        }}
                      >
                        <div>
                          <label style={{ fontSize: "0.72rem", fontWeight: 600, color: "#1e40af", display: "block", marginBottom: "4px" }}>
                            Percentage Value (%) *
                          </label>
                          <input
                            type="number"
                            step="0.01"
                            min="0"
                            max="100"
                            value={comp.value || ""}
                            onChange={(e) => {
                              const updated = [...components];
                              updated[idx].value = e.target.value;
                              setComponents(updated);
                            }}
                            placeholder="e.g. 50.00"
                            style={{ padding: "5px 8px", borderRadius: "5px", border: "1px solid #cbd5e1", fontSize: "0.82rem", width: "100%" }}
                            required
                          />
                        </div>
                        <div>
                          <label style={{ fontSize: "0.72rem", fontWeight: 600, color: "#1e40af", display: "block", marginBottom: "4px" }}>
                            Percentage Calculated Of *
                          </label>
                          <select
                            value={comp.percentage_of || "ctc"}
                            onChange={(e) => {
                              const updated = [...components];
                              updated[idx].percentage_of = e.target.value as any;
                              setComponents(updated);
                            }}
                            style={{ padding: "5px 8px", borderRadius: "5px", border: "1px solid #cbd5e1", fontSize: "0.82rem", width: "100%", background: "#ffffff" }}
                          >
                            <option value="ctc">% of Annual CTC</option>
                            <option value="basic">% of Basic Pay</option>
                          </select>
                        </div>
                      </div>
                    )}

                    {comp.calculation_type === "fixed" && (
                      <div style={{ marginTop: "10px", maxWidth: "260px" }}>
                        <label style={{ fontSize: "0.72rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                          Fixed Monthly Amount (₹) *
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          value={comp.value || ""}
                          onChange={(e) => {
                            const updated = [...components];
                            updated[idx].value = e.target.value;
                            setComponents(updated);
                          }}
                          placeholder="e.g. 2000.00"
                          style={{ padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.84rem", width: "100%" }}
                          required
                        />
                      </div>
                    )}

                    {comp.calculation_type === "balance" && (
                      <div style={{ marginTop: "8px", fontSize: "0.78rem", color: "#059669", display: "flex", alignItems: "center", gap: "6px" }}>
                        <span>ℹ️</span>
                        <span>Auto-computed residual component: absorbs whatever remains of the CTC so the total sums to exactly 100%.</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right Column: Sticky Allocation Visualizer & Summary */}
          <div style={{ position: "sticky", top: "1.5rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", padding: "1.5rem", boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                <span style={{ fontSize: "0.78rem", textTransform: "uppercase", fontWeight: 700, color: "#64748b" }}>
                  CTC Allocation (100%)
                </span>
                <span style={{ fontSize: "0.82rem", fontWeight: 700, color: totalAllocated > 100 ? "#dc2626" : totalAllocated === 100 ? "#16a34a" : "#2563eb" }}>
                  {totalAllocated.toFixed(1)}% Allocated
                </span>
              </div>

              {/* Progress Bar */}
              <div style={{ height: "10px", borderRadius: "5px", background: "#e2e8f0", display: "flex", overflow: "hidden", marginBottom: "1rem" }}>
                {basicVal > 0 && (
                  <div
                    title={`Basic Pay: ${basicVal}% of CTC`}
                    style={{ width: `${Math.min(100, basicVal)}%`, background: "#2563eb" }}
                  />
                )}
                {basicDerivedCtcPercent > 0 && (
                  <div
                    title={`HRA / Derived: ${basicDerivedCtcPercent.toFixed(1)}% of CTC`}
                    style={{ width: `${Math.min(100 - basicVal, basicDerivedCtcPercent)}%`, background: "#38bdf8" }}
                  />
                )}
                {hasBalance && balanceRemaining > 0 && (
                  <div
                    title={`Special Allowance Balance: ${balanceRemaining.toFixed(1)}% of CTC`}
                    style={{ width: `${balanceRemaining}%`, background: "#10b981" }}
                  />
                )}
              </div>

              {/* Legend */}
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", fontSize: "0.8rem", color: "#334155" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#2563eb" }} />
                    <span>Basic Pay</span>
                  </span>
                  <span style={{ fontWeight: 600 }}>{basicVal}%</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#38bdf8" }} />
                    <span>House Rent Allowance (HRA)</span>
                  </span>
                  <span style={{ fontWeight: 600 }}>{basicDerivedCtcPercent.toFixed(1)}%</span>
                </div>
                {hasBalance && (
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#10b981" }} />
                      <span>Special Allowance (Residual)</span>
                    </span>
                    <span style={{ fontWeight: 600 }}>{balanceRemaining.toFixed(1)}%</span>
                  </div>
                )}
              </div>

              {/* Notice */}
              <div style={{ marginTop: "1.25rem", padding: "10px 12px", borderRadius: "6px", background: "#f8fafc", border: "1px solid #e2e8f0", fontSize: "0.78rem", color: "#64748b", lineHeight: 1.4 }}>
                💡 <strong>Zoho Payroll standard:</strong> Keeping Basic Pay at 40-50% optimizes statutory contributions (EPF & ESI) while ensuring optimal take-home salary.
              </div>
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleCreateStructure}
                style={{ width: "100%", background: "#2563eb", borderColor: "#2563eb", borderRadius: "6px", padding: "10px", fontWeight: 600 }}
              >
                Save Salary Structure
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // MAIN PAYROLL SETUP PAGE
  return (
    <div style={{ background: "#f8fafc", minHeight: "100vh", padding: "1.5rem 2.5rem" }}>
      {/* Page Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <div>
          <h1 style={{ fontSize: "1.35rem", fontWeight: 700, color: "#0f172a", margin: 0 }}>
            Payroll Setup
          </h1>
          <p style={{ margin: "2px 0 0", fontSize: "0.84rem", color: "#64748b" }}>
            Manage salary structures, employee assignments, and statutory configs
          </p>
        </div>
        <div style={{ display: "flex", gap: "10px" }}>
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => setShowAssignModal(true)}
            style={{ background: "#ffffff", border: "1px solid #cbd5e1", borderRadius: "6px", fontWeight: 600, color: "#334155" }}
          >
            Assign Employee Salary
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setShowStructureModal(true)}
            style={{ background: "#2563eb", borderColor: "#2563eb", borderRadius: "6px", fontWeight: 600 }}
          >
            + Create Structure
          </button>
        </div>
      </div>

      {/* Segmented Top Tabs */}
      <div style={{ display: "flex", gap: "2rem", borderBottom: "1px solid #e2e8f0", marginBottom: "1.5rem" }}>
        {[
          { id: "structures", label: "Salary Structures" },
          { id: "statutory", label: "Statutory Config" },
          { id: "pt_slabs", label: "PT Slabs" },
          { id: "tax_slabs", label: "Tax Slabs" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`tab-btn ${activeTab === tab.id ? "active fw-bold" : ""}`}
            onClick={() => setActiveTab(tab.id as typeof activeTab)}
            style={{
              background: "transparent",
              border: "none",
              padding: "0.75rem 0",
              fontSize: "0.95rem",
              fontWeight: activeTab === tab.id ? 700 : 500,
              color: activeTab === tab.id ? "#2563eb" : "#64748b",
              borderBottom: activeTab === tab.id ? "2.5px solid #2563eb" : "2.5px solid transparent",
              cursor: "pointer",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab 1: Salary Structures */}
      {activeTab === "structures" && (
        <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", overflow: "hidden", boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)" }}>
          {loadingStructures ? (
            <div style={{ padding: "2.5rem", textAlign: "center", color: "#64748b" }}>Loading structures…</div>
          ) : structures.length === 0 ? (
            <div style={{ padding: "3rem", textAlign: "center", color: "#94a3b8" }}>
              <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>🏢</div>
              <h4>No salary structures defined yet</h4>
              <p className="text-muted text-sm">Click "+ Create Structure" to define compensation allocations.</p>
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #e2e8f0", color: "#64748b", fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "left", background: "#f8fafc" }}>
                  <th style={{ padding: "12px 16px" }}>STRUCTURE NAME</th>
                  <th style={{ padding: "12px 16px" }}>COUNTRY</th>
                  <th style={{ padding: "12px 16px" }}>LEVEL</th>
                  <th style={{ padding: "12px 16px" }}>COMPONENTS</th>
                  <th style={{ padding: "12px 16px" }}>STATUS</th>
                </tr>
              </thead>
              <tbody>
                {structures.map((s) => (
                  <tr key={s.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "14px 16px", fontWeight: 600, color: "#0f172a" }}>{s.name}</td>
                    <td style={{ padding: "14px 16px", color: "#475569" }}>{s.country}</td>
                    <td style={{ padding: "14px 16px", color: "#475569" }}>{s.level || "—"}</td>
                    <td style={{ padding: "14px 16px", color: "#475569" }}>{s.component_count} components</td>
                    <td style={{ padding: "14px 16px" }}>
                      <span
                        style={{
                          background: s.is_active ? "#dcfce7" : "#f1f5f9",
                          color: s.is_active ? "#15803d" : "#64748b",
                          fontSize: "0.75rem",
                          fontWeight: 700,
                          padding: "2px 8px",
                          borderRadius: "4px",
                        }}
                      >
                        {s.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Tab 2: Statutory Config */}
      {activeTab === "statutory" && (
        <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", padding: "2rem", maxWidth: "760px", boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)" }}>
          {loadingStat || !statConfig ? (
            <p>Loading statutory configuration…</p>
          ) : (
            <form onSubmit={handleSaveStatutory} className="stack gap-4">
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "12px",
                  padding: "12px 16px",
                  background: "#f0fdf4",
                  borderRadius: "8px",
                  border: "1px solid #bbf7d0",
                }}
              >
                <div>
                  <strong style={{ fontSize: "0.95rem", color: "#166534" }}>Auto-Localize Statutory Configuration</strong>
                  <p style={{ margin: "2px 0 0", fontSize: "0.8rem", color: "#15803d" }}>
                    Instantly load verified legal statutory rates (EPF 12%, ESI 0.75%, PT slabs) tailored to your registered jurisdiction.
                  </p>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-outline"
                  onClick={() => {
                    setStatConfig({
                      ...statConfig,
                      pf_enabled: true,
                      pf_restrict_to_ceiling: true,
                      esi_enabled: true,
                      pt_state: "Gujarat",
                      default_tax_regime: "new",
                    });
                    notify("Auto-populated regional statutory defaults (India / Gujarat: EPF + ESI + PT)", "success");
                  }}
                  style={{ background: "#ffffff", border: "1px solid #86efac", color: "#166534", fontWeight: 600 }}
                >
                  ⚡ Auto-Populate Regional Slabs
                </button>
              </div>

              <h3 style={{ margin: "1rem 0 0.5rem", fontSize: "0.98rem", color: "#0f172a" }}>EPF Settings (Employee Provident Fund)</h3>
              <div style={{ display: "flex", gap: "2rem" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.85rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={statConfig.pf_enabled}
                    onChange={(e) => setStatConfig({ ...statConfig, pf_enabled: e.target.checked })}
                    style={{ accentColor: "#2563eb" }}
                  />
                  <span>Enable EPF</span>
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.85rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={statConfig.pf_restrict_to_ceiling}
                    onChange={(e) => setStatConfig({ ...statConfig, pf_restrict_to_ceiling: e.target.checked })}
                    style={{ accentColor: "#2563eb" }}
                  />
                  <span>Restrict to Statutory Wage Ceiling (₹15,000)</span>
                </label>
              </div>

              <h3 style={{ margin: "1rem 0 0.5rem", fontSize: "0.98rem", color: "#0f172a" }}>ESI Settings (Employee State Insurance)</h3>
              <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.85rem", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={statConfig.esi_enabled}
                  onChange={(e) => setStatConfig({ ...statConfig, esi_enabled: e.target.checked })}
                  style={{ accentColor: "#2563eb" }}
                />
                <span>Enable ESI (Coverage threshold ₹21,000 gross)</span>
              </label>

              <h3 style={{ margin: "1rem 0 0.5rem", fontSize: "0.98rem", color: "#0f172a" }}>Professional Tax & TDS</h3>
              <div className="grid grid-2 gap-4">
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    PT State
                  </label>
                  <input
                    type="text"
                    value={statConfig.pt_state}
                    onChange={(e) => setStatConfig({ ...statConfig, pt_state: e.target.value })}
                    style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", width: "100%" }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Default Tax Regime
                  </label>
                  <select
                    value={statConfig.default_tax_regime}
                    onChange={(e) => setStatConfig({ ...statConfig, default_tax_regime: e.target.value })}
                    style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", width: "100%", background: "#f8fafc" }}
                  >
                    <option value="new">New Regime (Section 115BAC)</option>
                    <option value="old">Old Regime (with deductions)</option>
                  </select>
                </div>
              </div>

              <div style={{ marginTop: "1rem" }}>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={savingStat}
                  style={{ background: "#2563eb", borderColor: "#2563eb", borderRadius: "6px", padding: "8px 24px", fontWeight: 600 }}
                >
                  {savingStat ? "Saving…" : "Save Statutory Config"}
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* Tab 3: PT Slabs */}
      {activeTab === "pt_slabs" && (
        <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", overflow: "hidden", boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)" }}>
          <div style={{ padding: "1.25rem 1.5rem", borderBottom: "1px solid #f1f5f9" }}>
            <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>Professional Tax Slabs (Gujarat)</h3>
            <p style={{ margin: "2px 0 0", fontSize: "0.78rem", color: "#64748b" }}>Applicable state statutory tax schedules.</p>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e2e8f0", color: "#64748b", fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "left", background: "#f8fafc" }}>
                <th style={{ padding: "12px 16px" }}>MONTHLY INCOME RANGE</th>
                <th style={{ padding: "12px 16px" }}>MONTHLY TAX (₹)</th>
                <th style={{ padding: "12px 16px" }}>REMARKS</th>
              </tr>
            </thead>
            <tbody>
              {ptSlabs.map((s) => (
                <tr key={s.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "14px 16px", color: "#0f172a", fontWeight: 600 }}>
                    ₹{Number(s.income_min).toLocaleString()} {s.income_max ? `- ₹${Number(s.income_max).toLocaleString()}` : "and above"}
                  </td>
                  <td style={{ padding: "14px 16px", fontWeight: 700, color: "#2563eb" }}>₹{s.monthly_amount}</td>
                  <td style={{ padding: "14px 16px", color: "#64748b" }}>{s.source_note || "Standard Gujarat PT Schedule"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 4: Tax Slabs */}
      {activeTab === "tax_slabs" && (
        <div style={{ background: "#ffffff", borderRadius: "10px", border: "1px solid #e2e8f0", overflow: "hidden", boxShadow: "0 1px 3px rgba(0, 0, 0, 0.04)" }}>
          <div style={{ padding: "1.25rem 1.5rem", borderBottom: "1px solid #f1f5f9" }}>
            <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>Income Tax Slabs (FY 2026-27 / New Regime 115BAC)</h3>
            <p style={{ margin: "2px 0 0", fontSize: "0.78rem", color: "#64748b" }}>Source: Income Tax Portal FY 2026-27 (Confirmed unchanged from Budget 2026).</p>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e2e8f0", color: "#64748b", fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "left", background: "#f8fafc" }}>
                <th style={{ padding: "12px 16px" }}>INCOME SLAB</th>
                <th style={{ padding: "12px 16px" }}>TAX RATE</th>
                <th style={{ padding: "12px 16px" }}>CESS</th>
                <th style={{ padding: "12px 16px" }}>CITATION</th>
              </tr>
            </thead>
            <tbody>
              {taxSlabs.map((s) => (
                <tr key={s.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "14px 16px", fontWeight: 600, color: "#0f172a" }}>
                    ₹{Number(s.min_income).toLocaleString()} {s.max_income ? `- ₹${Number(s.max_income).toLocaleString()}` : "and above"}
                  </td>
                  <td style={{ padding: "14px 16px", fontWeight: 700, color: "#0f172a" }}>{s.rate_percent}%</td>
                  <td style={{ padding: "14px 16px", color: "#475569" }}>{s.cess_percent}%</td>
                  <td style={{ padding: "14px 16px", color: "#64748b", fontSize: "0.78rem" }}>{s.source_note || "IT Portal"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Polished Assign Salary Modal */}
      {showAssignModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(15, 23, 42, 0.6)",
            backdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "1rem",
          }}
          onClick={() => setShowAssignModal(false)}
        >
          <div
            style={{
              width: "100%",
              maxWidth: 500,
              background: "#ffffff",
              padding: "2rem",
              borderRadius: "12px",
              boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem", borderBottom: "1px solid #f1f5f9", paddingBottom: "10px" }}>
              <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>
                Assign Salary Structure
              </h3>
              <button
                type="button"
                onClick={() => setShowAssignModal(false)}
                style={{ background: "transparent", border: "none", color: "#64748b", cursor: "pointer" }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>

            <form onSubmit={handleAssignSalary} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div>
                <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                  Employee <span style={{ color: "#ef4444" }}>*</span>
                </label>
                <select
                  value={selectedEmpId}
                  onChange={(e) => setSelectedEmpId(e.target.value)}
                  style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", background: "#f8fafc" }}
                  required
                >
                  <option value="">-- Choose Employee --</option>
                  {employees.map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.first_name} {emp.last_name || ""} ({emp.employee_code})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                  Salary Structure <span style={{ color: "#ef4444" }}>*</span>
                </label>
                <select
                  value={selectedStructId}
                  onChange={(e) => setSelectedStructId(e.target.value)}
                  style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem", background: "#f8fafc" }}
                  required
                >
                  <option value="">-- Choose Structure --</option>
                  {structures.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.component_count} components)
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Annual CTC (₹) <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    placeholder="e.g. 1200000"
                    value={assignCtc}
                    onChange={(e) => setAssignCtc(e.target.value)}
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                    required
                  />
                </div>
                <div>
                  <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", display: "block", marginBottom: "4px" }}>
                    Effective From <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <input
                    type="date"
                    value={assignEffectiveFrom}
                    onChange={(e) => setAssignEffectiveFrom(e.target.value)}
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.86rem" }}
                    required
                  />
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "1.25rem", paddingTop: "1rem", borderTop: "1px solid #f1f5f9" }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowAssignModal(false)}
                  style={{ border: "1px solid #cbd5e1", borderRadius: "6px" }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary btn-sm"
                  disabled={assigning}
                  style={{ background: "#2563eb", borderColor: "#2563eb", borderRadius: "6px", padding: "6px 16px" }}
                >
                  {assigning ? "Saving…" : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
