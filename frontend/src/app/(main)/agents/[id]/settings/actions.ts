"use server";

import { updateAgent as updateAgentAPI } from "@/lib/api";
import type { components } from "@/api/schema";

export async function updateAgentSettings(
  agentId: string,
  agent: components["schemas"]["AgentUpdate"]
) {
  return await updateAgentAPI(agentId, agent);
}
