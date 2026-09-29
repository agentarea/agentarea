"use client";

import Link from "@/components/WorkspaceLink";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useFormSubmittingState } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";

export default function CreateSkillHeaderControls() {
  const t = useTranslations("SkillsPage.create");
  const isSubmitting = useFormSubmittingState("create-skill-form");

  return (
    <div className="flex items-center gap-2 py-1">
      <Button asChild size="xs" variant="outline">
        <Link href="/skills">{t("cancel")}</Link>
      </Button>
      <Button
        size="xs"
        type="submit"
        form="create-skill-form"
        isLoading={isSubmitting}
        disabled={isSubmitting}
      >
        <Plus />
        {t("createSkill")}
      </Button>
    </div>
  );
}
