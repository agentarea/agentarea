"use server";

import type { ScheduleTaskCreate, TaskCreate } from "@/api/client/types.gen";
import { createAgentTask, listAgents, scheduleAgentTask } from "@/lib/api";

export async function getAgents() {
  return await listAgents();
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
