import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { forgotPassword, resetPassword } from "../api";
import { forgotPasswordEmailSchema, resetPasswordSchema } from "../schemas";
import { parseApiError, fieldErrorsFromDetails } from "../../../shared/api/errors";
import { PasswordInput } from "../../../shared/components/PasswordInput";

type Step = "request" | "reset";

/** Page 4 (Spec 14.3, public). Two steps in one page per Spec 7.9/9.3:
 * step one always returns the same message regardless of whether the
 * account exists — the UI must never reveal which, so it shows that
 * message verbatim and moves on to step two unconditionally. */
export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("request");
  const [email, setEmail] = useState("");
  const [requestMessage, setRequestMessage] = useState<string | null>(null);

  const [otp, setOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleRequest(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setFieldErrors({});

    const parsed = forgotPasswordEmailSchema.safeParse(email);
    if (!parsed.success) {
      setFieldErrors({ email: parsed.error.issues[0]?.message ?? "Enter a valid email address" });
      return;
    }

    setSubmitting(true);
    try {
      const { message } = await forgotPassword(email.trim());
      setRequestMessage(message);
      setStep("reset");
    } catch (err) {
      // A genuine failure here (rate-limited, network, 500) is a different
      // class of problem than "does this email exist" — still surfaced,
      // just never used to imply an account match either way.
      setFormError(parseApiError(err).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReset(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setFieldErrors({});

    const parsed = resetPasswordSchema.safeParse({ otp, new_password: newPassword });
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
      await resetPassword({ email: email.trim(), otp: otp.trim(), new_password: newPassword });
      navigate("/login", { replace: true, state: { passwordReset: true } });
    } catch (err) {
      // Wrong code, expired code, and attempts-exhausted all come back as
      // the same "Invalid or expired code." (Spec 9.3's enumeration-safety
      // principle) — shown as-is, no special-casing needed.
      const parsedErr = parseApiError(err);
      setFormError(parsedErr.message);
      const fromServer = fieldErrorsFromDetails(parsedErr.details);
      if (Object.keys(fromServer).length > 0) setFieldErrors(fromServer);
    } finally {
      setSubmitting(false);
    }
  }

  if (step === "request") {
    return (
      <div className="center-screen">
        <form className="card stack auth-card" onSubmit={handleRequest}>
          <div>
            <h1>Forgot password</h1>
            <p className="subtitle">
              Enter your account email and we'll send a reset code if it matches an account.
            </p>
          </div>

          {formError && <div className="alert alert-error">{formError}</div>}

          <div className={"field" + (fieldErrors.email ? " has-error" : "")}>
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {fieldErrors.email && <span className="field-error">{fieldErrors.email}</span>}
          </div>

          <button className="btn btn-primary" type="submit" disabled={submitting}>
            {submitting ? "Sending…" : "Send reset code"}
          </button>

          <div className="text-sm">
            <Link to="/login">Back to sign in</Link>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="center-screen">
      <form className="card stack auth-card" onSubmit={handleReset}>
        <div>
          <h1>Enter your reset code</h1>
        </div>

        {requestMessage && <div className="alert alert-success">{requestMessage}</div>}
        {formError && <div className="alert alert-error">{formError}</div>}

        <div className={"field" + (fieldErrors.otp ? " has-error" : "")}>
          <label htmlFor="otp">Reset code</label>
          <input id="otp" value={otp} onChange={(e) => setOtp(e.target.value)} />
          {fieldErrors.otp && <span className="field-error">{fieldErrors.otp}</span>}
        </div>

        <PasswordInput
          id="new_password"
          label="New password"
          value={newPassword}
          onChange={setNewPassword}
          autoComplete="new-password"
          error={fieldErrors.new_password}
        />

        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Resetting…" : "Reset password"}
        </button>

        <div className="row-between text-sm">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setStep("request")}>
            Use a different email
          </button>
          <Link to="/login">Back to sign in</Link>
        </div>
      </form>
    </div>
  );
}
