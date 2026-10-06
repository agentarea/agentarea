import { describe, expect, it } from "vitest";
import {
  eventDisposition,
  matchesDisposition,
  resolveForwardSource,
  sortedForwardTargets,
  summarizeOutcomes,
} from "./streamOutcome";

describe("what happened to an event", () => {
  it("is 'unheard' when no subscription took it", () => {
    expect(eventDisposition(summarizeOutcomes([]))).toBe("unheard");
  });

  it("is an error if any subscriber failed, whatever the others did", () => {
    const summary = summarizeOutcomes([
      { verdict: "reacted" },
      { verdict: "error" },
      { verdict: "skipped" },
    ]);
    expect(summary).toEqual({
      reacted: 1,
      skipped: 1,
      error: 1,
      unknown: 0,
      total: 3,
    });
    expect(eventDisposition(summary)).toBe("error");
  });

  it("never reads a verdict it does not know as skipped or reacted", () => {
    const summary = summarizeOutcomes([
      { verdict: "reacted" },
      { verdict: "pending" },
      { verdict: "skipped" },
    ]);
    expect(summary).toEqual({
      reacted: 1,
      skipped: 1,
      error: 0,
      unknown: 1,
      total: 3,
    });
    expect(eventDisposition(summary)).toBe("unknown");
    expect(matchesDisposition([{ verdict: "pending" }], "skipped")).toBe(false);
  });

  it("is a reaction when one subscriber reacted and the rest skipped", () => {
    expect(
      eventDisposition(
        summarizeOutcomes([{ verdict: "skipped" }, { verdict: "reacted" }])
      )
    ).toBe("reacted");
  });

  it("filters by disposition, 'all' keeping everything", () => {
    const skipped = [{ verdict: "skipped" }];
    expect(matchesDisposition(skipped, "all")).toBe(true);
    expect(matchesDisposition(skipped, "skipped")).toBe(true);
    expect(matchesDisposition(skipped, "reacted")).toBe(false);
    expect(matchesDisposition([], "unheard")).toBe(true);
  });
});

describe("resolving a forwarded event's source", () => {
  it("is null when the event carries no causation", () => {
    expect(
      resolveForwardSource({
        causation_id: null,
        source: "webhook:abc",
        event_key: "webhook-id:abc",
      })
    ).toBeNull();
  });

  it("parses the source stream and sequence ForwardHandler encoded", () => {
    expect(
      resolveForwardSource({
        causation_id: "982eeeeb-0000-0000-0000-000000000000",
        source: "stream:b4ad852d-0000-0000-0000-000000000000",
        event_key: "b4ad852d-0000-0000-0000-000000000000:5",
      })
    ).toEqual({
      streamId: "b4ad852d-0000-0000-0000-000000000000",
      sequence: 5,
    });
  });

  it("is null for a shape ForwardHandler never produces", () => {
    expect(
      resolveForwardSource({
        causation_id: "set",
        source: "webhook:abc",
        event_key: "webhook-id:abc",
      })
    ).toBeNull();
  });
});

describe("a forward's output streams in append order", () => {
  it("sorts ids the way ForwardHandler iterates them", () => {
    expect(sortedForwardTargets(["b", "a", "c"])).toEqual(["a", "b", "c"]);
  });
});
