import { describe, expect, it } from "vitest";
import {
  loadAllTaskEventPages,
  TaskEventsHistoryError,
} from "./history";

const event = (id: string) => ({
  agent_id: "agent-1",
  id,
  event_type: "task.started",
  message: "started",
  metadata: {},
  task_id: "task-1",
  timestamp: "2026-09-17T00:00:00Z",
});

describe("loadAllTaskEventPages", () => {
  it("loads every page in order and passes the page size through", async () => {
    const calls: Array<[number, number]> = [];
    const result = await loadAllTaskEventPages(async (page, pageSize) => {
      calls.push([page, pageSize]);
      return page === 1
        ? { data: { events: [event("first")], has_next: true } }
        : { data: { events: [event("last")], has_next: false } };
    });

    expect(calls).toEqual([
      [1, 100],
      [2, 100],
    ]);
    expect(result?.map((item) => item.id)).toEqual(["first", "last"]);
  });

  it("preserves the API result when a page fails", async () => {
    const failed = { status: 503, error: { detail: "unavailable" } };
    await expect(
      loadAllTaskEventPages(async () => ({ error: failed }))
    ).rejects.toMatchObject({
      name: "TaskEventsHistoryError",
      result: { error: { status: 503 } },
    });
  });

  it("stops before another request when the consumer is cancelled", async () => {
    let calls = 0;
    const result = await loadAllTaskEventPages(
      async () => {
        calls += 1;
        return { data: { events: [event("first")], has_next: true } };
      },
      100,
      () => calls > 0
    );

    expect(result).toBeNull();
    expect(calls).toBe(1);
  });

  it("rejects malformed empty continuation pages", async () => {
    await expect(
      loadAllTaskEventPages(async () => ({
        data: { events: [], has_next: true },
      }))
    ).rejects.toBeInstanceOf(TaskEventsHistoryError);
  });
});
