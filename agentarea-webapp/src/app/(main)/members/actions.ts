"use server";

import {
  createWorkspaceInvitation,
  removeWorkspaceMember,
  revokeWorkspaceInvitation,
} from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";

function errMsg(error: unknown, fallback: string): string {
  const e = error as { detail?: unknown };
  if (Array.isArray(e?.detail)) {
    return (e.detail[0] as { msg?: string })?.msg || fallback;
  }
  if (typeof e?.detail === "string") return e.detail;
  return fallback;
}

export async function createInvitationAction(input: {
  email?: string;
  expiresInDays?: number;
}) {
  const { workspaceId } = await getAuthContext();
  if (!workspaceId) return { error: "No workspace context" };

  const body: { email?: string; expires_in_days?: number } = {};
  if (input.email && input.email.trim()) body.email = input.email.trim();
  if (input.expiresInDays != null) body.expires_in_days = input.expiresInDays;

  const { data, error } = await createWorkspaceInvitation(workspaceId, body);
  if (error) return { error: errMsg(error, "Failed to create invitation") };
  return { data };
}

export async function revokeInvitationAction(invitationId: string) {
  const { workspaceId } = await getAuthContext();
  if (!workspaceId) return { error: "No workspace context" };

  const { error } = await revokeWorkspaceInvitation(workspaceId, invitationId);
  if (error) return { error: errMsg(error, "Failed to revoke invitation") };
  return { ok: true };
}

export async function removeMemberAction(userId: string) {
  const { workspaceId } = await getAuthContext();
  if (!workspaceId) return { error: "No workspace context" };

  const { error } = await removeWorkspaceMember(workspaceId, userId);
  if (error) return { error: errMsg(error, "Failed to remove member") };
  return { ok: true };
}
