import { Database } from "bun:sqlite";
import { describe, expect, test } from "bun:test";
import { appendEvent, EVENT_LOG_MIGRATION } from "./log.ts";
import { encodeCursor, EventsError, EventsErrorCode, listEvents, parsePollParams, pollEvents, type EventType } from "./protocol.ts";

const assigned: EventType<{ assignee?: string }> = {
  name: "task.assigned",
  title: "Task assigned",
  description: "A task got an assignee",
  inputSchema: { type: "object", properties: { assignee: { type: "string" } }, additionalProperties: false },
  payloadSchema: { type: "object" },
  parseArguments(raw) {
    for (const key of Object.keys(raw)) if (key !== "assignee") throw new Error(`unknown argument ${key}`);
    if (raw.assignee !== undefined && typeof raw.assignee !== "string") throw new Error("assignee must be a string");
    return { assignee: raw.assignee as string | undefined };
  },
  admits: (args, data) => args.assignee === undefined || data.assignee === args.assignee,
};
const types = [assigned] as EventType<never>[];

function eventDb(): Database {
  const db = new Database(":memory:");
  EVENT_LOG_MIGRATION(db);
  return db;
}

function rejects(fn: () => unknown, code: EventsErrorCode) {
  try {
    fn();
  } catch (error) {
    expect(error).toBeInstanceOf(EventsError);
    expect((error as EventsError).code).toBe(code);
    return;
  }
  throw new Error("expected an EventsError");
}

describe("events/list", () => {
  test("lists each event type with poll delivery", () => {
    expect(listEvents(types)).toEqual({
      events: [
        {
          name: "task.assigned",
          title: "Task assigned",
          description: "A task got an assignee",
          delivery: ["poll"],
          inputSchema: assigned.inputSchema,
          payloadSchema: assigned.payloadSchema,
        },
      ],
    });
  });
});

describe("events/poll", () => {
  test("a poll without a cursor starts from now: no backlog, a cursor at the head", () => {
    const db = eventDb();
    appendEvent(db, "task.assigned", { key: "OPS-1", assignee: "bot" });
    const first = pollEvents(db, types, { name: "task.assigned", cursor: null });
    expect(first.events).toEqual([]);
    expect(first.cursor).toBe(encodeCursor(1));
    expect(first.nextPollMs).toBeGreaterThan(0);
  });

  test("the next poll returns what happened since, as occurrences, filtered by the arguments", () => {
    const db = eventDb();
    const { cursor } = pollEvents(db, types, { name: "task.assigned", cursor: null });
    const event = appendEvent(db, "task.assigned", { key: "OPS-2", assignee: "bot" });
    appendEvent(db, "task.assigned", { key: "OPS-3", assignee: "maya" });
    const next = pollEvents(db, types, { name: "task.assigned", arguments: { assignee: "bot" }, cursor });
    expect(next.events).toEqual([
      {
        eventId: event.id,
        name: "task.assigned",
        timestamp: event.at,
        data: { key: "OPS-2", assignee: "bot", id: event.id, kind: "task.assigned" },
      },
    ]);
    expect(pollEvents(db, types, { name: "task.assigned", arguments: { assignee: "bot" }, cursor: next.cursor }).events).toEqual([]);
  });

  test("events older than maxAgeMs are skipped and the page says so", () => {
    const db = eventDb();
    const now = new Date("2026-10-23T12:00:00Z");
    appendEvent(db, "task.assigned", { key: "OPS-1" }, new Date(now.getTime() - 60_000));
    appendEvent(db, "task.assigned", { key: "OPS-2" }, new Date(now.getTime() - 1_000));
    const page = pollEvents(db, types, { name: "task.assigned", cursor: encodeCursor(0), maxAgeMs: 10_000 }, now);
    expect(page.events.map((e) => e.data.key)).toEqual(["OPS-2"]);
    expect(page.truncated).toBe(true);
  });

  test("an unknown event, bad arguments and a foreign cursor are refused with their codes", () => {
    const db = eventDb();
    rejects(() => pollEvents(db, types, { name: "deal.won", cursor: null }), EventsErrorCode.NotFound);
    rejects(() => pollEvents(db, types, { name: "task.assigned", arguments: { project: "OPS" }, cursor: null }), EventsErrorCode.InvalidParams);
    rejects(() => pollEvents(db, types, { name: "task.assigned", cursor: "42" }), EventsErrorCode.InvalidParams);
  });
});

describe("events/poll params", () => {
  test("are read as the client sends them", () => {
    expect(parsePollParams({ name: "task.assigned", arguments: { assignee: "bot" }, cursor: null, maxEvents: 10, _meta: {} })).toEqual({
      name: "task.assigned",
      arguments: { assignee: "bot" },
      cursor: null,
      maxEvents: 10,
      maxAgeMs: undefined,
    });
  });

  test("refuse a missing name and malformed fields", () => {
    expect(() => parsePollParams({})).toThrow("name is required");
    expect(() => parsePollParams({ name: "x", cursor: 1 })).toThrow("cursor");
    expect(() => parsePollParams({ name: "x", arguments: [] })).toThrow("arguments");
    expect(() => parsePollParams({ name: "x", maxEvents: 0 })).toThrow("maxEvents");
  });
});
