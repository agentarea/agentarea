import { Suspense } from "react";
import { notFound } from "next/navigation";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { getAgent, listModelInstances } from "@/lib/api";
import AgentNewTask from "./components/AgentNewTask";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentNewTaskPage({ params }: Props) {
  const { id } = await params;
  const [agentResponse, modelInstancesResponse] = await Promise.all([
    getAgent(id),
    listModelInstances(),
  ]);
  if (!agentResponse.data) {
    notFound();
  }

  const agent = agentResponse.data;
  const modelInstances = modelInstancesResponse.data || [];
  const model = modelInstances.find((m: any) => m.id === agent.model_id);
  const model_info = model
    ? {
        provider_name: model.provider_name || undefined,
        model_display_name: model.model_display_name || undefined,
        config_name: model.config_name || undefined,
      }
    : undefined;

  return (
    <Suspense
      fallback={
        <div className="flex h-32 items-center justify-center">
          <LoadingSpinner />
        </div>
      }
    >
      <AgentNewTask agent={{ ...agent, model_info } as any} />
    </Suspense>
  );
}
