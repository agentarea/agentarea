import type {
  AgentCreate,
  AgentResponse,
  AgentUpdate,
  CodeToolConfig,
  McpToolConfigOutput,
  OpenApiToolConfig,
} from "@/api/client/types.gen";
import { zEventsConfig } from "@/api/client/zod.gen";
import type { AgentFormValues, AgentSkill } from "../create/types";

type AgentTool = NonNullable<AgentResponse["tools"]>[number];

const FORM_TOOL_TYPES: ReadonlySet<AgentTool["type"]> = new Set([
  "mcp",
  "openapi",
  "code",
]);

function toFormSkill(skill: Record<string, unknown>): AgentSkill {
  const { id, name, description } = skill;
  if (typeof id !== "string" || typeof name !== "string") {
    throw new Error(`Agent skill without an id or name: ${JSON.stringify(skill)}`);
  }
  return {
    id,
    name,
    description: typeof description === "string" ? description : null,
  };
}

export function fromAgent(agent: AgentResponse): AgentFormValues {
  const tools = agent.tools ?? [];

  return {
    name: agent.name,
    description: agent.description ?? "",
    instruction: agent.instruction ?? "",
    model_id: agent.model_id ?? "",
    tools_config: {
      mcp_server_configs: tools
        .filter((t): t is McpToolConfigOutput => t.type === "mcp")
        .map((t) => ({
          mcp_server_id: t.name,
          allowed_tools:
            t.settings?.allowed_tools?.map((tool) => ({
              tool_name: tool.tool_name,
              requires_user_confirmation: tool.requires_user_confirmation ?? false,
            })) ?? null,
        })),
      openapi_configs: tools
        .filter((t): t is OpenApiToolConfig => t.type === "openapi")
        .map((t) => ({
          // Legacy entries stored the display name in `name`.
          openapi_connection_id: t.settings?.openapi_connection_id ?? t.name,
          allowed_tools: t.settings?.allowed_tools ?? null,
          load_mode: t.settings?.load_mode ?? undefined,
          requires_user_confirmation: t.settings?.requires_user_confirmation ?? false,
        })),
      builtin_tools: tools
        .filter((t): t is CodeToolConfig => t.type === "code")
        .map((t) => ({
          tool_name: t.name,
          disabled_methods: Object.fromEntries(
            (t.settings?.disabled_methods ?? []).map((method) => [method, false])
          ),
          requires_user_confirmation: t.settings?.requires_user_confirmation ?? false,
        })),
      carried_tools: tools.filter((t) => !FORM_TOOL_TYPES.has(t.type)),
    },
    events_config: {
      events: zEventsConfig.parse(agent.events_config ?? {}).events ?? [],
    },
    planning: agent.planning ?? false,
    a2ui_enabled: agent.a2ui_enabled ?? false,
    skills: (agent.skills ?? []).map(toFormSkill),
  };
}

export function toToolsPayload(
  toolsConfig: AgentFormValues["tools_config"]
): NonNullable<AgentUpdate["tools"]> {
  const tools: NonNullable<AgentUpdate["tools"]> = [];

  for (const mcp of toolsConfig.mcp_server_configs) {
    const allowed =
      mcp.allowed_tools?.map((tool) => ({
        tool_name: tool.tool_name,
        requires_user_confirmation: tool.requires_user_confirmation ?? false,
      })) ?? null;
    tools.push({
      type: "mcp",
      name: mcp.mcp_server_id,
      settings: { allowed_tools: allowed },
    });
  }

  for (const openapi of toolsConfig.openapi_configs ?? []) {
    tools.push({
      type: "openapi",
      name: openapi.openapi_connection_id,
      settings: {
        openapi_connection_id: openapi.openapi_connection_id,
        allowed_tools: openapi.allowed_tools ?? null,
        load_mode: openapi.load_mode,
        requires_user_confirmation: openapi.requires_user_confirmation ?? null,
      },
    });
  }

  for (const builtin of toolsConfig.builtin_tools ?? []) {
    const disabled = builtin.disabled_methods
      ? Object.entries(builtin.disabled_methods)
          .filter(([, enabled]) => enabled === false)
          .map(([method]) => method)
      : null;
    tools.push({
      type: "code",
      name: builtin.tool_name,
      settings: {
        disabled_methods: disabled?.length ? disabled : null,
        requires_user_confirmation:
          builtin.requires_user_confirmation ?? null,
      },
    });
  }

  return [...tools, ...(toolsConfig.carried_tools ?? [])];
}

// The update endpoint reads null as "leave unchanged", so every collection is
// sent explicitly, empty included, for a cleared field to reach the agent.
function toAgentBody(input: AgentFormValues) {
  return {
    name: input.name,
    description: input.description,
    instruction: input.instruction,
    model_id: input.model_id,
    tools: toToolsPayload(input.tools_config),
    events_config: {
      events: input.events_config.events.map((event) => ({
        event_type: event.event_type,
        config: event.config ?? null,
        enabled: event.enabled ?? true,
      })),
    },
    planning: input.planning,
    a2ui_enabled: input.a2ui_enabled,
    skill_ids: (input.skills ?? []).map((skill) => skill.id),
  };
}

export function toAgentUpdate(input: AgentFormValues): AgentUpdate {
  return toAgentBody(input);
}

export function toAgentCreate(input: AgentFormValues): AgentCreate {
  return toAgentBody(input);
}
