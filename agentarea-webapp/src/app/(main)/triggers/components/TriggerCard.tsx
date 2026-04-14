"use client";

import { useTranslations } from "next-intl";
import { Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import LinkedCard from "@/components/LinkedCard/LinkedCard";

interface TriggerCardProps {
  trigger: any;
  catalog: any[];
}

function findCatalogEntry(trigger: any, catalog: any[]) {
  // Match polling triggers by data_extractor first
  if (trigger.data_extractor) {
    const match = catalog.find((e: any) => e.data_extractor === trigger.data_extractor);
    if (match) return match;
  }
  if (trigger.trigger_type === "cron") {
    return catalog.find((e) => e.id === "cron");
  }
  const wt = trigger.webhook_type || trigger.config?.webhook_type;
  return catalog.find((e: any) => e.webhook_type === wt) || catalog.find((e) => e.id === "webhook");
}

export default function TriggerCard({ trigger, catalog }: TriggerCardProps) {
  const t = useTranslations("TriggersPage");

  const entry = findCatalogEntry(trigger, catalog);
  const isActive = trigger.is_active;

  return (
    <LinkedCard
      href={`/triggers/${trigger.id}`}
      title={trigger.name}
      type="view"
      icon={Clock}
      subtitle={
        <div className="flex items-center gap-1.5">
          <Badge
            size="sm"
            variant="outline"
            className="gap-1 font-normal text-muted-foreground border-transparent bg-secondary/50 hover:bg-secondary/70 px-1.5 h-5"
          >
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
      <div className="text-xs text-muted-foreground">
        {trigger.agent_name}
      </div>
    </LinkedCard>
  );
}
