/**
 * Bank statement CSV: parsing with a caller-supplied column mapping, and
 * de-duplication against what the account already holds. Pure functions.
 */
import type { Transaction } from "../shared/books.ts";
import { toMinor } from "../shared/money.ts";
import { isDate } from "../shared/period.ts";

export const DATE_FORMATS = ["YYYY-MM-DD", "DD.MM.YYYY", "DD/MM/YYYY", "MM/DD/YYYY"] as const;
export type DateFormat = (typeof DATE_FORMATS)[number];

/** A column by its header name or by 0-based position. */
export type Column = string | number;

export interface StatementMapping {
  date: Column;
  /** One signed column: positive is money in. */
  amount?: Column;
  /** Or two unsigned columns. */
  moneyIn?: Column;
  moneyOut?: Column;
  /** Joined with " · " when several. */
  description: Column | Column[];
  counterparty?: Column;
  dateFormat?: DateFormat;
  delimiter?: string;
  hasHeader?: boolean;
  /** For card exports where a positive amount is a charge. */
  invertSign?: boolean;
}

export interface StatementRow {
  /** 1-based line in the CSV text. */
  line: number;
  date: string;
  /** Signed minor units: positive is money into the account. */
  amount: number;
  description: string;
  counterpartyName: string | null;
}

/** RFC 4180-style: quoted fields, doubled quotes, CRLF or LF. */
export function parseCsv(text: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"' && field === "") {
      quoted = true;
    } else if (char === delimiter) {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export function detectDelimiter(text: string): string {
  const first = text.split(/\r?\n/, 1)[0] ?? "";
  const counts = [";", "\t", ","].map((d) => [d, first.split(d).length - 1] as const);
  return counts.reduce((best, next) => (next[1] > best[1] ? next : best))[0];
}

export function parseDate(value: string, format: DateFormat): string | null {
  const text = value.trim().slice(0, 10);
  let y: string;
  let m: string;
  let d: string;
  if (format === "YYYY-MM-DD") [y, m, d] = text.split("-");
  else if (format === "DD.MM.YYYY") [d, m, y] = text.split(".");
  else if (format === "DD/MM/YYYY") [d, m, y] = text.split("/");
  else [m, d, y] = text.split("/");
  if (!y || !m || !d) return null;
  const date = `${y.padStart(4, "0")}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
  return isDate(date) ? date : null;
}

export function parseStatement(
  csv: string,
  mapping: StatementMapping,
  currency: string,
): { rows: StatementRow[]; errors: { line: number; message: string }[] } {
  if (mapping.amount === undefined && mapping.moneyIn === undefined && mapping.moneyOut === undefined) {
    throw new Error("The mapping needs an `amount` column, or `money_in` and/or `money_out` columns");
  }
  const delimiter = mapping.delimiter ?? detectDelimiter(csv);
  const table = parseCsv(csv.replace(/^﻿/, ""), delimiter);
  const hasHeader = mapping.hasHeader ?? true;
  const header = hasHeader ? (table[0] ?? []).map((h) => h.trim().toLowerCase()) : [];
  const indexOf = (column: Column): number => {
    if (typeof column === "number") return column;
    const index = header.indexOf(column.trim().toLowerCase());
    if (index < 0) {
      throw new Error(
        hasHeader
          ? `No column "${column}" in the CSV header (${table[0]?.join(", ")})`
          : `Column "${column}" needs a header row; pass a 0-based index instead`,
      );
    }
    return index;
  };
  const dateAt = indexOf(mapping.date);
  const amountAt = mapping.amount !== undefined ? indexOf(mapping.amount) : null;
  const inAt = mapping.moneyIn !== undefined ? indexOf(mapping.moneyIn) : null;
  const outAt = mapping.moneyOut !== undefined ? indexOf(mapping.moneyOut) : null;
  const descriptionAt = (Array.isArray(mapping.description) ? mapping.description : [mapping.description]).map(indexOf);
  const counterpartyAt = mapping.counterparty !== undefined ? indexOf(mapping.counterparty) : null;
  const format = mapping.dateFormat ?? "YYYY-MM-DD";

  const rows: StatementRow[] = [];
  const errors: { line: number; message: string }[] = [];
  const cell = (cells: string[], at: number | null) => (at === null ? "" : (cells[at] ?? "").trim());
  const amountOf = (text: string) => (text === "" ? 0 : toMinor(text.replace(/^\+/, "").replace(/\u2212/g, "-"), currency));

  table.forEach((cells, index) => {
    const line = index + 1;
    if (hasHeader && index === 0) return;
    if (cells.every((c) => c.trim() === "")) return;
    try {
      const date = parseDate(cell(cells, dateAt), format);
      if (!date) throw new Error(`"${cell(cells, dateAt)}" is not a ${format} date`);
      let amount =
        amountAt !== null
          ? amountOf(cell(cells, amountAt))
          : Math.abs(amountOf(cell(cells, inAt))) - Math.abs(amountOf(cell(cells, outAt)));
      if (mapping.invertSign) amount = -amount;
      if (amount === 0) throw new Error("The amount is zero or empty");
      const description = descriptionAt
        .map((at) => cell(cells, at))
        .filter(Boolean)
        .join(" · ");
      rows.push({ line, date, amount, description, counterpartyName: cell(cells, counterpartyAt) || null });
    } catch (failure) {
      errors.push({ line, message: failure instanceof Error ? failure.message : String(failure) });
    }
  });
  return { rows, errors };
}

const normalizeMemo = (memo: string) => memo.trim().replace(/\s+/g, " ").toLowerCase();

export const dedupeKey = (date: string, signedAmount: number, memo: string) =>
  `${date}|${signedAmount}|${normalizeMemo(memo)}`;

/** The keys an account already holds, with multiplicity. */
export function existingKeys(transactions: Transaction[], accountId: string): Map<string, number> {
  const keys = new Map<string, number>();
  const add = (key: string) => keys.set(key, (keys.get(key) ?? 0) + 1);
  for (const t of transactions) {
    const memo = t.bankMemo ?? t.description;
    if (t.accountId === accountId) {
      add(dedupeKey(t.date, t.direction === "in" ? t.amount : -t.amount, memo));
    } else if (t.direction === "transfer" && t.transferAccountId === accountId) {
      add(dedupeKey(t.date, t.transferAmount ?? t.amount, memo));
    }
  }
  return keys;
}

/**
 * Splits statement rows into new ones and ones the account already has, by
 * date + signed amount + memo. Counted, not just matched: two identical
 * coffees on one day in the file against one in the books imports one.
 */
export function planImport(
  transactions: Transaction[],
  accountId: string,
  rows: StatementRow[],
): { fresh: StatementRow[]; duplicates: StatementRow[] } {
  const remaining = existingKeys(transactions, accountId);
  const fresh: StatementRow[] = [];
  const duplicates: StatementRow[] = [];
  for (const row of rows) {
    const key = dedupeKey(row.date, row.amount, row.description);
    const left = remaining.get(key) ?? 0;
    if (left > 0) {
      remaining.set(key, left - 1);
      duplicates.push(row);
    } else {
      fresh.push(row);
    }
  }
  return { fresh, duplicates };
}
