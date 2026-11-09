import { describe, expect, it } from "vitest";
import { runsOn } from "./run-targets";

const sonnet = {
  id: "m-sonnet",
  name: "Claude Sonnet 5",
  provider: "Anthropic",
  iconUrl: null,
};
const codex = {
  id: "codex-1",
  kind: "codex",
  name: "codex-xorek",
  default_model: "gpt-6.1-terra",
  online: true,
};
const options = { models: [sonnet], runners: [codex] };

describe("runsOn", () => {
  it("names a platform agent's model", () => {
    expect(runsOn({ modelId: "m-sonnet", client: null }, options)).toEqual({
      on: "platform",
      model: sonnet,
    });
  });

  it("names a runner agent's client as the runner list reports it", () => {
    const summary = {
      id: "codex-1",
      kind: "codex",
      name: "codex-xorek",
      default_model: null,
      online: false,
    };

    expect(runsOn({ modelId: null, client: summary }, options)).toEqual({
      on: "runner",
      runner: codex,
    });
  });

  it("falls back to the agent's own summary of a runner the list does not carry", () => {
    const summary = {
      id: "claude-1",
      kind: "claude",
      name: "claude-laptop",
      default_model: null,
      online: false,
    };

    expect(runsOn({ modelId: null, client: summary }, options)).toEqual({
      on: "runner",
      runner: summary,
    });
  });

  it("names nothing for a model the workspace no longer has", () => {
    expect(runsOn({ modelId: "m-gone", client: null }, options)).toBeNull();
  });
});
