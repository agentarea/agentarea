"use client";

import { useTranslations } from "next-intl";
import { PencilLine } from "lucide-react";
import type { SkillResponse } from "@/api/client/types.gen";
import { RegistryBadge } from "@/components/RegistryBadge";
import { Badge } from "@/components/ui/badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  getSkillSourceStatusPresentation,
  getSkillUpdateStatusPresentation,
} from "@/lib/status";

/**
 * Where an installed catalog skill comes from and how it stands against its
 * registry: the registry and its trust, a newer version waiting for an admin,
 * the workspace's own edit, or the registry no longer publishing it.
 */
export default function SkillProvenance({
  skill,
}: {
  skill: Pick<SkillResponse, "registry_name" | "registry_trust"> & {
    update_available?: boolean | null;
    customized?: boolean | null;
    removed_upstream?: boolean | null;
  };
}) {
  const t = useTranslations("SkillsPage.update");
  const update = getSkillUpdateStatusPresentation(skill);
  const removed = getSkillSourceStatusPresentation(skill);

  if (!skill.registry_trust && !update && !removed && !skill.customized) {
    return null;
  }

  return (
    <span className="inline-flex min-w-0 shrink-0 items-center gap-1.5">
      {skill.registry_trust && (
        <RegistryBadge
          name={skill.registry_name}
          trust={skill.registry_trust}
          className="max-w-[180px]"
        />
      )}
      {removed && (
        <StatusIndicator
          kind={removed.kind}
          size="sm"
          className="whitespace-nowrap"
          title={t("removedUpstreamHint")}
        >
          {t("removedUpstream")}
        </StatusIndicator>
      )}
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
