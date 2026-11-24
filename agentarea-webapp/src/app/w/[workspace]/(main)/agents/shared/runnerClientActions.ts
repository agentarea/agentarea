"use server";

import type { ClientResponse } from "@/api/client/types.gen";
import { listClients, updateClient } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";

/** The workspace's Codex and Claude Code clients, whose runners an agent can run on. */
export async function listRunnerClientsAction(): Promise<
  { ok: true; clients: ClientResponse[] } | { ok: false; error: string }
> {
  const result = await listClients();
  if (!result.data) {
    return {
      ok: false,
      error: apiErrorMessage(result, "Clients could not be loaded"),
    };
  }
  return {
    ok: true,
    clients: result.data.filter((client) => client.has_runner),
  };
}

/** The model every agent on the client runs with unless a task names another. */
export async function setRunnerModelAction(
  clientId: string,
  model: string | null
): Promise<
  { ok: true; client: ClientResponse } | { ok: false; error: string }
> {
  const result = await updateClient(clientId, { default_model: model });
  if (!result.data) {
    return {
      ok: false,
      error: apiErrorMessage(result, "The model could not be saved"),
    };
  }
  return { ok: true, client: result.data };
}
