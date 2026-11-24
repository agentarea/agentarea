import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listWorkspaceInvitations, type WorkspaceInvitation } from "@/lib/api";
import { formatApiError } from "@/lib/api-errors";
import { getViewerCapabilities } from "@/lib/workspace-context";
import MembersClient from "./MembersClient";
import MembersLoadError from "./MembersLoadError";
import { loadWorkspaceMembers } from "./workspaceMembers";

// The data-fetching half of the members page, isolated so the page can wrap it
// in <Suspense> and show MembersSkeleton while it loads.
export default async function MembersData() {
  const [{ canAdminister }, t] = await Promise.all([
    getViewerCapabilities(),
    getTranslations("MembersPage"),
  ]);

  // Pending invitations are admin-only, so a member's page never asks for them.
  const [loaded, invitationsRes] = await Promise.all([
    loadWorkspaceMembers(),
    canAdminister ? listWorkspaceInvitations() : null,
  ]);

  const loadError = (message: string) => (
    <ContentBlock header={{ breadcrumb: [{ label: t("title") }] }}>
      <MembersLoadError message={message} />
    </ContentBlock>
  );

  if (!loaded.ok) {
    return loadError(
      loaded.reason === "noWorkspace" ? t("noWorkspaceContext") : loaded.message
    );
  }
  if (invitationsRes?.error) {
    return loadError(formatApiError(invitationsRes.error));
  }
  const invitations: WorkspaceInvitation[] = invitationsRes?.data ?? [];

  return (
    <MembersClient
      members={loaded.members}
      invitations={invitations}
      currentUser={loaded.currentUser}
      ownerUserId={loaded.ownerUserId}
      workspaceName={loaded.workspaceName ?? t("thisWorkspace")}
    />
  );
}
