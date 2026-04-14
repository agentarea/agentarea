import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTrigger, listAgents, listTriggerCatalog } from "@/lib/api";
import TriggerDetail from "./TriggerDetail";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const { data: trigger } = await getTrigger(id);
  return { title: (trigger as any)?.name ?? "Trigger" };
}

export default async function TriggerPage({ params }: Props) {
  const { id } = await params;

  const [triggerResponse, agentsResponse, catalogResponse] = await Promise.all([
    getTrigger(id),
    listAgents(),
    listTriggerCatalog(),
  ]);

  const trigger = triggerResponse.data;
  if (!trigger) notFound();

  const agents = (agentsResponse.data as any[]) || [];
  const agentName =
    agents.find((a: any) => a.id === (trigger as any).agent_id)?.name ||
    "Unknown Agent";

  const catalog = (catalogResponse.data as any[]) || [];

  // Match catalog entry: check data_extractor first, then cron/webhook type
  const triggerType = (trigger as any).trigger_type;
  const webhookType = (trigger as any).webhook_type;
  const dataExtractor = (trigger as any).data_extractor;
  const catalogEntry = catalog.find((c: any) => {
    if (dataExtractor) return c.data_extractor === dataExtractor;
    if (triggerType === "cron") return c.id === "cron";
    return c.webhook_type === webhookType;
  }) ?? null;

  return (
    <TriggerDetail
      trigger={trigger as any}
      agentName={agentName}
      catalogEntry={catalogEntry}
    />
  );
}
