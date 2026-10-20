import { describe, expect, it } from "vitest";
import {
  eventCategory,
  eventFacts,
  eventSummary,
  eventTypeKey,
  shownEventData,
} from "./taskEventDisplay";

describe("eventFacts tokens", () => {
  it("reads the counts a completed model call nests under usage.usage", () => {
    const facts = eventFacts({
      cost: "0.48",
      usage: {
        cost: "0.48",
        usage: {
          prompt_tokens: 1000,
          completion_tokens: 100,
          total_tokens: 1100,
          cached_prompt_tokens: 800,
        },
      },
    });

    expect(facts).toContainEqual({
      kind: "tokens",
      input: 1000,
      output: 100,
      cached: 800,
    });
  });

  it("has no cached count when nothing came from the cache", () => {
    const facts = eventFacts({
      usage: {
        prompt_tokens: 10,
        completion_tokens: 5,
        cached_prompt_tokens: 0,
      },
    });

    expect(facts).toContainEqual({
      kind: "tokens",
      input: 10,
      output: 5,
      cached: null,
    });
  });
});

describe("event types", () => {
  it("files each type under the category of its scope", () => {
    expect(eventCategory("turn.aborted")).toBe("turn");
    expect(eventCategory("model.changed")).toBe("llm");
    expect(eventCategory("service.payment")).toBe("budget");
    expect(eventCategory("command.received")).toBe("task");
    expect(eventCategory("some.future")).toBe("other");
  });

  it("names a type of the vocabulary and leaves anything else raw", () => {
    expect(eventTypeKey("turn.started")).toBe("turnStarted");
    expect(eventTypeKey("IterationStarted")).toBeNull();
  });
});

describe("eventSummary", () => {
  it("skips a marker standing in for a body the event did not keep", () => {
    expect(
      eventSummary({
        result: "[omitted from event log: 34 units]",
        error: "boom",
      })
    ).toBe("boom");
    expect(
      eventSummary({ result: "[omitted from event log: 34 units]" })
    ).toBeNull();
  });
});

describe("eventFacts model", () => {
  it("names the model that answered", () => {
    expect(eventFacts({ model_name: "gpt-6-luna" })).toContainEqual({
      kind: "model",
      value: "gpt-6-luna",
    });
  });

  it("names both sides of a model change", () => {
    expect(
      eventFacts({ from: { model_name: "a" }, to: { model_name: "b" } })
    ).toContainEqual({ kind: "model", value: "a → b" });
    expect(eventFacts({ old_model: "a", new_model: "b" })).toContainEqual({
      kind: "model",
      value: "a → b",
    });
  });
});

describe("message.received", () => {
  it("is a type of the vocabulary", () => {
    expect(eventTypeKey("message.received")).toBe("messageReceived");
  });
});

describe("shownEventData", () => {
  it("leaves out what the log did not keep, and is null when nothing else is there", () => {
    expect(
      shownEventData({
        tool_name: "shell",
        result: "[omitted from event log: 34 units]",
        arguments: { path: "[nested value omitted from event log]" },
      })
    ).toEqual({ tool_name: "shell" });
    expect(
      shownEventData({ result: "[omitted from event log: 2 units]" })
    ).toBeNull();
  });
});
