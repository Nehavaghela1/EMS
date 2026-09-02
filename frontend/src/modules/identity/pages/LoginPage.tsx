import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../../app/auth-context";
import { parseApiError, type ParsedApiError } from "../../../shared/api/errors";
import { PasswordInput } from "../../../shared/components/PasswordInput";

interface LocationState {
  from?: string;
  passwordReset?: boolean;
}

/** Part 3: a locked-out user should be told when the lock clears, not just
 * that it's locked (Spec 9.4 already returns `locked_until` — this is the
 * one place in the app that formats it for a human instead of showing the
 * server's raw ISO timestamp verbatim). Every other error still surfaces
 * the server's own message unchanged. */
function formatLoginError(error: ParsedApiError): string {
  if (error.code === "account_locked" && typeof error.details?.locked_until === "string") {
    const until = new Date(error.details.locked_until).toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
    });
    return `Too many failed attempts. Try again after ${until}, or reset your password below.`;
  }
  return error.message;
}

export function LoginPage() {
  const { login, sessionExpired } = useAuth();
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
      <form className="card stack auth-card" onSubmit={handleSubmit}>
        <div>
          <h1>EMS</h1>
          <p className="subtitle">Sign in to your account</p>
        </div>

        {!error && locationState?.passwordReset && (
          <div className="alert alert-success">Password reset. Sign in with your new password.</div>
        )}
        {!error && !locationState?.passwordReset && sessionExpired && (
          <div className="alert alert-error">Your session expired. Sign in again to continue.</div>
        )}
        {error && <div className="alert alert-error">{formatLoginError(error)}</div>}

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

        <PasswordInput
          id="password"
          label="Password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          required
        />

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
            <span className="text-xs text-muted">Companies on this email: {companies.join(", ")}</span>
          </div>
        )}

        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>

        <div className="row-between text-sm">
          <Link to="/register-company">Register your company</Link>
          <Link to="/forgot-password">Forgot password?</Link>
        </div>
      </form>
    </div>
  );
}
