import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../../app/auth-context";
import { parseApiError, type ParsedApiError } from "../../../shared/api/errors";

interface LocationState {
  from?: string;
  passwordReset?: boolean;
}

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const locationState = location.state as LocationState | null;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [companyCode, setCompanyCode] = useState("");
  const [companies, setCompanies] = useState<string[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password, companyCode || undefined);
      const dest = locationState?.from ?? "/dashboard";
      navigate(dest, { replace: true });
    } catch (err) {
      const parsed = parseApiError(err);
      setError(parsed);
      if (parsed.code === "company_required") {
        const list = parsed.details?.companies;
        setCompanies(Array.isArray(list) ? (list as string[]) : []);
      } else {
        setCompanies(null);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="center-screen">
      <form className="card stack" style={{ width: 360 }} onSubmit={handleSubmit}>
        <div>
          <h1 style={{ margin: "0 0 4px", fontSize: 20 }}>EMS Pro</h1>
          <p className="text-muted" style={{ margin: 0 }}>
            Sign in to your account
          </p>
        </div>

        {!error && locationState?.passwordReset && (
          <div className="alert alert-success">Password reset. Sign in with your new password.</div>
        )}
        {error && <div className="alert alert-error">{error.message}</div>}

        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {companies && (
          <div className="field">
            <label htmlFor="company_code">
              This email is registered at more than one company — enter the company code
            </label>
            <input
              id="company_code"
              type="text"
              required
              value={companyCode}
              onChange={(e) => setCompanyCode(e.target.value)}
            />
            <span className="text-muted" style={{ fontSize: 12 }}>
              Companies on this email: {companies.join(", ")}
            </span>
          </div>
        )}

        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>

        <div className="row-between" style={{ fontSize: 13 }}>
          <Link to="/register-company">Register your company</Link>
          <Link to="/forgot-password">Forgot password?</Link>
        </div>
      </form>
    </div>
  );
}
