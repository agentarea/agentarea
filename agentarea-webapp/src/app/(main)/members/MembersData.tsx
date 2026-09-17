import { getTranslations } from "next-intl/server";
import {
  listWorkspaceInvitations,
  listWorkspaceMembers,
  type WorkspaceInvitation,
  type WorkspaceMember,
} from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";
import { resolveIdentityProfiles } from "@/lib/identities";
import { getWorkspaceContext } from "@/lib/workspace-context";
import MembersClient from "./MembersClient";

function ensureCurrentUserMember(
  members: WorkspaceMember[],
  currentUser: {
    workspaceId: string | null;
    userId: string | null;
    email: string | null;
    name: string | null;
    username: string | null;
  }
): WorkspaceMember[] {
  if (!currentUser.workspaceId || !currentUser.userId) return members;
  if (members.some((member) => member.user_id === currentUser.userId)) {
    return members;
  }

  return [
    {
      id: currentUser.userId,
      workspace_id: currentUser.workspaceId,
      user_id: currentUser.userId,
      email: currentUser.email,
      display_name:
        currentUser.name || currentUser.email || currentUser.username || null,
      joined_at: new Date().toISOString(),
      invitation_id: null,
    },
    ...members,
  ];
}

// The data-fetching half of the members page, isolated so the page can wrap it
// in <Suspense> and show MembersSkeleton while it loads.
export default async function MembersData() {
  const [{ workspaceId, userId, email, name, username }, { active }, t] =
    await Promise.all([
      getAuthContext(),
      getWorkspaceContext(),
      getTranslations("MembersPage"),
    ]);

  let members: WorkspaceMember[] = [];
  let invitations: WorkspaceInvitation[] = [];

  if (workspaceId) {
    const [membersRes, invitationsRes] = await Promise.all([
      listWorkspaceMembers(workspaceId),
      listWorkspaceInvitations(workspaceId),
    ]);
    members = membersRes.data ?? [];
    invitations = invitationsRes.data ?? [];
  }

  members = ensureCurrentUserMember(members, {
    workspaceId,
    userId,
    email,
    name,
    username,
  });

  // The API knows profile details for the caller only; look the rest up in
  // the identity provider so members show as people, not ids.
  const profiles = await resolveIdentityProfiles(members.map((m) => m.user_id));
  members = members.map((m) => {
    const profile = profiles.get(m.user_id);
    if (!profile) return m;
    return {
      ...m,
      email: m.email ?? profile.email,
      display_name: m.display_name ?? profile.name ?? profile.email,
    };
  });

  // A personal workspace is owned by the user whose id it carries, so the
  // owner is known even when the API predates `owner_user_id` in its
  // workspace response and leaves the field out.
  const ownerUserId =
    active?.owner_user_id ??
    (active && userId && active.id === userId ? userId : null);

  return (
    <MembersClient
      members={members}
      invitations={invitations}
      currentUser={{ id: userId, email, name, username }}
      ownerUserId={ownerUserId}
      workspaceName={active?.name ?? t("thisWorkspace")}
    />
  );
}
