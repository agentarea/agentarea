"use client";

import Link from "@/components/WorkspaceLink";
import { useTranslations } from "next-intl";
import { useFormSubmittingState } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import { Button } from "@/components/ui/button";

export default function CreateTriggerHeaderControls({
  label,
}: {
  label: string;
}) {
  const t = useTranslations("Common");
  const isSubmitting = useFormSubmittingState("create-trigger-form");

  return (
    <div className="flex items-center gap-2 py-1">
      <Button asChild size="xs" variant="outline">
        <Link href="/triggers">{t("cancel")}</Link>
      </Button>
      <Button
        size="xs"
        type="submit"
        form="create-trigger-form"
        isLoading={isSubmitting}
        disabled={isSubmitting}
      >
        {label}
      </Button>
    </div>
  );
}
