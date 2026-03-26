"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
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

function formatRelativeTime(dateString: string | null | undefined): string {
  if (!dateString) return "Never";
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffDays > 30) {
    return date.toLocaleDateString();
  } else if (diffDays > 0) {
    return `${diffDays}d ago`;
  } else if (diffHours > 0) {
    return `${diffHours}h ago`;
  } else if (diffMins > 0) {
    return `${diffMins}m ago`;
  } else {
    return "Just now";
  }
}

function getStatusVariant(
  status: string
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "active":
      return "default";
    case "revoked":
      return "destructive";
    case "expired":
      return "secondary";
    default:
      return "outline";
  }
}

export default function APIKeysClient({
  initialKeys,
}: {
  initialKeys: APIKey[];
}) {
  const t = useTranslations("APIKeysPage");
  const { toast } = useToast();
  const router = useRouter();

  const keys = initialKeys;

  const [revokeOpen, setRevokeOpen] = useState(false);
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
      <div className="rounded-md border border-gray-200 dark:border-gray-700">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("table.name")}</TableHead>
              <TableHead>{t("table.tokenPrefix")}</TableHead>
              <TableHead>{t("table.status")}</TableHead>
              <TableHead>{t("table.created")}</TableHead>
              <TableHead>{t("table.expires")}</TableHead>
              <TableHead>{t("table.lastUsed")}</TableHead>
              <TableHead className="text-right">{t("table.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {keys.map((key) => (
              <TableRow key={key.id}>
                <TableCell className="font-medium">{key.name}</TableCell>
                <TableCell>
                  <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs dark:bg-gray-800">
                    {key.token_prefix}...
                  </code>
                </TableCell>
                <TableCell>
                  <Badge variant={getStatusVariant(key.status)}>
                    {t(`status.${key.status}`)}
                  </Badge>
                </TableCell>
                <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                  {formatRelativeTime(key.created_at)}
                </TableCell>
                <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                  {key.expires_at
                    ? formatRelativeTime(key.expires_at)
                    : "Never"}
                </TableCell>
                <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                  {formatRelativeTime(key.last_used_at)}
                </TableCell>
                <TableCell className="text-right">
                  {key.status === "active" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="gap-1 text-red-600 hover:bg-red-50 hover:text-red-700 dark:hover:bg-red-900/20"
                      onClick={() => {
                        setRevokeTarget(key);
                        setRevokeOpen(true);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      {t("revoke.button")}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={revokeOpen} onOpenChange={setRevokeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("revoke.title")}</DialogTitle>
            <DialogDescription>{t("revoke.description")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRevokeOpen(false)}
              disabled={revoking}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleRevoke}
              disabled={revoking}
            >
              {revoking ? "Revoking..." : t("revoke.button")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
