"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Copy, Check, Plus, Trash2, Key } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { createAPIKeyAction, revokeAPIKeyAction } from "./actions";

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

function getStatusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
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

export default function APIKeysClient({ initialKeys }: { initialKeys: APIKey[] }) {
  const t = useTranslations("APIKeysPage");
  const { toast } = useToast();
  const router = useRouter();

  const keys = initialKeys;

  // Create dialog state
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createExpiry, setCreateExpiry] = useState("");
  const [creating, setCreating] = useState(false);

  // New token display dialog state
  const [newTokenOpen, setNewTokenOpen] = useState(false);
  const [newToken, setNewToken] = useState("");
  const [copied, setCopied] = useState(false);

  // Revoke dialog state
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<APIKey | null>(null);
  const [revoking, setRevoking] = useState(false);

  async function handleCreate() {
    if (!createName.trim()) return;
    setCreating(true);
    const formData = new FormData();
    formData.set("name", createName.trim());
    if (createExpiry) {
      formData.set("expires_in_days", createExpiry);
    }
    const result = await createAPIKeyAction(formData);
    setCreating(false);

    if (result.error) {
      toast({
        title: t("error.createFailed"),
        description: result.error,
        variant: "destructive",
      });
      return;
    }

    setCreateOpen(false);
    setCreateName("");
    setCreateExpiry("");

    const token = (result.data as any)?.token;
    if (token) {
      setNewToken(token);
      setNewTokenOpen(true);
    }

    toast({ title: t("success.created") });
    router.refresh();
  }

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

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(newToken);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-600 dark:text-gray-400">
          {keys.length > 0 ? `${keys.length} key${keys.length !== 1 ? "s" : ""}` : ""}
        </p>
        <Button
          size="sm"
          className="gap-1"
          onClick={() => setCreateOpen(true)}
        >
          <Plus className="h-3.5 w-3.5" />
          {t("createKey")}
        </Button>
      </div>

      {/* Table or Empty State */}
      {keys.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 py-12 dark:border-gray-700">
          <Key className="mb-3 h-8 w-8 text-gray-400" />
          <p className="text-sm font-medium text-gray-900 dark:text-white">
            {t("noKeys")}
          </p>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {t("noKeysDescription")}
          </p>
          <Button
            size="sm"
            className="mt-4 gap-1"
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            {t("createKey")}
          </Button>
        </div>
      ) : (
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
                    {key.expires_at ? formatRelativeTime(key.expires_at) : "Never"}
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
      )}

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("create.title")}</DialogTitle>
            <DialogDescription>{t("create.description")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label htmlFor="api-key-name">{t("create.name")}</Label>
              <Input
                id="api-key-name"
                placeholder={t("create.namePlaceholder")}
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreate();
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="api-key-expiry">{t("create.expiresInDays")}</Label>
              <Input
                id="api-key-expiry"
                type="number"
                placeholder={t("create.expiresInDaysPlaceholder")}
                value={createExpiry}
                onChange={(e) => setCreateExpiry(e.target.value)}
                min="1"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCreateOpen(false)}
              disabled={creating}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={creating || !createName.trim()}
            >
              {creating ? "Creating..." : t("create.createButton")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Token Display Dialog */}
      <Dialog open={newTokenOpen} onOpenChange={setNewTokenOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("created.title")}</DialogTitle>
            <DialogDescription className="text-amber-600 dark:text-amber-400">
              {t("created.warning")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/50">
              <code className="flex-1 break-all text-sm">{newToken}</code>
              <Button
                variant="ghost"
                size="sm"
                className="shrink-0"
                onClick={handleCopy}
              >
                {copied ? (
                  <Check className="h-4 w-4 text-green-500" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
            {copied && (
              <p className="text-xs text-green-600 dark:text-green-400">
                {t("created.copied")}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button onClick={() => setNewTokenOpen(false)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Revoke Confirmation Dialog */}
      <Dialog open={revokeOpen} onOpenChange={setRevokeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("revoke.title")}</DialogTitle>
            <DialogDescription>
              {t("revoke.description")}
            </DialogDescription>
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
    </div>
  );
}
