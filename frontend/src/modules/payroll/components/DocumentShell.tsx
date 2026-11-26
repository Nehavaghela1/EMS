import React from "react";
import { type CompanyResponse } from "../../identity/api";

interface DocumentShellProps {
  title: string;
  subtitle?: string;
  company?: CompanyResponse | null;
  children: React.ReactNode;
  footerNote?: string;
}

/**
 * Standard DocumentShell used for Payslip, Tax Worksheet, Salary Structure and Salary Certificate.
 * Strictly fits on one A4 page with 12mm-15mm margins in print and clean card container in view mode.
 */
export const DocumentShell: React.FC<DocumentShellProps> = ({
  title,
  subtitle,
  company,
  children,
  footerNote = "— This is a system-generated official document and requires no signature. —",
}) => {
  const companyLogoUrl = company?.logo_url;
  const companyName = company?.name || "Company";
  const addressParts = [company?.address, company?.city, company?.pincode, company?.country].filter(Boolean);
  const companyAddress = addressParts.length > 0 ? addressParts.join(", ") : "";

  return (
    <div
      className="printable-document-shell"
      style={{
        width: "100%",
        maxWidth: "800px",
        margin: "0 auto",
        backgroundColor: "#ffffff",
        color: "#0f172a",
        padding: "24px 28px",
        boxSizing: "border-box",
        fontFamily: "inherit",
        fontSize: "0.84rem",
        lineHeight: 1.45,
      }}
    >
      {/* Document Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          borderBottom: "2px solid #0f172a",
          paddingBottom: "14px",
          marginBottom: "16px",
        }}
      >
        <div style={{ flex: 1, paddingRight: "16px" }}>
          <h2
            style={{
              margin: 0,
              fontSize: "1.25rem",
              fontWeight: 800,
              color: "#0f172a",
              letterSpacing: "-0.01em",
            }}
          >
            {companyName}
          </h2>
          {companyAddress && (
            <div
              style={{
                fontSize: "0.76rem",
                color: "#64748b",
                marginTop: "3px",
                lineHeight: 1.35,
              }}
            >
              {companyAddress}
            </div>
          )}
          <div
            style={{
              marginTop: "8px",
              display: "inline-block",
              background: "#f1f5f9",
              padding: "2px 8px",
              borderRadius: "4px",
              fontSize: "0.74rem",
              fontWeight: 700,
              color: "#334155",
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            {title}
          </div>
          {subtitle && (
            <div
              style={{
                fontSize: "0.78rem",
                fontWeight: 600,
                color: "#475569",
                marginTop: "4px",
              }}
            >
              {subtitle}
            </div>
          )}
        </div>

        {/* Company Logo or dynamic fallback mark */}
        {companyLogoUrl ? (
          <img
            src={companyLogoUrl}
            alt={companyName}
            style={{
              maxHeight: "52px",
              maxWidth: "140px",
              objectFit: "contain",
            }}
          />
        ) : (
          <div
            style={{
              height: "44px",
              padding: "0 12px",
              borderRadius: "8px",
              background: "#0f172a",
              color: "#ffffff",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 700,
              fontSize: "0.85rem",
              letterSpacing: "0.05em",
            }}
          >
            {companyName.slice(0, 3).toUpperCase()}
          </div>
        )}
      </div>

      {/* Document Body */}
      <div style={{ width: "100%" }}>{children}</div>

      {/* Footer */}
      {footerNote && (
        <div
          style={{
            borderTop: "1px solid #e2e8f0",
            marginTop: "18px",
            paddingTop: "10px",
            textAlign: "center",
            fontSize: "0.72rem",
            color: "#94a3b8",
          }}
        >
          {footerNote}
        </div>
      )}
    </div>
  );
};
