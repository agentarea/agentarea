"use server";

import type { components } from "@/api/schema";
import { createAgentTask } from "@/lib/api";

export async function createTask(
  agentId: string,
  task: components["schemas"]["TaskCreate"]
) {
  return await createAgentTask(agentId, task);
}
