"use client";

import { useTranslations } from "next-intl";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { Badge } from "@/components/ui/badge";
import {
  findTriggerCatalogEntry,
  getTriggerIconComponent,
  renderTriggerIcon,
} from "./triggerDisplay";

interface TriggerCardProps {
  trigger: any;
  catalog: any[];
}

export default function TriggerCard({ trigger, catalog }: TriggerCardProps) {
  const t = useTranslations("TriggersPage");

  const entry = findTriggerCatalogEntry(trigger, catalog);
  const Icon = getTriggerIconComponent(entry, trigger);
  const isActive = trigger.is_active;

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
          <Badge
            size="sm"
            variant={isActive ? "default" : "secondary"}
            className="h-5 px-1.5 font-normal"
          >
            {isActive ? t("status.active") : t("status.inactive")}
          </Badge>
        </div>
      }
    >
      <div className="text-xs text-muted-foreground">{trigger.agent_name}</div>
    </LinkedCard>
  );
}
