"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import ContentBlock from "@/components/ContentBlock";
import type { WorkspaceInvitation } from "@/lib/api";
import { InvitationsTable } from "./components/InvitationsTable";
import { InviteButton, InviteDialog } from "./components/InviteDialog";
import {
  getMemberAccess,
  getMemberLabel,
  getMemberSecondaryLabel,
  isMembersTab,
  sortInvitations,
  sortMembers,
  type CurrentUser,
  type DisplayMember,
  type InvitationsOrder,
  type MembersOrder,
  type MembersTab,
} from "./components/membersShared";
import { MembersTable } from "./components/MembersTable";
import { MembersToolbar } from "./components/MembersToolbar";

interface MembersClientProps {
  members: DisplayMember[];
  invitations: WorkspaceInvitation[];
  currentUser: CurrentUser;
  ownerUserId: string | null;
  workspaceName: string;
}

function SectionHead({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="space-y-0.5">
      <h2 className="text-sm font-medium">{title}</h2>
      <p className="text-xs text-muted-foreground">{description}</p>
    </div>
  );
}

export default function MembersClient({
  members,
  invitations,
  currentUser,
  ownerUserId,
  workspaceName,
}: MembersClientProps) {
  const t = useTranslations("MembersPage");
  const searchParams = useSearchParams();

  // The tab lives in client state so switching is instant; the URL is kept in
  // sync for deep links without a server round-trip (which re-fetched members
  // and identity profiles on every click).
  const tabParam = searchParams.get("tab");
  const [tab, setTabState] = useState<MembersTab>(
    isMembersTab(tabParam) ? tabParam : "members"
  );
  const setTab = useCallback((next: MembersTab) => {
    setTabState(next);
    const url = new URL(window.location.href);
    if (next === "members") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    window.history.replaceState(window.history.state, "", url);
  }, []);

  const [query, setQuery] = useState("");
  const [order, setOrder] = useState<MembersOrder>("access");
  const [invitationsOrder, setInvitationsOrder] =
    useState<InvitationsOrder>("expires");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteSession, setInviteSession] = useState(0);
  const openInvite = useCallback(() => {
    setInviteSession((session) => session + 1);
    setInviteOpen(true);
  }, []);

  const q = query.trim().toLowerCase();
  const accessLabels = useMemo(
    () => ({
      owner: t("accessOwner").toLowerCase(),
      member: t("accessMember").toLowerCase(),
    }),
    [t]
  );

  const visibleMembers = useMemo(() => {
    const filtered = q
      ? members.filter((m) =>
          [
            m.user_id,
            getMemberLabel(m, currentUser),
            getMemberSecondaryLabel(m, currentUser),
            accessLabels[getMemberAccess(m, ownerUserId)],
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(q)
        )
      : members;
    return sortMembers(filtered, order, ownerUserId);
  }, [members, q, currentUser, accessLabels, ownerUserId, order]);

  const visibleInvitations = useMemo(() => {
    const anyone = t("anyoneWithLink");
    const filtered = q
      ? invitations.filter((inv) =>
          (inv.email || anyone).toLowerCase().includes(q)
        )
      : invitations;
    return sortInvitations(filtered, invitationsOrder, anyone);
  }, [invitations, q, t, invitationsOrder]);

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("descriptionForWorkspace", { workspace: workspaceName }),
        controls: <InviteButton onClick={openInvite} />,
      }}
      subheader={
        <MembersToolbar
          tab={tab}
          onTabChange={setTab}
          counts={{ members: members.length, invitations: invitations.length }}
          onQueryChange={setQuery}
          order={order}
          onOrderChange={setOrder}
          invitationsOrder={invitationsOrder}
          onInvitationsOrderChange={setInvitationsOrder}
        />
      }
    >
      {tab === "members" ? (
        <section className="space-y-3">
          <SectionHead
            title={t("peopleTitle")}
            description={t("peopleDescription")}
          />
          <MembersTable
            members={visibleMembers}
            currentUser={currentUser}
            ownerUserId={ownerUserId}
            workspaceName={workspaceName}
            query={q}
            onInvite={openInvite}
          />
        </section>
      ) : (
        <section className="space-y-3">
          <SectionHead
            title={t("invitationsTitle")}
            description={t("invitationsDescription")}
          />
          <InvitationsTable
            invitations={visibleInvitations}
            query={q}
            onInvite={openInvite}
          />
        </section>
      )}

      <InviteDialog
        key={inviteSession}
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        onCreated={() => setTab("invitations")}
      />
    </ContentBlock>
  );
}
