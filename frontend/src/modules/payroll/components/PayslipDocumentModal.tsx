import React, { useRef, useState } from "react";
import { downloadMyPayslipPdf, type PayrollItem } from "../api";
import { type Employee } from "../../hr/api";
import { type CompanyResponse } from "../../identity/api";
import { DocumentActions } from "./DocumentActions";
import { triggerBlobDownload } from "../utils";
import { PayslipDocument } from "./PayslipDocument";

interface PayslipDocumentModalProps {
  isOpen: boolean;
  onClose: () => void;
  item: PayrollItem;
  employee?: Employee;
  company?: CompanyResponse | null;
  monthName: string;
  year: number;
}

export const PayslipDocumentModal: React.FC<PayslipDocumentModalProps> = ({
  isOpen,
  onClose,
  item,
  employee,
  company,
  monthName,
  year,
}) => {
  if (!isOpen) return null;

  const empName = employee ? `${employee.first_name} ${employee.last_name || ""}`.trim() : "Employee";
  const cleanPeriod = monthName.includes(String(year)) ? monthName : `${monthName} ${year}`;
  const contentRef = useRef<HTMLDivElement>(null);
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const blob = await downloadMyPayslipPdf(item.id);
      const periodStr = cleanPeriod.replace(/\s+/g, "_");
      triggerBlobDownload(
        blob,
        `Payslip_${empName.replace(/\s+/g, "_")}_${periodStr}.pdf`
      );
    } catch {
      // Fallback
      window.print();
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div
      className="modal-backdrop"
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(15, 23, 42, 0.7)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 99999,
        padding: "1rem",
        overflowY: "auto",
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{
          width: "100%",
          maxWidth: "840px",
          backgroundColor: "#ffffff",
          borderRadius: "12px",
          boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
          overflow: "hidden",
          maxHeight: "92vh",
          display: "flex",
          flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Control Bar (Hidden on print) */}
        <div
          className="no-print"
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "12px 24px",
            borderBottom: "1px solid #e2e8f0",
            backgroundColor: "#f8fafc",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "1.1rem" }}>📄</span>
            <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "#0f172a" }}>
              Payslip — {cleanPeriod}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <DocumentActions
              onDownload={handleDownload}
              isDownloading={downloading}
              documentElement={contentRef.current}
              documentTitle={`Payslip_${empName}_${cleanPeriod}`}
            />
            <button
              type="button"
              className="modal-close-btn"
              aria-label="Close"
              onClick={onClose}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "32px",
                height: "32px",
                border: "1px solid #cbd5e1",
                borderRadius: "6px",
                backgroundColor: "#ffffff",
                cursor: "pointer",
                color: "#64748b",
                fontSize: "1rem",
              }}
            >
              ✕
            </button>
          </div>
        </div>

        {/* Modal Printable Content */}
        <div
          ref={contentRef}
          data-print-content="true"
          style={{
            overflowY: "auto",
            padding: "16px",
            flex: 1,
            backgroundColor: "#ffffff",
          }}
        >
          <PayslipDocument
            item={item}
            employee={employee}
            company={company}
            monthName={monthName}
            year={year}
          />
        </div>
      </div>
    </div>
  );
};
