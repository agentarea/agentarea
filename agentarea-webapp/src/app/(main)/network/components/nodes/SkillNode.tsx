"use client";

import { type NodeProps } from "@xyflow/react";
import { Sparkles } from "lucide-react";
import NodeCard from "./NodeCard";

export default function SkillNode({ data }: NodeProps) {
  const d = data as Record<string, any>;
  const scope: string = d.metadata?.network_scope || "private";
  const subtitle = scope === "egress" ? "Skill · Egress" : "Skill";

  return (
    <NodeCard
      icon={<Sparkles className="h-6 w-6" />}
      label={d.label}
      subtitle={subtitle}
      color="sky"
      dimmed={d._dimmed}
      highlighted={d._highlighted}
    />
  );
}
