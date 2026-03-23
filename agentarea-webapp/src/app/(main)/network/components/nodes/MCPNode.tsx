"use client";

import { type NodeProps } from "@xyflow/react";
import { Plug } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import NodeCard from "./NodeCard";

export default function MCPNode({ data }: NodeProps) {
  const d = data as Record<string, any>;
  const scope: string = d.metadata?.network_scope || "private";
  const isEgress = scope === "egress";
  return (
    <NodeCard
      icon={<Plug className="h-3.5 w-3.5" />}
      category={`MCP / ${scope}`}
      label={d.label}
      color="green"
      riskLevel={isEgress ? "warning" : "none"}
      metadata={
        <div className="flex items-center gap-1.5 flex-wrap">
          {d.status && (
            <Badge
              variant={d.status === "running" ? "default" : "secondary"}
              className="text-[10px] px-1.5 py-0 h-4"
            >
              {d.status}
            </Badge>
          )}
          {d.metadata?.tool_count > 0 && (
            <span className="text-[10px] text-muted-foreground">
              {d.metadata.tool_count} tools
            </span>
          )}
        </div>
      }
    />
  );
}
