"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";

export default function CreateSavedTaskButton() {
  const t = useTranslations("SavedTasksPage");

  return (
    <Button className="shrink-0" size="xs" asChild>
      <Link href="/saved-tasks/create">
        <Plus />
        {t("create")}
      </Link>
    </Button>
  );
}
