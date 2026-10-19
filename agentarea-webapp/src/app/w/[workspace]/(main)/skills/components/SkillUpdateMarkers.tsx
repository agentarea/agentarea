"use client";

import { useTranslations } from "next-intl";
import { PencilLine } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getSkillUpdateStatusPresentation } from "@/lib/status";

/**
 * Where an installed catalog skill stands against its registry: a newer
 * version waits for an admin, and/or the workspace edited its copy.
 */
export default function SkillUpdateMarkers({
  skill,
}: {
  skill: { update_available?: boolean | null; customized?: boolean | null };
}) {
  const t = useTranslations("SkillsPage.update");
  const update = getSkillUpdateStatusPresentation(skill);

  if (!update && !skill.customized) return null;

  return (
    <span className="inline-flex shrink-0 items-center gap-1.5">
      {update && (
        <StatusIndicator
          kind={update.kind}
          size="sm"
          className="whitespace-nowrap"
        >
          {t("available")}
        </StatusIndicator>
      )}
      {skill.customized && (
        <Badge
          variant="secondary"
          size="sm"
          className="gap-1 whitespace-nowrap font-normal"
          title={t("customizedHint")}
        >
          <PencilLine aria-hidden className="h-3 w-3" />
          {t("customized")}
        </Badge>
      )}
    </span>
  );
}
