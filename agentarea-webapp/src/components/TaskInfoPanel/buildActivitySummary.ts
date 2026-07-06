import type { MessageComponentType } from "@/components/Chat/types";
import { describeToolCall } from "@/components/Chat/utils/describeToolCall";
import { fileBasename, isFileLike } from "@/components/Chat/utils/fileIcon";
import type {
  ServiceGroup,
  TaskActivitySummary,
} from "./components/ActivitySummary";

const SKILL_TOOL = "activate_skill";
const HIDDEN_TOOLS = new Set(["completion", "task_complete"]);
const SANDBOX_KEY = "__sandbox__";

interface ServerInfo {
  name: string;
  icon?: string;
  id?: string;
}

interface RawEventPayload {
  tool_call_id?: string;
  server_name?: string;
  mcp_server_name?: string;
  server_icon?: string;
  mcp_server_icon?: string;
  server_instance_id?: string;
  server_id?: string;
  original_data?: RawEventPayload;
}

interface RawEvent {
  data?: RawEventPayload;
}

interface ToolUse {
  name: string;
  success: boolean;
  args?: Record<string, unknown>;
  result?: unknown;
  executionTime?: string;
  toolCallId?: string;
}

function skillNameFromArgs(args?: Record<string, unknown>): string {
  if (!args) return SKILL_TOOL;
  const candidate = args.skill || args.name || args.skill_name || args.skill_id;
  if (typeof candidate === "string" && candidate) return candidate;
  const firstString = Object.values(args).find((v) => typeof v === "string");
  return (firstString as string) || SKILL_TOOL;
}

function delegationTarget(name: string, args?: Record<string, unknown>): string | null {
  const n = name.toLowerCase();
  if (n.startsWith("delegate_to_")) {
    const raw = name.slice("delegate_to_".length).replace(/[_-]+/g, " ").trim();
    return raw ? raw.charAt(0).toUpperCase() + raw.slice(1) : "another agent";
  }
  if (n.includes("delegate") || n.includes("call_agent") || n.includes("sub_agent")) {
    const t = args?.agent || args?.agent_name || args?.target;
    return typeof t === "string" && t ? t : "another agent";
  }
  return null;
}

function parseSeconds(s?: string): number {
  if (!s) return 0;
  const m = String(s).match(/([\d.]+)\s*s/);
  return m ? parseFloat(m[1]) : 0;
}

const FILE_TOKEN_RE = /[A-Za-z0-9._/\-]+\.[A-Za-z0-9]{1,8}/g;

function extractFilesFromText(text: string, into: Set<string>) {
  for (const match of text.matchAll(FILE_TOKEN_RE)) {
    if (isFileLike(match[0])) into.add(fileBasename(match[0]));
  }
}

/**
 * Map tool_call_id → MCP server info, read from the raw event stream.
 * MCP tool names aren't self-describing, so server attribution comes from the
 * event payload (server_name / server_icon / server_instance_id).
 */
function buildServerMap(rawEvents: RawEvent[]): Map<string, ServerInfo> {
  const map = new Map<string, ServerInfo>();
  for (const ev of rawEvents || []) {
    const d: RawEventPayload = ev?.data?.original_data ?? ev?.data ?? {};
    const id = d.tool_call_id ?? ev?.data?.tool_call_id;
    const name = d.server_name ?? d.mcp_server_name;
    const icon = d.server_icon ?? d.mcp_server_icon;
    const sid = d.server_instance_id ?? d.server_id;
    if (id && (name || sid)) {
      map.set(id, { name: name || "MCP server", icon, id: sid });
    }
  }
  return map;
}

function collectToolUses(messages: MessageComponentType[]): ToolUse[] {
  const uses: ToolUse[] = [];
  for (const m of messages) {
    if (m.type === "tool_result") {
      uses.push({
        name: m.data.tool_name,
        success: m.data.success !== false,
        args: m.data.arguments,
        result: m.data.result,
        executionTime: m.data.execution_time,
        toolCallId: m.data.tool_call_id,
      });
    } else if (m.type === "tool_call_started") {
      uses.push({
        name: m.data.tool_name,
        success: true,
        args: m.data.arguments,
        toolCallId: m.data.tool_call_id,
      });
    } else if (m.type === "tool_call_group") {
      for (const t of m.data.tools) {
        uses.push({
          name: t.tool_name,
          success: t.success !== false,
          args: t.arguments,
          result: t.result,
          executionTime: t.execution_time,
          toolCallId: t.tool_call_id,
        });
      }
    }
  }
  return uses;
}

