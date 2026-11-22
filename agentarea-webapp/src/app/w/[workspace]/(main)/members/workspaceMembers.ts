import "server-only";
import { cache } from "react";
import { listWorkspaceMembers } from "@/lib/api";
import { formatApiError } from "@/lib/api-errors";
import { getAuthContext } from "@/lib/getAuthContext";
import { resolveIdentityProfiles } from "@/lib/identities";
import { getWorkspaceContext } from "@/lib/workspace-context";
import type { CurrentUser, DisplayMember } from "./components/membersShared";

export type WorkspaceMembers =
  | {
      ok: true;
      members: DisplayMember[];
      ownerUserId: string | null;
      currentUser: CurrentUser;
      workspaceName: string | null;
    }
  | { ok: false; reason: "noWorkspace" }
  | { ok: false; reason: "failed"; message: string };

/**
 * The workspace's members as people, not ids, with the owner worked out.
 * Request-memoized: the members list, a member's layout and its tab pages all
 * read it.
 */
export const loadWorkspaceMembers = cache(
  async (): Promise<WorkspaceMembers> => {
    const [{ workspaceId, userId, email, name, username }, { active }] =
      await Promise.all([getAuthContext(), getWorkspaceContext()]);
    if (!workspaceId) return { ok: false, reason: "noWorkspace" };

    const res = await listWorkspaceMembers();
    // A failed call is not an empty workspace. Reporting "no members" when the
    // membership graph is down hides an outage behind a plausible screen.
    if (res.error) {
      return {
        ok: false,
        reason: "failed",
        message: formatApiError(res.error),
      };
    }

    // The API knows profile details for the caller only; look the rest up in
    // the identity provider.
    const raw = res.data ?? [];
    const profiles = await resolveIdentityProfiles(raw.map((m) => m.user_id));
    const members: DisplayMember[] = raw.map((m) => {
      const profile = profiles.get(m.user_id);
      if (!profile) return m;
      return {
        ...m,
        email: m.email ?? profile.email,
        display_name: m.display_name ?? profile.name ?? profile.email,
      };
    });

    // A personal workspace is owned by the user whose id it carries, so the
    // owner is known even when the API leaves `owner_user_id` out.
    const ownerUserId =
      members.find((member) => member.is_owner)?.user_id ??
      active?.owner_user_id ??
      (active && userId && active.id === userId ? userId : null);

    return {
      ok: true,
      members,
      ownerUserId,
      currentUser: { id: userId, email, name, username },
      workspaceName: active?.name ?? null,
    };
  }
);
