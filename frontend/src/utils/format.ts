/**
 * Display helpers shared by every screen that renders a score, a GPA or a
 * timestamp. Values arrive from the API as strings (Decimal) or numbers, and
 * anything unparseable is shown as it came rather than as NaN.
 */

/** A score, weight or grade point, to at most two decimals. */
export function formatNumber(value: string | number | null | undefined, fallback = ""): string {
  if (value === null || value === undefined || value === "") return fallback;
  const n = Number(value);
  return Number.isNaN(n)
    ? String(value)
    : n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** An ISO date as "3 Mar 2025". */
export function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** An ISO timestamp as "Mar 3, 2025, 4:05 PM". */
export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
