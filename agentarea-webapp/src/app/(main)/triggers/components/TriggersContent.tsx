import { getTranslations } from "next-intl/server";
import { listTriggers, listAgents, listTriggerCatalog } from "@/lib/api";
import TriggersList from "./TriggersList";

interface TriggersContentProps {
  viewMode: "grid" | "table";
  searchQuery: string;
}

export default async function TriggersContent({
  viewMode,
  searchQuery,
}: TriggersContentProps) {
  const t = await getTranslations("TriggersPage");

  const [triggersResponse, agentsResponse, catalogResponse] = await Promise.all([
    listTriggers(),
    listAgents(),
    listTriggerCatalog(),
  ]);

  if (triggersResponse.error) {
    return (
      <div className="flex h-64 items-center justify-center text-destructive">
        {t("error.loadFailed")}
      </div>
    );
  }

  const triggers = (triggersResponse.data as any[]) || [];
  const agents = (agentsResponse.data as any[]) || [];
  const catalog = (catalogResponse.data as any[]) || [];

  // Build agent name lookup
  const agentMap = new Map(agents.map((a: any) => [a.id, a.name]));

  // Enrich triggers with agent names
  const enrichedTriggers = triggers.map((trigger: any) => ({
    ...trigger,
    agent_name: agentMap.get(trigger.agent_id) || "Unknown Agent",
  }));

  // Filter triggers based on search query
  const filteredTriggers = searchQuery.trim()
    ? enrichedTriggers.filter(
        (trigger) =>
          trigger.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          (trigger.agent_name && trigger.agent_name.toLowerCase().includes(searchQuery.toLowerCase()))
      )
    : enrichedTriggers;

  return (
    <TriggersList
      triggers={filteredTriggers}
      catalog={catalog}
      viewMode={viewMode}
      searchQuery={searchQuery}
    />
  );
}
