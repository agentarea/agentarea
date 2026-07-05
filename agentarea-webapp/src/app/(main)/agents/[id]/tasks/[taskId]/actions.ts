"use server";

import {
  cancelAgentTask,
  getAgentTaskMessages,
  getAgentTaskStatus,
  listModelInstances,
  pauseAgentTask,
  resumeAgentTask,
  resolveEscalation as resolveEscalationApi,
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
  return await resolveEscalationApi(agentId, taskId, escalationId, approved, comment);
}
