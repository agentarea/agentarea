"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const tabParam = searchParams.get("tab");
  const tab: MembersTab = isMembersTab(tabParam) ? tabParam : "members";
  const setTab = useCallback(
    (next: MembersTab) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next === "members") params.delete("tab");
      else params.set("tab", next);
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  const [query, setQuery] = useState("");
  const [order, setOrder] = useState<MembersOrder>("access");
  const [invitationsOrder, setInvitationsOrder] =
    useState<InvitationsOrder>("expires");
  const [inviteOpen, setInviteOpen] = useState(false);
  const openInvite = useCallback(() => setInviteOpen(true), []);

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
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        onCreated={() => setTab("invitations")}
      />
    </ContentBlock>
  );
}
