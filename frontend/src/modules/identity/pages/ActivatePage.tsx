import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../app/auth-context";
import { landingPathForRole } from "../../../app/role-landing";
import { parseApiError, fieldErrorsFromDetails } from "../../../shared/api/errors";
import { activateAccount, previewActivation } from "../api";
import { activateAccountSchema } from "../schemas";

/** Page 3 (Spec 14.3, public). Route 10 previews the invite; route 11
 * activates and logs the caller straight in (Spec 10.2's own note: "no
 * second login step") — so success here goes directly to the landing
 * page via `establishSession`, never back through `/login`. */
export function ActivatePage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { establishSession } = useAuth();

  const previewQuery = useQuery({
    queryKey: ["activation-preview", token],
    queryFn: () => previewActivation(token as string),
    enabled: Boolean(token),
    retry: false,
  });

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setFormError(null);
    setFieldErrors({});

    const parsed = activateAccountSchema.safeParse({ username, password });
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
      const result = await activateAccount({ token, username: username.trim(), password });
      await establishSession(result.access_token);
      navigate(landingPathForRole("employee"), { replace: true });
    } catch (err) {
      const parsedErr = parseApiError(err);
      setFormError(parsedErr.message);
      if (parsedErr.code === "conflict") {
        setFieldErrors({ username: parsedErr.message });
      } else {
        const fromServer = fieldErrorsFromDetails(parsedErr.details);
        if (Object.keys(fromServer).length > 0) setFieldErrors(fromServer);
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (previewQuery.isLoading) {
    return (
      <div className="center-screen">
        <div className="spinner" />
      </div>
    );
  }

  if (previewQuery.isError) {
    // Route 10 returns 404 for an unknown, expired, or already-redeemed
    // token — the backend's own message ("Invitation not found or has
    // expired.") is already the clear, non-raw state this page needs.
    return (
      <div className="center-screen">
        <div className="card stack auth-card">
          <h1>Invitation no longer valid</h1>
          <p className="subtitle">
            {parseApiError(previewQuery.error).message} Ask your HR admin to resend the
            invitation.
          </p>
        </div>
      </div>
    );
  }

  const preview = previewQuery.data;
  if (!preview) return null;

  return (
    <div className="center-screen">
      <form className="card stack auth-card" onSubmit={handleSubmit}>
        <div>
          <h1>
            Welcome, {preview.first_name}
            {preview.last_name ? ` ${preview.last_name}` : ""}
          </h1>
          <p className="subtitle">
            Finish setting up your account at <strong>{preview.company_name}</strong>. This
            invitation expires {new Date(preview.expires_at).toLocaleString()}.
          </p>
        </div>

        {formError && !fieldErrors.username && <div className="alert alert-error">{formError}</div>}

        <div className={"field" + (fieldErrors.username ? " has-error" : "")}>
          <label htmlFor="username">Choose a username</label>
          <input
            id="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          {fieldErrors.username && <span className="field-error">{fieldErrors.username}</span>}
        </div>

        <div className={"field" + (fieldErrors.password ? " has-error" : "")}>
          <label htmlFor="password">Choose a password</label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {fieldErrors.password && <span className="field-error">{fieldErrors.password}</span>}
        </div>

        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Activating…" : "Activate account"}
        </button>
      </form>
    </div>
  );
}
