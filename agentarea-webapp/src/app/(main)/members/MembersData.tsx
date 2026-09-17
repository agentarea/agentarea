import { getTranslations } from "next-intl/server";
import {
  listWorkspaceInvitations,
  listWorkspaceMembers,
  type WorkspaceInvitation,
  type WorkspaceMember,
} from "@/lib/api";
import { formatApiError } from "@/lib/api-errors";
import { getAuthContext } from "@/lib/getAuthContext";
import MembersClient from "./MembersClient";
import MembersLoadError from "./MembersLoadError";

// The data-fetching half of the members page, isolated so the page can wrap it
// in <Suspense> and show MembersSkeleton while it loads.
export default async function MembersData() {
  const t = await getTranslations("MembersPage");
  const { workspaceId, userId } = await getAuthContext();

  if (!workspaceId) {
    return <MembersLoadError message={t("noWorkspaceContext")} />;
  }

  const [membersRes, invitationsRes] = await Promise.all([
    listWorkspaceMembers(workspaceId),
    listWorkspaceInvitations(workspaceId),
  ]);

  // A failed call is not an empty workspace. Reporting "no members" when the
  // membership graph is down hides an outage behind a plausible screen.
  const failure = membersRes.error ?? invitationsRes.error;
  if (failure) {
    return <MembersLoadError message={formatApiError(failure)} />;
  }

  const members: WorkspaceMember[] = membersRes.data ?? [];
  const invitations: WorkspaceInvitation[] = invitationsRes.data ?? [];

  return (
    <MembersClient
      members={members}
      invitations={invitations}
      currentUserId={userId}
    />
  );
}
