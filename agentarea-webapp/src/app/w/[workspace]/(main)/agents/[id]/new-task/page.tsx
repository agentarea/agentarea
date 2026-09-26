import { Suspense } from "react";
import type { Metadata } from "next";
import { FormSkeleton } from "@/components/Skeleton";
import { getAgent, listModelInstances } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import type { Agent } from "@/types";
import AgentNewTask from "./components/AgentNewTask";

export const metadata: Metadata = {
  title: "New Task",
};

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentNewTaskPage({ params }: Props) {
  const { id } = await params;
  const [agentResponse, modelInstancesResponse] = await Promise.all([
    getAgent(id),
    listModelInstances(),
  ]);

  const agent = requireApiData(agentResponse, "agent");
  const modelInstances = modelInstancesResponse.data || [];
  const model = modelInstances.find((m) => m.id === agent.model_id);
  const model_info = model
    ? {
        provider_name: model.provider_name || undefined,
        provider_icon_url: model.provider_icon_url || undefined,
        model_display_name: model.model_display_name || undefined,
        config_name: model.config_name || undefined,
      }
    : undefined;

  return (
    <Suspense fallback={<FormSkeleton className="p-4" />}>
      <AgentNewTask agent={{ ...agent, model_info } as Agent} />
    </Suspense>
  );
}
