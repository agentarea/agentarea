"use client";

import { type NodeProps } from "@xyflow/react";
import { Plug } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import NodeCard from "./NodeCard";

export default function MCPNode({ data }: NodeProps) {
  const d = data as Record<string, any>;
  const scope: string = d.metadata?.network_scope || "private";
  const isEgress = scope === "egress";
  const subtitle = isEgress ? "MCP · Egress" : "MCP Server";

  return (
    <NodeCard
      icon={<Plug className="h-6 w-6" />}
      label={d.label}
      subtitle={subtitle}
      color={isEgress ? "green" : "neutral"}
      dimmed={d._dimmed}
      highlighted={d._highlighted}
      badge={
        d.status ? (
          <Badge
            variant={d.status === "running" ? "default" : "secondary"}
            className="h-3.5 px-1 py-0 text-[9px] font-normal"
          >
            {d.status}
          </Badge>
        ) : null
      }
    />
  );
}
