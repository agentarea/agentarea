import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { listAgents, listModelInstances } from "@/lib/api";
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

  const [{ data: agents = [] }, { data: modelInstances = [] }] =
    await Promise.all([listAgents(), listModelInstances()]);

  const enrichedAgents = (agents as any[]).map((agent) => {
    const model = (modelInstances as any[]).find(
      (m) => m.id === agent.model_id
    );
    const model_info = model
      ? {
          provider_name: model.provider_name || undefined,
          model_display_name: model.model_display_name || undefined,
          config_name: model.config_name || undefined,
        }
      : undefined;
    return { ...agent, model_info };
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
