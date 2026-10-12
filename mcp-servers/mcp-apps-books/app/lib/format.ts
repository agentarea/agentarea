import { formatMoney } from "@shared/money";
import { shortDate } from "@shared/period";

export { shortDate };

export const money = (minor: number, currency: string, locale: string) => formatMoney(minor, currency, locale);
export const wholeMoney = (minor: number, currency: string, locale: string) =>
  formatMoney(minor, currency, locale, { whole: true });
export const compactMoney = (minor: number, currency: string, locale: string) =>
  formatMoney(minor, currency, locale, { compact: true });

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "28 Sep", or "28 Sep 2025" outside the reference year. */
export function dayMonth(date: string, reference?: string) {
  const label = `${Number(date.slice(8, 10))} ${MONTHS[Number(date.slice(5, 7)) - 1]}`;
  return reference && reference.slice(0, 4) !== date.slice(0, 4) ? `${label} ${date.slice(0, 4)}` : label;
}

/** Change against a previous value in percent, or null when there is no base to compare with. */
export function change(value: number, previous: number): number | null {
  if (previous === 0) return value === 0 ? 0 : null;
  return ((value - previous) / Math.abs(previous)) * 100;
}
