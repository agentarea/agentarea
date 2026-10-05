"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import { CreateProjectDialog } from "./CreateProjectDialog";

/**
 * The empty state owns the dialog it opens, so the first project can be created
 * without leaving the list.
 */
export function ProjectsEmptyState() {
  const t = useTranslations("ProjectsPage.empty");
  const [open, setOpen] = useState(false);

  return (
    <>
      <EmptyState
        title={t("title")}
        description={t("description")}
        hints={[
          { text: t("hintAgents") },
          { text: t("hintSkills") },
          { text: t("hintFiles") },
        ]}
        iconsType="agent"
        action={{ label: t("action"), onClick: () => setOpen(true) }}
      />
      <CreateProjectDialog
        open={open}
        onOpenChange={setOpen}
        showTrigger={false}
      />
    </>
  );
}
