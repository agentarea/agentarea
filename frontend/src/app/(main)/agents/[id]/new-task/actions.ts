"use server";

import { createAgentTask } from "@/lib/api";
import type { components } from "@/api/schema";

export async function createTask(
  agentId: string,
  task: components["schemas"]["TaskCreate"]
) {
  return await createAgentTask(agentId, task);
}
