"use server";

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
  const { workspaceId } = await getAuthContext();
  if (!workspaceId) return { error: "No workspace context" };

  const result = await removeWorkspaceMember(workspaceId, userId);
  if (result.error) {
    return { error: apiErrorMessage(result, "Failed to remove member") };
  }
  return { ok: true };
}
