"use server";

import type { AgentUpdate } from "@/api/client/types.gen";
import { updateAgent as updateAgentAPI } from "@/lib/api";

export async function updateAgentSettings(
  agentId: string,
  agent: AgentUpdate
) {
  return await updateAgentAPI(agentId, agent);
}
