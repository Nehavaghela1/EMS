import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listIndustryPresets, registerCompany } from "../api";
import { registerCompanySchema } from "../schemas";
import { parseApiError, fieldErrorsFromDetails } from "../../../shared/api/errors";

interface FormState {
  company_name: string;
  company_email: string;
  subdomain: string;
  company_size: string;
  industry: string;
  phone: string;
  password: string;
  confirm_password: string;
}

const EMPTY: FormState = {
  company_name: "",
  company_email: "",
  subdomain: "",
  company_size: "",
  industry: "",
  phone: "",
  password: "",
  confirm_password: "",
};

const COMPANY_SIZE_OPTIONS = [
  { value: "1-10", label: "1-10 employees (Startup / Early stage)" },
  { value: "11-50", label: "11-50 employees (Small business)" },
  { value: "51-200", label: "51-200 employees (Mid-sized company)" },
  { value: "201-500", label: "201-500 employees (Large enterprise)" },
  { value: "500+", label: "500+ employees (Global organization)" },
];

/** Page 2 (Spec 14.3, public). Route 12: creates the company `pending` with initial
 * admin credentials, chosen subdomain, and company size for automated onboarding. */
export function RegisterCompanyPage() {
  const industriesQuery = useQuery({ queryKey: ["industry-presets"], queryFn: listIndustryPresets });
  const [form, setForm] = useState<FormState>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [submitted, setSubmitted] = useState<{ name: string; code: string; email: string; subdomain?: string } | null>(null);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => {
      const next = { ...f, [key]: value };
      // Auto-suggest clean subdomain if user is typing company name and hasn't manually customized subdomain
      if (key === "company_name" && (!f.subdomain || f.subdomain === f.company_name.toLowerCase().replace(/[^a-z0-9]/g, ""))) {
        next.subdomain = value
          .toLowerCase()
          .replace(/[^a-z0-9-]/g, "")
          .replace(/-+/g, "-")
          .slice(0, 63);
      }
      return next;
    });
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
        subdomain: form.subdomain.trim() || undefined,
        company_size: form.company_size || undefined,
        industry: form.industry.trim() || undefined,
        phone: form.phone.trim() || undefined,
        password: form.password,
      });
      setSubmitted({
        name: company.name,
        code: company.code,
        email: form.company_email.trim(),
        subdomain: company.subdomain || form.subdomain.trim() || undefined,
      });
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
        <div className="card stack auth-card auth-card-wide" style={{ maxWidth: 540 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ fontSize: "28px" }}>🏢</span>
            <div>
              <h1 style={{ margin: 0 }}>Workspace Registered!</h1>
              <p className="subtitle" style={{ margin: 0, fontSize: "0.85rem" }}>
                Welcome to EMS Pro, <strong>{submitted.name}</strong>
              </p>
            </div>
          </div>
          <div className="alert alert-success" style={{ marginTop: "10px" }}>
            Workspace: <strong>{submitted.name}</strong> • Tenant Code: <code>{submitted.code}</code>
            {submitted.subdomain && (
              <div>
                Workspace URL: <code>https://{submitted.subdomain}.ems-pro.com</code>
              </div>
            )}
          </div>
          <p className="subtitle" style={{ lineHeight: 1.6 }}>
            Your admin workspace preferences and credentials have been established. Platform approval is underway for{" "}
            <strong>{submitted.name}</strong>. You can sign in directly using <strong>{submitted.email}</strong> as your tenant admin.
          </p>
          <div style={{ display: "flex", gap: "10px", marginTop: "8px" }}>
            <Link
              to={`/login?email=${encodeURIComponent(submitted.email)}&company=${encodeURIComponent(submitted.code)}`}
              className="btn btn-primary"
              style={{ flex: 1, textAlign: "center" }}
            >
              Enter {submitted.name} Workspace
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="center-screen" style={{ padding: "2rem 1rem" }}>
      <form className="card stack auth-card auth-card-wide" onSubmit={handleSubmit} style={{ maxWidth: 560 }}>
        <div>
          <h1>Register your company</h1>
          <p className="subtitle">
            Set up your organization workspace and administrative account on EMS Pro.
          </p>
        </div>

        {formError && <div className="alert alert-error">{formError}</div>}

        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "16px" }}>
          {/* Company Details */}
          <div className={"field" + (fieldErrors.company_name ? " has-error" : "")}>
            <label htmlFor="company_name">Company name *</label>
            <input
              id="company_name"
              placeholder="e.g. Acme Innovations"
              value={form.company_name}
              onChange={(e) => setField("company_name", e.target.value)}
              autoFocus
            />
            {fieldErrors.company_name && <span className="field-error">{fieldErrors.company_name}</span>}
          </div>

          <div className={"field" + (fieldErrors.company_email ? " has-error" : "")}>
            <label htmlFor="company_email">Admin / Company work email *</label>
            <input
              id="company_email"
              type="email"
              placeholder="admin@acme.com"
              value={form.company_email}
              onChange={(e) => setField("company_email", e.target.value)}
            />
            {fieldErrors.company_email && <span className="field-error">{fieldErrors.company_email}</span>}
          </div>

          {/* Desired Workspace URL / Subdomain */}
          <div className={"field" + (fieldErrors.subdomain ? " has-error" : "")}>
            <label htmlFor="subdomain">Desired Workspace URL / Subdomain</label>
            <div style={{ display: "flex", alignItems: "stretch", borderRadius: "6px", overflow: "hidden" }}>
              <span
                style={{
                  background: "var(--bg-muted, #f1f5f9)",
                  border: "1px solid var(--border-color, #cbd5e1)",
                  borderRight: "none",
                  padding: "0 12px",
                  display: "flex",
                  alignItems: "center",
                  fontSize: "0.85rem",
                  color: "var(--text-muted, #64748b)",
                  borderTopLeftRadius: "6px",
                  borderBottomLeftRadius: "6px",
                  whiteSpace: "nowrap",
                }}
              >
                https://
              </span>
              <input
                id="subdomain"
                placeholder="acme"
                value={form.subdomain}
                onChange={(e) => setField("subdomain", e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
                style={{
                  borderRadius: 0,
                  flex: 1,
                  fontFamily: "monospace",
                  fontWeight: 500,
                }}
              />
              <span
                style={{
                  background: "var(--bg-muted, #f1f5f9)",
                  border: "1px solid var(--border-color, #cbd5e1)",
                  borderLeft: "none",
                  padding: "0 12px",
                  display: "flex",
                  alignItems: "center",
                  fontSize: "0.85rem",
                  color: "var(--text-muted, #64748b)",
                  borderTopRightRadius: "6px",
                  borderBottomRightRadius: "6px",
                  whiteSpace: "nowrap",
                }}
              >
                .ems-pro.com
              </span>
            </div>
            {fieldErrors.subdomain && <span className="field-error">{fieldErrors.subdomain}</span>}
          </div>

          {/* Company Size / Employee Count */}
          <div className={"field" + (fieldErrors.company_size ? " has-error" : "")}>
            <label htmlFor="company_size">Company size / Employee count *</label>
            <select
              id="company_size"
              value={form.company_size}
              onChange={(e) => setField("company_size", e.target.value)}
            >
              <option value="">— Select employee range —</option>
              {COMPANY_SIZE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            {fieldErrors.company_size && <span className="field-error">{fieldErrors.company_size}</span>}
          </div>

          {/* Industry & Phone Row */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
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
                  Couldn't load industry list.
                </span>
              )}
            </div>

            <div className={"field" + (fieldErrors.phone ? " has-error" : "")}>
              <label htmlFor="phone">Contact phone (optional)</label>
              <input
                id="phone"
                type="tel"
                placeholder="+91 9876543210"
                value={form.phone}
                onChange={(e) => setField("phone", e.target.value)}
                pattern="^(\+?[0-9\s-]{7,15})?$"
                title="International phone number e.g. +91 9876543210"
              />
              {fieldErrors.phone && <span className="field-error">{fieldErrors.phone}</span>}
            </div>
          </div>

          {/* Password Section */}
          <div style={{ borderTop: "1px solid var(--border-color, #e2e8f0)", paddingTop: "14px", marginTop: "4px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <label style={{ fontWeight: 600, margin: 0 }}>Account Password *</label>
              <button
                type="button"
                className="btn-link"
                style={{ fontSize: "0.8rem", cursor: "pointer", background: "none", border: "none", color: "var(--primary-color, #2563eb)", padding: 0 }}
                onClick={() => setShowPassword((s) => !s)}
              >
                {showPassword ? "Hide password" : "Show password"}
              </button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div className={"field" + (fieldErrors.password ? " has-error" : "")}>
                <label htmlFor="password">Password *</label>
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="Min. 10 chars, 1 letter, 1 digit"
                  value={form.password}
                  onChange={(e) => setField("password", e.target.value)}
                  autoComplete="new-password"
                />
                {fieldErrors.password && <span className="field-error">{fieldErrors.password}</span>}
              </div>

              <div className={"field" + (fieldErrors.confirm_password ? " has-error" : "")}>
                <label htmlFor="confirm_password">Confirm password *</label>
                <input
                  id="confirm_password"
                  type={showPassword ? "text" : "password"}
                  placeholder="Repeat password"
                  value={form.confirm_password}
                  onChange={(e) => setField("confirm_password", e.target.value)}
                  autoComplete="new-password"
                />
                {fieldErrors.confirm_password && (
                  <span className="field-error">{fieldErrors.confirm_password}</span>
                )}
              </div>
            </div>
          </div>
        </div>

        <button className="btn btn-primary" type="submit" disabled={submitting} style={{ marginTop: "12px" }}>
          {submitting ? "Registering company…" : "Register company"}
        </button>

        <div className="text-sm" style={{ textAlign: "center" }}>
          Already have an account? <Link to="/login">Sign in</Link>
        </div>
      </form>
    </div>
  );
}

