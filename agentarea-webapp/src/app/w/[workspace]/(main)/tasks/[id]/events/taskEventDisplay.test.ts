import { describe, expect, it } from "vitest";
import { eventFacts } from "./taskEventDisplay";

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
      usage: { prompt_tokens: 10, completion_tokens: 5, cached_prompt_tokens: 0 },
    });

    expect(facts).toContainEqual({ kind: "tokens", input: 10, output: 5, cached: null });
  });
});
