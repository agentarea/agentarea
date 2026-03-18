"use client";

import { type NodeProps } from "@xyflow/react";
import { Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import NodeCard from "./NodeCard";

export default function TriggerNode({ data }: NodeProps) {
  const d = data as Record<string, any>;
  const triggerType: string = d.metadata?.trigger_type || "unknown";
  const isIngress = triggerType === "webhook";
  return (
    <NodeCard
      icon={<Zap className="h-3.5 w-3.5" />}
      category={`Trigger / ${isIngress ? "Ingress" : "Private"}`}
      label={d.label}
      color="amber"
      riskLevel={isIngress ? "warning" : "none"}
      hasTarget={false}
      metadata={
        <div className="flex items-center gap-1.5">
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4">
            {triggerType}
          </Badge>
          {d.status && (
            <span className="text-[10px] text-muted-foreground">{d.status}</span>
          )}
        </div>
      }
    />
  );
}
