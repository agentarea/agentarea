"use server";

import { client as serverClient } from "@/api/client/client.gen";
import { getInboxItemsV1InboxGet } from "@/api/client/sdk.gen";
import { listToolCallApprovals, resolvePrincipals } from "@/lib/api";

/**
 * How many decisions are waiting in this workspace: tasks held on an approval
 * and client tool calls held on an approval link.
 */
export async function getPendingApprovalCountAction() {
  const tasks = await getInboxItemsV1InboxGet({
    client: serverClient,
    query: { status: "waiting_for_approval", page_size: 1 },
  });
  const toolCalls = await listToolCallApprovals({
    status: "pending",
    page_size: 1,
  });
  if (tasks.error || toolCalls.error) {
    return { data: null, error: tasks.error ?? toolCalls.error };
  }
  return {
    data: (tasks.data?.total ?? 0) + (toolCalls.data?.total ?? 0),
    error: undefined,
  };
}

/** Display names for principal ids; ids the backend cannot resolve are absent. */
export async function resolvePrincipalNamesAction(ids: string[]) {
  const result = await resolvePrincipals(ids);
  const names: Record<string, string> = {};
  for (const principal of result.data ?? []) {
    const name = principal.display_name?.trim() || principal.email?.trim();
    if (name) names[principal.id] = name;
  }
  return { data: names, error: result.error };
}
