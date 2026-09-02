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
  type EmploymentType,
} from "../api";
import { employeeFormSchema } from "../schemas";

const EMPLOYMENT_TYPES: EmploymentType[] = ["full_time", "part_time", "contract", "intern"];

interface FormState {
  first_name: string;
  last_name: string;
  email: string;
  personal_email: string;
  phone: string;
  department_id: string;
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
  position: "",
  level: "",
  employment_type: "full_time",
  hire_date: "",
  probation_end_date: "",
  notice_period_days: "30",
};

export function EmployeeFormPage() {
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const { notify } = useToast();

  const [form, setForm] = useState<FormState>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const departmentsQuery = useQuery({
    queryKey: ["departments", "all-for-form"],
    queryFn: () => listDepartments({ page: 1, limit: 100 }),
  });

  const existingQuery = useQuery({
    queryKey: ["employee", id],
    queryFn: () => getEmployee(id as string),
    enabled: isEdit,
  });

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
        position: e.position ?? "",
        level: e.level ?? "",
        employment_type: e.employment_type,
        hire_date: e.hire_date,
        probation_end_date: e.probation_end_date ?? "",
        notice_period_days: String(e.notice_period_days),
      });
    }
  }, [existingQuery.data]);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setFieldErrors({});

    const parsed = employeeFormSchema.safeParse({
      ...form,
      notice_period_days: form.notice_period_days,
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
      department_id: form.department_id || undefined,
      position: form.position.trim() || undefined,
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
        notify("Employee created.");
        navigate(`/employees/${created.id}`, { state: { invite: created.invite } });
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

  if (isEdit && existingQuery.isLoading) {
    return (
      <div className="row">
        <div className="spinner" />
        <span className="text-muted">Loading…</span>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title={isEdit ? "Edit employee" : "New employee"} breadcrumb="HR / Employees" />
      <form className="card stack" onSubmit={handleSubmit} style={{ maxWidth: 640 }}>
        {formError && <div className="alert alert-error">{formError}</div>}

        <div className="form-grid">
          <div className={"field" + (fieldErrors.first_name ? " has-error" : "")}>
            <label>First name</label>
            <input value={form.first_name} onChange={(e) => setField("first_name", e.target.value)} />
            {fieldErrors.first_name && <span className="field-error">{fieldErrors.first_name}</span>}
          </div>
          <div className="field">
            <label>Last name</label>
            <input value={form.last_name} onChange={(e) => setField("last_name", e.target.value)} />
          </div>

          <div className={"field" + (fieldErrors.email ? " has-error" : "")}>
            <label>Work email</label>
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
                The activation invite goes here — they can't reach their work email until they've
                activated. Falls back to the work email above if left blank.
              </span>
            )}
          </div>

          <div className="field">
            <label>Phone</label>
            <input value={form.phone} onChange={(e) => setField("phone", e.target.value)} />
          </div>
          <div className="field">
            <label>Department</label>
            <select value={form.department_id} onChange={(e) => setField("department_id", e.target.value)}>
              <option value="">— None —</option>
              {departmentsQuery.data?.items.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>Position</label>
            <input value={form.position} onChange={(e) => setField("position", e.target.value)} />
          </div>
          <div className="field">
            <label>Level</label>
            <input value={form.level} onChange={(e) => setField("level", e.target.value)} />
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
            <label>Hire date</label>
            <input type="date" value={form.hire_date} onChange={(e) => setField("hire_date", e.target.value)} />
            {fieldErrors.hire_date && <span className="field-error">{fieldErrors.hire_date}</span>}
          </div>

          <div className="field">
            <label>Probation end date</label>
            <input
              type="date"
              value={form.probation_end_date}
              onChange={(e) => setField("probation_end_date", e.target.value)}
            />
          </div>
          <div className="field">
            <label>Notice period (days)</label>
            <input
              type="number"
              min={0}
              value={form.notice_period_days}
              onChange={(e) => setField("notice_period_days", e.target.value)}
            />
          </div>
        </div>

        <div className="row">
          <button className="btn btn-primary" type="submit" disabled={submitting}>
            {submitting ? "Saving…" : isEdit ? "Save changes" : "Create employee"}
          </button>
          <button type="button" className="btn" onClick={() => navigate(-1)}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
