"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function CreateTriggerButton() {
  const t = useTranslations("TriggersPage");

  return (
    <Button
      className="shrink-0"
      size="xs"
      asChild
      data-test="new-trigger-button"
    >
      <Link href="/triggers/create">
        <Plus />
        {t("createTrigger")}
      </Link>
    </Button>
  );
}
