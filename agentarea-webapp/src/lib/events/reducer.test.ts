import { describe, expect, it } from "vitest";
import { EventInput, reduceParts } from "./contract";
import {
  applyEvent,
  findPendingForm,
  initialState,
  isInteractionClosed,
  reduceState,
  terminalMessage,
} from "./reducer";

function feed(events: EventInput[]) {
  return reduceState(events);
}

describe("reducer parts (supersede-by-id)", () => {
  it("collapses chunk, chunk, final into one llm part with final content", () => {
    const state = feed([
      {
        eventType: "llm.call.chunk",
        data: { execution_id: "e", iteration: 0, chunk: "a" },
      },
      {
        eventType: "llm.call.chunk",
        data: { execution_id: "e", iteration: 0, chunk: "ab" },
      },
      {
        eventType: "llm.call.completed",
        data: { execution_id: "e", iteration: 0, content: "final" },
      },
    ]);
    expect(state.parts).toHaveLength(1);
    expect(state.parts[0].eventType).toBe("llm.call.completed");
    expect(state.parts[0].data.content).toBe("final");
  });

  it("collapses two input.request with the same id into one part", () => {
    const state = feed([
      {
        eventType: "input.request",
        data: { input_request_id: "ir", question: "a?" },
      },
      {
        eventType: "input.request",
        data: { input_request_id: "ir", question: "b?" },
      },
    ]);
    expect(state.parts).toHaveLength(1);
    expect(state.parts[0].data.question).toBe("b?");
  });

  it("resolves a form when input.response supersedes the same-id request", () => {
    const state = feed([
      {
        eventType: "input.request",
        data: { input_request_id: "ir", question: "a?" },
      },
      {
        eventType: "input.response",
        data: { input_request_id: "ir", answer: "yes" },
      },
    ]);
    expect(state.parts).toHaveLength(1);
    expect(state.parts[0].eventType).toBe("input.response");
    expect(state.parts[0].data.answer).toBe("yes");
  });

  it("is idempotent for out-of-order duplicate part events", () => {
    const events: EventInput[] = [
      { eventType: "tool.call", data: { tool_call_id: "tc", name: "read" } },
      { eventType: "tool.call", data: { tool_call_id: "tc", name: "read" } },
      { eventType: "tool.result", data: { tool_call_id: "tc", success: true } },
      { eventType: "tool.result", data: { tool_call_id: "tc", success: true } },
    ];
    const state = feed(events);
    expect(state.parts).toHaveLength(1);
    expect(state.parts[0].eventType).toBe("tool.result");
  });

  it("preserves the original slot of a superseded part", () => {
    const state = feed([
      { eventType: "tool.call", data: { tool_call_id: "a" } },
      { eventType: "tool.call", data: { tool_call_id: "b" } },
      { eventType: "tool.result", data: { tool_call_id: "a", success: true } },
    ]);
    expect(state.parts.map((p) => p.partId)).toEqual(["a", "b"]);
    expect(state.parts[0].eventType).toBe("tool.result");
  });
});

describe("reducer incremental == batch (the supersede invariant)", () => {
  const events: EventInput[] = [
    {
      eventType: "llm.call.started",
      data: { execution_id: "e", iteration: 0 },
    },
    {
      eventType: "llm.call.chunk",
      data: { execution_id: "e", iteration: 0, chunk: "hi" },
    },
    { eventType: "tool.call", data: { tool_call_id: "t1", name: "read" } },
    {
      eventType: "llm.call.chunk",
      data: { execution_id: "e", iteration: 0, chunk: "hi there" },
    },
    { eventType: "tool.result", data: { tool_call_id: "t1", success: true } },
    {
      eventType: "llm.call.completed",
      data: { execution_id: "e", iteration: 0, content: "done" },
    },
    {
      eventType: "input.request",
      data: { input_request_id: "ir", question: "q?" },
    },
    { eventType: "task.completed", data: { message: "all good" } },
  ];

  it("applying one-by-one equals applying the whole list at once", () => {
    let step = initialState();
    for (const e of events) step = applyEvent(step, e);
    const batch = reduceState(events);
    expect(step.parts).toEqual(batch.parts);
    expect(step.timeline).toEqual(batch.timeline);
    expect(step.status).toBe(batch.status);
    expect(step.terminalMessage).toBe(batch.terminalMessage);
  });

  it("state.parts equals the pure reduceParts over the same list", () => {
    const state = reduceState(events);
    expect(state.parts).toEqual(reduceParts(events));
  });
});

