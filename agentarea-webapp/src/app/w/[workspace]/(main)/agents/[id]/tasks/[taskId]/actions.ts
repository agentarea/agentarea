"use server";

import {
  cancelAgentTask,
  continueAgentTask,
  getAgentTaskMessages,
  getAgentTaskStatus,
  listModelInstances,
  pauseAgentTask,
  resolveEscalation as resolveEscalationApi,
  resumeAgentTask,
  sendTaskCommand,
} from "@/lib/api";

export async function getTaskStatus(agentId: string, taskId: string) {
  return await getAgentTaskStatus(agentId, taskId);
}

export async function getTaskMessages(agentId: string, taskId: string) {
  return await getAgentTaskMessages(agentId, taskId);
}

export async function pauseTask(agentId: string, taskId: string) {
  return await pauseAgentTask(agentId, taskId);
}

export async function resumeTask(agentId: string, taskId: string) {
  return await resumeAgentTask(agentId, taskId);
}

export async function cancelTask(agentId: string, taskId: string) {
  return await cancelAgentTask(agentId, taskId);
}

export async function continueTask(
  taskId: string,
  additionalIterations: number,
  additionalBudgetUsd?: string
) {
  return await continueAgentTask(
    taskId,
    additionalIterations,
    additionalBudgetUsd
  );
}

export async function listTaskModelOptions() {
  return await listModelInstances({ is_active: true });
}

export async function changeTaskModel(
  agentId: string,
  taskId: string,
  modelInstanceId: string
) {
  return await sendTaskCommand(agentId, taskId, {
    command: "change_model",
    model_instance_id: modelInstanceId,
  });
}

export async function resolveEscalation(
  agentId: string,
  taskId: string,
  escalationId: string,
  approved: boolean,
  comment: string = ""
) {
  return await resolveEscalationApi(
    agentId,
    taskId,
    escalationId,
    approved,
    comment
  );
}
