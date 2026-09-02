import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listIndustryPresets, registerCompany } from "../api";
import { registerCompanySchema } from "../schemas";
import { parseApiError, fieldErrorsFromDetails } from "../../../shared/api/errors";

interface FormState {
  company_name: string;
  company_email: string;
  industry: string;
  phone: string;
}

const EMPTY: FormState = { company_name: "", company_email: "", industry: "", phone: "" };

/** Page 2 (Spec 14.3, public). Route 12: creates the company `pending` —
 * no user is created here (10.2), so this page must not imply the caller
 * can log in yet. */
export function RegisterCompanyPage() {
  const industriesQuery = useQuery({ queryKey: ["industry-presets"], queryFn: listIndustryPresets });
  const [form, setForm] = useState<FormState>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState<{ name: string; code: string } | null>(null);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setFieldErrors({});

    const parsed = registerCompanySchema.safeParse(form);
    if (!parsed.success) {
      const errors: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path[0];
        if (typeof key === "string") errors[key] = issue.message;
      }
      setFieldErrors(errors);
      return;
    }

    setSubmitting(true);
    try {
      const company = await registerCompany({
        company_name: form.company_name.trim(),
        company_email: form.company_email.trim(),
        industry: form.industry.trim() || undefined,
        phone: form.phone.trim() || undefined,
      });
      setSubmitted({ name: company.name, code: company.code });
    } catch (err) {
      const parsedErr = parseApiError(err);
      setFormError(parsedErr.message);
      const fromServer = fieldErrorsFromDetails(parsedErr.details);
      if (Object.keys(fromServer).length > 0) setFieldErrors(fromServer);
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div className="center-screen">
        <div className="card stack" style={{ width: 420 }}>
          <h1 style={{ margin: "0 0 4px", fontSize: 20 }}>Registration complete</h1>
          <div className="alert alert-success">
            <strong>{submitted.name}</strong> (code {submitted.code}) is registered and now{" "}
            <strong>awaiting approval</strong>.
          </div>
          <p className="text-muted" style={{ margin: 0 }}>
            There is no account to sign in with yet — a platform administrator still has to
            approve the company. HR admin credentials are issued only once that happens, and
            will be sent to you then. There is nothing further to do right now.
          </p>
          <Link to="/login" className="btn">
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="center-screen">
      <form className="card stack" style={{ width: 420 }} onSubmit={handleSubmit}>
        <div>
          <h1 style={{ margin: "0 0 4px", fontSize: 20 }}>Register your company</h1>
          <p className="text-muted" style={{ margin: 0 }}>
            Your company is reviewed before it goes live — no account is created yet.
          </p>
        </div>

        {formError && <div className="alert alert-error">{formError}</div>}

        <div className={"field" + (fieldErrors.company_name ? " has-error" : "")}>
          <label htmlFor="company_name">Company name</label>
          <input
            id="company_name"
            value={form.company_name}
            onChange={(e) => setField("company_name", e.target.value)}
          />
          {fieldErrors.company_name && <span className="field-error">{fieldErrors.company_name}</span>}
        </div>

        <div className={"field" + (fieldErrors.company_email ? " has-error" : "")}>
          <label htmlFor="company_email">Company email</label>
          <input
            id="company_email"
            type="email"
            value={form.company_email}
            onChange={(e) => setField("company_email", e.target.value)}
          />
          {fieldErrors.company_email && <span className="field-error">{fieldErrors.company_email}</span>}
        </div>

        <div className="field">
          <label htmlFor="industry">Industry (optional)</label>
          <select
            id="industry"
            value={form.industry}
            onChange={(e) => setField("industry", e.target.value)}
            disabled={industriesQuery.isLoading}
          >
            <option value="">— None —</option>
            {industriesQuery.data?.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          {industriesQuery.isError && (
            <span className="field-error">
              Couldn't load the industry list ({parseApiError(industriesQuery.error).message}) —
              you can still register without one.
            </span>
          )}
          <span className="text-muted" style={{ fontSize: 12 }}>
            Used to pre-populate departments and leave types once approved.
          </span>
        </div>

        <div className="field">
          <label htmlFor="phone">Phone (optional)</label>
          <input id="phone" value={form.phone} onChange={(e) => setField("phone", e.target.value)} />
        </div>

        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Registering…" : "Register company"}
        </button>

        <div style={{ fontSize: 13 }}>
          <Link to="/login">Back to sign in</Link>
        </div>
      </form>
    </div>
  );
}
