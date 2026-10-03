"use server";

import { client as serverClient } from "@/api/client/client.gen";
import {
  getTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGet,
  getTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGet,
} from "@/api/client/sdk.gen";

export async function getTaskPolicySnapshotAction(taskId: string) {
  const result =
    await getTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGet({
      client: serverClient,
      path: { task_id: taskId },
    });
  return {
    data: result.data,
    error: result.error,
    status: result.response?.status,
  };
}

export async function getTaskSummaryAction(agentId: string, taskId: string) {
  const result = await getTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGet({
    client: serverClient,
    path: { agent_id: agentId, task_id: taskId },
  });
  return {
    data: result.data,
    error: result.error,
    status: result.response?.status,
  };
}
