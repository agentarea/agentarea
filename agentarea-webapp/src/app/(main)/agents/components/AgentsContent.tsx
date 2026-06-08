import { getAllTasks, listAgents, listModelInstances } from "@/lib/api";
import AgentsView, {
  type AgentsInitialState,
  type EnrichedAgent,
} from "./AgentsView";

interface AgentsContentProps {
  initial: AgentsInitialState;
}

export default async function AgentsContent({ initial }: AgentsContentProps) {
  const [
    { data: agents = [] },
    { data: modelInstances = [] },
    { data: tasks = [] },
  ] = await Promise.all([listAgents(), listModelInstances(), getAllTasks()]);

  // Count active (running) tasks per agent
  const activeTaskCountByAgent: Record<string, number> = {};
  for (const task of tasks as any[]) {
    if (task.status === "running") {
      const agentId = String(task.agent_id);
      activeTaskCountByAgent[agentId] =
        (activeTaskCountByAgent[agentId] ?? 0) + 1;
    }
  }

  const enrichedAgents: EnrichedAgent[] = (agents as any[]).map((agent) => {
    const model = (modelInstances as any[]).find((m) => m.id === agent.model_id);
    const model_info = model
      ? {
          provider_name: model.provider_name || undefined,
          provider_icon_url: model.provider_icon_url || undefined,
          model_display_name: model.model_display_name || undefined,
          config_name: model.config_name || undefined,
        }
      : undefined;
    return {
      ...agent,
      model_info,
      active_task_count: activeTaskCountByAgent[String(agent.id)] ?? 0,
    };
  });

  return <AgentsView agents={enrichedAgents} initial={initial} />;
}
