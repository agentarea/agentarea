import { getTranslations } from "next-intl/server";
import CatalogSuggestions from "@/components/CatalogSuggestions";
import EmptyState from "@/components/EmptyState";
import {
  listAgents,
  listModelInstances,
  listMCPServerInstances,
  listMCPServers,
  getAllTasks,
} from "@/lib/api";
import { McpInstance, McpServer } from "@/lib/mcp/resolveMcpRef";
import type { Agent } from "@/types";
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
  const taskList = (tasks ?? []) as Array<{ status?: string; agent_id?: string }>;
  const activeTaskCountByAgent: Record<string, number> = {};
  for (const task of taskList) {
    if (task.status === "running" && task.agent_id) {
      const agentId = String(task.agent_id);
      activeTaskCountByAgent[agentId] = (activeTaskCountByAgent[agentId] ?? 0) + 1;
    }
  }

  // Bridge the API response to the domain Agent type once, at the boundary.
  // (The /agents list returns only your own agents — catalog lives in Explore.)
  const agentList = (agents ?? []) as unknown as Agent[];
  const models = (modelInstances ?? []) as Array<{
    id: string;
    provider_name?: string | null;
    provider_icon_url?: string | null;
    model_display_name?: string | null;
    config_name?: string | null;
  }>;

  const enrichedAgents = agentList.map((agent) => {
    const model = models.find((m) => m.id === agent.model_id);
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
      <div className="space-y-4">
        <EmptyState
          title={t("noAgentsTitle")}
          description={t("noAgentsDescription")}
          iconsType="agent"
        />
        <CatalogSuggestions type="agents" />
      </div>
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
    <AgentsList initialAgents={filteredAgents} viewMode={viewMode} />
  );
}
