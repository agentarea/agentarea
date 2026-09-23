"use client";

import { useRef, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Key, Loader2, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";
import BaseModal from "@/components/BaseModal";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { deleteSecretAction, rotateSecretAction } from "../actions";
import type { Secret } from "./SecretsTable";

type Mode = "rotate" | "delete";

export function SecretRowActions({ secret }: { secret: Secret }) {
  const t = useTranslations("SecretsPage");
  const tCommon = useTranslations("Common");
  const router = useRouter();
  const [mode, setMode] = useState<Mode | null>(null);
  // Picked in the menu, opened once the menu has fully closed. A dialog that
  // opens while the menu is still mounted leaves `pointer-events: none` on
  // <body> after both are gone, and the page stops taking clicks.
  const pickedMode = useRef<Mode | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const close = () => {
    setMode(null);
    setValue("");
    setError(null);
  };

  const run = (action: () => Promise<{ error: string | null }>) => {
    setError(null);
    startTransition(async () => {
      const result = await action();
      if (result.error) {
        setError(result.error);
        return;
      }
      close();
      router.refresh();
    });
  };

  const remove = async () => {
    const result = await deleteSecretAction(secret.id);
    if (result.error) {
      toast.error(t("deleteDialog.failed"), { description: result.error });
      return;
    }
    toast.success(t("deleteDialog.deleted", { name: secret.name }));
    startTransition(() => router.refresh());
  };

  const usageCount = secret.used_by?.length ?? 0;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("rowActions.actionsFor", { name: secret.name })}
          >
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          onCloseAutoFocus={() => {
            setMode(pickedMode.current);
            pickedMode.current = null;
          }}
        >
          <DropdownMenuItem onSelect={() => (pickedMode.current = "rotate")}>
            {t("rowActions.replaceValue")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => (pickedMode.current = "delete")}
            className="text-destructive"
          >
            {tCommon("delete")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={mode === "rotate"} onOpenChange={(o) => !o && close()}>
        <BlueprintDialogContent
          title={t("replaceDialog.title")}
          description={t("replaceDialog.description", { name: secret.name })}
          note={
            usageCount > 0
              ? t("replaceDialog.usedIn", { count: usageCount })
              : undefined
          }
          actions={
            <Button
              size="sm"
              onClick={() => run(() => rotateSecretAction(secret.id, value))}
              disabled={pending || !value}
            >
              {pending && <Loader2 className="animate-spin" />}
              {t("replaceDialog.submit")}
            </Button>
          }
        >
          <BlueprintFields>
            <div className="space-y-2">
              <FormLabel htmlFor="rotate-value" icon={Key}>
                {t("replaceDialog.valueLabel")}
              </FormLabel>
              <Input
                id="rotate-value"
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

      <BaseModal
        type="delete"
        open={mode === "delete"}
        onOpenChange={(o) => !o && close()}
        title={t("deleteDialog.title", { name: secret.name })}
        description={
          usageCount > 0 ? (
            <>
              {t("deleteDialog.inUse")}
              {secret.used_by?.map((c) => (
                <span
                  key={`${c.consumer_type}-${c.consumer_id}-${c.field}`}
                  className="mt-1 block"
                >
                  {c.consumer_type} · {c.field}
                </span>
              ))}
            </>
          ) : (
            t("deleteDialog.irreversible")
          )
        }
        // Deleting is refused while anything points at the secret.
        confirmDisabled={usageCount > 0}
        onConfirm={remove}
      />
    </>
  );
}
