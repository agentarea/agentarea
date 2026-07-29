import type { Part } from "@/lib/events/contract";
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

interface ToolUse {
  name: string;
  success: boolean;
  args?: Record<string, unknown>;
  result?: unknown;
  executionTime?: string;
  toolCallId?: string;
  server?: ServerInfo;
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

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : undefined;
}

/**
 * Read MCP server attribution off a tool part. MCP tool names aren't
 * self-describing, so the server info (name / icon / instance id) rides on the
 * tool.call / tool.result part data.
 */
function serverInfoFromPart(data: Record<string, unknown>): ServerInfo | undefined {
  const name = asString(data.server_name) ?? asString(data.mcp_server_name);
  const icon = asString(data.server_icon) ?? asString(data.mcp_server_icon);
  const id = asString(data.server_instance_id) ?? asString(data.server_id);
  if (!name && !id) return undefined;
  return { name: name ?? "MCP server", icon, id };
}

/**
 * Collect tool invocations from the reduced part list. Supersede-by-id already
 * folded each tool.call/tool.result pair into a single part, so one part == one
 * invocation. tool.result parts carry the outcome; an unresolved tool.call part
 * still counts as a (successful, in-flight) use.
 */
function collectToolUses(parts: Part[]): ToolUse[] {
  const uses: ToolUse[] = [];
  for (const part of parts) {
    if (part.kind !== "tool") continue;
    const data = part.data;
    const name =
      asString(data.tool_name) ?? asString(data.name) ?? "";
    if (!name) continue;
    const isResult = part.eventType === "tool.result";
    const exitCode =
      typeof data.exit_code === "number" ? data.exit_code : null;
    const success = isResult
      ? exitCode != null
        ? exitCode === 0
        : data.success !== false
      : true;
    uses.push({
      name,
      success,
      args: asRecord(data.arguments) ?? asRecord(data.args),
      result: data.result,
      executionTime: asString(data.execution_time),
      toolCallId: asString(data.tool_call_id),
      server: serverInfoFromPart(data),
    });
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
 * Derive the side-panel activity summary from the reduced event parts.
 * Tools group by the service that ran them: each MCP server (with its logo)
 * gets its own group; built-in/shell tools collapse into a single "Sandbox"
 * group (shown by total runtime). Files touched are surfaced separately.
 */
export function buildActivitySummary(
  parts: Part[],
  eventCount: number
): TaskActivitySummary {
  const uses = collectToolUses(parts);

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

    const server = use.server;
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
  let llmCalls = 0;
  for (const part of parts) {
    if (part.kind !== "llm") continue;
    if (part.eventType !== "llm.call.completed") continue;
    llmCalls += 1;
    const usage = asRecord(part.data.usage);
    const inner = asRecord(usage?.usage);
    const totalTokensValue = inner?.total_tokens;
    if (typeof totalTokensValue === "number") totalTokens += totalTokensValue;
    const cost = Number(usage?.cost ?? part.data.cost);
    if (!Number.isNaN(cost)) totalCost += cost;
  }

  return {
    events: eventCount,
    llmCalls,
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
