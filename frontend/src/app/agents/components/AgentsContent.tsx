import { listAgents, listModelInstances } from "@/lib/api";
import AgentsList from "./AgentsList";

export default async function AgentsContent() {
  const [{ data: agents = [] }, { data: modelInstances = [] }] = await Promise.all([
    listAgents(),
    listModelInstances(),
  ]);

  const enrichedAgents = (agents as any[]).map((agent) => {
    const model = (modelInstances as any[]).find((m) => m.id === agent.model_id);
    const model_info = model
      ? {
          provider_name: model.provider_name || undefined,
          model_display_name: model.model_display_name || undefined,
          config_name: model.config_name || undefined,
        }
      : undefined;
    return { ...agent, model_info };
  });

  return <AgentsList initialAgents={enrichedAgents as any} />;
}
