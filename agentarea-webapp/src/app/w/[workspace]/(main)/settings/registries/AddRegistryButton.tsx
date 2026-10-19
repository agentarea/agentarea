"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import type { SelectableSecret } from "@/components/SecretSelect";
import { Button } from "@/components/ui/button";
import RegistryFormDialog from "./RegistryFormDialog";

export default function AddRegistryButton({
  secrets,
}: {
  secrets: Promise<SelectableSecret[]>;
}) {
  const t = useTranslations("Registries");
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button className="shrink-0" size="xs" onClick={() => setOpen(true)}>
        <Plus />
        {t("add")}
      </Button>
      {/* Mounted per opening, so it starts from an empty form each time. */}
      {open && (
        <RegistryFormDialog
          target={{ mode: "create" }}
          secrets={secrets}
          open
          onOpenChange={setOpen}
        />
      )}
    </>
  );
}
