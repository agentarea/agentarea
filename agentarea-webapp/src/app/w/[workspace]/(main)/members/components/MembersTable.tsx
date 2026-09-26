"use client";

import { useTransition } from "react";
import { useTranslations } from "next-intl";
import { LogOut, Search, Trash2, User, Users } from "lucide-react";
import { toast } from "sonner";
import BaseModal from "@/components/BaseModal";
import EmptyState from "@/components/EmptyState";
import Table, { type Column } from "@/components/Table/Table";
import { TableRowAction } from "@/components/Table/TableRowAction";
import { Badge } from "@/components/ui/badge";
import { BlueprintBadge } from "@/components/ui/blueprint-badge";
import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { deterministicHue } from "@/lib/avatar-hue";
import { removeMemberAction } from "../actions";
import {
  getMemberAccess,
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

function MemberRowActions({
  member,
  currentUser,
  access,
  ownerUserId,
  workspaceName,
}: {
  member: DisplayMember;
  currentUser: CurrentUser;
  access: MemberAccess;
  ownerUserId: string | null;
  workspaceName: string;
}) {
  const t = useTranslations("MembersPage");
  const router = useWorkspaceRouter();
  const [, startTransition] = useTransition();

  const isSelf = member.user_id === currentUser.id;
  const label = isAnonymousMember(member, currentUser)
    ? shortId(member.user_id)
    : getMemberLabel(member, currentUser);
  const canLeave = isSelf && access !== "owner";
  const canRemove =
    !isSelf &&
    ownerUserId !== null &&
    ownerUserId === currentUser.id &&
    access !== "owner";
  if (!canLeave && !canRemove) return null;

  const remove = async () => {
    const res = await removeMemberAction(member.user_id);
    if (res.error) {
      toast.error(isSelf ? t("leaveFailed") : t("removeFailed"), {
        description: res.error,
      });
      return;
    }
    if (res.pending) {
      toast(t("removalInProgress"), {
        description: isSelf
          ? t("leaveInProgressText")
          : t("removalInProgressText", { member: label }),
      });
    } else if (isSelf) {
      toast.success(t("youLeft"));
    } else {
      toast.success(t("memberRemoved"), {
        description: t("memberRemovedText", { member: label }),
      });
    }
    if (isSelf) {
      router.push("/");
    } else {
      startTransition(() => router.refresh());
    }
  };

  return (
    <BaseModal
      type="delete"
      title={isSelf ? t("leaveWorkspace") : t("removeMemberTitle")}
      description={
        isSelf
          ? t("leaveText", { workspace: workspaceName })
          : t("removeMemberText", { member: label, workspace: workspaceName })
      }
      confirmLabel={isSelf ? t("leave") : t("remove")}
      onConfirm={remove}
    >
      <TableRowAction
        variant="destructiveOutline"
        icon={isSelf ? <LogOut /> : <Trash2 />}
      >
        {isSelf ? t("leave") : t("remove")}
      </TableRowAction>
    </BaseModal>
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
      header: "",
      accessor: "actions",
      headerClassName: "w-0",
      cellClassName: "text-right",
      render: (_, member) =>
        member ? (
          <MemberRowActions
            member={member}
            currentUser={currentUser}
            access={getMemberAccess(member, ownerUserId)}
            ownerUserId={ownerUserId}
            workspaceName={workspaceName}
          />
        ) : null,
    },
  ];

  return <Table data={members} columns={columns} />;
}
