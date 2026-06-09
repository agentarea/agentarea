import { getTranslations } from "next-intl/server";
import { listTriggers, listAgents, listTriggerCatalog } from "@/lib/api";
import AutomationView, {
  type AutomationInitialState,
} from "./AutomationView";

interface TriggersContentProps {
  initial: AutomationInitialState;
}

export default async function TriggersContent({ initial }: TriggersContentProps) {
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

  // Build agent name lookup and enrich triggers with the agent's name.
  const agentMap = new Map(agents.map((a: any) => [a.id, a.name]));
  const enrichedTriggers = triggers.map((trigger: any) => ({
    ...trigger,
    agent_name: agentMap.get(trigger.agent_id) || "Unknown Agent",
  }));

  return (
    <AutomationView
      triggers={enrichedTriggers}
      catalog={catalog}
      initial={initial}
    />
  );
}
