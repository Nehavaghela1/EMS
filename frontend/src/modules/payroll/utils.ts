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
export function downloadDocumentAsHtml(element: HTMLElement, filename: string): void {
  const styles = Array.from(document.querySelectorAll("style, link[rel='stylesheet']"))
    .map((el) => el.outerHTML)
    .join("\n");

  const htmlContent = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${filename.replace(/\.html$/i, "")}</title>
  ${styles}
  <style>
    body {
      background-color: #ffffff;
      margin: 20px auto;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .no-print {
      display: none !important;
    }
  </style>
</head>
<body>
  ${element.outerHTML}
</body>
</html>`;

  const blob = new Blob([htmlContent], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".html") ? filename : `${filename}.html`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
