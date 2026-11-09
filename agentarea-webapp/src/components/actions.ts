"use server";

import type { ScheduleTaskCreate, TaskCreate } from "@/api/client/types.gen";
import { loadAgentRunTargets } from "@/lib/agent-run-targets";
import { createAgentTask, listAgents, scheduleAgentTask } from "@/lib/api";

export async function getAgents() {
  return await listAgents();
}

/** The workspace's agents with where each one's runs may go, for a composer that loads on demand. */
export async function getAgentsWithRunTargets() {
  const result = await listAgents();
  return {
    ...result,
    runTargets: result.data ? await loadAgentRunTargets(result.data) : {},
  };
}

export async function createTask(
  agentId: string,
  task: TaskCreate
) {
  return await createAgentTask(agentId, task);
}

export async function scheduleTask(agentId: string, task: ScheduleTaskCreate) {
  return await scheduleAgentTask(agentId, task);
}
