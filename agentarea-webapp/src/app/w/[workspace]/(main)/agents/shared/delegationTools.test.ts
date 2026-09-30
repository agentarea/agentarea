import type { AgentToolConfig, AgentUpdate } from "@/api/client/types.gen";
import { describe, expect, it } from "vitest";
import {
  delegateToolName,
  delegatesOf,
  isRemoteDelegate,
  patchDelegate,
  remoteDelegateProblem,
  withDelegates,
} from "./delegationTools";

const research: AgentToolConfig = {
  type: "agent",
  name: "bizdev-research",
  settings: {
    description_override: "Researches the lead before BizDev replies",
    requires_user_confirmation: true,
  },
};

const docs: AgentToolConfig = {
  type: "agent",
  name: "aadocs-writer",
  settings: {
    a2a_url: "https://agentarea.ru/v1/agents/x/a2a/rpc",
    auth_secret_name: "aadocs-key",
  },
};

const shell = {
  type: "code" as const,
  name: "agentarea/shell",
  settings: { requires_user_confirmation: true },
};

const tools: NonNullable<AgentUpdate["tools"]> = [shell, research, docs];

describe("delegatesOf", () => {
  it("returns the agent tools with their settings", () => {
    expect(delegatesOf(tools)).toEqual([research, docs]);
  });
});

describe("withDelegates", () => {
  it("replaces the delegates and keeps every other tool", () => {
    expect(withDelegates(tools, [docs])).toEqual([shell, docs]);
  });

  it("adds a new delegate after the others", () => {
    const review: AgentToolConfig = { type: "agent", name: "bizdev-review" };

    expect(withDelegates(tools, [research, docs, review])).toEqual([
      shell,
      research,
      docs,
      review,
    ]);
  });
});

describe("isRemoteDelegate", () => {
  it("is remote only with an A2A URL", () => {
    expect(isRemoteDelegate(docs)).toBe(true);
    expect(isRemoteDelegate(research)).toBe(false);
  });

  it("stays remote while its URL is being retyped", () => {
    const cleared = patchDelegate(docs, { a2a_url: "" });

    expect(cleared.settings?.a2a_url).toBe("");
    expect(isRemoteDelegate(cleared)).toBe(true);
  });
});

describe("patchDelegate", () => {
  it("merges settings and keeps the untouched ones", () => {
    expect(
      patchDelegate(research, { description_override: "Ask for leads" })
    ).toEqual({
      ...research,
      settings: {
        description_override: "Ask for leads",
        requires_user_confirmation: true,
      },
    });
  });

  it("keeps what is typed, spaces included", () => {
    expect(
      patchDelegate(research, { description_override: "Ask for " })
        .settings?.description_override
    ).toBe("Ask for ");
  });

  it("stores a cleared field as null", () => {
    expect(
      patchDelegate(docs, { auth_secret_name: "", description_override: "  " })
        .settings
    ).toEqual({
      a2a_url: docs.settings?.a2a_url,
      auth_secret_name: null,
      description_override: null,
    });
  });
});

describe("remoteDelegateProblem", () => {
  const url = "https://agentarea.ru/v1/agents/y/a2a/rpc";

  it("accepts a named agent with an http(s) URL", () => {
    expect(remoteDelegateProblem({ name: "support", url }, tools)).toBeNull();
  });

  it("needs a name", () => {
    expect(remoteDelegateProblem({ name: " ", url }, tools)).toBe(
      "nameRequired"
    );
  });

  it("rejects a name another delegate already uses", () => {
    expect(remoteDelegateProblem({ name: "aadocs-writer", url }, tools)).toBe(
      "nameTaken"
    );
  });

  it("rejects a name that becomes another delegate's tool name", () => {
    expect(remoteDelegateProblem({ name: "aadocs writer", url }, tools)).toBe(
      "nameTaken"
    );
  });

  it.each(["", "ftp://host/rpc", "agentarea.ru/rpc", "https://"])(
    "rejects the URL %j",
    (bad) => {
      expect(remoteDelegateProblem({ name: "support", url: bad }, tools)).toBe(
        "urlInvalid"
      );
    }
  );
});

describe("delegateToolName", () => {
  it.each([
    ["researcher", "delegate_to_researcher"],
    ["My Agent", "delegate_to_My_Agent"],
    ["agent-v2.0!", "delegate_to_agent_v2_0"],
    ["123bot", "delegate_to_agent_123bot"],
    ["a  b", "delegate_to_a_b"],
    ["---", "delegate_to_agent_"],
  ])("names %j like the runtime does", (name, expected) => {
    expect(delegateToolName(name)).toBe(expected);
  });
});
