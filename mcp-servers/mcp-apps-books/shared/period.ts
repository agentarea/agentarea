import type { PeriodKind } from "./books.ts";

const DAY = 86_400_000;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export const dateOf = (ms: number) => new Date(ms).toISOString().slice(0, 10);
/** A real calendar day as YYYY-MM-DD: some engines roll "02-30" over to March instead of refusing it. */
export const isDate = (value: string) => {
  if (!DATE.test(value)) return false;
  const ms = Date.parse(`${value}T00:00:00Z`);
  return !Number.isNaN(ms) && dateOf(ms) === value;
};
export const msOf = (date: string) => Date.parse(`${date}T00:00:00Z`);
export const addDays = (date: string, days: number) => dateOf(msOf(date) + days * DAY);
export const daysBetween = (from: string, to: string) => Math.round((msOf(to) - msOf(from)) / DAY);
export const monthOf = (date: string) => date.slice(0, 7);

export function addMonths(date: string, months: number): string {
  const d = new Date(msOf(date));
  const day = d.getUTCDate();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() + months);
  const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
  d.setUTCDate(Math.min(day, last));
  return dateOf(d.getTime());
}

/** Months `YYYY-MM` from the one holding `from` to the one holding `to`, inclusive. */
export function monthsBetween(from: string, to: string): string[] {
  const months: string[] = [];
  for (let cursor = `${monthOf(from)}-01`; monthOf(cursor) <= monthOf(to); cursor = addMonths(cursor, 1)) {
    months.push(monthOf(cursor));
  }
  return months;
}

export interface Period {
  kind: PeriodKind;
  from: string;
  to: string;
  label: string;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const monthLabel = (month: string) => `${MONTHS[Number(month.slice(5, 7)) - 1]} ${month.slice(0, 4)}`;
export const shortDate = (date: string) => `${Number(date.slice(8, 10))} ${MONTHS[Number(date.slice(5, 7)) - 1]} ${date.slice(0, 4)}`;

/** The calendar month, quarter or year holding `anchor`, or an explicit range. */
export function resolvePeriod(kind: PeriodKind, anchor: string, from?: string, to?: string): Period {
  const year = Number(anchor.slice(0, 4));
  const month = Number(anchor.slice(5, 7));
  if (kind === "custom") {
    if (!from || !to) throw new Error("A custom period needs both `from` and `to` (YYYY-MM-DD)");
    if (!isDate(from) || !isDate(to)) throw new Error("`from` and `to` must be dates as YYYY-MM-DD");
    if (from > to) throw new Error(`The period starts (${from}) after it ends (${to})`);
    return { kind, from, to, label: `${shortDate(from)} – ${shortDate(to)}` };
  }
  if (kind === "month") {
    const start = `${anchor.slice(0, 7)}-01`;
    return { kind, from: start, to: addDays(addMonths(start, 1), -1), label: monthLabel(anchor.slice(0, 7)) };
  }
  if (kind === "quarter") {
    const q = Math.floor((month - 1) / 3);
    const start = `${year}-${String(q * 3 + 1).padStart(2, "0")}-01`;
    return { kind, from: start, to: addDays(addMonths(start, 3), -1), label: `Q${q + 1} ${year}` };
  }
  return { kind, from: `${year}-01-01`, to: `${year}-12-31`, label: String(year) };
}

/** The period of the same kind right before (`step` -1) or after (+1) this one. */
export function shiftPeriod(period: Period, step: number): Period {
  if (period.kind === "custom") {
    const length = daysBetween(period.from, period.to) + 1;
    return resolvePeriod("custom", period.from, addDays(period.from, step * length), addDays(period.to, step * length));
  }
  const months = period.kind === "month" ? 1 : period.kind === "quarter" ? 3 : 12;
  return resolvePeriod(period.kind, addMonths(period.from, step * months));
}
