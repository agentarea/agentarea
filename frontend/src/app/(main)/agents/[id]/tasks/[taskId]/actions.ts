"use server";

import {
  getAgentTaskStatus,
  pauseAgentTask,
  resumeAgentTask,
  cancelAgentTask,
  getAgentTaskMessages
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
