import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import {
  listWorkspaceInvitations,
  listWorkspaceMembers,
  type WorkspaceInvitation,
  type WorkspaceMember,
} from "@/lib/api";
import { formatApiError } from "@/lib/api-errors";
import { getAuthContext } from "@/lib/getAuthContext";
import { resolveIdentityProfiles } from "@/lib/identities";
import {
  getViewerCapabilities,
  getWorkspaceContext,
} from "@/lib/workspace-context";
import MembersClient from "./MembersClient";
import MembersLoadError from "./MembersLoadError";

// The data-fetching half of the members page, isolated so the page can wrap it
// in <Suspense> and show MembersSkeleton while it loads.
export default async function MembersData() {
  const [
    { workspaceId, userId, email, name, username },
    { active },
    { canAdminister },
    t,
  ] = await Promise.all([
    getAuthContext(),
    getWorkspaceContext(),
    getViewerCapabilities(),
    getTranslations("MembersPage"),
  ]);

  const loadError = (message: string) => (
    <ContentBlock header={{ breadcrumb: [{ label: t("title") }] }}>
      <MembersLoadError message={message} />
    </ContentBlock>
  );

  if (!workspaceId) {
    return loadError(t("noWorkspaceContext"));
  }

  // Pending invitations are admin-only, so a member's page never asks for them.
  const [membersRes, invitationsRes] = await Promise.all([
    listWorkspaceMembers(),
    canAdminister ? listWorkspaceInvitations() : null,
  ]);

  // A failed call is not an empty workspace. Reporting "no members" when the
  // membership graph is down hides an outage behind a plausible screen.
  const failure = membersRes.error ?? invitationsRes?.error;
  if (failure) {
    return loadError(formatApiError(failure));
  }

  let members: WorkspaceMember[] = membersRes.data ?? [];
  const invitations: WorkspaceInvitation[] = invitationsRes?.data ?? [];

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
    members.find((member) => member.is_owner)?.user_id ??
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
