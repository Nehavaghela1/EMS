import { useEffect, useRef } from "react";

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Used for every destructive action (Spec 14.4) — deactivate an employee,
 * delete a department, etc.
 *
 * Escape-to-cancel and focus-on-open (hardening pass): neither existed
 * before — a keyboard user opening this dialog had no way to close it
 * without a mouse, and focus stayed wherever it was on the page behind it.
 * Focus lands on Cancel, not the (often destructive) Confirm button, so
 * pressing Enter right after the dialog opens never fires the dangerous
 * action by accident. */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onCancel]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div
        className="modal stack"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h3 id="confirm-dialog-title" style={{ margin: 0, fontSize: "1.05rem", fontWeight: 600, color: "#1e293b" }}>{title}</h3>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onCancel}
            disabled={busy}
            title="Close"
          >
            ✕
          </button>
        </div>
        <div className="modal-body" style={{ padding: "18px 20px" }}>
          <p style={{ margin: 0, fontSize: "0.88rem", color: "#64748b", lineHeight: 1.5 }}>
            {message}
          </p>
        </div>
        <div className="modal-footer" style={{ padding: "12px 20px" }}>
          <button ref={cancelRef} className="btn btn-outline" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            className={danger ? "btn btn-danger" : "btn btn-primary"}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
