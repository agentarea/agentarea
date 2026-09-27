"use server";

import type { A2UiActionPayload } from "@/api/client/types.gen";
import { zSendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPostBody } from "@/api/client/zod.gen";
import { sendA2UIAction } from "@/lib/api";

export async function sendA2UIActionAction(
  agentId: string,
  taskId: string,
  input: A2UiActionPayload
) {
  const body =
    zSendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPostBody.parse(input);
  return await sendA2UIAction(agentId, taskId, body);
}
