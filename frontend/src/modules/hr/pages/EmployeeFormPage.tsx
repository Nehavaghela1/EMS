import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { parseApiError, fieldErrorsFromDetails } from "../../../shared/api/errors";
import { useToast } from "../../../app/toast-context";
import {
  createEmployee,
  getEmployee,
  listDepartments,
  updateEmployee,
  type EmployeeCreateInput,
  type EmployeeCreateResponse,
  type EmploymentType,
} from "../api";
import { listLocations } from "../../identity/api";
import { listStructures, assignEmployeeSalary } from "../../payroll/api";
import { employeeFormSchema } from "../schemas";
import { getPositionsForDepartment, toTitleCase } from "../constants/departmentPositions";
import { ManagerCombobox } from "../components/ManagerCombobox";

const EMPLOYMENT_TYPES: EmploymentType[] = ["full_time", "part_time", "contract", "intern"];

interface FormState {
  first_name: string;
  last_name: string;
  email: string;
  personal_email: string;
  phone: string;
  department_id: string;
  location_id: string;
  reporting_manager_id: string;
  position: string;
  level: string;
  employment_type: EmploymentType;
  hire_date: string;
  probation_end_date: string;
  notice_period_days: string;
}

const EMPTY: FormState = {
  first_name: "",
  last_name: "",
  email: "",
  personal_email: "",
  phone: "",
  department_id: "",
  location_id: "",
  reporting_manager_id: "",
  position: "",
  level: "L1",
  employment_type: "full_time",
  hire_date: new Date().toISOString().split("T")[0],
  probation_end_date: "",
  notice_period_days: "30",
};

