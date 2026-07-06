import { getTranslations } from "next-intl/server";
import type { AgentResponse } from "@/api/client/types.gen";
import { listAgents, listTriggerCatalog } from "@/lib/api";
import { getTriggersCached } from "./triggersData";
import type { TriggerCatalogEntry } from "./triggerDisplay";
import TriggersList from "./TriggersList";

interface TriggersContentProps {
  viewMode: "grid" | "table";
  searchQuery: string;
  typeFilter: string;
}

export default async function TriggersContent({
  viewMode,
  searchQuery,
  typeFilter,
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
  let enrichedTriggers = triggers.map((trigger) => ({
    ...trigger,
    agent_name: agentMap.get(trigger.agent_id) || "Unknown Agent",
  }));

  // Filter by trigger type (All / Cron / Webhook)
  if (typeFilter === "cron") {
    enrichedTriggers = enrichedTriggers.filter(
      (trigger) => trigger.trigger_type === "cron"
    );
  } else if (typeFilter === "webhook") {
    enrichedTriggers = enrichedTriggers.filter(
      (trigger) => trigger.trigger_type === "webhook"
    );
  }

  // Filter triggers based on search query
  const filteredTriggers = searchQuery.trim()
    ? enrichedTriggers.filter(
        (trigger) =>
          trigger.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          (trigger.agent_name &&
            trigger.agent_name.toLowerCase().includes(searchQuery.toLowerCase()))
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
