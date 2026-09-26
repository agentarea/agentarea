import { notFound } from "next/navigation";
import { policyToRule } from "@/app/w/[workspace]/(main)/policies/components/policy-rules";
import { resolveAgentIdentity } from "@/lib/agent-identity";
import {
  getAgent,
  getModelInstance,
  listAgentTasks,
  listMCPServerInstances,
  listMCPServers,
  listOpenAPIConnections,
  listPolicies,
  type TaskResponse,
} from "@/lib/api";
import { getAgentOverview, getWorkspaceSettings } from "@/lib/api-dashboard";
import { McpInstance, McpServer } from "@/lib/mcp/resolveMcpRef";
import { getAgentStatusPresentation } from "@/lib/status";
import type { Agent } from "@/types/agent";
import type { Policy, PolicyEffect } from "@/types/policies";
import {
  type OpenApiConnectionRef,
  resolveAgentToolIcons,
} from "@/utils/agentToolIcons";
import { isAwaitingUserTask, isRunningTask } from "../../shared/taskStatus";
import {
  AgentOverviewView,
  type AgentOverviewModel,
} from "./AgentOverviewView";
import { CatalogAgentPreview } from "./CatalogAgentPreview";

const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);

/**
 * Data container for the agent overview: loads the agent, its tasks, spend,
 * registry-resolved tools and agent-scoped policies, then hands a plain view
 * model to {@link AgentOverviewView}.
 */
export async function AgentOverview({ agentId }: { agentId: string }) {
  const agentRes = await getAgent(agentId);
  const agent = agentRes.data as Agent | undefined;
  if (!agent) notFound();

  // Canonical ref for in-page links: keep URLs on the slug when available,
  // regardless of whether the page was opened by slug or id.
  const agentRef = agent.slug || agentId;

  // A read-only catalog agent has no tenant row, tasks, spend or guardrails.
  // Show a preview + "Add to workspace" CTA instead of the operational dashboard.
  if (agent.is_catalog) {
    return (
      <div className="main-content">
        <CatalogAgentPreview agent={agent} agentRef={agentRef} />
      </div>
    );
  }

  // Use the resolved UUID for endpoints that require it (list_agent_tasks, etc.).
  const realId: string = agent.id;

  const [
    overview,
    tasksRes,
    settings,
    mcpInstancesRes,
    mcpServersRes,
    openApiConnectionsRes,
    policiesRes,
    modelInstanceRes,
  ] = await Promise.all([
    getAgentOverview(realId).catch(() => null),
    listAgentTasks(realId).catch(() => ({ data: null, error: "load failed" })),
    getWorkspaceSettings().catch(() => null),
    listMCPServerInstances().catch(() => ({ data: [] })),
    listMCPServers({ page_size: 100 }).catch(() => ({ data: [] })),
    listOpenAPIConnections().catch(() => ({ data: [] })),
    listPolicies({ subject_type: "agent", subject_id: realId }).catch(() => ({
      data: [],
    })),
    agent.model_id
      ? getModelInstance(agent.model_id).catch(() => ({ data: undefined }))
      : Promise.resolve({ data: undefined }),
  ]);
  const tasks = (tasksRes?.data as TaskResponse[]) || [];

  const completedValues = (overview?.daily_tasks ?? []).map((d) => d.completed);
  const failedValues = (overview?.daily_tasks ?? []).map((d) => d.failed);

  const modelInstance = modelInstanceRes.data;
  const triggers = (overview?.upcoming ?? []).filter(
    (u) => u.kind === "trigger"
  );

  // Work that has not happened yet, soonest first (the API already sorts it).
  // `running_task` is dropped: the Running group lists those from the task
  // query, and one run in two places reads as two runs.
  const upcoming = (overview?.upcoming ?? [])
    .filter((u) => u.kind !== "running_task")
    .slice(0, 6);

  // Resolve the agent's tools into names via the live MCP registry so refs map
  // to real server names (same as the /agents list).
  const mcpServersData = mcpServersRes?.data;
  const mcpServers: McpServer[] = Array.isArray(mcpServersData)
    ? (mcpServersData as McpServer[])
    : ((mcpServersData as { items?: McpServer[] } | null | undefined)?.items ??
      []);
  const mcpInstanceList = (mcpInstancesRes?.data as McpInstance[]) ?? [];
  const toolIcons = resolveAgentToolIcons(agent, {
    mcpInstances: mcpInstanceList,
    mcpServers,
    openApiConnections:
      (openApiConnectionsRes?.data as OpenApiConnectionRef[]) ?? [],
  });

  // Agent-scoped governance rules, summarised by effect.
  const policyRules = ((policiesRes?.data as Policy[]) ?? [])
    .filter((p) => p.enabled !== false)
    .map(policyToRule);
  const effectCounts = policyRules.reduce<
    Partial<Record<PolicyEffect, number>>
  >((acc, rule) => {
    acc[rule.effect] = (acc[rule.effect] ?? 0) + 1;
    return acc;
  }, {});

  const { hue, iconKey } = resolveAgentIdentity(agent);

  const model: AgentOverviewModel = {
    agentRef,
    name: agent.name,
    description: agent.description,
    hue,
    iconKey,
    status: getAgentStatusPresentation(agent.status || "inactive"),
    model: {
      label:
        agent.model_info?.model_display_name ||
        modelInstance?.model_display_name ||
        modelInstance?.name ||
        agent.model_info?.config_name ||
        modelInstance?.config_name ||
        agent.model_id ||
        null,
      provider:
        agent.model_info?.provider_name || modelInstance?.provider_name || null,
      iconUrl:
        agent.model_info?.provider_icon_url ||
        modelInstance?.provider_icon_url ||
        null,
    },
    triggers: {
      count: triggers.length,
      titles: Array.from(new Set(triggers.map((u) => u.title).filter(Boolean))),
    },
    lastActivityAt: overview?.last_activity_at ?? null,
    stats: {
      completed7d: sum(completedValues.slice(-7)),
      failed7d: sum(failedValues.slice(-7)),
      throughput7d: sum(completedValues.slice(-7)) / 7,
      throughputPrev: sum(completedValues.slice(-14, -7)) / 7,
      maxDaily: Math.max(...completedValues, 0),
      costMtd: overview?.cost_mtd_usd ?? 0,
      cap: settings?.monthly_cap_usd ?? null,
      doneToday: overview?.tasks_done_today ?? 0,
      failedToday: overview?.tasks_failed_today ?? 0,
    },
    upcoming: upcoming.map((u) => ({
      // A cron trigger contributes one entry per fire time, so the id has to
      // carry the moment as well as the thing that fires.
      id: `${u.kind}-${u.trigger_id ?? u.task_id ?? "none"}-${u.fires_at}`,
      firesAt: u.fires_at,
      kind: u.kind,
      title: u.title,
      href: u.task_id
        ? `/tasks/${u.task_id}`
        : u.trigger_id
          ? `/triggers/${u.trigger_id}`
          : null,
    })),
    runningTasks: tasks.filter(isRunningTask),
    // Queued work is listed under Upcoming, not here -- "recent" is what has
    // already run, and showing a pending task in both reads as two tasks.
    recentTasks: tasks
      .filter(
        (task) =>
          !isRunningTask(task) &&
          !["pending", "submitted"].includes(String(task.status ?? ""))
      )
      .slice(0, 5),
    pendingApprovals: tasks.filter(isAwaitingUserTask),
    skills: (agent.skills ?? []).map((s) => s.name),
    connections: toolIcons.map((tool) => tool.label),
    policyCount: policyRules.length,
    effectCounts,
  };

  return <AgentOverviewView model={model} />;
}
