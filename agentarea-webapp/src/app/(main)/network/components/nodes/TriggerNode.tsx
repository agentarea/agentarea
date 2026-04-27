"use client";

import { type NodeProps } from "@xyflow/react";
import { Clock, Globe, Zap } from "lucide-react";
import NodeCard from "./NodeCard";

export default function TriggerNode({ data }: NodeProps) {
  const d = data as Record<string, any>;
  const triggerType: string = d.metadata?.trigger_type || "unknown";
  const isIngress = triggerType === "webhook";
  const isSchedule = triggerType === "schedule" || triggerType === "cron";

  const Icon = isIngress ? Globe : isSchedule ? Clock : Zap;
  const subtitle = isIngress
    ? "Webhook"
    : isSchedule
      ? "Schedule"
      : triggerType.charAt(0).toUpperCase() + triggerType.slice(1);

  return (
    <NodeCard
      icon={<Icon className="h-6 w-6" />}
      label={d.label}
      subtitle={subtitle}
      color={isIngress ? "amber" : "neutral"}
      hasTarget={false}
      dimmed={d._dimmed}
      highlighted={d._highlighted}
    />
  );
}
