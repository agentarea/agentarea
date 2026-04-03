"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import CreateAPIKeyDialog from "./CreateAPIKeyDialog";

export default function CreateAPIKeyButton() {
  const t = useTranslations("APIKeysPage");
  const router = useRouter();
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleSuccess = (token?: string) => {
    if (token) {
      router.push(`/admin/api-keys?new_token=${encodeURIComponent(token)}`);
    } else {
      router.refresh();
    }
  };

  return (
    <>
      <Button
        className="shrink-0 gap-2"
        size="xs"
        onClick={() => setDialogOpen(true)}
        data-test="create-api-key-button"
      >
        <Plus className="h-4 w-4" />
        {t("createKey")}
      </Button>
      <CreateAPIKeyDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSuccess={handleSuccess}
      />
    </>
  );
}
