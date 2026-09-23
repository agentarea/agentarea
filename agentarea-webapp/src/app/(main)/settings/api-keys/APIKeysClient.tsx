"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { ru } from "date-fns/locale";
import { Loader2, Trash2 } from "lucide-react";
import { ModalFeaturedIcon } from "@/components/BaseModal/ModalFeaturedIcon";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useToast } from "@/hooks/use-toast";
import { getApiKeyStatusPresentation } from "@/lib/status";
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

export default function APIKeysClient({
  initialKeys,
}: {
  initialKeys: APIKey[];
}) {
  const t = useTranslations("APIKeysPage");
  const tCommon = useTranslations("Common");
  const locale = useLocale();
  const { toast } = useToast();
  const router = useRouter();

  const keys = initialKeys;

  const dateLocale = locale === "ru" ? ru : undefined;

  const [revokeOpen, setRevokeOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createSession, setCreateSession] = useState(0);
  const [revokeTarget, setRevokeTarget] = useState<APIKey | null>(null);
  const [revoking, setRevoking] = useState(false);

  async function handleRevoke() {
    if (!revokeTarget) return;
    setRevoking(true);
    const result = await revokeAPIKeyAction(revokeTarget.id);
    setRevoking(false);

    if (result.error) {
      toast({
        title: t("error.revokeFailed"),
        description: result.error,
        variant: "destructive",
      });
      return;
    }

    setRevokeOpen(false);
    setRevokeTarget(null);
    toast({ title: t("success.revoked") });
    router.refresh();
  }

  const columns = [
    {
      accessor: "name",
      header: t("table.name"),
      cellClassName: "w-[20%]",
      render: (value: string) => (
        <span className="font-medium line-clamp-2">{value}</span>
      ),
    },
    {
      accessor: "token_prefix",
      header: t("table.tokenPrefix"),
      cellClassName: "w-[15%]",
      render: (value: string) => (
        <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs dark:bg-gray-800">
          {value}...
        </code>
      ),
    },
    {
      accessor: "status",
      header: t("table.status"),
      cellClassName: "w-[12%]",
      render: (value: APIKeyStatusType) => {
        const presentation = getApiKeyStatusPresentation(value);

        return (
          <StatusIndicator
            size="sm"
            tone={presentation.tone}
            pulse={presentation.pulse}
            className="whitespace-nowrap"
          >
            {t(`status.${value}`)}
          </StatusIndicator>
        );
      },
    },
    {
      accessor: "created_at",
      header: t("table.created"),
      cellClassName: "w-[15%]",
      render: (value: string) => (
        <TableDateDisplay dateString={value} onlyDate />
      ),
    },
    {
      accessor: "expires_at",
      header: t("table.expires"),
      cellClassName: "w-[15%]",
      render: (value: string | null) => (
        <span className="text-xs text-muted-foreground">
          {value
            ? formatDistanceToNow(new Date(value), {
                addSuffix: true,
                locale: dateLocale,
              })
            : t("never")}
        </span>
      ),
    },
    {
      accessor: "last_used_at",
      header: t("table.lastUsed"),
      cellClassName: "w-[13%]",
      render: (value: string | null) => (
        <span className="text-xs text-muted-foreground">
          {value
            ? formatDistanceToNow(new Date(value), {
                addSuffix: true,
                locale: dateLocale,
              })
            : t("never")}
        </span>
      ),
    },
    {
      accessor: "id",
      header: t("table.actions"),
      headerClassName: "text-right",
      cellClassName: "w-[10%] text-right",
      render: (_value: string, item: APIKey) =>
        item.status === "active" ? (
          <Button
            variant="destructiveOutline"
            size="xs"
            onClick={(e) => {
              e.stopPropagation();
              setRevokeTarget(item);
              setRevokeOpen(true);
            }}
          >
            <Trash2 />
            {t("revoke.button")}
          </Button>
        ) : null,
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

      <Dialog open={revokeOpen} onOpenChange={setRevokeOpen}>
        <DialogContent className="max-w-[400px] overflow-hidden">
          <ModalFeaturedIcon type="delete" />
          <DialogHeader className="relative z-10 mt-3">
            <DialogTitle className="pb-2">{t("revoke.title")}</DialogTitle>
            <DialogDescription>
              {t("revoke.description", { keyName: revokeTarget?.name || "" })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRevokeOpen(false)}
              disabled={revoking}
            >
              {tCommon("cancel")}
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={handleRevoke}
              disabled={revoking}
            >
              {t("revoke.button")}
              {revoking && <Loader2 className="animate-spin" />}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
