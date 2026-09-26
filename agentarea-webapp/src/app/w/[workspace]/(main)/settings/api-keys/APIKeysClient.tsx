"use client";

import { useState, useTransition } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { formatDistanceToNow } from "date-fns";
import { ru } from "date-fns/locale";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import BaseModal from "@/components/BaseModal";
import EmptyState from "@/components/EmptyState";
import Table, { type Column } from "@/components/Table/Table";
import { TableRowAction } from "@/components/Table/TableRowAction";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getApiKeyStatusPresentation } from "@/lib/status";
import { formatDate } from "@/utils/dateUtils";
import { revokeAPIKeyAction } from "./actions";
import CreateAPIKeyDialog from "./components/CreateAPIKeyDialog";

type APIKeyStatusType = "active" | "revoked" | "expired"; // pragma: allowlist secret

interface APIKey {
  id: string;
  name: string;
  token_prefix: string;
  status: APIKeyStatusType;
  created_at: string;
  expires_at?: string | null;
  last_used_at?: string | null;
}

function RevokeKeyAction({ apiKey }: { apiKey: APIKey }) {
  const t = useTranslations("APIKeysPage");
  const router = useWorkspaceRouter();
  const [, startTransition] = useTransition();

  const revoke = async () => {
    const result = await revokeAPIKeyAction(apiKey.id);
    if (result.error) {
      toast.error(t("error.revokeFailed"), { description: result.error });
      return;
    }
    toast.success(t("success.revoked"));
    startTransition(() => router.refresh());
  };

  return (
    <BaseModal
      type="delete"
      title={t("revoke.title")}
      description={t("revoke.description", { keyName: apiKey.name })}
      confirmLabel={t("revoke.button")}
      onConfirm={revoke}
    >
      <TableRowAction variant="destructiveOutline" icon={<Trash2 />}>
        {t("revoke.button")}
      </TableRowAction>
    </BaseModal>
  );
}

export default function APIKeysClient({
  initialKeys,
}: {
  initialKeys: APIKey[];
}) {
  const t = useTranslations("APIKeysPage");
  const locale = useLocale();

  const keys = initialKeys;

  const dateLocale = locale === "ru" ? ru : undefined;

  const [createOpen, setCreateOpen] = useState(false);
  const [createSession, setCreateSession] = useState(0);

  const columns: Column<APIKey>[] = [
    {
      header: t("table.name"),
      accessor: "name",
      cellClassName: "max-w-[320px]",
      render: (value) => (
        <span className="block truncate text-[13px] font-medium">
          {value as string}
        </span>
      ),
    },
    {
      header: t("table.tokenPrefix"),
      accessor: "token_prefix",
      headerClassName: "w-[140px]",
      cellClassName:
        "whitespace-nowrap font-mono text-xs text-muted-foreground",
      render: (value) => `${value as string}…`,
    },
    {
      header: t("table.status"),
      accessor: "status",
      headerClassName: "w-[120px]",
      render: (value) => {
        const status = value as APIKeyStatusType;
        const presentation = getApiKeyStatusPresentation(status);
        return (
          <StatusIndicator tone={presentation.tone} pulse={presentation.pulse}>
            {t(`status.${status}`)}
          </StatusIndicator>
        );
      },
    },
    {
      header: t("table.created"),
      accessor: "created_at",
      headerClassName: "w-[120px]",
      cellClassName: "whitespace-nowrap text-xs text-muted-foreground",
      render: (value) => formatDate(value as string, locale),
    },
    {
      header: t("table.expires"),
      accessor: "expires_at",
      headerClassName: "w-[120px]",
      cellClassName: "whitespace-nowrap text-xs text-muted-foreground",
      render: (value) =>
        value ? formatDate(value as string, locale) : t("never"),
    },
    {
      header: t("table.lastUsed"),
      accessor: "last_used_at",
      headerClassName: "w-[150px]",
      cellClassName: "whitespace-nowrap text-xs text-muted-foreground",
      render: (value) =>
        value
          ? formatDistanceToNow(new Date(value as string), {
              addSuffix: true,
              locale: dateLocale,
            })
          : t("never"),
    },
    {
      header: "",
      accessor: "actions",
      headerClassName: "w-0",
      cellClassName: "text-right",
      render: (_, item) =>
        item?.status === "active" ? <RevokeKeyAction apiKey={item} /> : null,
    },
  ];

  return (
    <>
      {keys.length === 0 ? (
        <EmptyState
          title={t("noKeys")}
          description={t("noKeysDescription")}
          hints={[
            { text: t("noKeysHintCreate") },
            { text: t("noKeysHintUse") },
            { text: t("noKeysHintRevoke") },
          ]}
          iconsType="apiKey"
          action={{
            label: t("createKey"),
            onClick: () => {
              setCreateSession((session) => session + 1);
              setCreateOpen(true);
            },
          }}
        />
      ) : (
        <Table data={keys} columns={columns} />
      )}

      {/* Outside the empty/table switch: the refresh after creating the
          first key swaps that branch, and the new key must stay on screen. */}
      <CreateAPIKeyDialog
        key={createSession}
        open={createOpen}
        onOpenChange={setCreateOpen}
      />
    </>
  );
}
