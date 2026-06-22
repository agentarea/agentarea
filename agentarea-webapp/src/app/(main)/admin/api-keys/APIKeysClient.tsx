"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { ru } from "date-fns/locale";
import { Check, CheckCircle, Copy, Loader2, Trash2 } from "lucide-react";
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

const APIKeyStatus = {
  ACTIVE: "active",
  REVOKED: "revoked",
  EXPIRED: "expired",
} as const;

type APIKeyStatusType = (typeof APIKeyStatus)[keyof typeof APIKeyStatus];

interface APIKey {
  id: string;
  name: string;
  token_prefix: string;
  status: APIKeyStatusType;
  created_at: string;
  expires_at?: string | null;
  last_used_at?: string | null;
}

const ModalIconBackground = ({ type }: { type: "delete" | "success" }) => {
  const iconBackground =
    type === "delete"
      ? "bg-destructive/30 text-destructive dark:bg-destructive dark:text-zinc-200"
      : "bg-accent/30 text-accent dark:bg-accent-foreground/20 dark:text-accent";

  const Icon = type === "delete" ? Trash2 : CheckCircle;

  return (
    <div className="relative w-max">
      <div
        data-featured-icon="true"
        className={`*:data-icon:size-6 relative flex size-12 shrink-0 items-center justify-center rounded-full ${iconBackground}`}
      >
        <Icon className="h-6 w-6" />
        <svg
          width="336"
          height="336"
          viewBox="0 0 336 336"
          fill="none"
          className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-zinc-300 dark:text-zinc-500"
        >
          <mask
            id="mask0_4947_375931"
            maskUnits="userSpaceOnUse"
            x="0"
            y="0"
            width="336"
            height="336"
            style={{ maskType: "alpha" }}
          >
            <rect
              width="336"
              height="336"
              fill="url(#paint0_radial_4947_375931)"
            ></rect>
          </mask>
          <g mask="url(#mask0_4947_375931)">
            <circle cx="168" cy="168" r="47.5" stroke="currentColor"></circle>
            <circle cx="168" cy="168" r="47.5" stroke="currentColor"></circle>
            <circle cx="168" cy="168" r="71.5" stroke="currentColor"></circle>
            <circle cx="168" cy="168" r="95.5" stroke="currentColor"></circle>
            <circle cx="168" cy="168" r="119.5" stroke="currentColor"></circle>
            <circle cx="168" cy="168" r="143.5" stroke="currentColor"></circle>
            <circle cx="168" cy="168" r="167.5" stroke="currentColor"></circle>
          </g>
          <defs>
            <radialGradient
              id="paint0_radial_4947_375931"
              cx="0"
              cy="0"
              r="1"
              gradientUnits="userSpaceOnUse"
              gradientTransform="translate(168 168) rotate(90) scale(168 168)"
            >
              <stop></stop>
              <stop offset="1" stopOpacity="0"></stop>
            </radialGradient>
          </defs>
        </svg>
      </div>
    </div>
  );
};

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
  const searchParams = useSearchParams();

  const keys = initialKeys;

  const dateLocale = locale === "ru" ? ru : undefined;

  const [revokeOpen, setRevokeOpen] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<APIKey | null>(null);
  const [revoking, setRevoking] = useState(false);

  const [newToken, setNewToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const token = searchParams.get("new_token");
    if (token) {
      setNewToken(token);
    }
  }, [searchParams]);

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

  async function handleCopyToken() {
    if (!newToken) return;
    try {
      await navigator.clipboard.writeText(newToken);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  }

  function handleCloseTokenModal() {
    setNewToken(null);
    setCopied(false);
    router.replace("/admin/api-keys");
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
            className="gap-1"
            onClick={(e) => {
              e.stopPropagation();
              setRevokeTarget(item);
              setRevokeOpen(true);
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
            {t("revoke.button")}
          </Button>
        ) : null,
    },
  ];

  if (keys.length === 0) {
    return (
      <EmptyState
        title={t("noKeys")}
        description={t("noKeysDescription")}
        iconsType="apiKey"
      />
    );
  }

  return (
    <>
      <Table data={keys} columns={columns} />

      <Dialog open={revokeOpen} onOpenChange={setRevokeOpen}>
        <DialogContent className="max-w-[400px] overflow-hidden dark:bg-zinc-800">
          <ModalIconBackground type="delete" />
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
              {revoking && <Loader2 className="h-4 w-4 animate-spin" />}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!newToken}
        onOpenChange={(open) => !open && handleCloseTokenModal()}
      >
        <DialogContent className="max-w-[530px] overflow-hidden dark:bg-zinc-800">
          <ModalIconBackground type="success" />
          <DialogHeader className="relative z-10 mt-3">
            <DialogTitle className="pb-2">{t("created.title")}</DialogTitle>
            <DialogDescription className="text-xs text-red-600 dark:text-red-400">
              {t("created.warning")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-1">
            <div className="flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/50">
              <code className="flex-1 break-all text-sm">{newToken}</code>
              <Button
                variant="ghost"
                size="sm"
                className="shrink-0"
                onClick={handleCopyToken}
              >
                {copied ? (
                  <Check className="h-4 w-4 text-green-500" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
          <DialogFooter>
            <Button size="sm" onClick={handleCloseTokenModal}>
              {t("created.done")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
