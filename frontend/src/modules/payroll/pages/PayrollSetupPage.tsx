import { useState, useEffect } from "react";
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

export function PayrollSetupPage() {
  const { notify } = useToast();
  const [activeTab, setActiveTab] = useState<"structures" | "statutory" | "pt_slabs" | "tax_slabs">("structures");

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
      const msg = err instanceof Error ? err.message : "Failed to create structure";
      notify(msg, "error");
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
      const msg = err instanceof Error ? err.message : "Failed to assign salary";
      notify(msg, "error");
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

  return (
    <div className="container">
      <div className="page-header flex justify-between align-center">
        <div>
          <h1>Payroll Setup</h1>
          <p className="text-muted">Manage salary structures, employee assignments, and statutory configs</p>
        </div>
        <div className="flex gap-2">
          <button className="btn btn-outline" onClick={() => setShowAssignModal(true)}>
            Assign Employee Salary
          </button>
          <button className="btn btn-primary" onClick={() => setShowStructureModal(true)}>
            + Create Structure
          </button>
        </div>
      </div>

      <div className="tabs flex gap-4 border-b my-4">
        <button
          className={`tab-btn ${activeTab === "structures" ? "active border-b-2 border-primary fw-bold" : ""}`}
          onClick={() => setActiveTab("structures")}
        >
          Salary Structures
        </button>
        <button
          className={`tab-btn ${activeTab === "statutory" ? "active border-b-2 border-primary fw-bold" : ""}`}
          onClick={() => setActiveTab("statutory")}
        >
          Statutory Config
        </button>
        <button
          className={`tab-btn ${activeTab === "pt_slabs" ? "active border-b-2 border-primary fw-bold" : ""}`}
          onClick={() => setActiveTab("pt_slabs")}
        >
          PT Slabs
        </button>
        <button
          className={`tab-btn ${activeTab === "tax_slabs" ? "active border-b-2 border-primary fw-bold" : ""}`}
          onClick={() => setActiveTab("tax_slabs")}
        >
          Tax Slabs
        </button>
      </div>

      {activeTab === "structures" && (
        <div className="card">
          {loadingStructures ? (
            <p>Loading structures...</p>
          ) : structures.length === 0 ? (
            <p className="text-muted">No salary structures defined yet.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Structure Name</th>
                  <th>Country</th>
                  <th>Level</th>
                  <th>Components</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {structures.map((s) => (
                  <tr key={s.id}>
                    <td className="fw-bold">{s.name}</td>
                    <td>{s.country}</td>
                    <td>{s.level || "—"}</td>
                    <td>{s.component_count} components</td>
                    <td>
                      <span className={`badge ${s.is_active ? "badge-success" : "badge-muted"}`}>
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

      {activeTab === "statutory" && (
        <div className="card max-w-2xl">
          {loadingStat || !statConfig ? (
            <p>Loading statutory configuration...</p>
          ) : (
            <form onSubmit={handleSaveStatutory} className="stack gap-4">
              <h3>EPF Settings (Employee Provident Fund)</h3>
              <div className="flex gap-4 align-center">
                <label className="flex gap-2 align-center">
                  <input
                    type="checkbox"
                    checked={statConfig.pf_enabled}
                    onChange={(e) => setStatConfig({ ...statConfig, pf_enabled: e.target.checked })}
                  />
                  Enable EPF
                </label>
                <label className="flex gap-2 align-center">
                  <input
                    type="checkbox"
                    checked={statConfig.pf_restrict_to_ceiling}
                    onChange={(e) =>
                      setStatConfig({ ...statConfig, pf_restrict_to_ceiling: e.target.checked })
                    }
                  />
                  Restrict to Statutory Wage Ceiling (₹15,000)
                </label>
              </div>

              <h3>ESI Settings (Employee State Insurance)</h3>
              <div className="flex gap-4 align-center">
                <label className="flex gap-2 align-center">
                  <input
                    type="checkbox"
                    checked={statConfig.esi_enabled}
                    onChange={(e) => setStatConfig({ ...statConfig, esi_enabled: e.target.checked })}
                  />
                  Enable ESI (Coverage threshold ₹21,000 gross)
                </label>
              </div>

              <h3>Professional Tax & TDS</h3>
              <div className="grid grid-2 gap-4">
                <div>
                  <label>PT State</label>
                  <input
                    type="text"
                    value={statConfig.pt_state || "Gujarat"}
                    onChange={(e) => setStatConfig({ ...statConfig, pt_state: e.target.value })}
                  />
                </div>
                <div>
                  <label>Default Tax Regime</label>
                  <select
                    value={statConfig.default_tax_regime}
                    onChange={(e) => setStatConfig({ ...statConfig, default_tax_regime: e.target.value })}
                  >
                    <option value="new">New Regime (Section 115BAC)</option>
                    <option value="old">Old Regime</option>
                  </select>
                </div>
              </div>

              <button type="submit" className="btn btn-primary mt-4" disabled={savingStat}>
                {savingStat ? "Saving..." : "Save Statutory Config"}
              </button>
            </form>
          )}
        </div>
      )}

      {activeTab === "pt_slabs" && (
        <div className="card">
          <h3>Professional Tax Slabs (State: Gujarat)</h3>
          <p className="text-muted text-sm mb-4">
            Source: Gujarat notification GHN-35-PFT-2022-S.3(2)(10)-TH dated 8 April 2022.
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>Income Range (Monthly Gross)</th>
                <th>PT Amount</th>
                <th>Source Citation</th>
              </tr>
            </thead>
            <tbody>
              {ptSlabs.map((s) => (
                <tr key={s.id}>
                  <td>
                    ₹{Number(s.income_min).toLocaleString()} {s.income_max ? `- ₹${Number(s.income_max).toLocaleString()}` : "and above"}
                  </td>
                  <td className="fw-bold">₹{s.monthly_amount}/month</td>
                  <td className="text-muted text-sm">{s.source_note || "Gujarat Gazette 2022"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {activeTab === "tax_slabs" && (
        <div className="card">
          <h3>Income Tax Slabs (FY 2026-27 / New Regime 115BAC)</h3>
          <p className="text-muted text-sm mb-4">
            Source: Income Tax Portal FY 2026-27 (Confirmed unchanged from Budget 2026).
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>Income Slab</th>
                <th>Tax Rate</th>
                <th>Cess</th>
                <th>Citation</th>
              </tr>
            </thead>
            <tbody>
              {taxSlabs.map((s) => (
                <tr key={s.id}>
                  <td>
                    ₹{Number(s.min_income).toLocaleString()} {s.max_income ? `- ₹${Number(s.max_income).toLocaleString()}` : "and above"}
                  </td>
                  <td className="fw-bold">{s.rate_percent}%</td>
                  <td>{s.cess_percent}%</td>
                  <td className="text-muted text-sm">{s.source_note || "IT Portal"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal: Create Structure */}
      {showStructureModal && (
        <div className="modal-backdrop" onClick={() => setShowStructureModal(false)}>
          <div className="modal card max-w-xl" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Create Salary Structure</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowStructureModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateStructure} className="stack gap-4">
              <div>
                <label>Structure Name</label>
                <input
                  type="text"
                  placeholder="e.g. Standard Full-time Structure"
                  value={structName}
                  onChange={(e) => setStructName(e.target.value)}
                  required
                />
              </div>
              <div className="grid grid-2 gap-4">
                <div>
                  <label>Country</label>
                  <input type="text" value={structCountry} onChange={(e) => setStructCountry(e.target.value)} />
                </div>
                <div>
                  <label>Level</label>
                  <input type="text" value={structLevel} onChange={(e) => setStructLevel(e.target.value)} />
                </div>
              </div>

              <h3>Components</h3>
              {components.map((comp, idx) => (
                <div key={idx} className="p-3 border rounded grid grid-3 gap-2 align-center">
                  <div>
                    <label className="text-xs">Code</label>
                    <input
                      type="text"
                      value={comp.code}
                      onChange={(e) => {
                        const updated = [...components];
                        updated[idx].code = e.target.value;
                        setComponents(updated);
                      }}
                    />
                  </div>
                  <div>
                    <label className="text-xs">Name</label>
                    <input
                      type="text"
                      value={comp.name}
                      onChange={(e) => {
                        const updated = [...components];
                        updated[idx].name = e.target.value;
                        setComponents(updated);
                      }}
                    />
                  </div>
                  <div>
                    <label className="text-xs">Calc Type</label>
                    <select
                      value={comp.calculation_type}
                      onChange={(e) => {
                        const updated = [...components];
                        updated[idx].calculation_type = e.target.value as any;
                        setComponents(updated);
                      }}
                    >
                      <option value="percentage">percentage</option>
                      <option value="fixed">fixed</option>
                      <option value="balance">balance</option>
                    </select>
                  </div>
                  {idx > 2 && (
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost text-red"
                      onClick={() => removeComponentLine(idx)}
                    >
                      Remove
                    </button>
                  )}
                </div>
              ))}
              <button type="button" className="btn btn-sm btn-outline" onClick={addComponentLine}>
                + Add Component
              </button>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowStructureModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Save Structure
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Assign Salary */}
      {showAssignModal && (
        <div className="modal-backdrop" onClick={() => setShowAssignModal(false)}>
          <div className="modal card max-w-lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Assign Salary Structure to Employee</h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowAssignModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleAssignSalary} className="stack gap-4">
              <div>
                <label>Select Employee</label>
                <select value={selectedEmpId} onChange={(e) => setSelectedEmpId(e.target.value)} required>
                  <option value="">-- Choose Employee --</option>
                  {employees.map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.first_name} {emp.last_name || ""} ({emp.employee_code})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label>Select Structure</label>
                <select value={selectedStructId} onChange={(e) => setSelectedStructId(e.target.value)} required>
                  <option value="">-- Choose Structure --</option>
                  {structures.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.component_count} components)
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-2 gap-4">
                <div>
                  <label>Annual CTC (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={assignCtc}
                    onChange={(e) => setAssignCtc(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label>Effective From</label>
                  <input
                    type="date"
                    value={assignEffectiveFrom}
                    onChange={(e) => setAssignEffectiveFrom(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowAssignModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={assigning}>
                  {assigning ? "Assigning..." : "Confirm Assignment"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
