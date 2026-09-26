"use server";

import { revalidatePath } from "next/cache";
import {
  createWorkspaceInvitation,
  removeWorkspaceMember,
  revokeWorkspaceInvitation,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getAuthContext } from "@/lib/getAuthContext";

export async function createInvitationAction(input: {
  email?: string;
  expiresInDays?: number;
}) {
  const body: { email?: string; expires_in_days?: number } = {};
  if (input.email && input.email.trim()) body.email = input.email.trim();
  if (input.expiresInDays != null) body.expires_in_days = input.expiresInDays;

  const result = await createWorkspaceInvitation(body);
  if (result.error) {
    return { error: apiErrorMessage(result, "Failed to create invitation") };
  }
  return { data: result.data };
}

export async function revokeInvitationAction(invitationId: string) {
  const result = await revokeWorkspaceInvitation(invitationId);
  if (result.error) {
    return { error: apiErrorMessage(result, "Failed to revoke invitation") };
  }
  return { ok: true };
}

export async function removeMemberAction(userId: string) {
  const { userId: callerId } = await getAuthContext();

  const result = await removeWorkspaceMember(userId);
  if (result.error) {
    return { error: apiErrorMessage(result, "Failed to remove member") };
  }

  // The switcher in the root layout still lists the workspace just left.
  if (callerId && userId === callerId) {
    revalidatePath("/", "layout");
  }

  // 202: the membership has ended but its access is still being revoked.
  return { ok: true, pending: result.status === 202 };
}
