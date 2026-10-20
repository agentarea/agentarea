"use client";

import { useTranslations } from "next-intl";
import { AgentAvatar } from "@/components/AgentAvatar";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { Badge } from "@/components/ui/badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getTriggerStatusPresentation } from "@/lib/status";
import { renderTriggerIcon, type EnrichedTrigger } from "./triggerDisplay";

interface TriggerCardProps {
  trigger: EnrichedTrigger;
}

export default function TriggerCard({ trigger }: TriggerCardProps) {
  const t = useTranslations("TriggersPage");

  const state =
    trigger.status === "needs_owner"
      ? "needs_owner"
      : trigger.is_active
        ? "active"
        : "inactive";
  const status = getTriggerStatusPresentation(state);

  return (
    <LinkedCard
      href={`/triggers/${trigger.id}`}
      title={trigger.name}
      type="view"
      subtitle={
        <div className="flex items-center gap-1.5">
          <Badge
            size="sm"
            variant="outline"
            className="gap-1 font-normal text-muted-foreground border-transparent bg-secondary/50 hover:bg-secondary/70 px-1.5 h-5"
          >
            {renderTriggerIcon(trigger, "h-3 w-3")}
            {t(`type.${trigger.trigger_type}`)}
          </Badge>
          <StatusIndicator
            size="sm"
            kind={status.kind}
            className="whitespace-nowrap"
          >
            {t(`status.${state}`)}
          </StatusIndicator>
        </div>
      }
    >
      {trigger.agent_name && (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <AgentAvatar
            agent={{
              id: trigger.agent_id || trigger.agent_name,
              name: trigger.agent_name,
            }}
            size="xs"
          />
          {trigger.agent_name}
        </div>
      )}
    </LinkedCard>
  );
}
