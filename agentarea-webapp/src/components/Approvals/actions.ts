"use server";

import { client as serverClient } from "@/api/client/client.gen";
import { getInboxItemsV1InboxGet } from "@/api/client/sdk.gen";
import { resolvePrincipals } from "@/lib/api";

/** How many tasks are waiting on an approval decision in this workspace. */
export async function getPendingApprovalCountAction() {
  const result = await getInboxItemsV1InboxGet({
    client: serverClient,
    query: { status: "waiting_for_approval", page_size: 1 },
  });
  return { data: result.data?.total ?? null, error: result.error };
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
