"use client";

import { type NodeProps } from "@xyflow/react";
import { Sparkles } from "lucide-react";
import NodeCard from "./NodeCard";

export default function SkillNode({ data }: NodeProps) {
  const d = data as Record<string, any>;
  const scope: string = d.metadata?.network_scope || "private";
  return (
    <NodeCard
      icon={<Sparkles className="h-3.5 w-3.5" />}
      category={`Skill / ${scope}`}
      label={d.label}
      color="purple"
      metadata={
        d.metadata?.description ? (
          <span className="text-[10px] text-muted-foreground line-clamp-1">
            {d.metadata.description}
          </span>
        ) : null
      }
    />
  );
}
