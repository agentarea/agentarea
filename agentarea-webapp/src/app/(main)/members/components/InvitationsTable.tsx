"use client";

import { useState, useTransition } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Link2, Loader2, Mail, Search } from "lucide-react";
import { toast } from "sonner";
import EmptyState from "@/components/EmptyState";
import Table, { type Column } from "@/components/Table/Table";
import { Button } from "@/components/ui/button";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import {
  StatusIndicator,
  type StatusIndicatorTone,
} from "@/components/ui/status-indicator";
import type { WorkspaceInvitation } from "@/lib/api";
import { revokeInvitationAction } from "../actions";
import {
  formatDate,
  getInvitationStatus,
  type InvitationStatusKey,
} from "./membersShared";

interface InvitationsTableProps {
  invitations: WorkspaceInvitation[];
  query: string;
  onInvite: () => void;
}

const STATUS_TONE: Record<InvitationStatusKey, StatusIndicatorTone> = {
  pending: "neutral",
  soon: "warning",
  today: "warning",
  expired: "danger",
};

function RecipientCell({ invitation }: { invitation: WorkspaceInvitation }) {
  const t = useTranslations("MembersPage");
  const byEmail = Boolean(invitation.email);
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <EntityAvatar
        size={28}
        variant="soft"
        icon={
          byEmail ? <Mail strokeWidth={1.8} /> : <Link2 strokeWidth={1.8} />
        }
      />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-[13px] font-medium">
          {invitation.email || t("anyoneWithLink")}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {byEmail ? t("emailInvitation") : t("linkInvitation")}
        </span>
      </span>
    </span>
  );
}

function InvitationStatusCell({
  invitation,
  now,
}: {
  invitation: WorkspaceInvitation;
  now: Date;
}) {
  const t = useTranslations("MembersPage");
  const status = getInvitationStatus(invitation, now);
  const label =
    status.key === "expired"
      ? t("statusExpired")
      : status.key === "today"
        ? t("statusExpiresToday")
        : status.key === "soon"
          ? t("statusExpiresIn", { days: status.days })
          : t("statusPending");
  return (
    <StatusIndicator tone={STATUS_TONE[status.key]}>{label}</StatusIndicator>
  );
}

function RevokeButton({ invitation }: { invitation: WorkspaceInvitation }) {
  const t = useTranslations("MembersPage");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);

  const revoke = () => {
    setBusy(true);
    startTransition(async () => {
      const res = await revokeInvitationAction(invitation.id);
      setBusy(false);
      if (res.error) {
        toast.error(t("revokeFailed"), { description: res.error });
        return;
      }
      toast.success(t("invitationRevoked"), {
        description: invitation.email
          ? t("invitationRevokedEmail", { email: invitation.email })
          : t("invitationRevokedLink"),
      });
      router.refresh();
    });
  };

  const isBusy = busy && pending;
  return (
    <Button
      variant="ghost"
      size="xs"
      className="text-muted-foreground opacity-0 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100 data-[busy=true]:opacity-100"
      data-busy={isBusy}
      disabled={isBusy}
      onClick={revoke}
    >
      {isBusy && <Loader2 className="animate-spin" />}
      {t("revoke")}
    </Button>
  );
}

export function InvitationsTable({
  invitations,
  query,
  onInvite,
}: InvitationsTableProps) {
  const t = useTranslations("MembersPage");
  const locale = useLocale();
  // One clock for the whole table, so every row agrees on "today".
  const [now] = useState(() => new Date());

  if (invitations.length === 0) {
    return query ? (
      <EmptyState
        icons={[Search]}
        title={t("noInvitationsMatchTitle", { query })}
        description={t("noMatchDescription")}
      />
    ) : (
      <EmptyState
        icons={[Link2]}
        title={t("noInvitationsTitle")}
        description={t("noInvitationsDescription")}
        action={{ label: t("invitePeople"), onClick: onInvite }}
      />
    );
  }

  const columns: Column<WorkspaceInvitation>[] = [
    {
      header: t("recipient"),
      accessor: "email",
      render: (_, inv) => (inv ? <RecipientCell invitation={inv} /> : null),
    },
    {
      header: t("status"),
      accessor: "status",
      headerClassName: "w-[170px]",
      render: (_, inv) =>
        inv ? <InvitationStatusCell invitation={inv} now={now} /> : null,
    },
    {
      header: t("sent"),
      accessor: "created_at",
      headerClassName: "w-[120px]",
      cellClassName: "whitespace-nowrap text-xs text-muted-foreground",
      render: (value) => formatDate(value as string, locale),
    },
    {
      header: t("expires"),
      accessor: "expires_at",
      headerClassName: "w-[120px]",
      cellClassName: "whitespace-nowrap text-xs text-muted-foreground",
      render: (value) => formatDate(value as string, locale),
    },
    {
      header: "",
      accessor: "actions",
      headerClassName: "w-0",
      cellClassName: "text-right",
      render: (_, inv) => (inv ? <RevokeButton invitation={inv} /> : null),
    },
  ];

  return <Table data={invitations} columns={columns} />;
}
