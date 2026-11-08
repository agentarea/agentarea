import { describe, expect, it } from "vitest";
import {
  offeredLevel,
  runnerModel,
  runnerModels,
  withReasoning,
} from "./runner-models";

const client = {
  models: [
    {
      name: "gpt-6.1-terra",
      reasoning_levels: ["low", "medium", "high"],
      default_reasoning: "low",
    },
    { name: "gpt-6-mini" },
    { reasoning_levels: ["low"] },
  ],
};

describe("runnerModels", () => {
  it("reads the levels each reported model takes and skips a nameless one", () => {
    expect(runnerModels(client)).toEqual([
      {
        name: "gpt-6.1-terra",
        reasoningLevels: ["low", "medium", "high"],
        defaultReasoning: "low",
      },
      { name: "gpt-6-mini", reasoningLevels: [], defaultReasoning: null },
    ]);
    expect(runnerModels({ models: null })).toEqual([]);
  });
});

describe("offeredLevel", () => {
  const terra = runnerModel(client, "gpt-6.1-terra");
  const mini = runnerModel(client, "gpt-6-mini");

  it("keeps a level the model offers", () => {
    expect(offeredLevel(terra, "high")).toBe("high");
  });

  it("falls back to the model's default when the model does not offer the level", () => {
    expect(offeredLevel(mini, "high")).toBe("");
    expect(offeredLevel(terra, "xhigh")).toBe("");
    expect(offeredLevel(null, "high")).toBe("");
    expect(offeredLevel(terra, null)).toBe("");
  });
});

describe("withReasoning", () => {
  it("appends a set level to the model", () => {
    expect(withReasoning("gpt-6.1-terra", "high")).toBe("gpt-6.1-terra · high");
    expect(withReasoning("gpt-6.1-terra", null)).toBe("gpt-6.1-terra");
    expect(withReasoning(null, "high")).toBeNull();
  });
});
