import { Database } from "bun:sqlite";
import { describe, expect, test } from "bun:test";
import { appendEvent, EVENT_LOG_MIGRATION, EVENT_RETENTION_MS, headPosition, readEvents } from "./log.ts";

function eventDb(): Database {
  const db = new Database(":memory:");
  EVENT_LOG_MIGRATION(db);
  return db;
}

const all = () => true;

describe("event log", () => {
  test("an empty log starts at position 0 and reads nothing", () => {
    const db = eventDb();
    expect(headPosition(db)).toBe(0);
    expect(readEvents(db, { name: "task.assigned", after: 0, limit: 10, admits: all })).toEqual({
      events: [],
      position: 0,
      hasMore: false,
      truncated: false,
    });
  });

  test("a reader from the head sees only what is appended after it", () => {
    const db = eventDb();
    appendEvent(db, "task.assigned", { key: "OPS-1" });
    const head = headPosition(db);
    appendEvent(db, "task.assigned", { key: "OPS-2" });
    const page = readEvents(db, { name: "task.assigned", after: head, limit: 10, admits: all });
    expect(page.events.map((e) => e.data.key)).toEqual(["OPS-2"]);
    expect(page.position).toBe(headPosition(db));
  });

  test("other event names and rejected events are skipped but still move the position", () => {
    const db = eventDb();
    appendEvent(db, "deal.won", { key: "D-1" });
    appendEvent(db, "task.assigned", { key: "OPS-1", assignee: "maya" });
    appendEvent(db, "task.assigned", { key: "OPS-2", assignee: "bot" });
    const page = readEvents(db, { name: "task.assigned", after: 0, limit: 10, admits: (d) => d.assignee === "bot" });
    expect(page.events.map((e) => e.data.key)).toEqual(["OPS-2"]);
    expect(page.position).toBe(3);
    expect(readEvents(db, { name: "task.assigned", after: page.position, limit: 10, admits: all }).events).toEqual([]);
  });

  test("a full page stops at its last event and says there is more", () => {
    const db = eventDb();
    for (let i = 1; i <= 5; i++) appendEvent(db, "task.assigned", { n: i });
    const first = readEvents(db, { name: "task.assigned", after: 0, limit: 2, admits: all });
    expect(first.events.map((e) => e.data.n)).toEqual([1, 2]);
    expect(first.hasMore).toBe(true);
    const rest = readEvents(db, { name: "task.assigned", after: first.position, limit: 10, admits: all });
    expect(rest.events.map((e) => e.data.n)).toEqual([3, 4, 5]);
    expect(rest.hasMore).toBe(false);
  });

  test("events past the retention are pruned on append, and a reader behind them is told", () => {
    const db = eventDb();
    const old = new Date("2026-10-01T00:00:00Z");
    appendEvent(db, "task.assigned", { key: "OPS-1" }, old);
    appendEvent(db, "task.assigned", { key: "OPS-2" }, new Date(old.getTime() + EVENT_RETENTION_MS + 1));
    const page = readEvents(db, { name: "task.assigned", after: 0, limit: 10, admits: all });
    expect(page.events.map((e) => e.data.key)).toEqual(["OPS-2"]);
    expect(page.truncated).toBe(true);
    expect(readEvents(db, { name: "task.assigned", after: 1, limit: 10, admits: all }).truncated).toBe(false);
  });

  test("an event keeps its id, name, time and data", () => {
    const db = eventDb();
    const at = new Date("2026-10-23T10:00:00Z");
    const appended = appendEvent(db, "task.assigned", { key: "OPS-1", nested: { a: 1 } }, at);
    const [read] = readEvents(db, { name: "task.assigned", after: 0, limit: 1, admits: all }).events;
    expect(read).toEqual(appended);
    expect(read!.at).toBe(at.toISOString());
    expect(read!.id).toMatch(/^[0-9a-f-]{36}$/);
  });
});
