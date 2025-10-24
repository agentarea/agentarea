"use server";

import type { components } from "@/api/schema";
import { createAgentTask, listAgents } from "@/lib/api";

export async function getAgents() {
  return await listAgents();
}

export async function createTask(
  agentId: string,
  task: components["schemas"]["TaskCreate"]
) {
  return await createAgentTask(agentId, task);
}
