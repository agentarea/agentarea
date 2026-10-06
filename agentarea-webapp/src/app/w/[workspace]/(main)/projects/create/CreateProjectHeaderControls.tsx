"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { useFormSubmittingState } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";
import { PROJECT_FORM_ID } from "../shared/ProjectForm";

export default function CreateProjectHeaderControls() {
  const t = useTranslations("ProjectsPage.create");
  const tCommon = useTranslations("Common");
  const isSubmitting = useFormSubmittingState(PROJECT_FORM_ID);

  return (
    <div className="flex items-center gap-2 py-1">
      <Button asChild size="xs" variant="outline">
        <Link href="/projects">{tCommon("cancel")}</Link>
      </Button>
      <Button
        size="xs"
        type="submit"
        form={PROJECT_FORM_ID}
        isLoading={isSubmitting}
        disabled={isSubmitting}
      >
        <Plus />
        {t("submit")}
      </Button>
    </div>
  );
}
