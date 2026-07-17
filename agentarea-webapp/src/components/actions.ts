"use server";

import type { TaskCreate } from "@/api/client/types.gen";
import { createAgentTask, listAgents } from "@/lib/api";

export async function getAgents() {
  return await listAgents();
}

export async function createTask(
  agentId: string,
  task: TaskCreate
) {
  return await createAgentTask(agentId, task);
}
