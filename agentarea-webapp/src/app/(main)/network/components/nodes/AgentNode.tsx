"use client";

import { type Node, type NodeProps } from "@xyflow/react";
import { Bot, Sparkles } from "lucide-react";
import type { NetworkFlowNodeData } from "../../types";
import NodeCard from "./NodeCard";

export default function AgentNode({ data }: NodeProps<Node<NetworkFlowNodeData>>) {
  const name = data.label || "Unnamed Agent";
  const modelInfo = data.metadata.model_info as { model_display_name?: string } | undefined;
  const modelName = modelInfo?.model_display_name;
  const subtitle = modelName ? `Agent · ${modelName}` : "Agent";
  const embeddedSkills = (data.metadata.embedded_skills_count as number | undefined) ?? 0;

  return (
    <NodeCard
      icon={<Bot className="h-6 w-6" />}
      label={name}
      subtitle={subtitle}
      color="neutral"
      dimmed={data._dimmed}
      highlighted={data._highlighted}
      badge={
        embeddedSkills > 0 ? (
          <span className="inline-flex items-center gap-0.5 rounded-full bg-blue-50 px-1.5 py-0 text-[9px] font-medium text-blue-700 ring-1 ring-blue-100 dark:bg-blue-950/40 dark:text-blue-300 dark:ring-blue-900/60">
            <Sparkles className="h-2.5 w-2.5" />
            {embeddedSkills}
          </span>
        ) : null
      }
    />
  );
}
