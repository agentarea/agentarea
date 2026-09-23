"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Key, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import BaseModal from "@/components/BaseModal";
import FormLabel from "@/components/FormLabel/FormLabel";
import { TableRowAction } from "@/components/Table/TableRowAction";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { Dialog, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { deleteSecretAction, rotateSecretAction } from "../actions";
import type { Secret } from "./SecretsTable";
import { useSecretTypeLabel } from "./useSecretTypeLabel";

function ReplaceValueAction({ secret }: { secret: Secret }) {
  const t = useTranslations("SecretsPage");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setValue("");
      setError(null);
    }
  };

  const replace = () => {
    setError(null);
    startTransition(async () => {
      const result = await rotateSecretAction(secret.id, value);
      if (result.error) {
        setError(result.error);
        return;
      }
      onOpenChange(false);
      router.refresh();
    });
  };

  const usageCount = secret.used_by?.length ?? 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <TableRowAction icon={<RefreshCw />}>
          {t("rowActions.replace")}
        </TableRowAction>
      </DialogTrigger>
      <BlueprintDialogContent
        title={t("replaceDialog.title")}
        description={t("replaceDialog.description", { name: secret.name })}
        note={
          usageCount > 0
            ? t("replaceDialog.usedIn", { count: usageCount })
            : undefined
        }
        actions={
          <Button size="sm" onClick={replace} disabled={pending || !value}>
            {pending && <Loader2 className="animate-spin" />}
            {t("replaceDialog.submit")}
          </Button>
        }
      >
        <BlueprintFields>
          <div className="space-y-2">
            <FormLabel htmlFor={`rotate-value-${secret.id}`} icon={Key}>
              {t("replaceDialog.valueLabel")}
            </FormLabel>
            <Input
              id={`rotate-value-${secret.id}`}
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="off"
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

function DeleteSecretAction({ secret }: { secret: Secret }) {
  const t = useTranslations("SecretsPage");
  const tCommon = useTranslations("Common");
  const typeLabel = useSecretTypeLabel();
  const router = useRouter();
  const [, startTransition] = useTransition();

  const remove = async () => {
    const result = await deleteSecretAction(secret.id);
    if (result.error) {
      toast.error(t("deleteDialog.failed"), { description: result.error });
      return;
    }
    toast.success(t("deleteDialog.deleted", { name: secret.name }));
    startTransition(() => router.refresh());
  };

  const usedBy = secret.used_by ?? [];

  return (
    <BaseModal
      type="delete"
      title={t("deleteDialog.title", { name: secret.name })}
      description={
        usedBy.length > 0 ? (
          <>
            {t("deleteDialog.inUse")}
            {usedBy.map((c) => (
              <span
                key={`${c.consumer_type}-${c.consumer_id}-${c.field}`}
                className="mt-1 block"
              >
                {typeLabel(c.consumer_type)} · {c.field}
              </span>
            ))}
          </>
        ) : (
          t("deleteDialog.irreversible")
        )
      }
      // Deleting is refused while anything points at the secret.
      confirmDisabled={usedBy.length > 0}
      onConfirm={remove}
    >
      <TableRowAction variant="destructiveOutline" icon={<Trash2 />}>
        {tCommon("delete")}
      </TableRowAction>
    </BaseModal>
  );
}

/** Hover actions for a secret the user owns directly. */
export function SecretRowActions({ secret }: { secret: Secret }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <ReplaceValueAction secret={secret} />
      <DeleteSecretAction secret={secret} />
    </span>
  );
}
