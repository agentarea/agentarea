import {
  listWorkspaceInvitations,
  listWorkspaceMembers,
  type WorkspaceInvitation,
  type WorkspaceMember,
} from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";
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
    <MembersClient
      members={members}
      invitations={invitations}
      currentUserId={userId}
      currentUserEmail={email}
      currentUserName={name}
      currentUsername={username}
    />
  );
}
