import type { AgentCreate, AgentUpdate } from "@/api/client/types.gen";
import type { AgentFormValues } from "../create/types";

export function toToolsPayload(
  toolsConfig: AgentFormValues["tools_config"]
): AgentCreate["tools"] {
  const tools: NonNullable<AgentCreate["tools"]> = [];

  for (const mcp of toolsConfig?.mcp_server_configs ?? []) {
    const allowed = (mcp.allowed_tools ?? []).map((tool) => ({
      tool_name: tool.tool_name,
      requires_user_confirmation: tool.requires_user_confirmation ?? false,
    }));
    tools.push({
      type: "mcp",
      name: mcp.mcp_server_id,
      settings: { allowed_tools: allowed.length ? allowed : null },
    });
  }

  for (const openapi of toolsConfig?.openapi_configs ?? []) {
    tools.push({
      type: "openapi",
      name: openapi.openapi_connection_id,
      settings: {
        openapi_connection_id: openapi.openapi_connection_id,
        allowed_tools: openapi.allowed_tools?.length
          ? openapi.allowed_tools
          : null,
        load_mode: openapi.load_mode,
      },
    });
  }

  for (const builtin of toolsConfig?.builtin_tools ?? []) {
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

  return tools.length ? tools : null;
}

function toEventsPayload(
  eventsConfig: AgentFormValues["events_config"]
): AgentCreate["events_config"] {
  return eventsConfig?.events?.length
    ? {
        events: eventsConfig.events.map((event) => ({
          event_type: event.event_type,
          config: event.config ?? null,
          enabled: event.enabled ?? true,
        })),
      }
    : null;
}

export function toAgentCreate(input: AgentFormValues): AgentCreate {
  return {
    name: input.name,
    description: input.description || "",
    instruction: input.instruction,
    model_id: input.model_id,
    tools: toToolsPayload(input.tools_config),
    events_config: toEventsPayload(input.events_config),
    planning: input.planning ?? null,
    a2ui_enabled: input.a2ui_enabled ?? null,
    skill_ids: input.skills?.length ? input.skills.map((skill) => skill.id) : null,
  };
}

export function toAgentUpdate(
  input: AgentFormValues,
  skillIds?: string[] | null
): AgentUpdate {
  return {
    name: input.name,
    description: input.description || "",
    instruction: input.instruction,
    model_id: input.model_id,
    tools: toToolsPayload(input.tools_config),
    events_config: toEventsPayload(input.events_config),
    planning: input.planning ?? null,
    a2ui_enabled: input.a2ui_enabled ?? null,
    skill_ids:
      skillIds !== undefined && skillIds !== null
        ? skillIds.length
          ? skillIds
          : null
        : input.skills?.length
          ? input.skills.map((skill) => skill.id)
          : null,
  };
}
