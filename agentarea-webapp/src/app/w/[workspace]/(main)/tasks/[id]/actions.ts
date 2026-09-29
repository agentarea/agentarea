"use server";

import { client as serverClient } from "@/api/client/client.gen";
import { getTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGet } from "@/api/client/sdk.gen";

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
