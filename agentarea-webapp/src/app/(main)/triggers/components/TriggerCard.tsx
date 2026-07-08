"use client";

import { useTranslations } from "next-intl";
import { AgentAvatar } from "@/components/AgentAvatar";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { Badge } from "@/components/ui/badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getTriggerStatusPresentation } from "@/lib/status";
import {
  findTriggerCatalogEntry,
  getTriggerIconComponent,
  renderTriggerIcon,
  type EnrichedTrigger,
  type TriggerCatalogEntry,
} from "./triggerDisplay";

interface TriggerCardProps {
  trigger: EnrichedTrigger;
  catalog: TriggerCatalogEntry[];
}

export default function TriggerCard({ trigger, catalog }: TriggerCardProps) {
  const t = useTranslations("TriggersPage");

  const entry = findTriggerCatalogEntry(trigger, catalog);
  const Icon = getTriggerIconComponent(entry, trigger);
  const isActive = trigger.is_active;
  const status = getTriggerStatusPresentation(isActive ? "active" : "inactive");

  return (
    <LinkedCard
      href={`/triggers/${trigger.id}`}
      title={trigger.name}
      type="view"
      icon={Icon}
      subtitle={
        <div className="flex items-center gap-1.5">
          <Badge
            size="sm"
            variant="outline"
            className="gap-1 font-normal text-muted-foreground border-transparent bg-secondary/50 hover:bg-secondary/70 px-1.5 h-5"
          >
            {renderTriggerIcon(entry, trigger, "h-3 w-3")}
            {entry?.name ?? trigger.trigger_type}
          </Badge>
          <StatusIndicator
            size="sm"
            tone={status.tone}
            pulse={status.pulse}
            className="whitespace-nowrap"
          >
            {isActive ? t("status.active") : t("status.inactive")}
          </StatusIndicator>
        </div>
      }
    >
      {trigger.agent_name && (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <AgentAvatar
            agent={{ id: trigger.agent_id || trigger.agent_name, name: trigger.agent_name }}
            size="xs"
          />
          {trigger.agent_name}
        </div>
      )}
    </LinkedCard>
  );
}
