"use server";

import { getAgentTaskEvents } from "@/lib/api";

export async function getTaskEvents(
  agentId: string,
  taskId: string,
  options: {
    page?: number;
    page_size?: number;
    event_type?: string;
  } = {}
) {
  return await getAgentTaskEvents(agentId, taskId, options);
}
