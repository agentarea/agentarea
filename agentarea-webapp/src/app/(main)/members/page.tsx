import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import {
  listWorkspaceInvitations,
  listWorkspaceMembers,
  type WorkspaceInvitation,
  type WorkspaceMember,
} from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";
import MembersClient from "./MembersClient";

export const metadata: Metadata = {
  title: "Members",
};

export default async function MembersPage() {
  const t = await getTranslations("MembersPage");
  const { workspaceId, userId } = await getAuthContext();

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

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
      }}
    >
      <div className="main-content">
        <MembersClient
          members={members}
          invitations={invitations}
          currentUserId={userId}
        />
      </div>
    </ContentBlock>
  );
}
