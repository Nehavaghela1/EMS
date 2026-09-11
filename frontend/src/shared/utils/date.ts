/**
 * Formats any date string or Date object to DD/MM/YYYY.
 * Handles ISO strings (YYYY-MM-DD, YYYY-MM-DDTHH:mm:ssZ), Date instances, and timestamp strings.
 * Returns fallback (default "—") if invalid or empty.
 */
export function formatDate(val: string | Date | null | undefined, fallback: string = "—"): string {
  if (!val) return fallback;

  if (typeof val === "string") {
    const trimmed = val.trim();
    if (!trimmed) return fallback;

    // Check if it's already YYYY-MM-DD exactly
    const ymdMatch = /^(\d{4})-(\d{2})-(\d{2})/.exec(trimmed);
    if (ymdMatch) {
      const [, yyyy, mm, dd] = ymdMatch;
      return `${dd}/${mm}/${yyyy}`;
    }
  }

  const d = typeof val === "string" ? new Date(val) : val;
  if (isNaN(d.getTime())) return fallback;

  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();

  return `${dd}/${mm}/${yyyy}`;
}

/**
 * Formats date and time to DD/MM/YYYY, HH:mm
 */
export function formatDateTime(val: string | Date | null | undefined, fallback: string = "—"): string {
  if (!val) return fallback;
  const d = typeof val === "string" ? new Date(val) : val;
  if (isNaN(d.getTime())) return fallback;

  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");

  return `${dd}/${mm}/${yyyy}, ${hh}:${min}`;
}
