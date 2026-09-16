import type { WorkspaceInvitation, WorkspaceMember } from "@/lib/api";

export type DisplayMember = WorkspaceMember & {
  name?: string | null;
  username?: string | null;
};

export type CurrentUser = {
  id: string | null;
  email: string | null;
  name: string | null;
  username: string | null;
};

export type MembersTab = "members" | "invitations";
export type MembersOrder = "access" | "id";
export type InvitationsOrder = "expires" | "recipient";
export type MemberAccess = "owner" | "member";

export const MEMBERS_TABS: MembersTab[] = ["members", "invitations"];

export function isMembersTab(value: unknown): value is MembersTab {
  return (
    typeof value === "string" && MEMBERS_TABS.includes(value as MembersTab)
  );
}

export function getMemberLabel(
  member: DisplayMember,
  currentUser: CurrentUser
): string {
  const isSelf = member.user_id === currentUser.id;
  return (
    member.display_name ||
    member.email ||
    member.name ||
    member.username ||
    (isSelf &&
      (currentUser.name || currentUser.email || currentUser.username)) ||
    member.user_id
  );
}

export function getMemberSecondaryLabel(
  member: DisplayMember,
  currentUser: CurrentUser
): string | null {
  const label = getMemberLabel(member, currentUser);
  const isSelf = member.user_id === currentUser.id;
  if (member.email && member.email !== label) return member.email;
  if (member.username && member.username !== label) return member.username;
  if (isSelf && currentUser.email && currentUser.email !== label) {
    return currentUser.email;
  }
  if (isSelf && currentUser.username && currentUser.username !== label) {
    return currentUser.username;
  }
  return null;
}

/** True when the member is shown by user id only (no profile details known). */
export function isAnonymousMember(
  member: DisplayMember,
  currentUser: CurrentUser
): boolean {
  return getMemberLabel(member, currentUser) === member.user_id;
}

/**
 * Exactly one member owns the workspace (`owner_user_id`); everyone else is a
 * plain member. When the owner is unknown nobody is marked as such.
 */
export function getMemberAccess(
  member: DisplayMember,
  ownerUserId: string | null
): MemberAccess {
  return ownerUserId && member.user_id === ownerUserId ? "owner" : "member";
}

const ACCESS_ORDER: MemberAccess[] = ["owner", "member"];

export function sortMembers(
  members: DisplayMember[],
  order: MembersOrder,
  ownerUserId: string | null
): DisplayMember[] {
  return [...members].sort((a, b) => {
    if (order === "access") {
      const diff =
        ACCESS_ORDER.indexOf(getMemberAccess(a, ownerUserId)) -
        ACCESS_ORDER.indexOf(getMemberAccess(b, ownerUserId));
      if (diff !== 0) return diff;
    }
    return a.user_id.localeCompare(b.user_id);
  });
}

export function shortId(id: string): string {
  return id.length > 13 ? `${id.slice(0, 13)}…` : id;
}

export function formatDate(value: string | null | undefined, locale: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export type InvitationStatusKey = "pending" | "soon" | "today" | "expired";

export function getInvitationStatus(
  invitation: WorkspaceInvitation,
  now: Date
): { key: InvitationStatusKey; days: number } {
  const expires = new Date(invitation.expires_at).getTime();
  if (Number.isNaN(expires)) return { key: "pending", days: 0 };
  const days = Math.ceil((expires - now.getTime()) / 86_400_000);
  if (days < 0) return { key: "expired", days };
  if (days === 0) return { key: "today", days };
  if (days <= 3) return { key: "soon", days };
  return { key: "pending", days };
}

export function sortInvitations(
  invitations: WorkspaceInvitation[],
  order: InvitationsOrder,
  anyoneLabel: string
): WorkspaceInvitation[] {
  return [...invitations].sort((a, b) => {
    if (order === "recipient") {
      return (a.email || anyoneLabel).localeCompare(b.email || anyoneLabel);
    }
    return new Date(a.expires_at).getTime() - new Date(b.expires_at).getTime();
  });
}