export function EmployeeFormPage() {
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const { notify } = useToast();

  // Wizard step: 1 = Basic & Job Role, 2 = Compensation & Payroll Breakdown
  const [wizardStep, setWizardStep] = useState<1 | 2>(1);
  const [createdEmployee, setCreatedEmployee] = useState<EmployeeCreateResponse | null>(null);

  // Step 2 Compensation State
  const [structureId, setStructureId] = useState<string>("");
  const [ctc, setCtc] = useState<string>("");
  const [effectiveFrom, setEffectiveFrom] = useState<string>(new Date().toISOString().split("T")[0]);
  const [assigningSalary, setAssigningSalary] = useState(false);
  const [step2Error, setStep2Error] = useState<string | null>(null);

  const [form, setForm] = useState<FormState>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const departmentsQuery = useQuery({
    queryKey: ["departments", "all-for-form"],
    queryFn: () => listDepartments({ page: 1, limit: 100 }),
  });

  const locationsQuery = useQuery({
    queryKey: ["locations", "all-for-form"],
    queryFn: () => listLocations(),
  });

  const structuresQuery = useQuery({
    queryKey: ["salary-structures-for-wizard"],
    queryFn: () => listStructures(1, 100),
    enabled: !isEdit,
  });

  const existingQuery = useQuery({
    queryKey: ["employee", id],
    queryFn: () => getEmployee(id as string),
    enabled: isEdit,
  });

  const [positionMode, setPositionMode] = useState<string>("");
  const [customPosition, setCustomPosition] = useState<string>("");

  useEffect(() => {
    if (existingQuery.data) {
      const e = existingQuery.data;
      setForm({
        first_name: e.first_name,
        last_name: e.last_name ?? "",
        email: e.email,
        personal_email: e.personal_email ?? "",
        phone: e.phone ?? "",
        department_id: e.department_id ?? "",
        location_id: e.location_id ?? "",
        reporting_manager_id: e.reporting_manager_id ?? "",
        position: e.position ?? "",
        level: e.level ?? "L1",
        employment_type: e.employment_type,
        hire_date: e.hire_date,
        probation_end_date: e.probation_end_date ?? "",
        notice_period_days: String(e.notice_period_days),
      });

      // Synchronize position mode with department standard positions
      const deptName = departmentsQuery.data?.items.find((d) => d.id === e.department_id)?.name;
      const stdPositions = getPositionsForDepartment(deptName);
      if (e.position && stdPositions.includes(e.position)) {
        setPositionMode(e.position);
        setCustomPosition("");
      } else if (e.position) {
        setPositionMode("__other__");
        setCustomPosition(e.position);
      } else {
        setPositionMode("");
        setCustomPosition("");
      }
    }
  }, [existingQuery.data, departmentsQuery.data]);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  // Handle department change: reset designation so irrelevant titles aren't preserved
  function handleDepartmentChange(deptId: string) {
    setField("department_id", deptId);
    setPositionMode("");
    setCustomPosition("");
    setField("position", "");
  }

  // Handle position select change
  function handlePositionSelectChange(val: string) {
    setPositionMode(val);
    if (val === "__other__") {
      setField("position", toTitleCase(customPosition));
    } else {
      setCustomPosition("");
      setField("position", val);
    }
  }

  // Handle custom position input change
  function handleCustomPositionChange(rawVal: string) {
    setCustomPosition(rawVal);
    setField("position", toTitleCase(rawVal));
  }

  async function handleStep1Submit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setFieldErrors({});

    // Validate that if "Other (Specify)" is selected, designation is not empty
    if (positionMode === "__other__" && !customPosition.trim()) {
      setFieldErrors((prev) => ({
        ...prev,
        position: "Please specify the designation title.",
      }));
      return;
    }

    const finalPosition =
      positionMode === "__other__"
        ? toTitleCase(customPosition.trim())
        : positionMode.trim();

    const parsed = employeeFormSchema.safeParse({
      first_name: form.first_name,
      last_name: form.last_name || undefined,
      email: form.email,
      personal_email: form.personal_email || undefined,
      phone: form.phone || undefined,
      department_id: form.department_id,
      location_id: form.location_id || undefined,
      reporting_manager_id: form.reporting_manager_id || undefined,
      position: finalPosition || undefined,
      level: form.level || undefined,
      employment_type: form.employment_type,
      hire_date: form.hire_date,
      probation_end_date: form.probation_end_date || undefined,
      notice_period_days: form.notice_period_days || undefined,
    });
    if (!parsed.success) {
      const errors: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path[0];
        if (typeof key === "string") errors[key] = issue.message;
      }
      setFieldErrors(errors);
      return;
    }

    const payload: EmployeeCreateInput = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim() || undefined,
      email: form.email.trim(),
      personal_email: form.personal_email.trim() || undefined,
      phone: form.phone.trim() || undefined,
      department_id: form.department_id, // Strictly required
      location_id: form.location_id || undefined,
      reporting_manager_id: form.reporting_manager_id || undefined,
      position: finalPosition || undefined,
      level: form.level.trim() || undefined,
      employment_type: form.employment_type,
      hire_date: form.hire_date,
      probation_end_date: form.probation_end_date || undefined,
      notice_period_days: form.notice_period_days ? Number(form.notice_period_days) : undefined,
    };

    setSubmitting(true);
    try {
      if (isEdit && id) {
        await updateEmployee(id, payload);
        notify("Employee updated.");
        navigate(`/employees/${id}`);
      } else {
        const created = await createEmployee(payload);
        notify("Employee created & invite triggered!");
        setCreatedEmployee(created);
        setWizardStep(2);
      }
    } catch (err) {
      const parsedErr = parseApiError(err);
      setFormError(parsedErr.message);
      const fromServer = fieldErrorsFromDetails(parsedErr.details);
      if (Object.keys(fromServer).length > 0) setFieldErrors(fromServer);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAssignSalary(e: FormEvent) {
    e.preventDefault();
    if (!createdEmployee?.id) return;
    if (!structureId || !ctc) {
      setStep2Error("Please select a salary structure and enter annual CTC.");
      return;
    }
    setAssigningSalary(true);
    setStep2Error(null);
    try {
      await assignEmployeeSalary(createdEmployee.id, {
        structure_id: structureId,
        ctc: ctc.trim(),
        effective_from: effectiveFrom,
      });
      notify("Salary structure assigned.");
      navigate(`/employees/${createdEmployee.id}`, { state: { invite: createdEmployee.invite } });
    } catch (err) {
      const parsed = parseApiError(err);
      setStep2Error(parsed.message);
    } finally {
      setAssigningSalary(false);
    }
  }

  function handleSkipSalary() {
    if (createdEmployee) {
      navigate(`/employees/${createdEmployee.id}`, { state: { invite: createdEmployee.invite } });
    } else {
      navigate("/employees");
    }
  }

  if (isEdit && existingQuery.isLoading) {
    return (
      <div className="row">
        <div className="spinner" />
        <span className="text-muted">Loading…</span>
      </div>
    );
  }

  return (
    <div className="stack gap-4">
      {/* Back Link */}
      <div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          style={{ paddingLeft: 0, textDecoration: "none" }}
          onClick={() => navigate(isEdit ? `/employees/${id}` : "/employees")}
        >
          ← Back to {isEdit ? "Profile" : "Employees"}
        </button>
      </div>

      <PageHeader
        title={isEdit ? "Edit employee" : "Onboard New Employee"}
        breadcrumb={isEdit ? "HR / Edit Employee" : "HR / Employee Onboarding Wizard"}
      />

      {/* Onboarding Wizard Stepper (Only on New Employee) */}
      {!isEdit && (
        <div
          style={{
            maxWidth: 640,
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "12px",
            marginBottom: "8px",
          }}
        >
          <div
            style={{
              padding: "12px 16px",
              borderRadius: "8px",
              border: wizardStep === 1 ? "2px solid #2563eb" : "1px solid #e2e8f0",
              background: wizardStep === 1 ? "#eff6ff" : "#f8fafc",
              display: "flex",
              alignItems: "center",
              gap: "10px",
            }}
          >
            <span
              style={{
                width: "28px",
                height: "28px",
                borderRadius: "50%",
                background: wizardStep >= 1 ? "#2563eb" : "#cbd5e1",
                color: "#fff",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 700,
                fontSize: "0.85rem",
              }}
            >
              {createdEmployee ? "✓" : "1"}
            </span>
            <div>
              <div style={{ fontWeight: 600, fontSize: "0.9rem", color: "#1e293b" }}>
                Step 1: Basic & Job Role
              </div>
              <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
                Profile details & email invite
              </div>
            </div>
          </div>

          <div
            style={{
              padding: "12px 16px",
              borderRadius: "8px",
              border: wizardStep === 2 ? "2px solid #2563eb" : "1px solid #e2e8f0",
              background: wizardStep === 2 ? "#eff6ff" : "#f8fafc",
              display: "flex",
              alignItems: "center",
              gap: "10px",
            }}
          >
            <span
              style={{
                width: "28px",
                height: "28px",
                borderRadius: "50%",
                background: wizardStep === 2 ? "#2563eb" : "#cbd5e1",
                color: "#fff",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 700,
                fontSize: "0.85rem",
              }}
            >
              2
            </span>
            <div>
              <div style={{ fontWeight: 600, fontSize: "0.9rem", color: "#1e293b" }}>
                Step 2: Compensation Setup
              </div>
              <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
                Salary structure (Optional)
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Step 1 Form */}
      {wizardStep === 1 && (
        <form className="card stack" onSubmit={handleStep1Submit} style={{ maxWidth: 640 }}>
          {formError && <div className="alert alert-error">{formError}</div>}

          <div className="form-grid">
            <div className={"field" + (fieldErrors.first_name ? " has-error" : "")}>
              <label>First name *</label>
              <input value={form.first_name} onChange={(e) => setField("first_name", e.target.value)} />
              {fieldErrors.first_name && <span className="field-error">{fieldErrors.first_name}</span>}
            </div>
            <div className="field">
              <label>Last name</label>
              <input value={form.last_name} onChange={(e) => setField("last_name", e.target.value)} />
            </div>

            <div className={"field" + (fieldErrors.email ? " has-error" : "")}>
              <label>Work email *</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setField("email", e.target.value)}
                disabled={isEdit}
              />
              {fieldErrors.email && <span className="field-error">{fieldErrors.email}</span>}
            </div>
            <div className={"field" + (fieldErrors.personal_email ? " has-error" : "")}>
              <label>Personal email</label>
              <input
                type="email"
                value={form.personal_email}
                onChange={(e) => setField("personal_email", e.target.value)}
              />
              {fieldErrors.personal_email && <span className="field-error">{fieldErrors.personal_email}</span>}
              {!isEdit && (
                <span className="field-hint">
                  Activation invite is sent here. Falls back to work email if empty.
                </span>
              )}
            </div>

            <div className="field">
              <label>Phone</label>
              <input value={form.phone} onChange={(e) => setField("phone", e.target.value)} />
            </div>

            {/* Work Location / Branch Selection */}
            <div className={"field" + (fieldErrors.location_id ? " has-error" : "")}>
              <label>Work Location / Branch</label>
              <select
                value={form.location_id}
                onChange={(e) => setField("location_id", e.target.value)}
              >
                <option value="">— Unassigned (Remote/Corporate) —</option>
                {locationsQuery.data?.map((loc) => (
                  <option key={loc.id} value={loc.id}>
                    {loc.name} {loc.is_primary ? "(Head Office)" : ""}
                  </option>
                ))}
              </select>
              {fieldErrors.location_id && (
                <span className="field-error">{fieldErrors.location_id}</span>
              )}
            </div>
            
            {/* Mandatory Department Selection */}
            <div className={"field" + (fieldErrors.department_id ? " has-error" : "")}>
              <label>Department *</label>
              <select
                value={form.department_id}
                onChange={(e) => handleDepartmentChange(e.target.value)}
              >
                <option value="">— Select Department (Mandatory) —</option>
                {departmentsQuery.data?.items.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
              {fieldErrors.department_id && (
                <span className="field-error">{fieldErrors.department_id}</span>
              )}
            </div>

            {/* Department-Aware Position / Designation Selection */}
            <div className={"field" + (fieldErrors.position ? " has-error" : "")}>
              <div className="row-between align-center mb-1">
                <label style={{ margin: 0 }}>Position / Role Designation</label>
                {form.department_id && (
                  <span className="text-xs text-muted">
                    Recommended for {departmentsQuery.data?.items.find((d) => d.id === form.department_id)?.name}
                  </span>
                )}
              </div>

              <select
                value={positionMode}
                onChange={(e) => handlePositionSelectChange(e.target.value)}
                disabled={!form.department_id}
              >
                <option value="">
                  {form.department_id ? "— Select Designation —" : "— Select Department First —"}
                </option>
                {getPositionsForDepartment(
                  departmentsQuery.data?.items.find((d) => d.id === form.department_id)?.name
                ).map((pos) => (
                  <option key={pos} value={pos}>
                    {pos}
                  </option>
                ))}
                <option value="__other__">Other (Specify)...</option>
              </select>

              {/* When "Other (Specify)" is selected, slide down text input */}
              {positionMode === "__other__" && (
                <div className="stack gap-1 mt-2" style={{ animation: "fadeIn 0.2s ease-in-out" }}>
                  <label style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text, #334155)" }}>
                    Specify Designation *
                  </label>
                  <input
                    type="text"
                    value={customPosition}
                    onChange={(e) => handleCustomPositionChange(e.target.value)}
                    onBlur={() => {
                      // Auto-trim and format to Title Case on blur
                      const formatted = toTitleCase(customPosition);
                      setCustomPosition(formatted);
                      setField("position", formatted);
                    }}
                    placeholder="e.g. Prompt Engineer, Data Architect, Solutions Consultant"
                    autoFocus
                  />
                  <span className="field-hint" style={{ fontSize: "0.75rem" }}>
                    Auto-formatted to Title Case upon saving.
                  </span>
                </div>
              )}

              {fieldErrors.position && (
                <span className="field-error">{fieldErrors.position}</span>
              )}
            </div>

            {/* Reporting Manager Combobox */}
            <div className={"field" + (fieldErrors.reporting_manager_id ? " has-error" : "")}>
              <label>Reporting Manager</label>
              <ManagerCombobox
                value={form.reporting_manager_id}
                onChange={(mgrId) => setField("reporting_manager_id", mgrId)}
                excludeId={id}
                initialManagerName={existingQuery.data?.manager_name ?? undefined}
                initialManagerPosition={existingQuery.data?.manager_position ?? undefined}
              />
              {fieldErrors.reporting_manager_id && (
                <span className="field-error">{fieldErrors.reporting_manager_id}</span>
              )}
              <span className="field-hint">
                Direct supervisor who approves leaves and attendance regularizations.
              </span>
            </div>

            <div className="field">
              <label>Level (Band)</label>
              <select
                value={form.level}
                onChange={(e) => {
                  const newLevel = e.target.value;
                  setField("level", newLevel);
                  // Auto-suggest policy notice period if not customized
                  if (!isEdit || form.notice_period_days === "30" || form.notice_period_days === "60" || form.notice_period_days === "90" || form.notice_period_days === "15") {
                    const policyDays = newLevel === "L3" ? "90" : newLevel === "L2" ? "60" : "30";
                    setField("notice_period_days", policyDays);
                  }
                }}
              >
                <option value="L1">L1 — Junior / Entry Level (30d notice)</option>
                <option value="L2">L2 — Mid Level (60d notice)</option>
                <option value="L3">L3 — Lead / Senior / Executive (90d notice)</option>
              </select>
              <span className="field-hint">Policy notice period maps automatically from band.</span>
            </div>

            <div className="field">
              <label>Employment type</label>
              <select
                value={form.employment_type}
                onChange={(e) => setField("employment_type", e.target.value as EmploymentType)}
              >
                {EMPLOYMENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace("_", " ")}
                  </option>
                ))}
              </select>
            </div>
            <div className={"field" + (fieldErrors.hire_date ? " has-error" : "")}>
              <label>Hire date *</label>
              <input type="date" value={form.hire_date} onChange={(e) => setField("hire_date", e.target.value)} />
              {fieldErrors.hire_date && <span className="field-error">{fieldErrors.hire_date}</span>}
            </div>

            <div className="field">
              <label>Probation end date</label>
              <input
                type="date"
                value={form.probation_end_date}
                onChange={(e) => {
                  const probDate = e.target.value;
                  setField("probation_end_date", probDate);
                  if (probDate && (!isEdit || form.notice_period_days === "30" || form.notice_period_days === "60" || form.notice_period_days === "90")) {
                    // In probation, notice is standard 15 days
                    setField("notice_period_days", "15");
                  } else if (!probDate) {
                    const policyDays = form.level === "L3" ? "90" : form.level === "L2" ? "60" : "30";
                    setField("notice_period_days", policyDays);
                  }
                }}
              />
              <span className="field-hint">During probation period, policy notice is 15 days.</span>
            </div>
            <div className="field">
              <label>Notice period (days)</label>
              <input
                type="number"
                min={0}
                value={form.notice_period_days}
                onChange={(e) => setField("notice_period_days", e.target.value)}
              />
              <span className="field-hint">Defaulted from band/probation policy; adjustable as needed.</span>
            </div>
          </div>

          <div className="row" style={{ marginTop: "1rem" }}>
            <button className="btn btn-primary" type="submit" disabled={submitting}>
              {submitting
                ? "Saving…"
                : isEdit
                ? "Save changes"
                : "Create & Continue to Step 2 →"}
            </button>
            <button type="button" className="btn" onClick={() => navigate(-1)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Step 2: Compensation & Payroll Setup */}
      {wizardStep === 2 && (
        <form className="card stack" onSubmit={handleAssignSalary} style={{ maxWidth: 640 }}>
          <div className="alert alert-success">
            <strong>Step 1 Complete:</strong> Employee profile created and activation invite triggered!
          </div>

          <div>
            <h2 style={{ fontSize: "1.1rem", margin: "0 0 4px" }}>Step 2: Compensation & Payroll Breakdown</h2>
            <p className="subtitle" style={{ margin: 0, fontSize: "0.85rem" }}>
              Assign a pre-configured salary structure and annual CTC for this employee. You can also skip this and configure it later under Payroll Setup.
            </p>
          </div>

          {step2Error && <div className="alert alert-error">{step2Error}</div>}

          <div className="form-grid">
            <div className="field">
              <label>Salary Structure</label>
              <select value={structureId} onChange={(e) => setStructureId(e.target.value)}>
                <option value="">— Select Salary Structure —</option>
                {structuresQuery.data?.items.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.country} • {s.level || "All Levels"})
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label>Annual CTC (Gross Cost to Company)</label>
              <input
                type="number"
                step="1000"
                placeholder="e.g. 1200000"
                value={ctc}
                onChange={(e) => setCtc(e.target.value)}
              />
            </div>

            <div className="field">
              <label>Effective From</label>
              <input
                type="date"
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
              />
            </div>
          </div>

          <div className="row" style={{ marginTop: "1rem" }}>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={assigningSalary || !structureId || !ctc}
            >
              {assigningSalary ? "Assigning…" : "Save Compensation & Finish"}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={handleSkipSalary}
            >
              Skip for now →
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

