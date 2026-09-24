import { describe, expect, it } from "vitest";
import type {
  AgentResponse,
  McpServerInstanceResponse,
} from "@/api/client/types.gen";
import { buildExecutionResources } from "./executionResources";

const agent: AgentResponse = {
  id: "orchestrator-id",
  name: "Operations lead",
  slug: "operations-lead",
  status: "active",
};

const mcp: McpServerInstanceResponse = {
  id: "33333333-3333-4333-8333-333333333333",
  name: "Workspace GitHub",
  description: null,
  created_at: "2026-09-11T00:00:00Z",
  updated_at: "2026-09-11T00:00:00Z",
  server_spec_id: "server-id",
  json_spec: {},
  verification: {},
  tools: [{ name: "list_issues" }, { name: "delete_repository" }],
};

const base = {
  agent,
  agents: [agent],
  availableMcps: [mcp],
  availableSkills: [
    { id: "44444444-4444-4444-8444-444444444444", name: "Triage" },
  ],
  selectedMcps: [],
  selectedSkills: [],
};

describe("automation execution resources", () => {
  it("marks name-only task selections unavailable even if a workspace name matches", () => {
    const result = buildExecutionResources({
      ...base,
      selectedMcps: [{ id: mcp.name }],
      selectedSkills: [{ id: "Triage" }],
    });
    expect(result.mcps[0]).toMatchObject({ unavailable: true, tools: [] });
    expect(result.skills[0]).toMatchObject({ unavailable: true });
  });

  it("deduplicates name and UUID MCP references without widening inherited tool scope", () => {
    const settings = {
      allowed_tools: [
        { tool_name: "list_issues", requires_user_confirmation: true },
      ],
    };
    const result = buildExecutionResources({
      ...base,
      agent: { ...agent, tools: [{ type: "mcp", name: mcp.name, settings }] },
      selectedMcps: [{ id: mcp.id }, { id: mcp.id }],
    });

    expect(result.mcps).toHaveLength(1);
    expect(result.mcps[0]).toMatchObject({
      id: mcp.id,
      name: mcp.name,
      inherited: true,
      restricted: true,
      settings,
      taskRefIds: [mcp.id],
      tools: [{ name: "list_issues", approval: true, unavailable: false }],
    });
  });

  it("keeps server approval on every tool and marks removed configured tools unavailable", () => {
    const result = buildExecutionResources({
      ...base,
      agent: {
        ...agent,
        tools: [
          {
            type: "mcp",
            name: mcp.id,
            settings: {
              requires_user_confirmation: true,
              allowed_tools: [
                { tool_name: "list_issues" },
                { tool_name: "removed_tool" },
              ],
            },
          },
        ],
      },
    });
    expect(result.mcps[0].tools).toEqual([
      { name: "list_issues", approval: true, unavailable: false },
      { name: "removed_tool", approval: true, unavailable: true },
    ]);
  });

  it("treats an empty tool selection as no tools, not all tools", () => {
    const result = buildExecutionResources({
      ...base,
      agent: {
        ...agent,
        tools: [
          { type: "mcp", name: mcp.id, settings: { allowed_tools: [] } },
          { type: "openapi", name: "CRM", settings: { allowed_tools: [] } },
        ],
      },
    });
    expect(result.mcps[0]).toMatchObject({ restricted: true, tools: [] });
    expect(result.capabilities[0]).toMatchObject({ allowedTools: [] });
  });

  it("shows an unrestricted task addition with concrete tools and removable task origin", () => {
    const result = buildExecutionResources({
      ...base,
      selectedMcps: [{ id: mcp.id }],
    });
    expect(result.mcps[0]).toMatchObject({
      inherited: false,
      restricted: false,
      taskRefIds: [mcp.id],
    });
    expect(result.mcps[0].tools.map((tool) => tool.name)).toEqual([
      "list_issues",
      "delete_repository",
    ]);
  });

  it("does not treat an unresolved MCP name as an available connection", () => {
    const result = buildExecutionResources({
      ...base,
      selectedMcps: [{ id: "deleted-id", name: "Deleted MCP" }],
    });
    expect(result.mcps[0]).toMatchObject({
      id: "deleted-id",
      name: "Deleted MCP",
      unavailable: true,
      tools: [],
    });
  });

  it("merges selected skill IDs while keeping inherited skills when the catalog is unavailable", () => {
    const result = buildExecutionResources({
      ...base,
      availableSkills: [],
      agent: {
        ...agent,
        skills: [
          { id: "44444444-4444-4444-8444-444444444444", name: "Triage" },
        ],
      },
      selectedSkills: [
        { id: "44444444-4444-4444-8444-444444444444" },
        { id: "missing-skill", name: "Removed skill" },
      ],
    });
    expect(result.skills).toEqual([
      {
        id: "44444444-4444-4444-8444-444444444444",
        name: "Triage",
        inherited: true,
        taskRefIds: ["44444444-4444-4444-8444-444444444444"],
        unavailable: false,
      },
      {
        id: "missing-skill",
        name: "Removed skill",
        inherited: false,
        taskRefIds: ["missing-skill"],
        unavailable: true,
      },
    ]);
  });

  it("resolves delegation by exact agent name and keeps remote bindings distinct", () => {
    const result = buildExecutionResources({
      ...base,
      agents: [
        { ...agent, id: "reviewer-id", name: "Reviewer", slug: "reviewer" },
      ],
      agent: {
        ...agent,
        tools: [
          {
            type: "agent",
            name: "Reviewer",
            settings: { requires_user_confirmation: true },
          },
          { type: "agent", name: "reviewer" },
          {
            type: "agent",
            name: "Remote reviewer",
            settings: { a2a_url: "https://remote.example/a2a" },
          },
        ],
      },
    });
    expect(result.delegatedAgents).toMatchObject([
      {
        id: "reviewer-id",
        name: "Reviewer",
        unavailable: false,
        remote: false,
        approval: true,
      },
      { id: "reviewer", unavailable: true, remote: false },
      { name: "Remote reviewer", unavailable: false, remote: true },
    ]);
  });

  it("retains built-in method exclusions and OpenAPI operation restrictions", () => {
    const result = buildExecutionResources({
      ...base,
      agent: {
        ...agent,
        tools: [
          {
            type: "code",
            name: "file_tools",
            settings: { disabled_methods: ["delete_file"] },
          },
          {
            type: "openapi",
            name: "CRM",
            settings: {
              allowed_tools: ["list_contacts"],
              requires_user_confirmation: true,
            },
          },
        ],
      },
    });
    expect(result.capabilities).toMatchObject([
      { name: "file_tools", type: "code", disabledMethods: ["delete_file"] },
      {
        name: "CRM",
        type: "openapi",
        allowedTools: ["list_contacts"],
        approval: true,
      },
    ]);
  });

  it("shows task additions while the orchestrator has not been loaded", () => {
    const result = buildExecutionResources({
      ...base,
      agent: null,
      selectedSkills: [{ id: "44444444-4444-4444-8444-444444444444" }],
    });
    expect(result.delegatedAgents).toEqual([]);
    expect(result.skills).toMatchObject([
      { name: "Triage", inherited: false, unavailable: false },
    ]);
  });
});
