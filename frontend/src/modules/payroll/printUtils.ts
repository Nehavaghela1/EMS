import { type PayrollItem } from "./api";
import { type Employee } from "../hr/api";
import { type CompanyResponse } from "../identity/api";
import { formatMonthYear } from "./utils";
import { numberToWords } from "./components/PayslipDocument";

export function printCleanPayslip(
  item: PayrollItem,
  employee: Employee | undefined | null,
  company: CompanyResponse | null | undefined
): void {
  const printWindow = window.open("", "_blank");
  if (!printWindow) {
    window.print();
    return;
  }

  const empName = employee ? `${employee.first_name} ${employee.last_name || ""}`.trim() : "Employee";
  const empCode = employee?.employee_code || "—";
  const designation = (employee as any)?.position || (employee as any)?.job_title || "—";
  const department = employee?.department_name || "—";
  const dateOfJoining = employee?.hire_date ? new Date(employee.hire_date).toLocaleDateString("en-GB") : "—";
  const bankAccount: string = item.payout_account_number ?? "—";

  const netPayNum = Number(item.net_salary) || 0;
  const grossPayNum = Number(item.gross_salary) || 0;
  const totalDeductionsNum = Number(item.total_deductions) || 0;
  const reimbursementNum = Number(item.reimbursement_amount) || 0;

  const periodLabel = formatMonthYear(item);
  const title = `Payslip_${empName.replace(/\s+/g, "_")}_${periodLabel.replace(/\s+/g, "_")}`;

  const companyName = company?.name || "Company";
  const addressParts = [company?.address, company?.city, company?.pincode, company?.country].filter(Boolean);
  const companyAddress = addressParts.length > 0 ? addressParts.join(", ") : "";

  const earningsRows =
    item.earnings_json && item.earnings_json.length > 0
      ? item.earnings_json
          .map(
            (e) => `
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 6px 0; color: #334155;">${e.name}</td>
          <td style="padding: 6px 0; text-align: right; font-weight: 600;">₹${Number(e.amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
        </tr>`
          )
          .join("")
      : `
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 6px 0; color: #334155;">Gross Salary</td>
          <td style="padding: 6px 0; text-align: right; font-weight: 600;">₹${grossPayNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
        </tr>`;

  const deductionsRows =
    item.deductions_json && item.deductions_json.length > 0
      ? item.deductions_json
          .map(
            (d) => `
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 6px 0; color: #334155;">${d.name}</td>
          <td style="padding: 6px 0; text-align: right; font-weight: 600; color: #dc2626;">₹${Number(d.amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
        </tr>`
          )
          .join("")
      : `
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 6px 0; color: #334155;">Deductions</td>
          <td style="padding: 6px 0; text-align: right; font-weight: 600; color: #dc2626;">₹${totalDeductionsNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
        </tr>`;

  const reimbursementsNote =
    reimbursementNum > 0
      ? ` + Reimbursements (₹${reimbursementNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })})`
      : "";

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${title}</title>
  <style>
    @page {
      size: A4 portrait;
      margin: 12mm 15mm;
    }
    body {
      background: #ffffff !important;
      color: #0f172a !important;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      margin: 0 !important;
      padding: 24px !important;
      line-height: 1.45;
      font-size: 0.84rem;
    }
    table {
      width: 100%;
      border-collapse: collapse;
    }
  </style>
</head>
<body>
  <div style="max-width: 800px; margin: 0 auto; box-sizing: border-box;">
    <!-- Document Header -->
    <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #0f172a; padding-bottom: 14px; marginBottom: 16px;">
      <div style="flex: 1; padding-right: 16px;">
        <h2 style="margin: 0; font-size: 1.25rem; font-weight: 800; color: #0f172a; letter-spacing: -0.01em;">${companyName}</h2>
        ${companyAddress ? `<p style="margin: 2px 0 0; color: #64748b; font-size: 0.78rem;">${companyAddress}</p>` : ""}
        <div style="display: inline-block; margin-top: 6px; padding: 2px 8px; background: #e0f2fe; color: #0369a1; border-radius: 4px; font-weight: 700; font-size: 0.7rem; text-transform: uppercase;">
          PAYSLIP
        </div>
        <p style="margin: 4px 0 0; font-size: 0.78rem; color: #475569;">Payslip for the month of ${periodLabel}</p>
      </div>
    </div>

    <!-- Employee Metadata Grid -->
    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px 16px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin: 16px 0; background: #f8fafc; font-size: 0.78rem;">
      <div>
        <span style="color: #64748b;">Employee Name:</span>
        <strong style="display: block; color: #0f172a;">${empName}</strong>
      </div>
      <div>
        <span style="color: #64748b;">Employee Code:</span>
        <strong style="display: block; color: #0f172a;">${empCode}</strong>
      </div>
      <div>
        <span style="color: #64748b;">Designation:</span>
        <strong style="display: block; color: #0f172a;">${designation}</strong>
      </div>
      <div>
        <span style="color: #64748b;">Department:</span>
        <strong style="display: block; color: #0f172a;">${department}</strong>
      </div>
      <div>
        <span style="color: #64748b;">Date of Joining:</span>
        <strong style="display: block; color: #0f172a;">${dateOfJoining}</strong>
      </div>
      <div>
        <span style="color: #64748b;">Bank Account:</span>
        <strong style="display: block; color: #0f172a; font-family: monospace;">${bankAccount}</strong>
      </div>
    </div>

    <!-- Attendance Strip -->
    <div style="display: flex; justify-content: space-around; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 12px; margin-bottom: 16px; background: #ffffff; font-size: 0.78rem; text-align: center;">
      <div>
        <span style="color: #64748b;">Working Days</span>
        <strong style="display: block; color: #0f172a;">${item.working_days || "—"}</strong>
      </div>
      <div>
        <span style="color: #64748b;">Present Days</span>
        <strong style="display: block; color: #16a34a;">${item.present_days || "—"}</strong>
      </div>
      <div>
        <span style="color: #64748b;">Paid Leave</span>
        <strong style="display: block; color: #0284c7;">${item.paid_leave_days || "0.0"}</strong>
      </div>
      <div>
        <span style="color: #64748b;">Loss of Pay (LOP)</span>
        <strong style="display: block; color: #dc2626;">${item.lop_days || "0.0"}</strong>
      </div>
    </div>

    <!-- Earnings & Deductions Tables -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;">
      <!-- Earnings -->
      <div>
        <table style="font-size: 0.78rem;">
          <thead>
            <tr style="border-bottom: 1.5px solid #cbd5e1;">
              <th style="text-align: left; padding: 6px 0; color: #475569; text-transform: uppercase;">EARNINGS</th>
              <th style="text-align: right; padding: 6px 0; color: #475569; text-transform: uppercase;">AMOUNT</th>
            </tr>
          </thead>
          <tbody>
            ${earningsRows}
            <tr style="border-top: 1.5px solid #cbd5e1; font-weight: 700;">
              <td style="padding: 8px 0; color: #0f172a;">Total Earnings</td>
              <td style="padding: 8px 0; text-align: right; color: #16a34a;">₹${grossPayNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Deductions -->
      <div>
        <table style="font-size: 0.78rem;">
          <thead>
            <tr style="border-bottom: 1.5px solid #cbd5e1;">
              <th style="text-align: left; padding: 6px 0; color: #475569; text-transform: uppercase;">DEDUCTIONS</th>
              <th style="text-align: right; padding: 6px 0; color: #475569; text-transform: uppercase;">AMOUNT</th>
            </tr>
          </thead>
          <tbody>
            ${deductionsRows}
            <tr style="border-top: 1.5px solid #cbd5e1; font-weight: 700;">
              <td style="padding: 8px 0; color: #0f172a;">Total Deductions</td>
              <td style="padding: 8px 0; text-align: right; color: #dc2626;">₹${totalDeductionsNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Total Net Payable Bar -->
    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 16px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
      <div>
        <div style="font-weight: 800; color: #0f172a; font-size: 0.88rem;">TOTAL NET PAYABLE</div>
        <div style="font-size: 0.72rem; color: #64748b;">Gross Earnings - Total Deductions${reimbursementsNote}</div>
      </div>
      <div style="font-size: 1.25rem; font-weight: 800; color: #0f172a;">
        ₹${netPayNum.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
      </div>
    </div>

    <!-- Amount in words -->
    <div style="text-align: right; font-size: 0.75rem; color: #475569; margin-bottom: 24px;">
      <strong>Amount In Words: </strong> ${numberToWords(netPayNum)}
    </div>

    <div style="text-align: center; font-size: 0.72rem; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 14px;">
      — This is a computer-generated payroll document and requires no signature. —
    </div>
  </div>
</body>
</html>`;

  printWindow.document.open();
  printWindow.document.write(html);
  printWindow.document.close();
  printWindow.focus();
  setTimeout(() => {
    printWindow.print();
  }, 250);
}
