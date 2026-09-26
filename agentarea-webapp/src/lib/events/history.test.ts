import { describe, expect, it } from "vitest";
import { eventTimestamp, normalizeHistory } from "./normalize";

const TS = "2026-09-16T14:48:52.534000Z";

/**
 * History rows and the SSE catch-up replay are the same events from two
 * sources: the persisted row's `id` IS the envelope's `event_id` (verified
 * against a live task). Dropping it on the way in defeats the dedup, so the
 * catch-up replays every row a second time.
 */
describe("normalizeHistory", () => {
  it("carries the row id through as the event id the dedup keys on", () => {
    const input = normalizeHistory({
      id: "a0d067e1-35e5-4738-930e-e9328dff6408",
      event_type: "task.started",
      timestamp: TS,
      metadata: { task_id: "t-1" },
    });

    expect(input.data.event_id).toBe("a0d067e1-35e5-4738-930e-e9328dff6408");
  });

  it("keeps the event type and metadata", () => {
    const input = normalizeHistory({
      id: "e-1",
      event_type: "llm.call.completed",
      timestamp: TS,
      metadata: { task_id: "t-1", iteration: 2 },
    });

    expect(input.eventType).toBe("llm.call.completed");
    expect(input.data.task_id).toBe("t-1");
    expect(input.data.iteration).toBe(2);
  });

  it("flattens original_data over metadata", () => {
    const input = normalizeHistory({
      id: "e-1",
      event_type: "tool.result",
      timestamp: TS,
      metadata: {
        task_id: "t-1",
        original_data: { tool_call_id: "tc-1", success: true },
      },
    });

    expect(input.data.tool_call_id).toBe("tc-1");
    expect(input.data.success).toBe(true);
    expect(input.data.original_data).toBeUndefined();
  });

  it("does not overwrite an event_id already present in the payload", () => {
    const input = normalizeHistory({
      id: "row-id",
      event_type: "task.started",
      timestamp: TS,
      metadata: { event_id: "payload-id" },
    });

    expect(input.data.event_id).toBe("payload-id");
  });

  it("survives a row with no id", () => {
    const input = normalizeHistory({
      event_type: "task.started",
      timestamp: TS,
      metadata: { task_id: "t-1" },
    });

    expect(input.data.event_id).toBeUndefined();
    expect(input.eventType).toBe("task.started");
  });

  it("never takes the row message, which the payload already carries", () => {
    const row = {
      id: "e-1",
      event_type: "task.failed",
      timestamp: TS,
      message: "Event: task.failed",
      metadata: { error: "no evidence for this lead" },
    };
    const input = normalizeHistory(row);

    expect(input.data.message).toBeUndefined();
    expect(input.data.error).toBe("no evidence for this lead");
  });

  it("carries the row timestamp, which metadata never has", () => {
    const input = normalizeHistory({
      id: "e-1",
      event_type: "tool.call",
      timestamp: TS,
      metadata: { tool_call_id: "tc-1" },
    });

    expect(input.data.timestamp).toBe(TS);
  });
});

describe("eventTimestamp", () => {
  it("reads the timestamp an event carries", () => {
    expect(eventTimestamp({ timestamp: TS })?.toISOString()).toBe(
      "2026-09-16T14:48:52.534Z"
    );
  });

  it("falls back to the envelope's original_timestamp", () => {
    expect(eventTimestamp({ original_timestamp: TS })?.toISOString()).toBe(
      "2026-09-16T14:48:52.534Z"
    );
  });

  it("is null, never the current time, when the event has no timestamp", () => {
    expect(eventTimestamp({})).toBeNull();
    expect(eventTimestamp({ timestamp: "not a date" })).toBeNull();
  });
});
