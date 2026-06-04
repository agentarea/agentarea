import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import {
  listAgents,
  listModelInstances,
  listMCPServerInstances,
  listMCPServers,
  getAllTasks,
} from "@/lib/api";
import { McpInstance, McpServer } from "@/lib/mcp/resolveMcpRef";
import { resolveAgentToolIcons } from "@/utils/agentToolIcons";
import AgentsList from "./AgentsList";

interface AgentsContentProps {
  searchQuery?: string;
  viewMode?: string;
}

export default async function AgentsContent({
  searchQuery = "",
  viewMode = "grid",
}: AgentsContentProps) {
  const t = await getTranslations("AgentsPage");

  const [
    { data: agents = [] },
    { data: modelInstances = [] },
    { data: mcpInstances = [] },
    { data: mcpServersData },
    { data: tasks = [] },
  ] = await Promise.all([
    listAgents(),
    listModelInstances(),
    listMCPServerInstances(),
    listMCPServers({ page_size: 100 }),
    getAllTasks(),
  ]);

  const mcpServers: McpServer[] = Array.isArray(mcpServersData)
    ? (mcpServersData as McpServer[])
    : ((mcpServersData as { items?: McpServer[] } | null | undefined)?.items ??
      []);
  const mcpInstanceList = (mcpInstances as McpInstance[]) ?? [];

  // Count active (running) tasks per agent
  const activeTaskCountByAgent: Record<string, number> = {};
  for (const task of (tasks as any[])) {
    if (task.status === "running") {
      const agentId = String(task.agent_id);
      activeTaskCountByAgent[agentId] = (activeTaskCountByAgent[agentId] ?? 0) + 1;
    }
  }

  const enrichedAgents = (agents as any[]).map((agent) => {
    const model = (modelInstances as any[]).find(
      (m) => m.id === agent.model_id
    );
    const model_info = model
      ? {
          provider_name: model.provider_name || undefined,
          provider_icon_url: model.provider_icon_url || undefined,
          model_display_name: model.model_display_name || undefined,
          config_name: model.config_name || undefined,
        }
      : undefined;
    const active_task_count = activeTaskCountByAgent[String(agent.id)] ?? 0;
    const tool_icons = resolveAgentToolIcons(agent, mcpInstanceList, mcpServers);
    return { ...agent, model_info, active_task_count, tool_icons };
  });

  // Filter agents based on search query
  let filteredAgents = enrichedAgents;
  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredAgents = enrichedAgents.filter(
      (agent) =>
        agent.name?.toLowerCase().includes(query) ||
        agent.description?.toLowerCase().includes(query) ||
        agent.model_info?.provider_name?.toLowerCase().includes(query) ||
        agent.model_info?.model_display_name?.toLowerCase().includes(query) ||
        agent.model_info?.config_name?.toLowerCase().includes(query)
    );
  }

  // Handle empty states
  if (enrichedAgents.length === 0) {
    return (
      <EmptyState
        title={t("noAgentsTitle")}
        description={t("noAgentsDescription")}
        iconsType="agent"
      />
    );
  }

  if (filteredAgents.length === 0) {
    return (
      <EmptyState
        title={t("noMatchingAgents")}
        description={`${t("noMatchingAgentsDescription")}: "${searchQuery}"`}
        iconsType="agent"
      />
    );
  }

  return (
    <AgentsList initialAgents={filteredAgents as any} viewMode={viewMode} />
  );
}
