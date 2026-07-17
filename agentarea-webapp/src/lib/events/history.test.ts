import { describe, expect, it } from "vitest";
import { normalizeHistory } from "./normalize";

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
      metadata: { task_id: "t-1" },
    });

    expect(input.data.event_id).toBe("a0d067e1-35e5-4738-930e-e9328dff6408");
  });

  it("keeps the event type and metadata", () => {
    const input = normalizeHistory({
      id: "e-1",
      event_type: "llm.call.completed",
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
      metadata: { event_id: "payload-id" },
    });

    expect(input.data.event_id).toBe("payload-id");
  });

  it("survives a row with no id", () => {
    const input = normalizeHistory({
      event_type: "task.started",
      metadata: { task_id: "t-1" },
    });

    expect(input.data.event_id).toBeUndefined();
    expect(input.eventType).toBe("task.started");
  });

  it("uses the row message when the payload has none", () => {
    const input = normalizeHistory({
      id: "e-1",
      event_type: "task.completed",
      message: "done",
      metadata: {},
    });

    expect(input.data.message).toBe("done");
  });
});
