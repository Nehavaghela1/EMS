const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/**
 * Shared formatter to format Month and Year from a payslip item.
 * Never parses UUID hyphens.
 */
export function formatMonthYear(item: { month?: number | null; year?: number | null } | null | undefined): string {
  if (!item || !item.month || !item.year) {
    return "Statement";
  }
  const monthName = MONTH_NAMES[item.month - 1] || `Month ${item.month}`;
  return `${monthName} ${item.year}`;
}

export function formatShortMonthYear(item: { month?: number | null; year?: number | null } | null | undefined): string {
  if (!item || !item.month || !item.year) {
    return "—";
  }
  const monthName = MONTH_NAMES[item.month - 1] || "";
  const shortMonth = monthName.slice(0, 3).toUpperCase();
  return `${shortMonth} ${item.year}`;
}

/**
 * Downloads an HTML element's rendered contents directly as a standalone HTML document file.
 * Generates an actual file download without opening the print dialog.
 */
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
