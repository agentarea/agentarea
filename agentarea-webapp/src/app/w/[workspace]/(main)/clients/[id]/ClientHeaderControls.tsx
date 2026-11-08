"use client";

import { useState, useTransition, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { Pencil } from "lucide-react";
import type { ClientResponse } from "@/api/client";
import DeleteButton from "@/components/DeleteButton";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { deleteClientAction } from "@/lib/server-actions";
import { saveClientDetailsAction } from "./actions";

/** The harness header's edit (name, description) and delete. */
export default function ClientHeaderControls({
  client,
}: {
  client: ClientResponse;
}) {
  const t = useTranslations("ClientsPage");
  const tCommon = useTranslations("Common");
  const router = useWorkspaceRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  // Not a form action: React would reset the fields on a failed save too.
  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    startTransition(async () => {
      const result = await saveClientDetailsAction(client.id, form);
      if (result.error !== null) {
        setError(result.error);
        return;
      }
      setOpen(false);
      router.refresh();
    });
  };

  return (
    <div className="flex items-center gap-2 py-1">
      <Button
        size="xs"
        variant="outline"
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
      >
        <Pencil />
        {tCommon("edit")}
      </Button>
      <DeleteButton
        size="xs"
        itemId={client.id}
        itemName={client.name}
        onDelete={deleteClientAction}
        redirectPath="/clients"
        title={t("deleteTitle")}
        description={t("deleteDescription", { name: client.name })}
      />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("edit")}</DialogTitle>
          </DialogHeader>
          <form onSubmit={save} className="space-y-4">
            {error && <FormError>{error}</FormError>}
            <div className="space-y-1.5">
              <FormLabel htmlFor="client-name" required>
                {t("name")}
              </FormLabel>
              <Input
                id="client-name"
                name="name"
                required
                placeholder="my-codex"
                defaultValue={client.name}
              />
            </div>
            <div className="space-y-1.5">
              <FormLabel htmlFor="client-description" optional>
                {t("descriptionLabel")}
              </FormLabel>
              <Textarea
                id="client-description"
                name="description"
                placeholder={t("descriptionPlaceholder")}
                defaultValue={client.description ?? ""}
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setOpen(false)}
              >
                {tCommon("cancel")}
              </Button>
              <Button
                type="submit"
                size="sm"
                isLoading={pending}
                disabled={pending}
              >
                {tCommon("save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