function addToolToGroup(group: ServiceGroup, use: ToolUse) {
  group.count += 1;
  group.durationSec += parseSeconds(use.executionTime);
  if (!group.firstCallId && use.toolCallId) group.firstCallId = use.toolCallId;
  const detail = describeToolCall(use.name, use.args);
  const existing = group.tools.find((t) => t.name === use.name);
  if (existing) {
    existing.count += 1;
    if (!use.success) existing.failed += 1;
    if (detail.code && existing.uses.length < 4) existing.uses.push(detail.code);
    if (use.toolCallId) existing.callIds.push(use.toolCallId);
  } else {
    group.tools.push({
      name: use.name,
      count: 1,
      failed: use.success ? 0 : 1,
      uses: detail.code ? [detail.code] : [],
      callIds: use.toolCallId ? [use.toolCallId] : [],
    });
  }
}

/**
 * Derive the side-panel activity summary from the parsed timeline messages.
 * Tools group by the service that ran them: each MCP server (with its logo)
 * gets its own group; built-in/shell tools collapse into a single "Sandbox"
 * group (shown by total runtime). Files touched are surfaced separately.
 */
export function buildActivitySummary(
  messages: MessageComponentType[],
  eventCount: number,
  rawEvents: RawEvent[] = []
): TaskActivitySummary {
  const uses = collectToolUses(messages);
  const serverMap = buildServerMap(rawEvents);

  const learnedSkills = new Map<string, string | undefined>();
  const delegatedAgents = new Set<string>();
  const files = new Set<string>();
  const groups = new Map<string, ServiceGroup>();
  let toolsCalled = 0;
  let toolsFailed = 0;

  const groupFor = (key: string, init: () => ServiceGroup): ServiceGroup => {
    let g = groups.get(key);
    if (!g) {
      g = init();
      groups.set(key, g);
    }
    return g;
  };

  for (const use of uses) {
    if (!use.name) continue;

    if (use.name === SKILL_TOOL) {
      const skillName = skillNameFromArgs(use.args);
      if (!learnedSkills.has(skillName)) learnedSkills.set(skillName, use.toolCallId);
      continue;
    }

    const target = delegationTarget(use.name, use.args);
    if (target) {
      delegatedAgents.add(target);
      continue;
    }

    if (HIDDEN_TOOLS.has(use.name)) continue;

    toolsCalled += 1;
    if (!use.success) toolsFailed += 1;

    // Files the agent touched — from arguments, command strings and results.
    if (use.args) extractFilesFromText(JSON.stringify(use.args), files);
    if (typeof use.result === "string") extractFilesFromText(use.result, files);

    const server = use.toolCallId ? serverMap.get(use.toolCallId) : undefined;
    const group = server
      ? groupFor(`mcp:${server.name}`, () => ({
          key: `mcp:${server.name}`,
          name: server.name,
          icon: server.icon,
          isMcp: true,
          count: 0,
          durationSec: 0,
          tools: [],
        }))
      : groupFor(SANDBOX_KEY, () => ({
          key: SANDBOX_KEY,
          name: "Sandbox",
          isMcp: false,
          count: 0,
          durationSec: 0,
          tools: [],
        }));

    addToolToGroup(group, use);
  }

  const services = [...groups.values()].sort((a, b) => {
    if (a.isMcp !== b.isMcp) return a.isMcp ? -1 : 1;
    return b.count - a.count;
  });

  let totalTokens = 0;
  let totalCost = 0;
  for (const m of messages) {
    if (m.type === "llm_response" && m.data.usage) {
      totalTokens += m.data.usage.usage?.total_tokens || 0;
      totalCost += Number(m.data.usage.cost) || 0;
    }
  }

  return {
    events: eventCount,
    llmCalls: messages.filter((m) => m.type === "llm_response").length,
    totalTokens,
    totalCost,
    toolsCalled,
    toolsFailed,
    uniqueTools: services.flatMap((s) => s.tools.map((t) => t.name)),
    services,
    files: [...files].slice(0, 12),
    learnedSkills: [...learnedSkills].map(([name, callId]) => ({ name, callId })),
    delegatedAgents: [...delegatedAgents],
  };
}
