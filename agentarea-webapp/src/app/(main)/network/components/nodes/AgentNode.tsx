"use client";

import { type NodeProps } from "@xyflow/react";
import { Bot } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import NodeCard from "./NodeCard";

export default function AgentNode({ data }: NodeProps) {
  const d = data as Record<string, any>;
  return (
    <NodeCard
      icon={<Bot className="h-3.5 w-3.5" />}
      category="Agent"
      label={d.label}
      color="blue"
      href={d.id ? `/agents/${d.id}/edit` : undefined}
      metadata={
        <div className="flex items-center gap-1.5 flex-wrap">
          {d.status && (
            <Badge
              variant={d.status === "active" ? "default" : "secondary"}
              className="text-[10px] px-1.5 py-0 h-4"
            >
              {d.status}
            </Badge>
          )}
          {d.metadata?.model_id && (
            <span className="text-[10px] text-muted-foreground truncate">
              {d.metadata.model_id}
            </span>
          )}
        </div>
      }
    />
  );
}
