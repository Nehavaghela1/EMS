import React, { useState } from "react";

interface CompanyLogoProps {
  name: string;
  logoUrl?: string | null;
  size?: number | string;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * CompanyLogo component:
 * Renders the real company logo if valid; if missing or fails to load,
 * renders a clean neutral company initial block. Never shows an employee avatar.
 */
export const CompanyLogo: React.FC<CompanyLogoProps> = ({
  name,
  logoUrl,
  size = 36,
  className,
  style,
}) => {
  const [imageError, setImageError] = useState(false);

  const initial = (name || "C").trim().charAt(0).toUpperCase();
  const dimension = typeof size === "number" ? `${size}px` : size;

  const baseContainerStyle: React.CSSProperties = {
    width: dimension,
    height: dimension,
    borderRadius: "8px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    overflow: "hidden",
    boxSizing: "border-box",
    ...style,
  };

  if (logoUrl && !imageError) {
    return (
      <div
        className={className}
        style={{
          ...baseContainerStyle,
          background: "#ffffff",
          border: "1px solid rgba(0, 0, 0, 0.08)",
          padding: "2px",
        }}
      >
        <img
          src={logoUrl}
          alt={name}
          onError={() => setImageError(true)}
          style={{
            maxWidth: "100%",
            maxHeight: "100%",
            objectFit: "contain",
          }}
        />
      </div>
    );
  }

  return (
    <div
      className={className}
      style={{
        ...baseContainerStyle,
        background: "#0f172a",
        color: "#ffffff",
        fontWeight: 700,
        fontSize: typeof size === "number" ? `${Math.max(12, Math.floor(size * 0.44))}px` : "0.95rem",
        letterSpacing: "0.02em",
        userSelect: "none",
      }}
    >
      {initial}
    </div>
  );
};
