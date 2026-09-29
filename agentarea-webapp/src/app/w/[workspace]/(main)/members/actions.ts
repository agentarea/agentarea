"use server";

import { revalidatePath } from "next/cache";
import { getTranslations } from "next-intl/server";
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
    const t = await getTranslations("MembersPage");
    return { error: apiErrorMessage(result, t("createInvitationFailed")) };
  }
  return { data: result.data };
}

export async function revokeInvitationAction(invitationId: string) {
  const result = await revokeWorkspaceInvitation(invitationId);
  if (result.error) {
    const t = await getTranslations("MembersPage");
    return { error: apiErrorMessage(result, t("revokeFailed")) };
  }
  return { ok: true };
}

export async function removeMemberAction(userId: string) {
  const { userId: callerId } = await getAuthContext();

  const isSelf = Boolean(callerId) && userId === callerId;

  const result = await removeWorkspaceMember(userId);
  if (result.error) {
    const t = await getTranslations("MembersPage");
    return {
      error: apiErrorMessage(
        result,
        isSelf ? t("leaveFailed") : t("removeFailed")
      ),
    };
  }

  // The switcher in the root layout still lists the workspace just left.
  if (isSelf) {
    revalidatePath("/", "layout");
  }

  // 202: the membership has ended but its access is still being revoked.
  return { ok: true, pending: result.status === 202 };
}
