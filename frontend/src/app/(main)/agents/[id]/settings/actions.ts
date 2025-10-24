"use server";

import type { components } from "@/api/schema";
import { updateAgent as updateAgentAPI } from "@/lib/api";

export async function updateAgentSettings(
  agentId: string,
  agent: components["schemas"]["AgentUpdate"]
) {
  return await updateAgentAPI(agentId, agent);
}
