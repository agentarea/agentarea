"use client";

import { type Node, type NodeProps } from "@xyflow/react";
import { Globe } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { NetworkFlowNodeData } from "../../types";
import NodeCard from "./NodeCard";

export default function OpenAPINode({ data }: NodeProps<Node<NetworkFlowNodeData>>) {
  const toolCount = (data.metadata.tool_count as number | undefined) ?? 0;

  return (
    <NodeCard
      icon={<Globe className="h-6 w-6" />}
      label={data.label}
      subtitle="OpenAPI · Egress"
      color="rose"
      dimmed={data._dimmed}
      highlighted={data._highlighted}
      badge={
        toolCount > 0 ? (
          <Badge
            variant="secondary"
            className="h-3.5 px-1 py-0 text-[9px] font-normal"
          >
            {toolCount} ops
          </Badge>
        ) : null
      }
    />
  );
}
