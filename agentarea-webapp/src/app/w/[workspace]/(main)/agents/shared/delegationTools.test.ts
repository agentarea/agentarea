import type { AgentUpdate } from "@/api/client/types.gen";
import { describe, expect, it } from "vitest";
import { delegatesOf, withDelegates } from "./delegationTools";

const research = {
  type: "agent" as const,
  name: "bizdev-research",
  settings: {
    description_override: "Researches the lead before BizDev replies",
    requires_user_confirmation: true,
  },
};

const outreach = {
  type: "agent" as const,
  name: "bizdev-outreach",
  settings: { description_override: "Sends the approved reply" },
};

const shell = {
  type: "code" as const,
  name: "agentarea/shell",
  settings: { requires_user_confirmation: true },
};

const tools: NonNullable<AgentUpdate["tools"]> = [shell, research, outreach];

describe("withDelegates", () => {
  it("toggling one delegate off keeps the other delegate unchanged", () => {
    const next = withDelegates(tools, new Set(["bizdev-research"]));

    expect(next).toEqual([shell, research]);
  });

  it("adds a newly toggled delegate in the minimal shape", () => {
    const next = withDelegates(
      tools,
      new Set(["bizdev-research", "bizdev-outreach", "bizdev-review"])
    );

    expect(next).toEqual([
      shell,
      research,
      outreach,
      { type: "agent", name: "bizdev-review" },
    ]);
  });
});

describe("delegatesOf", () => {
  it("lists only agent tools, in order", () => {
    expect(delegatesOf(tools)).toEqual(["bizdev-research", "bizdev-outreach"]);
  });
});
