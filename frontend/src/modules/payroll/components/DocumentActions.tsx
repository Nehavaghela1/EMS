import React from "react";

interface DocumentActionsProps {
  onDownload: () => void;
  onPrint?: () => void;
  documentElement?: HTMLElement | null;
  documentTitle?: string;
  downloadLabel?: string;
  printLabel?: string;
  isDownloading?: boolean;
  className?: string;
}

/**
 * Standard action bar on every payroll document.
 * Thin outline inline SVG icons, blue text links separated by middot.
 */
export const DocumentActions: React.FC<DocumentActionsProps> = ({
  onDownload,
  onPrint,
  documentElement,
  documentTitle,
  downloadLabel = "Download",
  printLabel = "Print",
  isDownloading = false,
  className = "no-print",
}) => {
  const handlePrintClick = () => {
    if (onPrint) {
      onPrint();
      return;
    }

    // Default clean print behavior: open document in its own tab
    const printTarget =
      documentElement ||
      (document.querySelector(".modal-backdrop [data-print-content='true']") as HTMLElement) ||
      (document.querySelector("[data-print-content='true']") as HTMLElement);

    if (printTarget) {
      const printWindow = window.open("", "_blank");
      if (printWindow) {
        const styles = Array.from(document.querySelectorAll("style, link[rel='stylesheet']"))
          .map((el) => el.outerHTML)
          .join("\n");
        const title = documentTitle || document.title || "Document";

        printWindow.document.open();
        printWindow.document.write(`<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${title}</title>
  ${styles}
  <style>
    body {
      background: #ffffff !important;
      margin: 0 !important;
      padding: 20px !important;
      display: block !important;
    }
    .no-print {
      display: none !important;
    }
  </style>
</head>
<body>
  ${printTarget.outerHTML}
</body>
</html>`);
        printWindow.document.close();
        printWindow.focus();
        setTimeout(() => {
          printWindow.print();
        }, 250);
        return;
      }
    }

    // Fallback if window.open was blocked
    window.print();
  };
  return (
    <div
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "8px",
        fontSize: "0.84rem",
        fontWeight: 600,
      }}
    >
      <button
        type="button"
        onClick={onDownload}
        disabled={isDownloading}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          color: "#2563eb",
          cursor: isDownloading ? "not-allowed" : "pointer",
          display: "inline-flex",
          alignItems: "center",
          gap: "5px",
          fontFamily: "inherit",
          fontSize: "inherit",
          fontWeight: "inherit",
          textDecoration: "none",
        }}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        <span>{isDownloading ? "Downloading..." : downloadLabel}</span>
      </button>

      <span style={{ color: "#94a3b8", userSelect: "none" }}>•</span>

      <button
        type="button"
        onClick={handlePrintClick}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          color: "#2563eb",
          cursor: "pointer",
          display: "inline-flex",
          alignItems: "center",
          gap: "5px",
          fontFamily: "inherit",
          fontSize: "inherit",
          fontWeight: "inherit",
          textDecoration: "none",
        }}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="6 9 6 2 18 2 18 9" />
          <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
          <rect width="12" height="8" x="6" y="14" />
        </svg>
        <span>{printLabel}</span>
      </button>
    </div>
  );
};
