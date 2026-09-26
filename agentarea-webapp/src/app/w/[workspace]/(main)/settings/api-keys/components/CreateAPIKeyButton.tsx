"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import CreateAPIKeyDialog from "./CreateAPIKeyDialog";

export default function CreateAPIKeyButton() {
  const t = useTranslations("APIKeysPage");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogSession, setDialogSession] = useState(0);

  return (
    <>
      <Button
        className="shrink-0"
        size="xs"
        onClick={() => {
          setDialogSession((session) => session + 1);
          setDialogOpen(true);
        }}
        data-test="create-api-key-button"
      >
        <Plus />
        {t("createKey")}
      </Button>
      <CreateAPIKeyDialog
        key={dialogSession}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      />
    </>
  );
}
