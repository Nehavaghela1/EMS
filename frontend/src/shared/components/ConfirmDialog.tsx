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
 * delete a department, etc. */
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
  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal stack" onClick={(e) => e.stopPropagation()}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <p className="text-muted" style={{ margin: 0 }}>
          {message}
        </p>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel} disabled={busy}>
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
