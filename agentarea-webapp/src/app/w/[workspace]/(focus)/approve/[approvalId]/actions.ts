"use server";

import { decideToolCallApproval } from "@/lib/api";

/** Record the person's decision on a held tool call; the page refreshes after. */
export async function decideToolCallApprovalAction(
  approvalId: string,
  approved: boolean,
  comment: string
) {
  return await decideToolCallApproval(approvalId, {
    approved,
    comment: comment || null,
  });
}
