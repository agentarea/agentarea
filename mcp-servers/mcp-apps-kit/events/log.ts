/**
 * An app's outgoing events, kept in its own database so an event is written in
 * the same transaction as the change it reports.
 *
 * Positions are the log's sequence numbers. They only grow, and a reader's
 * position moves past every row it scanned, so events of other names or ones
 * its filter rejects are never looked at twice. Rows older than the retention
 * are pruned on append; a reader whose position falls behind the pruned ones
 * is told its page is truncated.
 */
import type { Database } from "bun:sqlite";
import type { Migration } from "../store/store.ts";

export const EVENT_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;

/** The log's tables. An app appends it to its MIGRATIONS once. */
export const EVENT_LOG_MIGRATION: Migration = (db) =>
  db.run(`
    CREATE TABLE app_events (
      seq  INTEGER PRIMARY KEY AUTOINCREMENT,
      id   TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      at   TEXT NOT NULL,
      data TEXT NOT NULL
    );
    CREATE INDEX app_events_name ON app_events (name, seq);
    CREATE TABLE app_events_pruned (
      id      INTEGER PRIMARY KEY CHECK (id = 1),
      through INTEGER NOT NULL
    );
  `);

export type EventData = Record<string, unknown>;

export type AppEvent = { seq: number; id: string; name: string; at: string; data: EventData };

export type EventPage = {
  events: AppEvent[];
  /** Where the next read starts. */
  position: number;
  hasMore: boolean;
  /** Events between the reader's position and this page were pruned. */
  truncated: boolean;
};

type Row = { seq: number; id: string; name: string; at: string; data: string };

const SCAN = 200;

/** Appends one event inside the caller's transaction and prunes what the retention has passed. */
export function appendEvent(db: Database, name: string, data: EventData, at: Date = new Date()): AppEvent {
  const event: AppEvent = { seq: 0, id: crypto.randomUUID(), name, at: at.toISOString(), data };
  const inserted = db
    .query<{ seq: number }, [string, string, string, string]>(
      "INSERT INTO app_events (id, name, at, data) VALUES (?, ?, ?, ?) RETURNING seq",
    )
    .get(event.id, name, event.at, JSON.stringify(data));
  event.seq = inserted!.seq;
  const cutoff = new Date(at.getTime() - EVENT_RETENTION_MS).toISOString();
  const stale = db
    .query<{ through: number | null }, [string]>("SELECT MAX(seq) AS through FROM app_events WHERE at < ?")
    .get(cutoff);
  if (stale?.through != null) {
    db.run("DELETE FROM app_events WHERE seq <= ?", [stale.through]);
    db.run(
      "INSERT INTO app_events_pruned (id, through) VALUES (1, ?) ON CONFLICT (id) DO UPDATE SET through = MAX(through, excluded.through)",
      [stale.through],
    );
  }
  return event;
}

/** The position after the last event ever appended: a reader starting here sees only new events. */
export function headPosition(db: Database): number {
  const row = db
    .query<{ seq: number }, []>("SELECT seq FROM sqlite_sequence WHERE name = 'app_events'")
    .get();
  return row?.seq ?? 0;
}

/** Up to `limit` events named `name` after `after` that `admits` accepts. */
export function readEvents(
  db: Database,
  options: { name: string; after: number; limit: number; admits: (data: EventData, event: AppEvent) => boolean },
): EventPage {
  const { name, after, limit, admits } = options;
  const pruned = db.query<{ through: number }, []>("SELECT through FROM app_events_pruned WHERE id = 1").get();
  const truncated = (pruned?.through ?? 0) > after;
  const head = headPosition(db);
  const scan = db.query<Row, [string, number, number]>(
    "SELECT seq, id, name, at, data FROM app_events WHERE name = ? AND seq > ? ORDER BY seq LIMIT ?",
  );
  const events: AppEvent[] = [];
  let position = after;
  for (;;) {
    const rows = scan.all(name, position, SCAN);
    for (const row of rows) {
      if (events.length === limit) {
        return { events, position, hasMore: true, truncated };
      }
      position = row.seq;
      const event: AppEvent = { seq: row.seq, id: row.id, name: row.name, at: row.at, data: JSON.parse(row.data) as EventData };
      if (admits(event.data, event)) events.push(event);
    }
    if (rows.length < SCAN) break;
  }
  return { events, position: Math.max(position, head), hasMore: false, truncated };
}
