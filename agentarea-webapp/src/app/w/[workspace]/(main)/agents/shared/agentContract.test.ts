import type { AgentResponse } from "@/api/client/types.gen";
import { describe, expect, it } from "vitest";
import {
  fromAgent,
  toAgentCreate,
  toAgentUpdate,
  toToolsPayload,
} from "./agentContract";

describe("toToolsPayload", () => {
  it("keeps null (all tools) distinct from an empty selection (no tools)", () => {
    const tools = toToolsPayload({
      mcp_server_configs: [
        { mcp_server_id: "github-all", allowed_tools: null },
        { mcp_server_id: "github-none", allowed_tools: [] },
        {
          mcp_server_id: "github-some",
          allowed_tools: [{ tool_name: "list_issues" }],
        },
      ],
      openapi_configs: [
        { openapi_connection_id: "crm-all", allowed_tools: null },
        { openapi_connection_id: "crm-none", allowed_tools: [] },
      ],
    });

    expect(tools).toMatchObject([
      { type: "mcp", settings: { allowed_tools: null } },
      { type: "mcp", settings: { allowed_tools: [] } },
      {
        type: "mcp",
        settings: {
          allowed_tools: [
            { tool_name: "list_issues", requires_user_confirmation: false },
          ],
        },
      },
      { type: "openapi", settings: { allowed_tools: null } },
      { type: "openapi", settings: { allowed_tools: [] } },
    ]);
  });

  it("sends [] for an agent with no tools, never null", () => {
    expect(toToolsPayload({ mcp_server_configs: [] })).toEqual([]);
    expect(
      toToolsPayload({
        mcp_server_configs: [],
        builtin_tools: [],
        openapi_configs: [],
      })
    ).toEqual([]);
  });
});

describe("toAgentCreate", () => {
  it("always sends tools and triggers as arrays", () => {
    const body = toAgentCreate({
      name: "Support desk",
      description: "",
      instruction: "",
      model_id: "",
      tools_config: { mcp_server_configs: [] },
      planning: false,
      a2ui_enabled: false,
    });

    expect(body.tools).toEqual([]);
    expect(body.triggers).toEqual([]);
    expect(body).not.toHaveProperty("events_config");
  });
});

const delegation = {
  type: "agent" as const,
  name: "bizdev-research",
  settings: {
    description_override: "Researches the lead before BizDev replies",
    requires_user_confirmation: true,
  },
};

const tools: NonNullable<AgentResponse["tools"]> = [
  {
    type: "mcp",
    name: "agentarea-github",
    settings: {
      allowed_tools: [
        { tool_name: "list_issues", requires_user_confirmation: false },
        { tool_name: "create_issue", requires_user_confirmation: true },
      ],
    },
  },
  {
    type: "openapi",
    name: "crm-connection-id",
    settings: {
      openapi_connection_id: "crm-connection-id",
      allowed_tools: ["createLead"],
      load_mode: "searchable",
      requires_user_confirmation: true,
    },
  },
  {
    type: "code",
    name: "agentarea/shell",
    settings: {
      disabled_methods: ["write_file"],
      requires_user_confirmation: true,
    },
  },
  delegation,
];

const agent: AgentResponse = {
  id: "7d0c7a52-6a55-4c4c-9a55-2f3f9c1d0b11",
  slug: "bizdev-review",
  name: "BizDev — Review",
  status: "active",
  description: "Reviews inbound leads for agentarea.dev",
  instruction: "Score each lead and draft a reply.",
  model_id: "3b8f1f4e-5f55-4a51-8f53-0a4b8f2f7c21",
  planning: true,
  a2ui_enabled: true,
  skills: [
    { id: "skill-lead-scoring", name: "Lead scoring", description: null },
    { id: "skill-reply-drafts", name: "Reply drafts", description: "Tone guide" },
  ],
  tools,
};

describe("fromAgent -> toAgentUpdate", () => {
  it("round-trips every tool, load_mode, skill and a2ui_enabled", () => {
    const update = toAgentUpdate(fromAgent(agent));

    expect(update.tools).toHaveLength(tools.length);
    expect(update.tools).toEqual(expect.arrayContaining(tools));
    expect(update.skill_ids).toEqual(["skill-lead-scoring", "skill-reply-drafts"]);
    expect(update.a2ui_enabled).toBe(true);
    expect(update.planning).toBe(true);
    expect(update.name).toBe("BizDev — Review");
  });

  it("drops a removed skill and keeps the delegation tools", () => {
    const values = fromAgent(agent);
    values.skills = (values.skills ?? []).filter((s) => s.id !== "skill-reply-drafts");

    const update = toAgentUpdate(values);

    expect(update.skill_ids).toEqual(["skill-lead-scoring"]);
    expect(update.tools).toContainEqual(delegation);
  });

  it("sends explicit empties so a cleared form clears the agent", () => {
    const values = fromAgent(agent);
    values.skills = [];
    values.tools_config = {
      ...values.tools_config,
      mcp_server_configs: [],
      openapi_configs: [],
      builtin_tools: [],
    };

    const update = toAgentUpdate(values);

    expect(update.skill_ids).toEqual([]);
    expect(update.tools).toEqual([delegation]);
  });
});
