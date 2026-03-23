"use server";

import {
  cancelAgentTask,
  getAgentTaskMessages,
  getAgentTaskStatus,
  pauseAgentTask,
  resumeAgentTask,
  resolveEscalation as resolveEscalationApi,
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

export async function resolveEscalation(
  agentId: string,
  taskId: string,
  escalationId: string,
  approved: boolean,
  comment: string = ""
) {
  return await resolveEscalationApi(agentId, taskId, escalationId, approved, comment);
}
