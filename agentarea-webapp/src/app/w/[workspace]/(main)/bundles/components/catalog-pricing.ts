// How a catalog connection's price reads. The amounts come priced from the
// server (vendor rate, or what billing charges on the platform's key); this
// only formats them.

import type { CatalogToolPrice } from "@/api/client/types.gen";

const PER_CALL_UNITS = new Set(["call", "request"]);
// What "always on" means for a monthly figure: an average month in hours.
const HOURS_PER_MONTH = 730;

/**
 * "0,04 ₽" in the viewer's locale; a call can cost a fraction of a kopeck.
 * `whole` rounds a large estimate to whole units: "≈ 774 ₽", not "773,80 ₽".
 */
export function formatMoney(
  amount: string | number,
  currency: string,
  locale: string,
  { whole = false } = {}
): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 4,
  }).format(Number(amount));
}

/** "0,04": the amount alone, for a chip whose icon already names the currency. */
export function formatPriceNumber(amount: string, locale: string): string {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(Number(amount));
}

/** Whether the price is per call rather than per unit of something a call uses. */
export function isPerCall(price: CatalogToolPrice): boolean {
  return PER_CALL_UNITS.has(price.unit);
}

/** What an hour costs over a month of running without a stop. */
export function monthlyFromHourly(hourly: string): number {
  return Number(hourly) * HOURS_PER_MONTH;
}

/** "0.1" vCPU: a reserved share of a core, without trailing zeros. */
export function formatVcpu(vcpu: string, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(
    Number(vcpu)
  );
}

/** "128 MiB" below a GiB, "1.5 GiB" from there on. */
export function formatMemory(memoryGib: string, locale: string): string {
  const gib = Number(memoryGib);
  if (gib < 1) {
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(gib * 1024)} MiB`;
  }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(gib)} GiB`;
}
