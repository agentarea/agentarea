import { describe, expect, it } from "vitest";
import {
  ARTIFACT_CREATED,
  canonicalType,
  derivePart,
  EVENT_TYPES,
  isTaskEventType,
  LLM_COMPLETED,
  reduceParts,
  TOOL_CALL,
  TOOL_RESULT,
  VOCABULARY_VERSION,
} from "./contract";

describe("vocabulary", () => {
  it("is versioned", () => {
    expect(VOCABULARY_VERSION).toBeGreaterThanOrEqual(1);
  });

  it("holds only dotted lowercase types, each once", () => {
    for (const type of EVENT_TYPES) {
      expect(type).toMatch(/^[a-z0-9_]+(\.[a-z0-9_]+)+$/);
    }
    expect(new Set(EVENT_TYPES).size).toBe(EVENT_TYPES.length);
  });

  it("knows the turn and timeline types", () => {
    for (const type of [
      "turn.started",
      "turn.completed",
      "turn.aborted",
      "budget.warning",
      "context.compacted",
      "command.received",
      "delegation.started",
      "execution.continued_as_new",
    ]) {
      expect(isTaskEventType(type)).toBe(true);
    }
  });

  it("does not know the bare names", () => {
    for (const type of [
      "IterationStarted",
      "BudgetWarning",
      "WorkflowCommandReceived",
      "execution_paused",
    ]) {
      expect(isTaskEventType(type)).toBe(false);
    }
  });
});

describe("canonicalType", () => {
  it("passes canonical dotted types through unchanged", () => {
    expect(canonicalType("llm.call.started")).toBe("llm.call.started");
    expect(canonicalType("llm.call.chunk")).toBe("llm.call.chunk");
    expect(canonicalType("tool.call")).toBe(TOOL_CALL);
    expect(canonicalType("tool.result")).toBe(TOOL_RESULT);
    expect(canonicalType("input.request")).toBe("input.request");
    expect(canonicalType("approval.decided")).toBe("approval.decided");
    expect(canonicalType("task.completed")).toBe("task.completed");
    expect(canonicalType("task.cancelled")).toBe("task.cancelled");
  });

  it("strips a defensive leading workflow. prefix", () => {
    expect(canonicalType("workflow.task.completed")).toBe("task.completed");
    expect(canonicalType("workflow.llm.call.chunk")).toBe("llm.call.chunk");
  });

  it("returns other types unchanged (no alias table)", () => {
    expect(canonicalType("budget.warning")).toBe("budget.warning");
    expect(canonicalType("turn.started")).toBe("turn.started");
  });

  it("is idempotent", () => {
    const once = canonicalType("llm.call.chunk");
    expect(canonicalType(once)).toBe(once);
    expect(canonicalType(canonicalType("workflow.task.completed"))).toBe(
      "task.completed"
    );
  });
});

describe("derivePart", () => {
  it("derives a tool part keyed by tool_call_id", () => {
    const part = derivePart("tool.call", { tool_call_id: "tc-1" });
    expect(part).toMatchObject({
      partId: "tc-1",
      kind: "tool",
      eventType: TOOL_CALL,
    });
  });

  it("shares one partId across llm chunk and final of the same iteration", () => {
    const chunk = derivePart("llm.call.chunk", {
      execution_id: "ex-1",
      iteration: 2,
    });
    const final = derivePart("llm.call.completed", {
      execution_id: "ex-1",
      iteration: 2,
    });
    expect(chunk?.partId).toBe("ex-1:2");
    expect(final?.partId).toBe("ex-1:2");
    expect(final?.eventType).toBe(LLM_COMPLETED);
  });

  it("returns null for an llm event missing execution_id or iteration", () => {
    expect(derivePart("llm.call.chunk", { execution_id: "ex-1" })).toBeNull();
    expect(derivePart("llm.call.chunk", { iteration: 0 })).toBeNull();
  });

  it("keys an input form by input_request_id, falling back to request_id", () => {
    expect(
      derivePart("input.request", { input_request_id: "ir-1" })?.partId
    ).toBe("ir-1");
    expect(derivePart("input.request", { request_id: "rq-1" })?.partId).toBe(
      "rq-1"
    );
  });

  it("keys an approval form by escalation_id, falling back to request_id", () => {
    expect(
      derivePart("approval.requested", { escalation_id: "esc-1" })?.partId
    ).toBe("esc-1");
    expect(
      derivePart("approval.requested", { request_id: "rq-2" })?.partId
    ).toBe("rq-2");
  });

  it("keys an artifact by artifact_id", () => {
    expect(
      derivePart("artifact.created", { artifact_id: "af-1" })?.eventType
    ).toBe(ARTIFACT_CREATED);
  });

  it("returns null for lifecycle/terminal task.* events", () => {
    expect(derivePart("task.completed", {})).toBeNull();
    expect(derivePart("task.failed", { message: "boom" })).toBeNull();
    expect(derivePart("task.cancelled", {})).toBeNull();
  });
});

describe("reduceParts", () => {
  it("collapses chunk, chunk, final into a single llm part (final wins)", () => {
    const parts = reduceParts([
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
    expect(parts).toHaveLength(1);
    expect(parts[0].eventType).toBe(LLM_COMPLETED);
    expect(parts[0].data.content).toBe("final");
  });

  it("skips non-part lifecycle events", () => {
    const parts = reduceParts([
      { eventType: "task.completed", data: { message: "done" } },
      { eventType: "tool.call", data: { tool_call_id: "tc" } },
    ]);
    expect(parts).toHaveLength(1);
    expect(parts[0].kind).toBe("tool");
  });

  it("keeps a compaction call out of the transcript", () => {
    const parts = reduceParts([
      {
        eventType: "llm.call.completed",
        data: { execution_id: "e", iteration: 1, content: "answer" },
      },
      {
        eventType: "llm.call.completed",
        data: {
          execution_id: "e",
          iteration: 1,
          purpose: "compaction",
          content: "",
        },
      },
      {
        eventType: "llm.call.completed",
        data: {
          execution_id: "e",
          iteration: 2,
          purpose: "compaction",
          content: "",
        },
      },
    ]);
    expect(parts).toHaveLength(1);
    expect(parts[0].data.content).toBe("answer");
  });
});

// context.compacted showed only in the Events tab, never in the transcript.
describe("compaction notice", () => {
  it("derives a notice part keyed by the event id", () => {
    const part = derivePart("context.compacted", {
      event_id: "ev-1",
      messages_compacted: 12,
    });
    expect(part).toEqual({
      partId: "ev-1",
      kind: "notice",
      eventType: "context.compacted",
      data: { event_id: "ev-1", messages_compacted: 12 },
    });
  });
});

describe("message.received", () => {
  it("is a message part keyed by its event, so each one keeps its own slot", () => {
    expect(
      derivePart("message.received", { event_id: "ev-9", content: "and?" })
    ).toEqual({
      partId: "ev-9",
      kind: "message",
      eventType: "message.received",
      data: { event_id: "ev-9", content: "and?" },
    });
  });
});
