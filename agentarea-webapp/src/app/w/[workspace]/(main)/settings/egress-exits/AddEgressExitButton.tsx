"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import EgressExitFormDialog, {
  type SecretChoices,
} from "./EgressExitFormDialog";

export default function AddEgressExitButton({
  secrets,
}: {
  secrets: Promise<SecretChoices>;
}) {
  const t = useTranslations("EgressExits");
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button className="shrink-0" size="xs" onClick={() => setOpen(true)}>
        <Plus />
        {t("add")}
      </Button>
      {/* Mounted per opening, so it starts from an empty form each time. */}
      {open && (
        <EgressExitFormDialog
          target={{ mode: "create" }}
          secrets={secrets}
          open
          onOpenChange={setOpen}
        />
      )}
    </>
  );
}
