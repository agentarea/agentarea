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

export default async function MembersPage() {
  const t = await getTranslations("MembersPage");
  const { workspaceId, userId, email, name, username } = await getAuthContext();

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
          currentUserEmail={email}
          currentUserName={name}
          currentUsername={username}
        />
      </div>
    </ContentBlock>
  );
}
