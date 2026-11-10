"use server";

import type { ScheduleTaskCreate, TaskCreate } from "@/api/client/types.gen";
import {
  createAgentTask,
  getHarnessAgent,
  listAgents,
  scheduleAgentTask,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { loadRunOptions } from "@/lib/run-options";

export async function getAgents() {
  return await listAgents();
}

/** The models and runners a run can be sent to, for a composer that loads on demand. */
export async function getRunOptions() {
  return await loadRunOptions();
}

/** The agent to give a task to when it goes to this harness itself, with no agent configured. */
export async function getHarnessAgentAction(clientId: string) {
  const result = await getHarnessAgent(clientId);
  if (!result.data) {
    return {
      ok: false as const,
      error: apiErrorMessage(result, "The harness could not be reached"),
    };
  }
  const agent = result.data;
  return {
    ok: true as const,
    agent: {
      id: String(agent.id),
      name: agent.name,
      description: agent.description ?? null,
      modelId: null,
      client: agent.client ?? null,
      harnessClientId: clientId,
    },
  };
}

export async function createTask(agentId: string, task: TaskCreate) {
  return await createAgentTask(agentId, task);
}

export async function scheduleTask(agentId: string, task: ScheduleTaskCreate) {
  return await scheduleAgentTask(agentId, task);
}
