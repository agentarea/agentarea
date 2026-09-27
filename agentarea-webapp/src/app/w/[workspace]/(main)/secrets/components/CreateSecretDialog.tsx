"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { FileText, Key, Loader2, Plus, Tag } from "lucide-react";
import type { SecretResponse } from "@/api/client/types.gen";
import { AdminOnlyHint } from "@/components/AdminOnlyState";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { Dialog, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { createSecretAction } from "../actions";

type CreateSecretDialogProps = {
  /** Controlled mode — lets an empty state open the dialog without a trigger. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  showTrigger?: boolean;
  /** Set by a picker that wants the new secret rather than a page reload. */
  onCreated?: (secret: SecretResponse) => void;
};

export function CreateSecretDialog({
  open: controlledOpen,
  onOpenChange,
  showTrigger = true,
  onCreated,
}: CreateSecretDialogProps = {}) {
  const t = useTranslations("SecretsPage");
  const router = useWorkspaceRouter();
  const { canAdminister } = useViewerCapabilities();
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = onOpenChange ?? setUncontrolledOpen;
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const submit = () => {
    setError(null);
    startTransition(async () => {
      // Name rules and reserved prefixes are the server's to enforce — it owns
      // the list of names the platform already uses — so its message is shown
      // rather than a guess made here.
      const result = await createSecretAction({ name, value, description });
      if (result.error !== null) {
        setError(result.error);
        return;
      }
      setName("");
      setValue("");
      setDescription("");
      setOpen(false);
      if (onCreated) {
        onCreated(result.secret);
        return;
      }
      router.refresh();
    });
  };

  if (!canAdminister) {
    return showTrigger ? (
      <div className="flex items-center gap-3">
        <AdminOnlyHint action="createSecret" className="max-sm:hidden" />
        <Button className="shrink-0" size="xs" disabled>
          <Plus />
          {t("newSecret")}
        </Button>
      </div>
    ) : null;
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {showTrigger && (
        <DialogTrigger asChild>
          <Button className="shrink-0" size="xs">
            <Plus />
            {t("newSecret")}
          </Button>
        </DialogTrigger>
      )}
      <BlueprintDialogContent
        title={t("createDialog.title")}
        description={t("createDialog.description")}
        note={t("createDialog.footerNote")}
        actions={
          <Button
            size="sm"
            onClick={submit}
            disabled={pending || !name || !value}
          >
            {pending && <Loader2 className="animate-spin" />}
            {t("createDialog.submit")}
          </Button>
        }
      >
        <BlueprintFields>
          <div className="space-y-2">
            <FormLabel htmlFor="secret-name" icon={Tag}>
              {t("createDialog.nameLabel")}
            </FormLabel>
            <Input
              id="secret-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("createDialog.namePlaceholder")}
              autoComplete="off"
            />
            <p className="note">{t("createDialog.nameHint")}</p>
          </div>

          <div className="space-y-2">
            <FormLabel htmlFor="secret-value" icon={Key}>
              {t("createDialog.valueLabel")}
            </FormLabel>
            <Input
              id="secret-value"
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="space-y-2">
            <FormLabel htmlFor="secret-description" icon={FileText} optional>
              {t("createDialog.descriptionLabel")}
            </FormLabel>
            <Input
              id="secret-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("createDialog.descriptionPlaceholder")}
            />
          </div>

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </BlueprintFields>
      </BlueprintDialogContent>
    </Dialog>
  );
}
