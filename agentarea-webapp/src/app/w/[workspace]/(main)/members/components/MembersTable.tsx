"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Search, User, Users } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import Table, { type Column } from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { Badge } from "@/components/ui/badge";
import { BlueprintBadge } from "@/components/ui/blueprint-badge";
import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";
import { MemberRemoveButton } from "./MemberRemoveButton";
import {
  getMemberAccess,
  getMemberHref,
  getMemberLabel,
  getMemberSecondaryLabel,
  isAnonymousMember,
  shortId,
  type CurrentUser,
  type DisplayMember,
  type MemberAccess,
} from "./membersShared";

interface MembersTableProps {
  members: DisplayMember[];
  currentUser: CurrentUser;
  ownerUserId: string | null;
  workspaceName: string;
  query: string;
  onInvite?: () => void;
}

const ACCESS_BADGE: Record<MemberAccess, "default" | "secondary"> = {
  owner: "default",
  member: "secondary",
};

function MemberCell({
  member,
  currentUser,
}: {
  member: DisplayMember;
  currentUser: CurrentUser;
}) {
  const t = useTranslations("MembersPage");
  const isSelf = member.user_id === currentUser.id;
  const anonymous = isAnonymousMember(member, currentUser);
  const label = getMemberLabel(member, currentUser);
  const secondary = getMemberSecondaryLabel(member, currentUser);

  return (
    <span className="flex min-w-0 items-center gap-2.5">
      {anonymous ? (
        <EntityAvatar
          size={28}
          variant="soft"
          color="#71717a"
          icon={<User strokeWidth={1.8} />}
        />
      ) : (
        <EntityAvatar
          size={28}
          variant="pigment"
          hue={deterministicHue(member.user_id || label)}
          text={nameInitials(label)}
          aria-hidden
        />
      )}
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="flex min-w-0 items-center gap-2">
          <span
            className={
              anonymous
                ? "truncate font-mono text-xs font-medium"
                : "truncate text-[13px] font-medium"
            }
            title={member.user_id}
          >
            {anonymous ? shortId(member.user_id) : label}
          </span>
          {isSelf && <BlueprintBadge>{t("you")}</BlueprintBadge>}
        </span>
        {(secondary || anonymous) && (
          <span className="truncate text-xs text-muted-foreground">
            {secondary ?? t("noProfileDetails")}
          </span>
        )}
      </span>
    </span>
  );
}

export function MembersTable({
  members,
  currentUser,
  ownerUserId,
  workspaceName,
  query,
  onInvite,
}: MembersTableProps) {
  const t = useTranslations("MembersPage");
  const [removalPending, setRemovalPending] = useState<{
    userId: string;
    label: string;
  } | null>(null);
  // The notice covers the gap until the member leaves the list.
  if (
    removalPending &&
    !members.some((member) => member.user_id === removalPending.userId)
  ) {
    setRemovalPending(null);
  }

  if (members.length === 0) {
    return query ? (
      <EmptyState
        icons={[Search]}
        title={t("noMatchTitle", { query })}
        description={t("noMatchDescription")}
      />
    ) : (
      <EmptyState
        icons={[Users]}
        title={t("noMembersTitle")}
        description={t("noMembersDescription")}
        action={
          onInvite ? { label: t("invitePeople"), onClick: onInvite } : undefined
        }
      />
    );
  }

  const columns: Column<DisplayMember>[] = [
    {
      header: t("member"),
      accessor: "user_id",
      rowLink: true,
      render: (_, member) =>
        member ? (
          <MemberCell member={member} currentUser={currentUser} />
        ) : null,
    },
    {
      header: t("accessColumn"),
      accessor: "access",
      headerClassName: "w-[180px]",
      render: (_, member) => {
        if (!member) return null;
        const access = getMemberAccess(member, ownerUserId);
        return (
          <Badge
            variant={ACCESS_BADGE[access]}
            title={
              access === "owner" ? t("accessOwnerHint") : t("accessMemberHint")
            }
          >
            {access === "owner" ? t("accessOwner") : t("accessMember")}
          </Badge>
        );
      },
    },
    {
      header: t("joined"),
      accessor: "joined_at",
      headerClassName: "w-[160px] max-md:hidden",
      cellClassName: "max-md:hidden",
      render: (_, member) =>
        member?.joined_at ? (
          <TableDateDisplay dateString={member.joined_at} onlyDate />
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      header: "",
      accessor: "actions",
      headerClassName: "w-0",
      cellClassName: "text-right",
      render: (_, member) =>
        member ? (
          <MemberRemoveButton
            member={member}
            currentUser={currentUser}
            ownerUserId={ownerUserId}
            workspaceName={workspaceName}
            placement="row"
            onRemovalPending={setRemovalPending}
          />
        ) : null,
    },
  ];

  return (
    <>
      {removalPending && (
        <p className="mb-3 text-xs text-muted-foreground" role="status">
          {t("removalInProgressText", { member: removalPending.label })}
        </p>
      )}
      <Table data={members} columns={columns} rowHref={getMemberHref} />
    </>
  );
}
