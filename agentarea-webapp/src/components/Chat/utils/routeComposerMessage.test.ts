import { describe, expect, it } from "vitest";
import type { EventInput } from "@/lib/events/contract";
import { reduceState } from "@/lib/events/reducer";
import {
  adoptCreatedTaskId,
  routeComposerMessage,
} from "./routeComposerMessage";

// FullChat folds `task.started` into the stream when it adopts a created task.
const started = (taskId: string): EventInput => ({
  eventType: "task.started",
  data: { task_id: taskId },
});
const completed = (waiting: boolean): EventInput => ({
  eventType: "task.completed",
  data: {
    result: "Delivered",
    ...(waiting ? { execution_status: "waiting" } : {}),
  },
});

describe("adoptCreatedTaskId", () => {
  it("adopts every newly created task, not just the first", () => {
    expect(adoptCreatedTaskId(null, { task_id: "task-a" })).toBe("task-a");
    expect(adoptCreatedTaskId("task-a", { task_id: "task-b" })).toBe("task-b");
  });

  it("ignores a repeat of the task already owned and a malformed id", () => {
    expect(adoptCreatedTaskId("task-a", { task_id: "task-a" })).toBeNull();
    expect(adoptCreatedTaskId("task-a", { task_id: 42 })).toBeNull();
    expect(adoptCreatedTaskId("task-a", {})).toBeNull();
  });
});

describe("routeComposerMessage", () => {
  it("starts a new task once the earlier execution closed", () => {
    const state = reduceState([started("task-a"), completed(false)]);

    expect(
      routeComposerMessage(state, { currentTaskId: "task-a", hasFiles: false })
    ).toEqual({ route: "create" });
  });

  it("queues a follow-up on a task still waiting for one", () => {
    const state = reduceState([
      started("task-a"),
      completed(false),
      started("task-b"),
      completed(true),
    ]);

    expect(
      routeComposerMessage(state, { currentTaskId: "task-b", hasFiles: false })
    ).toEqual({ route: "current", pendingInputId: undefined });
  });

  it("answers an open input request with the message", () => {
    const state = reduceState([
      started("task-a"),
      {
        eventType: "input.request",
        data: { input_request_id: "ir-1", question: "Which repo?" },
      },
    ]);

    expect(
      routeComposerMessage(state, { currentTaskId: "task-a", hasFiles: false })
    ).toEqual({ route: "current", pendingInputId: "ir-1" });
  });

  it("queues rather than answers while an approval is pending", () => {
    const state = reduceState([
      started("task-a"),
      {
        eventType: "approval.request",
        data: { escalation_id: "ap-1", tool_name: "delete_repo" },
      },
    ]);

    const route = routeComposerMessage(state, {
      currentTaskId: "task-a",
      hasFiles: false,
    });

    expect(route).toEqual({ route: "current", pendingInputId: undefined });
  });

  it("starts a new task for attachments, which the current task cannot take", () => {
    const state = reduceState([started("task-a"), completed(true)]);

    expect(
      routeComposerMessage(state, { currentTaskId: "task-a", hasFiles: true })
    ).toEqual({ route: "create" });
  });

  it("starts a new task when there is none yet", () => {
    const state = reduceState([completed(true)]);

    expect(
      routeComposerMessage(state, { currentTaskId: null, hasFiles: false })
    ).toEqual({ route: "create" });
  });
});
