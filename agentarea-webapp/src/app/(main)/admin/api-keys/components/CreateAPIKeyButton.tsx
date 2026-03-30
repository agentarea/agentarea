"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function CreateAPIKeyButton() {
  const t = useTranslations("APIKeysPage");

  return (
    <Link href="/admin/api-keys/create">
      <Button
        className="shrink-0 gap-2"
        size="xs"
        data-test="create-api-key-button"
      >
        <Plus className="h-4 w-4" />
        {t("createKey")}
      </Button>
    </Link>
  );
}
