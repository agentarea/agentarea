// How a catalog connection's price reads. The amounts come priced from the
// server (vendor rate, or what billing charges on the platform's key); this
// only formats them.

import type { CatalogToolPrice } from "@/api/client/types.gen";

const PER_CALL_UNITS = new Set(["call", "request"]);

/** "0,04 ₽" in the viewer's locale; a call can cost a fraction of a kopeck. */
export function formatPriceAmount(
  price: CatalogToolPrice,
  locale: string
): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: price.currency,
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(Number(price.amount));
}

/** Whether the price is per call rather than per unit of something a call uses. */
export function isPerCall(price: CatalogToolPrice): boolean {
  return PER_CALL_UNITS.has(price.unit);
}
