"use server";

import type { A2UiActionPayload } from "@/api/client/types.gen";
import { zSendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPostBody } from "@/api/client/zod.gen";
import { sendA2UIAction } from "@/lib/api";

function errorMessage(error: unknown, fallback: string): string {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export async function sendA2UIActionAction(
  agentId: string,
  taskId: string,
  input: A2UiActionPayload
): Promise<void> {
  const body =
    zSendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPostBody.parse(input);
  const { error } = await sendA2UIAction(agentId, taskId, body);
  if (error) {
    throw new Error(errorMessage(error, "A2UI action failed"));
  }
}
