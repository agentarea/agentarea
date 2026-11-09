import "server-only";
import type { AgentResponse } from "@/api/client/types.gen";
import { listClients, listModelInstances } from "@/lib/api";
import { runTargets, type RunTargets } from "@/lib/run-targets";
import { RUNNER_KINDS } from "@/lib/runner-kinds";

/**
 * Where each agent's runs may go, by agent id. Empty when the clients or the
 * models cannot be read: the composer then offers no choice and a run goes
 * where its agent runs.
 */
export async function loadAgentRunTargets(
  agents: Pick<AgentResponse, "id" | "model_id" | "client">[]
): Promise<Record<string, RunTargets>> {
  const [instances, clients] = await Promise.all([
    listModelInstances(),
    listClients(),
  ]);
  if (!instances.data || !clients.data) {
    console.error(
      "Run targets could not be loaded",
      instances.error ?? clients.error
    );
    return {};
  }
  const models = instances.data;
  const runners = clients.data.filter((client) =>
    RUNNER_KINDS.includes(client.kind)
  );
  return Object.fromEntries(
    agents.map((agent) => {
      const instance = models.find((m) => m.id === agent.model_id);
      const model = instance
        ? {
            name:
              instance.model_display_name ||
              instance.config_name ||
              instance.name,
            provider: instance.provider_name || null,
            iconUrl: instance.provider_icon_url || null,
          }
        : null;
      return [
        String(agent.id),
        runTargets({ model, client: agent.client ?? null }, runners),
      ];
    })
  );
}
