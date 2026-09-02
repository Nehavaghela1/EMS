import { useId, useState } from "react";

interface Props {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: "current-password" | "new-password";
  required?: boolean;
  autoFocus?: boolean;
  error?: string;
  id?: string;
}

/** Every password field in the app (login, activation, reset,
 * change-password) goes through this — one real, accessible toggle
 * button (aria-pressed + aria-label, not a bare icon with no name) rather
 * than four independent copies of the same eye icon. */
export function PasswordInput({
  label,
  value,
  onChange,
  autoComplete = "current-password",
  required = false,
  autoFocus = false,
  error,
  id,
}: Props) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const [visible, setVisible] = useState(false);

  return (
    <div className={"field" + (error ? " has-error" : "")}>
      <label htmlFor={inputId}>{label}</label>
      <div className="password-field">
        <input
          id={inputId}
          type={visible ? "text" : "password"}
          autoComplete={autoComplete}
          required={required}
          autoFocus={autoFocus}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          type="button"
          className="password-toggle"
          aria-pressed={visible}
          aria-label={visible ? "Hide password" : "Show password"}
          onClick={() => setVisible((v) => !v)}
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
      {error && <span className="field-error">{error}</span>}
    </div>
  );
}
