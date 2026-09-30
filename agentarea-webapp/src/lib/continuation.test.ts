import { describe, expect, it } from "vitest";
import {
  continuationFields,
  defaultContinuationForm,
  latestContinuationReason,
  parseContinuationGrant,
  type ContinuationForm,
} from "./continuation";

const empty: ContinuationForm = {
  iterations: "",
  budget: "",
  tokens: "",
  toolCalls: "",
};

describe("latestContinuationReason", () => {
  it("reads the newest awaiting_continuation failure_reason", () => {
    expect(
      latestContinuationReason([
        {
          eventType: "task.awaiting_continuation",
          data: { failure_reason: "iteration_limit" },
        },
        { eventType: "task.continued", data: {} },
        {
          eventType: "workflow.task.awaiting_continuation",
          data: { failure_reason: "token_limit" },
        },
      ])
    ).toBe("token_limit");
  });

  it("is null without a continuation event", () => {
    expect(
      latestContinuationReason([{ eventType: "task.started", data: {} }])
    ).toBeNull();
  });
});

describe("continuationFields", () => {
  it("leads with the exhausted limit and keeps iterations and budget", () => {
    expect(continuationFields("token_limit")).toEqual([
      "tokens",
      "iterations",
      "budget",
    ]);
    expect(continuationFields("tool_call_limit")).toEqual([
      "toolCalls",
      "iterations",
      "budget",
    ]);
    expect(continuationFields("budget_exceeded")).toEqual([
      "budget",
      "iterations",
    ]);
  });

  it("shows every grant when the reason is unknown", () => {
    expect(continuationFields(null)).toEqual([
      "iterations",
      "budget",
      "tokens",
      "toolCalls",
    ]);
  });
});

describe("defaultContinuationForm", () => {
  it("pre-fills only the exhausted limit", () => {
    expect(defaultContinuationForm("tool_call_limit")).toEqual({
      ...empty,
      toolCalls: "50",
    });
    expect(defaultContinuationForm(null)).toEqual({
      ...empty,
      iterations: "10",
    });
  });
});

describe("parseContinuationGrant", () => {
  it("builds a token grant for a token limit", () => {
    expect(
      parseContinuationGrant({ ...empty, tokens: "50000" }, "token_limit")
    ).toEqual({
      ok: true,
      payload: {
        additional_iterations: 0,
        additional_tokens: 50000,
        additional_tool_calls: 0,
      },
    });
  });

  it("requires the grant that lifts the exhausted limit", () => {
    expect(
      parseContinuationGrant({ ...empty, iterations: "5" }, "token_limit")
    ).toEqual({ ok: false, error: "tokens_required" });
    expect(
      parseContinuationGrant({ ...empty, budget: "2.50" }, "tool_call_limit")
    ).toEqual({ ok: false, error: "toolCalls_required" });
  });

  it("ignores inputs the reason does not show", () => {
    expect(
      parseContinuationGrant(
        { ...empty, iterations: "3", tokens: "999" },
        "iteration_limit"
      )
    ).toEqual({
      ok: true,
      payload: {
        additional_iterations: 3,
        additional_tokens: 0,
        additional_tool_calls: 0,
      },
    });
  });

  it("carries a budget top-up as a decimal string", () => {
    expect(
      parseContinuationGrant({ ...empty, budget: " 2.50 " }, "budget_exceeded")
    ).toEqual({
      ok: true,
      payload: {
        additional_iterations: 0,
        additional_tokens: 0,
        additional_tool_calls: 0,
        additional_budget_usd: "2.50",
      },
    });
  });

  it("rejects negative, fractional and out-of-range counts", () => {
    for (const form of [
      { ...empty, tokens: "-1" },
      { ...empty, tokens: "1.5" },
      { ...empty, tokens: "10000001" },
      { ...empty, toolCalls: "10001" },
      { ...empty, budget: "0" },
    ]) {
      expect(parseContinuationGrant(form, null)).toEqual({
        ok: false,
        error: "invalid",
      });
    }
  });

  it("requires at least one grant when the reason is unknown", () => {
    expect(parseContinuationGrant(empty, null)).toEqual({
      ok: false,
      error: "grant_required",
    });
  });
});
