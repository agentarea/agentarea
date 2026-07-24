import { describe, expect, it } from "vitest";
import { EventInput, reduceParts } from "./contract";
import { applyEvent, initialState, reduceState } from "./reducer";

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