describe("reducer timeline and terminal message", () => {
  it("collects task.* lifecycle events in order and exposes the terminal message", () => {
    const state = feed([
      { eventType: "tool.call", data: { tool_call_id: "t" } },
      { eventType: "task.failed", data: { reason: "budget exceeded" } },
    ]);
    expect(state.timeline.map((t) => t.eventType)).toEqual(["task.failed"]);
    expect(state.status).toBe("failed");
    expect(state.terminalMessage).toBe("budget exceeded");
  });

  it("gives a failed task its error when it carries no message or reason", () => {
    const state = feed([
      { eventType: "task.failed", data: { error: "no evidence" } },
    ]);
    expect(state.status).toBe("failed");
    expect(state.terminalMessage).toBe("no evidence");
  });

  it("gives a cancelled task its reason", () => {
    const state = feed([
      { eventType: "task.cancelled", data: { reason: "stopped by owner" } },
    ]);
    expect(state.status).toBe("cancelled");
    expect(state.terminalMessage).toBe("stopped by owner");
  });

  it("orders a failure's reason the way the backend contract does", () => {
    expect(
      terminalMessage("task.failed", { reason: "reason", error: "error" })
    ).toBe("reason");
    expect(
      terminalMessage("task.failed", { message: "message", reason: "reason" })
    ).toBe("message");
    expect(
      terminalMessage("task.cancelled", {
        blocked_reason: "blocked",
        error_type: "Timeout",
      })
    ).toBe("blocked");
    expect(terminalMessage("task.failed", { error_type: "Timeout" })).toBe(
      "Timeout"
    );
    expect(terminalMessage("task.failed", {})).toBe("Task failed.");
    expect(terminalMessage("task.cancelled", {})).toBe("Task cancelled.");
  });

  it("shows the same reason in the banner and the timeline row", () => {
    const data = { reason: "reason", error: "error" };
    const state = feed([{ eventType: "task.failed", data }]);
    expect(state.terminalMessage).toBe(
      terminalMessage(state.timeline[0].eventType, state.timeline[0].data)
    );
  });

  it("lets a failure that follows completion decide how the run ended", () => {
    const state = feed([
      { eventType: "tool.call", data: { tool_call_id: "t" } },
      { eventType: "tool.result", data: { tool_call_id: "t", success: true } },
      { eventType: "task.completed", data: { result: "profile written" } },
      { eventType: "task.failed", data: { error: "no evidence" } },
    ]);
    expect(state.status).toBe("failed");
    expect(state.terminalMessage).toBe("no evidence");
    expect(state.completedRuns).toHaveLength(1);
    expect(state.completedRuns[0].partIds).toEqual(["t"]);
    expect(state.completedRuns[0].terminalType).toBe("task.failed");
    expect(state.completedRuns[0].terminalMessage).toBe("no evidence");
  });

  it("keeps a run that ended waiting for follow-up when a cancel arrives later", () => {
    const state = feed([
      { eventType: "tool.call", data: { tool_call_id: "t" } },
      { eventType: "tool.result", data: { tool_call_id: "t", success: true } },
      {
        eventType: "task.awaiting_follow_up",
        data: { final_response: "the answer" },
      },
      { eventType: "task.cancelled", data: { reason: "conversation closed" } },
    ]);
    expect(state.status).toBe("cancelled");
    expect(state.completedRuns).toHaveLength(1);
    expect(state.completedRuns[0].terminalType).toBe("task.awaiting_follow_up");
    expect(state.completedRuns[0].terminalMessage).toBe("the answer");
  });

  it("derives a completed message from final_response when message is absent", () => {
    const state = feed([
      { eventType: "task.completed", data: { final_response: "shipped" } },
    ]);
    expect(state.status).toBe("completed");
    expect(state.terminalMessage).toBe("shipped");
  });

  it("stays running with a null terminal message before any terminal event", () => {
    const state = feed([
      { eventType: "tool.call", data: { tool_call_id: "t" } },
    ]);
    expect(state.status).toBe("running");
    expect(state.terminalMessage).toBeNull();
  });

  it("tracks continuation wait and resume as nonterminal lifecycle states", () => {
    const waiting = feed([
      {
        eventType: "task.awaiting_continuation",
        data: { failure_reason: "iteration_limit" },
      },
    ]);
    expect(waiting.status).toBe("waiting_for_continuation");
    expect(waiting.terminalMessage).toBeNull();

    const continued = applyEvent(waiting, {
      eventType: "task.continued",
      data: { continuation_count: 1 },
    });
    expect(continued.status).toBe("running");
  });
});

