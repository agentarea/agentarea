import { describe, expect, it } from "vitest";
import type { AgentResponse } from "@/api/client/types.gen";
import { buildConnectionUsage, readLastDispatch } from "./usage";

function agent(
  name: string,
  tools: AgentResponse["tools"]
): AgentResponse {
  return {
    id: `id-${name}`,
    name,
    slug: name,
    status: "active",
    tools,
  } as AgentResponse;
}

const connections = [
  { id: "11111111-1111-1111-1111-111111111111", name: "github" },
  { id: "22222222-2222-2222-2222-222222222222", name: "stripe" },
];

describe("buildConnectionUsage", () => {
  it("matches a connection referenced by name as well as by id", () => {
    const usage = buildConnectionUsage(
      [
        agent("by-id", [
          {
            type: "mcp",
            name: "11111111-1111-1111-1111-111111111111",
            settings: { allowed_tools: [{ tool_name: "create_issue" }] },
          },
        ]),
        agent("by-name", [
          {
            type: "mcp",
            name: "github",
            settings: { allowed_tools: [{ tool_name: "list_issues" }] },
          },
        ]),
      ],
      connections
    );

    expect(usage["11111111-1111-1111-1111-111111111111"]).toEqual({
      agents: 2,
      grantedTools: 2,
    });
  });

  it("counts distinct granted tools, not grants", () => {
    const usage = buildConnectionUsage(
      [
        agent("a", [
          {
            type: "mcp",
            name: "github",
            settings: {
              allowed_tools: [
                { tool_name: "create_issue" },
                { tool_name: "list_issues" },
              ],
            },
          },
        ]),
        agent("b", [
          {
            type: "mcp",
            name: "github",
            settings: { allowed_tools: [{ tool_name: "create_issue" }] },
          },
        ]),
      ],
      connections
    );

    expect(usage["11111111-1111-1111-1111-111111111111"].grantedTools).toBe(2);
  });

  it("reports an unrestricted grant as null instead of a number", () => {
    const usage = buildConnectionUsage(
      [agent("wildcard", [{ type: "mcp", name: "github", settings: null }])],
      connections
    );

    expect(usage["11111111-1111-1111-1111-111111111111"]).toEqual({
      agents: 1,
      grantedTools: null,
    });
  });

  it("leaves untouched connections at zero", () => {
    const usage = buildConnectionUsage(
      [agent("a", [{ type: "mcp", name: "github", settings: null }])],
      connections
    );

    expect(usage["22222222-2222-2222-2222-222222222222"]).toEqual({
      agents: 0,
      grantedTools: 0,
    });
  });

  it("ignores non-MCP tool configs that share a connection name", () => {
    const usage = buildConnectionUsage(
      [
        agent("coder", [
          { type: "code", name: "github" } as NonNullable<
            AgentResponse["tools"]
          >[number],
        ]),
      ],
      connections
    );

    expect(usage["11111111-1111-1111-1111-111111111111"].agents).toBe(0);
  });
});

describe("readLastDispatch", () => {
  it("reads the dispatch record written on every tool call", () => {
    expect(
      readLastDispatch({
        schema_version: 1,
        status: "failed",
        at: "2026-09-21T10:00:00Z",
        error: "connection refused",
      })
    ).toEqual({
      status: "failed",
      at: "2026-09-21T10:00:00Z",
      error: "connection refused",
    });
  });

  it("treats a missing record as never called", () => {
    expect(readLastDispatch(null)).toBeNull();
    expect(readLastDispatch({})).toBeNull();
  });

  it("unwraps a structured error object", () => {
    expect(
      readLastDispatch({ status: "failed", at: null, error: { message: "boom" } })
    ).toEqual({ status: "failed", at: null, error: "boom" });
  });
});
