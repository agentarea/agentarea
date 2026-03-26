"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { Check, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { createAPIKeyAction } from "../actions";

export default function CreateAPIKeyButton() {
  const t = useTranslations("APIKeysPage");
  const { toast } = useToast();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState("");
  const [creating, setCreating] = useState(false);
  const [newToken, setNewToken] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (searchParams.get("dialog") === "create") {
      setOpen(true);
      router.replace("/admin/api-keys");
    }
  }, [searchParams, router]);

  async function handleCreate() {
    if (!name.trim()) return;
    setCreating(true);
    const formData = new FormData();
    formData.set("name", name.trim());
    if (expiry) {
      formData.set("expires_in_days", expiry);
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

    setOpen(false);
    setName("");
    setExpiry("");

    const token = (result.data as any)?.token;
    if (token) {
      setNewToken(token);
    }

    toast({ title: t("success.created") });
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
    <>
      <Button
        className="shrink-0 gap-2"
        size="xs"
        onClick={() => setOpen(true)}
        data-test="create-api-key-button"
      >
        <Plus className="h-4 w-4" />
        {t("createKey")}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
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
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreate();
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="api-key-expiry">
                {t("create.expiresInDays")}
              </Label>
              <Input
                id="api-key-expiry"
                type="number"
                placeholder={t("create.expiresInDaysPlaceholder")}
                value={expiry}
                onChange={(e) => setExpiry(e.target.value)}
                min="1"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={creating}
            >
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={creating || !name.trim()}>
              {creating ? "Creating..." : t("create.createButton")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!newToken} onOpenChange={() => setNewToken("")}>
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
                {copied ? <Check className="h-4 w-4 text-green-500" /> : "Copy"}
              </Button>
            </div>
            {copied && (
              <p className="text-xs text-green-600 dark:text-green-400">
                {t("created.copied")}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button onClick={() => setNewToken("")}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
