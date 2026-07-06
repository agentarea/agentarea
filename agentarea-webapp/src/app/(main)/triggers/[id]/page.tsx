import type { Metadata } from "next";
import type { AgentResponse, TriggerResponse } from "@/api/client/types.gen";
import { getTrigger, listAgents, listTriggerCatalog } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import TriggerDetail from "./TriggerDetail";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const trigger = requireApiData<TriggerResponse>(await getTrigger(id), "trigger");
  return { title: trigger.name ?? "Trigger" };
}

export default async function TriggerPage({ params }: Props) {
  const { id } = await params;

  const [triggerResponse, agentsResponse, catalogResponse] = await Promise.all([
    getTrigger(id),
    listAgents(),
    listTriggerCatalog(),
  ]);

  const trigger = requireApiData<TriggerResponse>(triggerResponse, "trigger");

  const agents: AgentResponse[] = agentsResponse.data ?? [];
  const agentName =
    agents.find((a) => a.id === trigger.agent_id)?.name || "Unknown Agent";

  const catalog: Array<Record<string, unknown>> = catalogResponse.data ?? [];

  // Match catalog entry: check data_extractor first, then cron/webhook type
  const triggerType = trigger.trigger_type;
  const webhookType = trigger.webhook_type;
  const dataExtractor = trigger.data_extractor;
  const catalogEntry =
    catalog.find((c) => {
      if (dataExtractor) return c.data_extractor === dataExtractor;
      if (triggerType === "cron") return c.id === "cron";
      return c.webhook_type === webhookType;
    }) ?? null;

  return (
    <TriggerDetail
      trigger={trigger}
      agentName={agentName}
      catalogEntry={catalogEntry}
    />
  );
}
