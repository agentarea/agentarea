"use client";

import { type Node, type NodeProps } from "@xyflow/react";
import { Sparkles } from "lucide-react";
import type { NetworkFlowNodeData } from "../../types";
import NodeCard from "./NodeCard";

export default function SkillNode({ data }: NodeProps<Node<NetworkFlowNodeData>>) {
  const scope = (data.metadata.network_scope as string | undefined) ?? "private";
  const subtitle = scope === "egress" ? "Skill · Egress" : "Skill";

  return (
    <NodeCard
      icon={<Sparkles className="h-6 w-6" />}
      label={data.label}
      subtitle={subtitle}
      color="sky"
      dimmed={data._dimmed}
      highlighted={data._highlighted}
    />
  );
}
