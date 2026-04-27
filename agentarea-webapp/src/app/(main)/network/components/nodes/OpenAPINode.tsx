"use client";

import { type NodeProps } from "@xyflow/react";
import { Globe } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import NodeCard from "./NodeCard";

export default function OpenAPINode({ data }: NodeProps) {
  const d = data as Record<string, any>;
  const toolCount: number = d.metadata?.tool_count ?? 0;

  return (
    <NodeCard
      icon={<Globe className="h-6 w-6" />}
      label={d.label}
      subtitle="OpenAPI · Egress"
      color="rose"
      dimmed={d._dimmed}
      highlighted={d._highlighted}
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
