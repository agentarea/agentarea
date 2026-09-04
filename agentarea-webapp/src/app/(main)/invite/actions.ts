"use server";

import { acceptWorkspaceInvitation } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";

export async function acceptInvitationAction(token: string) {
  if (!token) return { error: "Missing invitation token" };
  const result = await acceptWorkspaceInvitation(token);
  if (result.error) {
    return { error: apiErrorMessage(result, "Failed to accept invitation") };
  }
  return { data: result.data };
}
