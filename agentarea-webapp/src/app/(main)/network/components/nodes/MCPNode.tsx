"use client";

import { type Node, type NodeProps } from "@xyflow/react";
import { Plug } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { NetworkFlowNodeData } from "../../types";
import NodeCard from "./NodeCard";

export default function MCPNode({ data }: NodeProps<Node<NetworkFlowNodeData>>) {
  const scope = (data.metadata.network_scope as string | undefined) ?? "private";
  const isEgress = scope === "egress";
  const subtitle = isEgress ? "MCP · Egress" : "MCP Server";

  return (
    <NodeCard
      icon={<Plug className="h-6 w-6" />}
      label={data.label}
      subtitle={subtitle}
      color={isEgress ? "green" : "neutral"}
      dimmed={data._dimmed}
      highlighted={data._highlighted}
      badge={
        data.status ? (
          <Badge
            variant={data.status === "running" ? "default" : "secondary"}
            className="h-3.5 px-1 py-0 text-[9px] font-normal"
          >
            {data.status}
          </Badge>
        ) : null
      }
    />
  );
}
