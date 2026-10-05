"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";

export default function CreateProjectButton() {
  const t = useTranslations("ProjectsPage");

  return (
    <Button className="shrink-0" size="xs" asChild>
      <Link href="/projects/create">
        <Plus />
        {t("newProject")}
      </Link>
    </Button>
  );
}
