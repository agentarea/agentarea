import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTrigger, listAgents } from "@/lib/api";
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

  const [triggerResponse, agentsResponse] = await Promise.all([
    getTrigger(id),
    listAgents(),
  ]);

  const trigger = triggerResponse.data;
  if (!trigger) notFound();

  const agents = (agentsResponse.data as any[]) || [];
  const agentName =
    agents.find((a: any) => a.id === (trigger as any).agent_id)?.name ||
    "Unknown Agent";

  return (
    <TriggerDetail trigger={trigger as any} agentName={agentName} />
  );
}
