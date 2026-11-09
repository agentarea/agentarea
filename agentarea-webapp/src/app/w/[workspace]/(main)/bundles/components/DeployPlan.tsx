"use client";

import { useTranslations } from "next-intl";
import { ListChecks, Send, ShieldCheck, type LucideIcon } from "lucide-react";
import type { EntityKind, ImportPreview } from "@/api/client/types.gen";
import {
  FactRow,
  SectionCard,
  SectionCardHead,
  SoftTile,
} from "@/components/Overview/OverviewCard";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { getBundleEntityStatusPresentation } from "@/lib/status";

// What a bundle entity of each kind becomes in the workspace.
export const BUNDLE_KIND_ICONS: Record<EntityKind, LucideIcon> = {
  agent: ENTITY_ICONS.agent,
  mcp: ENTITY_ICONS.mcp,
  skill: ENTITY_ICONS.skill,
  channel: Send,
  automation: ENTITY_ICONS.trigger,
  policy: ShieldCheck,
};

type PlanStatusKey =
  | "will_create"
  | "will_update"
  | "unchanged"
  | "already_exists"
  | "orphaned"
  | "changes_not_applied"
  | "unsupported";

/** What an install of the draft does with each entity, as analyze planned it. */
export function DeployPlan({ plan }: { plan: ImportPreview }) {
  const t = useTranslations("BundleInstall");
  const tStatus = useTranslations("BundleInstall.planStatus");
  const entities = plan.entities ?? [];

  return (
    <SectionCard>
      <SectionCardHead
        icon={<ListChecks />}
        title={t("planTitle")}
        count={entities.length}
      />
      <p className="border-b border-border/60 px-[15px] py-[9px] text-xs text-muted-foreground">
        {t("planHint")}
      </p>
      {entities.map((entity) => {
        const Icon = BUNDLE_KIND_ICONS[entity.kind];
        const status = getBundleEntityStatusPresentation(entity.status);
        return (
          <FactRow
            key={`${entity.kind}:${entity.key}`}
            tile={<SoftTile icon={<Icon />} />}
            title={entity.name}
            sub={entity.detail}
            trailing={
              <StatusIndicator kind={status.kind} size="sm">
                {status.labelKey
                  ? tStatus(status.labelKey as PlanStatusKey)
                  : status.label}
              </StatusIndicator>
            }
          />
        );
      })}
    </SectionCard>
  );
}
