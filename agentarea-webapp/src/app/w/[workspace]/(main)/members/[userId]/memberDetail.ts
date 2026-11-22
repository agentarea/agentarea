import "server-only";
import { cache } from "react";
import { notFound } from "next/navigation";
import type { TriggerResponse } from "@/api/client/types.gen";
import { listTriggers } from "@/lib/api";
import {
  getMemberLabel,
  isAnonymousMember,
  shortId,
} from "../components/membersShared";
import { loadWorkspaceMembers } from "../workspaceMembers";

function decodeParam(raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

/**
 * The member a `/members/[userId]` route is about, with the workspace facts
 * every tab needs. 404s for anyone who is not (or no longer) a member.
 */
export const getMemberCached = cache(async (rawUserId: string) => {
  const userId = decodeParam(rawUserId);
  const loaded = await loadWorkspaceMembers();
  if (!loaded.ok) {
    throw new Error(
      loaded.reason === "failed" ? loaded.message : "No active workspace"
    );
  }
  const member = loaded.members.find((m) => m.user_id === userId);
  if (!member) notFound();
  const label = isAnonymousMember(member, loaded.currentUser)
    ? shortId(member.user_id)
    : getMemberLabel(member, loaded.currentUser);
  return { ...loaded, member, label };
});

/**
 * Automations this person set up. They run on their creator's authority, so
 * removing the member stops them until someone else takes them over. Null when
 * the list could not be loaded.
 */
export const getMemberTriggersCached = cache(
  async (userId: string): Promise<TriggerResponse[] | null> => {
    const { data, error } = await listTriggers();
    if (error || !data) {
      console.error("Failed to load triggers for a member", error);
      return null;
    }
    return (data as TriggerResponse[]).filter((t) => t.created_by === userId);
  }
);