describe("business status and execution lifecycle", () => {
  it("reopens a recreated surface without reopening its answered request", () => {
    let state = feed([
      { eventType: "a2ui.create", data: { surface_id: "form" } },
      {
        eventType: "input.request",
        data: { input_request_id: "first", surface_id: "form" },
      },
      {
        eventType: "input.response",
        data: { input_request_id: "first", surface_id: "form" },
      },
    ]);
    expect(isInteractionClosed(state, state.byId.form)).toBe(true);
    state = applyEvent(state, {
      eventType: "a2ui.create",
      data: { surface_id: "form" },
    });
    state = applyEvent(state, {
      eventType: "input.request",
      data: { input_request_id: "second", surface_id: "form" },
    });
    expect(isInteractionClosed(state, state.byId.form)).toBe(false);
    expect(findPendingForm(state)?.partId).toBe("second");
  });

  it("retires old controls when another task starts without discarding its transcript", () => {
    let state = feed([
      { eventType: "a2ui.create", data: { surface_id: "form" } },
      { eventType: "input.request", data: { input_request_id: "first" } },
      { eventType: "task.started", data: { task_id: "new-task" } },
    ]);
    expect(isInteractionClosed(state, state.byId.form)).toBe(true);
    expect(isInteractionClosed(state, state.byId.first)).toBe(true);
    expect(findPendingForm(state)).toBeNull();
    state = applyEvent(state, {
      eventType: "input.request",
      data: { input_request_id: "second" },
    });
    expect(findPendingForm(state)?.partId).toBe("second");
  });

  it("waits for every matching human response before resuming", () => {
    let state = feed([
      {
        eventType: "input.request",
        data: { input_request_id: "input", question: "Which project?" },
      },
      { eventType: "approval.request", data: { escalation_id: "approval" } },
    ]);
    expect(state.status).toBe("waiting_for_input");
    expect(state.executionStatus).toBe("waiting");
    state = applyEvent(state, {
      eventType: "input.response",
      data: { input_request_id: "unrelated" },
    });
    expect(state.status).toBe("waiting_for_input");
    expect(findPendingForm(state)?.partId).toBe("input");
    state = applyEvent(state, {
      eventType: "input.response",
      data: { input_request_id: "input" },
    });
    expect(state.status).toBe("waiting_for_approval");
    state = applyEvent(state, {
      eventType: "approval.response",
      data: { escalation_id: "approval", approved: true },
    });
    expect(state.status).toBe("running");
    expect(state.executionStatus).toBe("running");
    expect(findPendingForm(state)).toBeNull();
  });

  it("does not offer expired or late input after a blocked execution", () => {
    let state = feed([
      { eventType: "input.request", data: { input_request_id: "input" } },
      {
        eventType: "task.failed",
        data: { blocked: true, reason: "Input expired" },
      },
    ]);
    expect(state.status).toBe("blocked");
    expect(findPendingForm(state)).toBeNull();
    expect(isInteractionClosed(state, state.parts[0])).toBe(true);
    state = applyEvent(state, {
      eventType: "input.request",
      data: { input_request_id: "late" },
    });
    expect(state.status).toBe("blocked");
    expect(findPendingForm(state)).toBeNull();
  });

  it("keeps a completed turn open for follow-up until execution actually ends", () => {
    let state = feed([
      {
        eventType: "llm.call.completed",
        data: { execution_id: "e", iteration: 1, content: "Result" },
      },
      {
        eventType: "task.awaiting_follow_up",
        data: { final_response: "Result" },
      },
      {
        eventType: "task.completed",
        data: { result: "Result", execution_status: "waiting" },
      },
    ]);
    expect(state.status).toBe("completed");
    expect(state.executionStatus).toBe("waiting");
    expect(state.completedRuns).toHaveLength(1);
    state = applyEvent(state, {
      eventType: "llm.call.started",
      data: { execution_id: "e", iteration: 2 },
    });
    expect(state.status).toBe("running");
    expect(state.executionStatus).toBe("running");
    state = applyEvent(state, {
      eventType: "task.completed",
      data: { result: "Next result", execution_status: "waiting" },
    });
    state = applyEvent(state, {
      eventType: "execution.finished",
      data: { execution_status: "completed" },
    });
    expect(state.status).toBe("completed");
    expect(state.executionStatus).toBe("finished");
    expect(state.completedRuns).toHaveLength(2);
  });
});
