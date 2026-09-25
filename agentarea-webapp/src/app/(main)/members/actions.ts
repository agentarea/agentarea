"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import {
  createWorkspaceInvitation,
  removeWorkspaceMember,
  revokeWorkspaceInvitation,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getAuthContext } from "@/lib/getAuthContext";
import { WORKSPACE_SLUG_COOKIE } from "@/lib/workspaces";

export async function createInvitationAction(input: {
  email?: string;
  expiresInDays?: number;
}) {
  const { workspaceId } = await getAuthContext();
  if (!workspaceId) return { error: "No workspace context" };

  const body: { email?: string; expires_in_days?: number } = {};
  if (input.email && input.email.trim()) body.email = input.email.trim();
  if (input.expiresInDays != null) body.expires_in_days = input.expiresInDays;

  const result = await createWorkspaceInvitation(workspaceId, body);
  if (result.error) {
    return { error: apiErrorMessage(result, "Failed to create invitation") };
  }
  return { data: result.data };
}

export async function revokeInvitationAction(invitationId: string) {
  const { workspaceId } = await getAuthContext();
  if (!workspaceId) return { error: "No workspace context" };

  const result = await revokeWorkspaceInvitation(workspaceId, invitationId);
  if (result.error) {
    return { error: apiErrorMessage(result, "Failed to revoke invitation") };
  }
  return { ok: true };
}

export async function removeMemberAction(userId: string) {
  const { workspaceId, userId: callerId } = await getAuthContext();
  if (!workspaceId) return { error: "No workspace context" };

  const result = await removeWorkspaceMember(workspaceId, userId);
  if (result.error) {
    return { error: apiErrorMessage(result, "Failed to remove member") };
  }

  // Leaving invalidates the active-workspace cookie: it is sent with every
  // later request, and the backend now refuses it, which would lock the user
  // out of the whole app rather than just this page.
  if (callerId && userId === callerId) {
    const cookieStore = await cookies();
    cookieStore.delete(WORKSPACE_SLUG_COOKIE);
    revalidatePath("/", "layout");
  }

  // 202: the membership has ended but its access is still being revoked.
  return { ok: true, pending: result.status === 202 };
}
