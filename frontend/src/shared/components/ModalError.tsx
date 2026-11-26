import React from "react";

export interface ModalErrorProps {
  error: string | null | undefined;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Shared ModalError component:
 * - Renders validation/API errors inside modal dialogs
 * - Keeps error scoped inside the modal next to inputs or at the modal top so errors never leak to background pages
 */
export const ModalError: React.FC<ModalErrorProps> = ({ error, className = "", style }) => {
  if (!error) return null;

  return (
    <div
      role="alert"
      className={`alert alert-error text-sm ${className}`.trim()}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "8px 12px",
        borderRadius: "6px",
        backgroundColor: "#fef2f2",
        color: "#991b1b",
        border: "1px solid #fecaca",
        marginBottom: "12px",
        fontSize: "0.85rem",
        ...style,
      }}
    >
      <span aria-hidden="true" style={{ fontSize: "1rem" }}>⚠️</span>
      <span style={{ flex: 1, wordBreak: "break-word" }}>{error}</span>
    </div>
  );
};
