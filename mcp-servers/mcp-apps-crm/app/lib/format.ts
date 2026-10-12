const DAY = 86_400_000;

const formats = new Map<string, Intl.NumberFormat>();
function moneyFormat(currency: string, compact: boolean): Intl.NumberFormat {
  const key = `${currency}:${compact}`;
  let format = formats.get(key);
  if (!format) {
    format = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
      notation: compact ? "compact" : "standard",
      maximumFractionDigits: compact ? 1 : 0,
    });
    formats.set(key, format);
  }
  return format;
}

export const formatMoney = (value: number, currency: string) => moneyFormat(currency, false).format(value);
/** Compact above 100k: "₽1.2M", "$48K". */
export const formatMoneyShort = (value: number, currency: string) =>
  moneyFormat(currency, Math.abs(value) >= 100_000).format(value);
export const formatPercent = (value: number) => `${Math.round(value * 100)}%`;

export const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });

/** A calendar date ("2026-10-31") stays that date in every timezone. */
export const formatDay = (day: string) =>
  new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });

export const formatDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

const startOfDay = (ms: number) => {
  const date = new Date(ms);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
};

/** Calendar days from `reference` to `iso` in the viewer's timezone. */
export const dayOffset = (iso: string, reference: string) =>
  Math.round((startOfDay(Date.parse(iso)) - startOfDay(Date.parse(reference))) / DAY);

/** "Today", "Tomorrow", "In 3d", "Yesterday", "4d ago" against the CRM's clock. */
export function relativeDay(iso: string, reference: string): string {
  const offset = dayOffset(iso, reference);
  if (offset === 0) return "Today";
  if (offset === 1) return "Tomorrow";
  if (offset === -1) return "Yesterday";
  return offset > 0 ? `In ${offset}d` : `${-offset}d ago`;
}

/** Value of a `<input type="date">` for a moment, in the viewer's timezone. */
export function dateInputValue(ms: number): string {
  const date = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
