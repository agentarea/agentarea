import type {
  AgentResponse,
  McpServerInstanceResponse,
  McpToolSettings,
} from "@/api/client/types.gen";
import { resolveMcpRef } from "@/lib/mcp/resolveMcpRef";
import type { TaskParameterRef } from "../components/taskParameters";

export type ExecutionResource = {
  id: string;
  name: string;
  inherited: boolean;
  taskRefIds: string[];
  unavailable: boolean;
};

export type ExecutionMcp = ExecutionResource & {
  settings: McpToolSettings | null;
  tools: Array<{ name: string; approval: boolean; unavailable: boolean }>;
  restricted: boolean;
};

type ExecutionResourceInput = {
  agent: AgentResponse | null;
  agents: AgentResponse[];
  availableMcps: McpServerInstanceResponse[];
  availableSkills: TaskParameterRef[];
  selectedMcps: TaskParameterRef[];
  selectedSkills: TaskParameterRef[];
};

const TASK_RESOURCE_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Resolve configured references before merging so task additions retain agent restrictions. */
export function buildExecutionResources({
  agent,
  agents,
  availableMcps,
  availableSkills,
  selectedMcps,
  selectedSkills,
}: ExecutionResourceInput) {
  const mcps = new Map<string, ExecutionMcp>();

  const addMcp = (
    ref: TaskParameterRef,
    inherited: boolean,
    settings: McpToolSettings | null = null
  ) => {
    const resolved =
      inherited || TASK_RESOURCE_ID.test(ref.id)
        ? resolveMcpRef(
            inherited ? ref.id : ref.id.toLowerCase(),
            availableMcps,
            []
          )
        : null;
    const instance = resolved?.status === "instance" ? resolved.instance : null;
    const id = instance?.id ?? ref.id;
    const existing = mcps.get(id);
    if (existing) {
      if (!inherited && !existing.taskRefIds.includes(ref.id)) {
        existing.taskRefIds.push(ref.id);
      }
      return;
    }

    const available =
      resolved?.status === "instance" ? resolved.availableTools : [];
    const allowed = settings?.allowed_tools ?? null;
    const restricted = allowed !== null;
    const serverApproval = Boolean(settings?.requires_user_confirmation);
    const tools = allowed
      ? allowed.map((permission) => ({
          name: permission.tool_name,
          approval:
            serverApproval || Boolean(permission.requires_user_confirmation),
          unavailable:
            available.length > 0 &&
            !available.some((tool) => tool.name === permission.tool_name),
        }))
      : available.map((tool) => ({
          name: tool.name,
          approval: serverApproval,
          unavailable: false,
        }));

    mcps.set(id, {
      id,
      name: instance?.name ?? ref.name ?? ref.id,
      inherited,
      taskRefIds: inherited ? [] : [ref.id],
      unavailable: instance === null,
      settings,
      tools,
      restricted,
    });
  };

  for (const tool of agent?.tools ?? []) {
    if (tool.type === "mcp")
      addMcp({ id: tool.name }, true, tool.settings ?? null);
  }
  selectedMcps.forEach((ref) => addMcp(ref, false));

  const inheritedSkills: TaskParameterRef[] = (agent?.skills ?? []).flatMap(
    (skill) =>
      typeof skill.id === "string"
        ? [
            {
              id: skill.id,
              name: typeof skill.name === "string" ? skill.name : null,
            },
          ]
        : []
  );
  const skills = new Map<string, ExecutionResource>();
  const knownSkills = [...availableSkills, ...inheritedSkills];
  const addSkill = (ref: TaskParameterRef, inherited: boolean) => {
    const resolved =
      inherited || TASK_RESOURCE_ID.test(ref.id)
        ? knownSkills.find(
            (skill) => skill.id.toLowerCase() === ref.id.toLowerCase()
          )
        : undefined;
    const id = resolved?.id ?? ref.id;
    const existing = skills.get(id);
    if (existing) {
      if (!inherited && !existing.taskRefIds.includes(ref.id))
        existing.taskRefIds.push(ref.id);
      return;
    }
    skills.set(id, {
      id,
      name: resolved?.name ?? ref.name ?? ref.id,
      inherited,
      taskRefIds: inherited ? [] : [ref.id],
      unavailable: !resolved,
    });
  };
  inheritedSkills.forEach((ref) => addSkill(ref, true));
  selectedSkills.forEach((ref) => addSkill(ref, false));

  const delegatedAgents = (agent?.tools ?? []).flatMap((tool) => {
    if (tool.type !== "agent") return [];
    // Delegation resolves an exact agent name, not a slug or fuzzy display match.
    const remote = Boolean(tool.settings?.a2a_url);
    const target = remote
      ? undefined
      : agents.find((candidate) => candidate.name === tool.name);
    return [
      {
        id: target?.id ?? tool.name,
        name: target?.name ?? tool.name,
        inherited: true,
        taskRefIds: [],
        unavailable: !remote && !target,
        remote,
        approval: Boolean(tool.settings?.requires_user_confirmation),
      },
    ];
  });

  const capabilities = (agent?.tools ?? []).flatMap<{
    id: string;
    name: string;
    type: "code" | "openapi";
    approval: boolean;
    disabledMethods: string[];
    allowedTools: string[] | null;
  }>((tool) => {
    if (tool.type === "code") {
      return [
        {
          id: `code:${tool.name}`,
          name: tool.name,
          type: tool.type,
          approval: Boolean(tool.settings?.requires_user_confirmation),
          disabledMethods: tool.settings?.disabled_methods ?? [],
          allowedTools: null,
        },
      ];
    }
    if (tool.type === "openapi") {
      return [
        {
          id: `openapi:${tool.settings?.openapi_connection_id ?? tool.name}`,
          name: tool.name,
          type: tool.type,
          approval: Boolean(tool.settings?.requires_user_confirmation),
          disabledMethods: [],
          allowedTools: tool.settings?.allowed_tools ?? null,
        },
      ];
    }
    return [];
  });

  return {
    mcps: [...mcps.values()],
    skills: [...skills.values()],
    delegatedAgents,
    capabilities,
  };
}
