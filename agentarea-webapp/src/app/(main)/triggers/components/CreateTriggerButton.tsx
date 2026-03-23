"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function CreateTriggerButton() {
  const t = useTranslations("TriggersPage");

  return (
    <Button
      className="shrink-0 gap-2"
      size="xs"
      asChild
      data-test="new-trigger-button"
    >
      <Link href="/triggers/create">
        <Plus className="mr-2 h-4 w-4" />
        {t("createTrigger")}
      </Link>
    </Button>
  );
}
