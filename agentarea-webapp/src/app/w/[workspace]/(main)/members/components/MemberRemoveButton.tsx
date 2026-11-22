"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { LogOut, Trash2 } from "lucide-react";
import BaseModal from "@/components/BaseModal";
import { TableRowAction } from "@/components/Table/TableRowAction";
import { Button } from "@/components/ui/button";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { formatApiError } from "@/lib/api-errors";
import { removeMemberAction } from "../actions";
import {
  getMemberAccess,
  getMemberLabel,
  isAnonymousMember,
  shortId,
  type CurrentUser,
  type DisplayMember,
} from "./membersShared";

/**
 * Leave (yourself) or Remove (someone else, by the owner) behind a confirm
 * dialog. Renders nothing when the viewer may do neither.
 *
 * `placement="row"` is the hover-revealed table action and refreshes the list;
 * `placement="header"` sits on the member's own page and goes back to the list.
 */
export function MemberRemoveButton({
  member,
  currentUser,
  ownerUserId,
  workspaceName,
  placement,
  consequence,
  onRemovalPending,
}: {
  member: DisplayMember;
  currentUser: CurrentUser;
  ownerUserId: string | null;
  workspaceName: string;
  placement: "row" | "header";
  /** What else stops when this member goes, appended to the confirmation. */
  consequence?: string;
  onRemovalPending?: (pending: { userId: string; label: string }) => void;
}) {
  const t = useTranslations("MembersPage");
  const router = useWorkspaceRouter();
  const [, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const access = getMemberAccess(member, ownerUserId);
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
    setError(null);
    let res: Awaited<ReturnType<typeof removeMemberAction>>;
    try {
      res = await removeMemberAction(member.user_id);
    } catch (err) {
      console.error("Failed to remove member", err);
      setError(
        `${isSelf ? t("leaveFailed") : t("removeFailed")}: ${formatApiError(err)}`
      );
      return;
    }
    if (res.error) {
      setError(res.error);
      return;
    }
    if (isSelf) {
      router.push("/");
      return;
    }
    // The row disappears on refresh; the table keeps the notice.
    if (res.pending) onRemovalPending?.({ userId: member.user_id, label });
    if (placement === "header") {
      router.push("/members");
    } else {
      startTransition(() => router.refresh());
    }
  };

  const text = isSelf ? t("leave") : t("remove");
  const icon = isSelf ? <LogOut /> : <Trash2 />;
  const description = isSelf
    ? t("leaveText", { workspace: workspaceName })
    : t("removeMemberText", { member: label, workspace: workspaceName });

  return (
    // A table row navigates on click, and the dialog's events bubble through
    // its portal to the row; neither should open the member's page.
    <span
      className="inline-flex items-center gap-2"
      onClick={(event) => event.stopPropagation()}
    >
      {error && (
        <span className="form-error max-w-xs text-left" role="alert">
          {error}
        </span>
      )}
      <BaseModal
        type="delete"
        title={isSelf ? t("leaveWorkspace") : t("removeMemberTitle")}
        description={
          consequence ? `${description} ${consequence}` : description
        }
        confirmLabel={text}
        onConfirm={remove}
      >
        {placement === "row" ? (
          <TableRowAction variant="destructiveOutline" icon={icon}>
            {text}
          </TableRowAction>
        ) : (
          <Button variant="destructiveOutline" size="xs" className="gap-2">
            {icon}
            {text}
          </Button>
        )}
      </BaseModal>
    </span>
  );
}
