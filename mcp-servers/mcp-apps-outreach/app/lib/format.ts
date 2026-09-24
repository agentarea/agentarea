const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const integer = new Intl.NumberFormat("en-US");
const compactCurrency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});
const fullCurrency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const formatNumber = (value: number) => integer.format(value);
export const formatCurrency = (value: number) => (value >= 10_000 ? compactCurrency : fullCurrency).format(value);
export const formatPercent = (value: number, digits = 1) => `${(value * 100).toFixed(digits).replace(/\.0$/, "")}%`;

/** "3h ago", measured against the dataset's own clock rather than the viewer's. */
export function timeAgo(iso: string, reference: string): string {
  const delta = Date.parse(reference) - Date.parse(iso);
  if (delta < MINUTE) return "just now";
  if (delta < HOUR) return `${Math.floor(delta / MINUTE)}m ago`;
  if (delta < DAY) return `${Math.floor(delta / HOUR)}h ago`;
  if (delta < 30 * DAY) return `${Math.floor(delta / DAY)}d ago`;
  return formatDate(iso);
}

export function timeUntil(iso: string, reference: string): string {
  const delta = Date.parse(iso) - Date.parse(reference);
  if (delta <= HOUR) return "due now";
  if (delta < DAY) return `in ${Math.round(delta / HOUR)}h`;
  return `in ${Math.round(delta / DAY)}d`;
}

export const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

export const formatDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }) + " UTC";

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
