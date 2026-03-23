"use client";

import { useTranslations } from "next-intl";
import { Clock, Webhook, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import LinkedCard from "@/components/LinkedCard/LinkedCard";

interface TriggerCardProps {
  trigger: any;
}

export default function TriggerCard({ trigger }: TriggerCardProps) {
  const t = useTranslations("TriggersPage");

  const isCron = trigger.trigger_type === "cron";
  const isActive = trigger.is_active;

  return (
    <LinkedCard
      href={`/triggers/${trigger.id}`}
      title={trigger.name}
      type="view"
      icon={isCron ? Clock : Webhook}
      subtitle={
        <div className="flex items-center gap-1.5">
          <Badge
            size="sm"
            variant="outline"
            className="gap-1 font-normal text-muted-foreground border-transparent bg-secondary/50 hover:bg-secondary/70 px-1.5 h-5"
          >
            {isCron ? <Clock className="h-3 w-3" /> : <Webhook className="h-3 w-3" />}
            {isCron ? t("type.cron") : t("type.webhook")}
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
