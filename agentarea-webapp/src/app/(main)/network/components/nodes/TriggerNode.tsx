"use client";

import { type Node, type NodeProps } from "@xyflow/react";
import { Clock, Globe, Zap } from "lucide-react";
import type { NetworkFlowNodeData } from "../../types";
import NodeCard from "./NodeCard";

export default function TriggerNode({ data }: NodeProps<Node<NetworkFlowNodeData>>) {
  const triggerType = (data.metadata.trigger_type as string | undefined) ?? "unknown";
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
      label={data.label}
      subtitle={subtitle}
      color={isIngress ? "amber" : "neutral"}
      hasTarget={false}
      dimmed={data._dimmed}
      highlighted={data._highlighted}
    />
  );
}
