import "server-only";
import { listClients, listModelInstances } from "@/lib/api";
import type { RunOptions } from "@/lib/run-targets";
import { RUNNER_KINDS } from "@/lib/runner-kinds";

/**
 * The workspace's chat models and runner clients a run can be sent to. Null
 * when they cannot be read: the composer then offers no choice and a run goes
 * where its agent runs.
 */
export async function loadRunOptions(): Promise<RunOptions | null> {
  const [instances, clients] = await Promise.all([
    listModelInstances({ is_active: true, kind: "chat" }),
    listClients(),
  ]);
  if (!instances.data || !clients.data) {
    console.error(
      "Run options could not be loaded",
      instances.error ?? clients.error
    );
    return null;
  }
  return {
    models: instances.data.map((instance) => ({
      id: instance.id,
      name:
        instance.model_display_name || instance.config_name || instance.name,
      provider: instance.provider_name || null,
      iconUrl: instance.provider_icon_url || null,
    })),
    runners: clients.data.filter((client) =>
      RUNNER_KINDS.includes(client.kind)
    ),
  };
}
