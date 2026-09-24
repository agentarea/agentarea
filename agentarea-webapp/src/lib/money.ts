export const DEFAULT_CURRENCY = "USD";

/**
 * Format a money amount in the billing currency the workspace actually pays
 * in (see `useCurrency()` in `@/hooks/useCurrency`, backed by C2
 * `GET /v1/pricing/currency`) — never assume USD.
 *
 * A per-task LLM cost is routinely a fraction of a cent, so:
 * - amounts under one minor unit (a cent, for USD/RUB) keep 4 fraction
 *   digits (`$0.0071`, not `$0.00`) so the real cost survives
 * - one minor unit and up formats as ordinary currency (2 digits)
 * - a positive amount too small to show even at 4 digits (would format as
 *   all zeros) renders as "< " + the smallest displayable unit, so it never
 *   reads as exactly zero
 */
export function formatMoney(
  amount: number,
  currency: string = DEFAULT_CURRENCY,
  locale: string = "en"
): string {
  const n = Number(amount);
  const value = Number.isFinite(n) ? n : 0;
  const abs = Math.abs(value);

  const fractionDigits = abs > 0 && abs < 0.01 ? 4 : 2;
  const format = (v: number) =>
    new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(v);

  const smallestUnit = 10 ** -fractionDigits;
  if (abs > 0 && abs < smallestUnit / 2) {
    return `< ${format(smallestUnit)}`;
  }

  return format(value);
}

/**
 * The currency's own symbol/sign (e.g. "$", "₽"), for places that render an
 * amount input with the symbol as a prefix rather than through
 * `formatMoney`. Falls back to the currency code itself if Intl has no
 * narrower symbol for it.
 */
export function getCurrencySymbol(
  currency: string = DEFAULT_CURRENCY,
  locale: string = "en"
): string {
  const parts = new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
  }).formatToParts(0);
  return parts.find((part) => part.type === "currency")?.value ?? currency;
}
