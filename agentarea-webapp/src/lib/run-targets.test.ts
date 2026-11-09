import { describe, expect, it } from "vitest";
import { ON_PLATFORM, runTargets } from "./run-targets";

const sonnet = {
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
const claude = {
  id: "claude-1",
  kind: "claude",
  name: "claude-laptop",
  default_model: null,
  online: false,
};

describe("runTargets", () => {
  it("offers a platform agent its model first, then every runner", () => {
    const { targets, agentTarget } = runTargets(
      { model: sonnet, client: null },
      [codex, claude]
    );

    expect(targets.map((t) => t.id)).toEqual([
      ON_PLATFORM,
      "codex-1",
      "claude-1",
    ]);
    expect(agentTarget).toBe(ON_PLATFORM);
  });

  it("puts the agent's own runner first and leaves the platform out", () => {
    const { targets, agentTarget } = runTargets(
      { model: null, client: claude },
      [codex, claude]
    );

    expect(targets.map((t) => t.id)).toEqual(["claude-1", "codex-1"]);
    expect(agentTarget).toBe("claude-1");
  });

  it("keeps the agent's runner even when the list does not carry it", () => {
    const { targets } = runTargets({ model: null, client: codex }, [claude]);

    expect(targets.map((t) => t.id)).toEqual(["codex-1", "claude-1"]);
  });

  it("has nowhere to run an agent with neither a model nor a runner by default", () => {
    const { targets, agentTarget } = runTargets(
      { model: null, client: null },
      [codex]
    );

    expect(targets.map((t) => t.id)).toEqual(["codex-1"]);
    expect(agentTarget).toBeNull();
  });
});
