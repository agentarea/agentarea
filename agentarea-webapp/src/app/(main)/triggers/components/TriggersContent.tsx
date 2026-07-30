import { getTranslations } from "next-intl/server";
import type { AgentResponse } from "@/api/client/types.gen";
import { listAgents, listTriggerCatalog } from "@/lib/api";
import { getTriggersCached } from "./triggersData";
import type { TriggerCatalogEntry } from "./triggerDisplay";
import TriggersList from "./TriggersList";

interface TriggersContentProps {
  viewMode: "grid" | "table";
  searchQuery: string;
  groupBy: "channel" | "none";
  orderBy: "name" | "created";
}

export default async function TriggersContent({
  viewMode,
  searchQuery,
  groupBy,
  orderBy,
}: TriggersContentProps) {
  const t = await getTranslations("TriggersPage");

  const [triggersResult, agentsResponse, catalogResponse] = await Promise.all([
    getTriggersCached(),
    listAgents(),
    listTriggerCatalog(),
  ]);

  if (triggersResult.error) {
    return (
      <div className="flex h-64 items-center justify-center text-destructive">
        {t("error.loadFailed")}
      </div>
    );
  }

  const triggers = triggersResult.triggers;
  const agents: AgentResponse[] = agentsResponse.data ?? [];
  const catalog = (catalogResponse.data ?? []) as TriggerCatalogEntry[];

  // Build agent name lookup
  const agentMap = new Map(agents.map((a) => [a.id, a.name]));

  // Enrich triggers with agent names
  const enrichedTriggers = triggers.map((trigger) => ({
    ...trigger,
    agent_name: agentMap.get(trigger.agent_id) || "Unknown Agent",
  }));

  // Filter triggers based on search query
  const filteredTriggers = searchQuery.trim()
    ? enrichedTriggers.filter(
        (trigger) =>
          trigger.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          (trigger.agent_name &&
            trigger.agent_name.toLowerCase().includes(searchQuery.toLowerCase()))
      )
    : enrichedTriggers;

  const sortedTriggers = [...filteredTriggers].sort((a, b) => {
    if (orderBy === "created") {
      const left = a.created_at ? new Date(a.created_at).getTime() : 0;
      const right = b.created_at ? new Date(b.created_at).getTime() : 0;
      return right - left;
    }
    return a.name.localeCompare(b.name);
  });

  return (
    <TriggersList
      triggers={sortedTriggers}
      catalog={catalog}
      viewMode={viewMode}
      searchQuery={searchQuery}
      groupBy={groupBy}
    />
  );
}
