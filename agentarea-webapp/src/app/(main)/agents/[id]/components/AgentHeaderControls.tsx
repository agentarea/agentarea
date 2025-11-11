"use client";

import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { useFormSubmittingState } from "../../shared/useFormSubmittingState";

export default function AgentHeaderControls() {
  const pathname = usePathname();
  const onSettings = pathname?.endsWith("/settings");
  const tCommon = useTranslations("Common");
  const isSubmitting = useFormSubmittingState();

  if (!onSettings) return null;

  return (
    <div className="flex items-center gap-2 py-1">
      <Button size="xs" type="submit" form="agent-form" isLoading={isSubmitting}>
        {tCommon("saveChanges")}
      </Button>
    </div>
  );
}
