/**
 * Rows of an app's tables, moved between sqlite and the app's in-memory model.
 *
 * An app describes its tables once, maps its model to rows and back, and
 * writes a changed model with `syncRows`: only rows that were added, changed
 * or removed since `readRows` touch the database.
 */
import type { Database } from "bun:sqlite";

export type Value = string | number | null;
export type Row = Record<string, Value>;
export type Rows = Record<string, Row[]>;

export type Table = {
  name: string;
  columns: readonly string[];
  /** Primary key columns. */
  key: readonly string[];
  /** Read order; defaults to insertion order (rowid). */
  orderBy?: string;
};

export function readRows(db: Database, tables: readonly Table[]): Rows {
  return Object.fromEntries(
    tables.map((t) => [t.name, db.query(`SELECT ${t.columns.join(", ")} FROM ${t.name} ORDER BY ${t.orderBy ?? "rowid"}`).all() as Row[]]),
  );
}

const values = (t: Table, row: Row, columns = t.columns) => columns.map((c) => row[c] ?? null);
const keyOf = (t: Table, row: Row) => JSON.stringify(t.key.map((c) => row[c] ?? null));

function inserter(db: Database, t: Table) {
  return db.prepare(`INSERT INTO ${t.name} (${t.columns.join(", ")}) VALUES (${t.columns.map(() => "?").join(", ")})`);
}

/** Inserts every row, parents first in table order; foreign keys are checked at commit. */
export function insertRows(db: Database, tables: readonly Table[], rows: Rows): void {
  db.run("PRAGMA defer_foreign_keys = ON");
  for (const t of tables) {
    const insert = inserter(db, t);
    for (const row of rows[t.name] ?? []) insert.run(...values(t, row));
  }
}

/**
 * Writes the difference between `before` (as read) and `after` (the changed model).
 * Foreign keys are checked at commit, so the order of changes across tables does not matter.
 * Returns how many rows changed.
 */
export function syncRows(db: Database, tables: readonly Table[], before: Rows, after: Rows): number {
  db.run("PRAGMA defer_foreign_keys = ON");
  let changed = 0;
  const removals: (() => void)[] = [];
  for (const t of tables) {
    const left = new Map((before[t.name] ?? []).map((row) => [keyOf(t, row), row]));
    const rest = t.columns.filter((c) => !t.key.includes(c));
    const where = t.key.map((c) => `${c} = ?`).join(" AND ");
    const insert = inserter(db, t);
    const update = rest.length ? db.prepare(`UPDATE ${t.name} SET ${rest.map((c) => `${c} = ?`).join(", ")} WHERE ${where}`) : null;
    for (const row of after[t.name] ?? []) {
      const k = keyOf(t, row);
      const previous = left.get(k);
      if (!previous) {
        insert.run(...values(t, row));
        changed += 1;
        continue;
      }
      left.delete(k);
      if (update && rest.some((c) => (previous[c] ?? null) !== (row[c] ?? null))) {
        update.run(...values(t, row, rest), ...values(t, row, t.key));
        changed += 1;
      }
    }
    if (left.size > 0) {
      const remove = db.prepare(`DELETE FROM ${t.name} WHERE ${where}`);
      const gone = [...left.values()];
      removals.push(() => {
        for (const row of gone) remove.run(...values(t, row, t.key));
      });
      changed += gone.length;
    }
  }
  for (const remove of removals.reverse()) remove();
  return changed;
}
