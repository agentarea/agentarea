import { describe, it, expect } from "vitest";
import {
  canonicalType,
  derivePart,
  reduceParts,
  LLM_COMPLETED,
  TOOL_CALL,
  TOOL_RESULT,
  ARTIFACT_CREATED,
} from "./contract";

describe("canonicalType", () => {
  it("passes canonical dotted types through unchanged", () => {
    expect(canonicalType("llm.call.started")).toBe("llm.call.started");
    expect(canonicalType("llm.call.chunk")).toBe("llm.call.chunk");
    expect(canonicalType("tool.call")).toBe(TOOL_CALL);
    expect(canonicalType("tool.result")).toBe(TOOL_RESULT);
    expect(canonicalType("input.request")).toBe("input.request");
    expect(canonicalType("approval.response")).toBe("approval.response");
    expect(canonicalType("task.completed")).toBe("task.completed");
    expect(canonicalType("task.cancelled")).toBe("task.cancelled");
  });

  it("strips a defensive leading workflow. prefix", () => {
    expect(canonicalType("workflow.task.completed")).toBe("task.completed");
    expect(canonicalType("workflow.llm.call.chunk")).toBe("llm.call.chunk");
  });

  it("returns unknown types unchanged (no alias table)", () => {
    expect(canonicalType("BudgetWarning")).toBe("BudgetWarning");
    expect(canonicalType("IterationStarted")).toBe("IterationStarted");
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
      derivePart("approval.request", { escalation_id: "esc-1" })?.partId
    ).toBe("esc-1");
    expect(
      derivePart("approval.request", { request_id: "rq-2" })?.partId
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
      { eventType: "llm.call.chunk", data: { execution_id: "e", iteration: 0, chunk: "a" } },
      { eventType: "llm.call.chunk", data: { execution_id: "e", iteration: 0, chunk: "ab" } },
      { eventType: "llm.call.completed", data: { execution_id: "e", iteration: 0, content: "final" } },
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
});
